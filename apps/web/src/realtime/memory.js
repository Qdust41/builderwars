/** In-browser bus for tests and offline UI work. Nothing leaves the tab. */
export class InMemoryRealtimeClient {
    listeners = new Map();
    async subscribe(channel, onEvent, handlers) {
        const set = this.listeners.get(channel) ?? new Set();
        set.add(onEvent);
        this.listeners.set(channel, set);
        handlers?.onReady?.();
        return () => {
            set.delete(onEvent);
        };
    }
    /** Test/dev helper to inject an event. */
    emit(channel, event) {
        this.listeners.get(channel)?.forEach((listener) => listener(event));
    }
}
