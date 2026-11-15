import { afterEach, describe, expect, it, vi } from "vitest";
import { AppSyncEventsClient, base64Url, toAppSyncChannel } from "./appsync";
class FakeSocket {
    url;
    protocols;
    readyState = 0;
    sent = [];
    closed = false;
    onopen = null;
    onmessage = null;
    onclose = null;
    onerror = null;
    constructor(url, protocols) {
        this.url = url;
        this.protocols = protocols;
    }
    send(data) {
        this.sent.push(JSON.parse(data));
    }
    close() {
        this.closed = true;
        this.readyState = 3;
        this.onclose?.({});
    }
    open() {
        this.readyState = 1;
        this.onopen?.({});
    }
    receive(msg) {
        this.onmessage?.({ data: JSON.stringify(msg) });
    }
}
const flush = () => new Promise((r) => setTimeout(r, 0));
function setup() {
    const sockets = [];
    let id = 0;
    const client = new AppSyncEventsClient({
        httpDomain: "abc.appsync-api.us-east-1.amazonaws.com",
        realtimeDomain: "abc.appsync-realtime-api.us-east-1.amazonaws.com",
        auth: async () => ({ Authorization: "id-token" }),
        createSocket: (url, protocols) => {
            const s = new FakeSocket(url, protocols);
            sockets.push(s);
            return s;
        },
        reconnectDelay: () => 0,
        newId: () => `sub-${++id}`,
    });
    return { client, sockets };
}
const deviceEvent = {
    event_id: "e1",
    type: "device.log",
    project_id: "prj_1",
    session_id: null,
    device_id: "dev_1",
    data: { at: "2026-11-14T20:00:00Z", kind: "log", level: "info", message: "hi" },
};
afterEach(() => vi.useRealTimers());
describe("AppSyncEventsClient", () => {
    it("connects with the event-ws subprotocol and auth header, then subscribes", async () => {
        const { client, sockets } = setup();
        const onReady = vi.fn();
        const events = [];
        await client.subscribe("projects/prj-1/devices/dev-1", (e) => events.push(e), { onReady });
        await flush();
        const [socket] = sockets;
        expect(socket.url).toBe("wss://abc.appsync-realtime-api.us-east-1.amazonaws.com/event/realtime");
        expect(socket.protocols[0]).toBe("aws-appsync-event-ws");
        const header = JSON.parse(atob(socket.protocols[1].slice("header-".length).replace(/-/g, "+").replace(/_/g, "/")));
        expect(header).toEqual({
            host: "abc.appsync-api.us-east-1.amazonaws.com",
            Authorization: "id-token",
        });
        socket.open();
        expect(socket.sent).toEqual([{ type: "connection_init" }]);
        socket.receive({ type: "connection_ack", connectionTimeoutMs: 300000 });
        await flush();
        expect(socket.sent[1]).toEqual({
            type: "subscribe",
            id: "sub-1",
            channel: "/projects/prj-1/devices/dev-1",
            authorization: { host: "abc.appsync-api.us-east-1.amazonaws.com", Authorization: "id-token" },
        });
        socket.receive({ type: "subscribe_success", id: "sub-1" });
        expect(onReady).toHaveBeenCalledOnce();
        socket.receive({ type: "data", id: "sub-1", event: JSON.stringify(deviceEvent) });
        socket.receive({ type: "data", id: "sub-1", event: JSON.stringify({ ...deviceEvent, type: "x.y" }) });
        socket.receive({ type: "data", id: "other", event: JSON.stringify(deviceEvent) });
        expect(events.map((e) => e.data.message)).toEqual(["hi"]);
    });
    it("resubscribes after the connection drops and fires ready again", async () => {
        const { client, sockets } = setup();
        const onReady = vi.fn();
        const onError = vi.fn();
        await client.subscribe("projects/p/devices/d", () => undefined, { onReady, onError });
        await flush();
        sockets[0].open();
        sockets[0].receive({ type: "connection_ack" });
        await flush();
        sockets[0].receive({ type: "subscribe_success", id: "sub-1" });
        sockets[0].close();
        expect(onError).toHaveBeenCalledOnce();
        await flush();
        await flush();
        expect(sockets).toHaveLength(2);
        sockets[1].open();
        sockets[1].receive({ type: "connection_ack" });
        await flush();
        expect(sockets[1].sent.at(-1)).toMatchObject({ type: "subscribe", id: "sub-1" });
        sockets[1].receive({ type: "subscribe_success", id: "sub-1" });
        expect(onReady).toHaveBeenCalledTimes(2);
    });
    it("closes the socket when no keepalive arrives in time", async () => {
        vi.useFakeTimers();
        const { client, sockets } = setup();
        await client.subscribe("c", () => undefined);
        await vi.advanceTimersByTimeAsync(0);
        sockets[0].open();
        sockets[0].receive({ type: "connection_ack", connectionTimeoutMs: 1000 });
        await vi.advanceTimersByTimeAsync(900);
        sockets[0].receive({ type: "ka" });
        await vi.advanceTimersByTimeAsync(900);
        expect(sockets[0].closed).toBe(false);
        await vi.advanceTimersByTimeAsync(200);
        expect(sockets[0].closed).toBe(true);
    });
    it("unsubscribes and closes the socket with the last subscription", async () => {
        const { client, sockets } = setup();
        const off = await client.subscribe("c", () => undefined);
        await flush();
        sockets[0].open();
        sockets[0].receive({ type: "connection_ack" });
        await flush();
        off();
        expect(sockets[0].sent.at(-1)).toEqual({ type: "unsubscribe", id: "sub-1" });
        expect(sockets[0].closed).toBe(true);
        await flush();
        expect(sockets).toHaveLength(1); // no reconnect after a deliberate close
    });
    it("reports a refused subscription", async () => {
        const { client, sockets } = setup();
        const onError = vi.fn();
        await client.subscribe("c", () => undefined, { onError });
        await flush();
        sockets[0].open();
        sockets[0].receive({ type: "connection_ack" });
        await flush();
        sockets[0].receive({ type: "subscribe_error", id: "sub-1", errors: [{ message: "Unauthorized" }] });
        expect(onError.mock.calls[0][0].message).toContain("Unauthorized");
    });
});
describe("helpers", () => {
    it("encodes base64url without padding and prefixes channels", () => {
        expect(base64Url("??>")).toBe("Pz8-");
        expect(toAppSyncChannel("projects/a")).toBe("/projects/a");
    });
});
