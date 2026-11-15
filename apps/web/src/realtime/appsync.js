import { reconnectDelayMs } from "./backoff";
import { parseRealtimeEvent, } from "./types";
const OPEN = 1;
const DEFAULT_KEEPALIVE_TIMEOUT_MS = 300_000;
export class AppSyncEventsClient {
    config;
    socket = null;
    connected = false;
    subs = new Map();
    attempt = 0;
    keepaliveTimer;
    reconnectTimer;
    keepaliveTimeoutMs = DEFAULT_KEEPALIVE_TIMEOUT_MS;
    constructor(config) {
        this.config = config;
    }
    async subscribe(channel, onEvent, handlers = {}) {
        const sub = {
            id: this.config.newId?.() ?? crypto.randomUUID(),
            channel: toAppSyncChannel(channel),
            onEvent,
            handlers,
        };
        this.subs.set(sub.id, sub);
        if (this.connected)
            void this.sendSubscribe(sub);
        else if (!this.socket && this.reconnectTimer === undefined)
            void this.connect();
        return () => this.unsubscribe(sub.id);
    }
    unsubscribe(id) {
        if (!this.subs.delete(id))
            return;
        if (this.connected)
            this.send({ type: "unsubscribe", id });
        if (this.subs.size === 0)
            this.shutdown();
    }
    async connect() {
        let headers;
        try {
            headers = await this.authHeaders();
        }
        catch (err) {
            this.fail(err);
            return;
        }
        if (this.subs.size === 0)
            return;
        const create = this.config.createSocket ??
            ((url, protocols) => new WebSocket(url, protocols));
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
            if (this.socket !== socket)
                return;
            this.socket = null;
            this.connected = false;
            clearTimeout(this.keepaliveTimer);
            if (this.subs.size > 0)
                this.fail(new Error("AppSync Events connection closed"));
        };
    }
    onMessage(raw) {
        let msg;
        try {
            msg = JSON.parse(String(raw));
        }
        catch {
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
                for (const sub of this.subs.values())
                    void this.sendSubscribe(sub);
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
                if (!sub)
                    return;
                const event = parseRealtimeEvent(msg.event);
                if (event)
                    sub.onEvent(event);
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
    async sendSubscribe(sub) {
        let authorization;
        try {
            authorization = await this.authHeaders();
        }
        catch (err) {
            sub.handlers.onError?.(err instanceof Error ? err : new Error(String(err)));
            return;
        }
        if (!this.subs.has(sub.id))
            return;
        this.send({ type: "subscribe", id: sub.id, channel: sub.channel, authorization });
    }
    async authHeaders() {
        return { host: this.config.httpDomain, ...(await this.config.auth()) };
    }
    send(message) {
        if (this.socket && this.socket.readyState === OPEN)
            this.socket.send(JSON.stringify(message));
    }
    armKeepalive() {
        clearTimeout(this.keepaliveTimer);
        // No "ka" within the server's timeout means the connection is dead.
        this.keepaliveTimer = setTimeout(() => this.socket?.close(), this.keepaliveTimeoutMs);
    }
    fail(err) {
        const error = err instanceof Error ? err : new Error(String(err));
        for (const sub of this.subs.values())
            sub.handlers.onError?.(error);
        if (this.subs.size === 0 || this.reconnectTimer !== undefined)
            return;
        const delay = (this.config.reconnectDelay ?? reconnectDelayMs)(this.attempt++);
        this.reconnectTimer = setTimeout(() => {
            this.reconnectTimer = undefined;
            if (this.subs.size > 0 && !this.socket)
                void this.connect();
        }, delay);
    }
    shutdown() {
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
export function toAppSyncChannel(channel) {
    return channel.startsWith("/") ? channel : `/${channel}`;
}
export function base64Url(text) {
    const bytes = new TextEncoder().encode(text);
    let binary = "";
    for (const b of bytes)
        binary += String.fromCharCode(b);
    return btoa(binary).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}
function describeErrors(errors) {
    if (!Array.isArray(errors))
        return "unknown error";
    return errors
        .map((e) => (typeof e === "object" && e && "message" in e ? String(e.message) : String(e)))
        .join("; ");
}
