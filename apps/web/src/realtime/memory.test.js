import { describe, expect, it } from "vitest";
import { InMemoryRealtimeClient } from "./memory";
const event = (type) => ({
    event_id: crypto.randomUUID(),
    schema_version: 1,
    type,
    project_id: "p",
    session_id: "s",
    device_id: null,
    actor_id: null,
    occurred_at: new Date().toISOString(),
    data: {},
});
describe("InMemoryRealtimeClient", () => {
    it("delivers only to the subscribed channel and stops after unsubscribe", async () => {
        const client = new InMemoryRealtimeClient();
        const seen = [];
        const unsubscribe = await client.subscribe("projects/p/sessions/s", (e) => seen.push(e.type));
        client.emit("projects/p/sessions/other", event("user.joined"));
        client.emit("projects/p/sessions/s", event("device.connected"));
        unsubscribe();
        client.emit("projects/p/sessions/s", event("user.left"));
        expect(seen).toEqual(["device.connected"]);
    });
});
