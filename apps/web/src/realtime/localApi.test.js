import { describe, expect, it, vi } from "vitest";
import { devUserAuth } from "../api/client";
import { LocalApiRealtimeClient, readServerSentEvents } from "./localApi";
function streamOf(chunks, keepOpen = false) {
    const enc = new TextEncoder();
    return new ReadableStream({
        start(controller) {
            for (const c of chunks)
                controller.enqueue(enc.encode(c));
            if (!keepOpen)
                controller.close();
        },
    });
}
const event = {
    event_id: "e1",
    type: "device.telemetry",
    project_id: "prj_1",
    session_id: null,
    device_id: "dev_1",
    data: { samples: [] },
};
describe("readServerSentEvents", () => {
    it("joins events split across chunks and skips comments", async () => {
        const seen = [];
        await readServerSentEvents(streamOf([": subscribed\n\n", "data: {\"a\"", ":1}\n\ndata: x\r\n\r\n"]), (d) => seen.push(d));
        expect(seen).toEqual(['{"a":1}', "x"]);
    });
});
describe("LocalApiRealtimeClient", () => {
    it("sends the dev identity, reports ready, delivers events and stops on unsubscribe", async () => {
        const calls = [];
        const fetchImpl = vi.fn(async (url, init) => {
            calls.push([url, init]);
            return new Response(streamOf([`data: ${JSON.stringify(event)}\n\n`], true), { status: 200 });
        });
        const client = new LocalApiRealtimeClient("/api", devUserAuth("alice"), fetchImpl);
        const events = [];
        const onReady = vi.fn();
        const off = await client.subscribe("projects/prj-1/devices/dev-1", (e) => events.push(e), {
            onReady,
        });
        await vi.waitFor(() => expect(events).toHaveLength(1));
        expect(onReady).toHaveBeenCalledOnce();
        expect(calls[0][0]).toBe("/api/local/realtime?channel=projects%2Fprj-1%2Fdevices%2Fdev-1");
        expect((calls[0][1]?.headers)["X-Dev-User"]).toBe("alice");
        off();
        expect((calls[0][1]?.signal).aborted).toBe(true);
    });
    it("reports errors and reconnects, firing ready again", async () => {
        let n = 0;
        const fetchImpl = vi.fn(async () => {
            n += 1;
            if (n === 1)
                return new Response("nope", { status: 503 });
            return new Response(streamOf([], true), { status: 200 });
        });
        const client = new LocalApiRealtimeClient("", devUserAuth("a"), fetchImpl, () => 0);
        const onError = vi.fn();
        const onReady = vi.fn();
        const off = await client.subscribe("c", () => undefined, { onError, onReady });
        await vi.waitFor(() => expect(onReady).toHaveBeenCalledOnce());
        expect(onError).toHaveBeenCalledOnce();
        off();
    });
});
