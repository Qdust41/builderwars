import type { AuthHeaderProvider, Fetch } from "../api/client";
import { reconnectDelayMs } from "./backoff";
import {
  parseRealtimeEvent,
  type RealtimeClient,
  type RealtimeEvent,
  type SubscriptionHandlers,
  type Unsubscribe,
} from "./types";

/**
 * LOCAL ONLY: reads the local API's server-sent event stream (`GET /local/realtime`), which
 * stands in for AppSync Events when the API runs with its in-memory backend. Uses `fetch`
 * rather than `EventSource` so the dev identity header can be sent.
 */
export class LocalApiRealtimeClient implements RealtimeClient {
  constructor(
    private readonly baseUrl: string,
    private readonly auth: AuthHeaderProvider,
    private readonly fetchImpl: Fetch = (input, init) => fetch(input, init),
    private readonly delay: (attempt: number) => number = reconnectDelayMs,
  ) {}

  async subscribe(
    channel: string,
    onEvent: (event: RealtimeEvent) => void,
    handlers: SubscriptionHandlers = {},
  ): Promise<Unsubscribe> {
    const abort = new AbortController();
    let attempt = 0;

    const run = async () => {
      while (!abort.signal.aborted) {
        try {
          const res = await this.fetchImpl(
            `${this.baseUrl}/local/realtime?channel=${encodeURIComponent(channel)}`,
            { headers: await this.auth(), signal: abort.signal },
          );
          if (!res.ok || !res.body) throw new Error(`realtime stream: HTTP ${res.status}`);
          attempt = 0;
          handlers.onReady?.();
          await readServerSentEvents(res.body, (data) => {
            const event = parseRealtimeEvent(data);
            if (event) onEvent(event);
          });
          if (abort.signal.aborted) return;
          throw new Error("realtime stream closed");
        } catch (err) {
          if (abort.signal.aborted) return;
          handlers.onError?.(err instanceof Error ? err : new Error(String(err)));
          await sleep(this.delay(attempt++), abort.signal);
        }
      }
    };
    void run();
    return () => abort.abort();
  }
}

/** Calls `onData` with each event's `data` field; returns when the stream ends. */
export async function readServerSentEvents(
  body: ReadableStream<Uint8Array>,
  onData: (data: string) => void,
): Promise<void> {
  const reader = body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) return;
    buffer += decoder.decode(value, { stream: true }).replace(/\r\n?/g, "\n");
    let end: number;
    while ((end = buffer.indexOf("\n\n")) >= 0) {
      const block = buffer.slice(0, end);
      buffer = buffer.slice(end + 2);
      const data = block
        .split("\n")
        .filter((line) => line.startsWith("data:"))
        .map((line) => line.slice(5).replace(/^ /, ""))
        .join("\n");
      if (data) onData(data);
    }
  }
}

function sleep(ms: number, signal: AbortSignal): Promise<void> {
  return new Promise((resolve) => {
    const timer = setTimeout(resolve, ms);
    signal.addEventListener("abort", () => {
      clearTimeout(timer);
      resolve();
    });
  });
}
