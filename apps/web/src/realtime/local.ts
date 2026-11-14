import type { RealtimeClient, RealtimeEvent, Unsubscribe } from "./types";

/** In-browser bus for local development and tests. Nothing leaves the tab. */
export class LocalRealtimeClient implements RealtimeClient {
  private readonly listeners = new Map<string, Set<(e: RealtimeEvent) => void>>();

  async subscribe(channel: string, onEvent: (e: RealtimeEvent) => void): Promise<Unsubscribe> {
    const set = this.listeners.get(channel) ?? new Set();
    set.add(onEvent);
    this.listeners.set(channel, set);
    return () => {
      set.delete(onEvent);
    };
  }

  /** Test/dev helper to inject an event. */
  emit(channel: string, event: RealtimeEvent): void {
    this.listeners.get(channel)?.forEach((listener) => listener(event));
  }
}
