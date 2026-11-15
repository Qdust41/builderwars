import { reconnectDelayMs } from "./backoff";
import {
  parseRealtimeEvent,
  type RealtimeClient,
  type RealtimeEvent,
  type SubscriptionHandlers,
  type Unsubscribe,
} from "./types";

/**
 * AWS AppSync Events adapter (WebSocket protocol `aws-appsync-event-ws`).
 *
 * - One socket per client, shared by all subscriptions; opened lazily, closed when the last
 *   subscription goes away.
 * - Subscribe only to channels the API handed out (`GET /devices/{id}/channel`,
 *   `GET /sessions/{id}/channel`), which checks membership. TODO (infrastructure): the
 *   server-side onSubscribe handler must re-check membership.
 * - Incoming events are validated against the realtime contract; unknown types are dropped.
 * - After any reconnect every subscription is renewed and `onReady` fires, so callers refetch
 *   state from the API (events may have been missed).
 * Keep all AppSync-specific code in this module.
 */

/** Auth headers for AppSync, e.g. `{ Authorization: <Cognito ID token> }`. */
export type AppSyncAuthProvider = () => Promise<Record<string, string>>;

export interface WebSocketLike {
  readonly readyState: number;
  onopen: ((ev: unknown) => void) | null;
  onmessage: ((ev: { data: unknown }) => void) | null;
  onclose: ((ev: unknown) => void) | null;
  onerror: ((ev: unknown) => void) | null;
  send(data: string): void;
  close(code?: number, reason?: string): void;
}

export interface AppSyncEventsConfig {
  /** The Events API HTTP domain (CDK output `EventsHttpDns`), used as the auth `host`. */
  httpDomain: string;
  /** The realtime domain (CDK output `EventsRealtimeDns`). */
  realtimeDomain: string;
  auth: AppSyncAuthProvider;
  createSocket?: (url: string, protocols: string[]) => WebSocketLike;
  reconnectDelay?: (attempt: number) => number;
  newId?: () => string;
}

interface Subscription {
  id: string;
  channel: string;
  onEvent: (event: RealtimeEvent) => void;
  handlers: SubscriptionHandlers;
}

const OPEN = 1;
const DEFAULT_KEEPALIVE_TIMEOUT_MS = 300_000;

export class AppSyncEventsClient implements RealtimeClient {
  private socket: WebSocketLike | null = null;
  private connected = false;
  private readonly subs = new Map<string, Subscription>();
  private attempt = 0;
  private keepaliveTimer: ReturnType<typeof setTimeout> | undefined;
  private reconnectTimer: ReturnType<typeof setTimeout> | undefined;
  private keepaliveTimeoutMs = DEFAULT_KEEPALIVE_TIMEOUT_MS;

  constructor(private readonly config: AppSyncEventsConfig) {}

  async subscribe(
    channel: string,
    onEvent: (event: RealtimeEvent) => void,
    handlers: SubscriptionHandlers = {},
  ): Promise<Unsubscribe> {
    const sub: Subscription = {
      id: this.config.newId?.() ?? crypto.randomUUID(),
      channel: toAppSyncChannel(channel),
      onEvent,
      handlers,
    };
    this.subs.set(sub.id, sub);
    if (this.connected) void this.sendSubscribe(sub);
    else if (!this.socket && this.reconnectTimer === undefined) void this.connect();
    return () => this.unsubscribe(sub.id);
  }

  private unsubscribe(id: string): void {
    if (!this.subs.delete(id)) return;
    if (this.connected) this.send({ type: "unsubscribe", id });
    if (this.subs.size === 0) this.shutdown();
  }

  private async connect(): Promise<void> {
    let headers: Record<string, string>;
    try {
      headers = await this.authHeaders();
    } catch (err) {
      this.fail(err);
      return;
    }
    if (this.subs.size === 0) return;
    const create =
      this.config.createSocket ??
      ((url: string, protocols: string[]) => new WebSocket(url, protocols) as WebSocketLike);
    const socket = create(`wss://${this.config.realtimeDomain}/event/realtime`, [
      "aws-appsync-event-ws",
      `header-${base64Url(JSON.stringify(headers))}`,
    ]);
    this.socket = socket;
    socket.onopen = () => this.send({ type: "connection_init" });
    socket.onmessage = (ev) => this.onMessage(ev.data);
    socket.onerror = () => {
      /* onclose follows and handles the retry */
    };
    socket.onclose = () => {
      if (this.socket !== socket) return;
      this.socket = null;
      this.connected = false;
      clearTimeout(this.keepaliveTimer);
      if (this.subs.size > 0) this.fail(new Error("AppSync Events connection closed"));
    };
  }

  private onMessage(raw: unknown): void {
    let msg: Record<string, unknown>;
    try {
      msg = JSON.parse(String(raw)) as Record<string, unknown>;
    } catch {
      return;
    }
    switch (msg.type) {
      case "connection_ack":
        this.connected = true;
        this.attempt = 0;
        if (typeof msg.connectionTimeoutMs === "number") {
          this.keepaliveTimeoutMs = msg.connectionTimeoutMs;
        }
        this.armKeepalive();
        for (const sub of this.subs.values()) void this.sendSubscribe(sub);
        return;
      case "ka":
        this.armKeepalive();
        return;
      case "subscribe_success": {
        const sub = this.subs.get(String(msg.id));
        sub?.handlers.onReady?.();
        return;
      }
      case "subscribe_error": {
        const sub = this.subs.get(String(msg.id));
        sub?.handlers.onError?.(new Error(`subscribe failed: ${describeErrors(msg.errors)}`));
        return;
      }
      case "data": {
        const sub = this.subs.get(String(msg.id));
        if (!sub) return;
        const event = parseRealtimeEvent(msg.event);
        if (event) sub.onEvent(event);
        return;
      }
      case "connection_error":
      case "error":
        this.socket?.close();
        return;
      default:
        return;
    }
  }

  private async sendSubscribe(sub: Subscription): Promise<void> {
    let authorization: Record<string, string>;
    try {
      authorization = await this.authHeaders();
    } catch (err) {
      sub.handlers.onError?.(err instanceof Error ? err : new Error(String(err)));
      return;
    }
    if (!this.subs.has(sub.id)) return;
    this.send({ type: "subscribe", id: sub.id, channel: sub.channel, authorization });
  }

  private async authHeaders(): Promise<Record<string, string>> {
    return { host: this.config.httpDomain, ...(await this.config.auth()) };
  }

  private send(message: Record<string, unknown>): void {
    if (this.socket && this.socket.readyState === OPEN) this.socket.send(JSON.stringify(message));
  }

  private armKeepalive(): void {
    clearTimeout(this.keepaliveTimer);
    // No "ka" within the server's timeout means the connection is dead.
    this.keepaliveTimer = setTimeout(() => this.socket?.close(), this.keepaliveTimeoutMs);
  }

  private fail(err: unknown): void {
    const error = err instanceof Error ? err : new Error(String(err));
    for (const sub of this.subs.values()) sub.handlers.onError?.(error);
    if (this.subs.size === 0 || this.reconnectTimer !== undefined) return;
    const delay = (this.config.reconnectDelay ?? reconnectDelayMs)(this.attempt++);
    this.reconnectTimer = setTimeout(() => {
      this.reconnectTimer = undefined;
      if (this.subs.size > 0 && !this.socket) void this.connect();
    }, delay);
  }

  private shutdown(): void {
    clearTimeout(this.keepaliveTimer);
    clearTimeout(this.reconnectTimer);
    this.reconnectTimer = undefined;
    const socket = this.socket;
    this.socket = null;
    this.connected = false;
    socket?.close();
  }
}

/** API channels are `projects/...`; AppSync wants a leading slash (namespace `projects`). */
export function toAppSyncChannel(channel: string): string {
  return channel.startsWith("/") ? channel : `/${channel}`;
}

export function base64Url(text: string): string {
  const bytes = new TextEncoder().encode(text);
  let binary = "";
  for (const b of bytes) binary += String.fromCharCode(b);
  return btoa(binary).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

function describeErrors(errors: unknown): string {
  if (!Array.isArray(errors)) return "unknown error";
  return errors
    .map((e) => (typeof e === "object" && e && "message" in e ? String(e.message) : String(e)))
    .join("; ");
}
