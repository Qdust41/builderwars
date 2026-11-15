import type {
  RealtimeClient,
  RealtimeEvent,
  SubscriptionHandlers,
  Unsubscribe,
} from "./types";

/** In-browser bus for tests and offline UI work. Nothing leaves the tab. */
export class InMemoryRealtimeClient implements RealtimeClient {
  private readonly listeners = new Map<string, Set<(e: RealtimeEvent) => void>>();

  async subscribe(
    channel: string,
    onEvent: (e: RealtimeEvent) => void,
    handlers?: SubscriptionHandlers,
  ): Promise<Unsubscribe> {
    const set = this.listeners.get(channel) ?? new Set();
    set.add(onEvent);
    this.listeners.set(channel, set);
    handlers?.onReady?.();
    return () => {
      set.delete(onEvent);
    };
  }

  /** Test/dev helper to inject an event. */
  emit(channel: string, event: RealtimeEvent): void {
    this.listeners.get(channel)?.forEach((listener) => listener(event));
  }
}
