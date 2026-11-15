/** Reconnect delay: 0.5 s, 1 s, 2 s ... capped at 15 s, with up to 20% jitter. */
export function reconnectDelayMs(attempt, random = Math.random) {
    const base = Math.min(15_000, 500 * 2 ** Math.max(0, attempt));
    return Math.round(base * (1 + 0.2 * random()));
}
