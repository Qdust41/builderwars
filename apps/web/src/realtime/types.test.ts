import { describe, expect, it } from "vitest";
import { parseRealtimeEvent } from "./types";

const base = {
  event_id: "e1",
  schema_version: 1,
  type: "device.log",
  project_id: "prj_1",
  session_id: null,
  device_id: "dev_1",
  actor_id: "dev_1",
  occurred_at: "2026-11-14T20:00:00Z",
  data: { message: "hi" },
};

describe("parseRealtimeEvent", () => {
  it("accepts a device event, as an object or a JSON string", () => {
    expect(parseRealtimeEvent(base)?.device_id).toBe("dev_1");
    expect(parseRealtimeEvent(JSON.stringify(base))?.type).toBe("device.log");
  });

  it("drops unknown types, missing or double scopes, and junk", () => {
    expect(parseRealtimeEvent({ ...base, type: "device.flash" })).toBeNull();
    expect(parseRealtimeEvent({ ...base, device_id: null })).toBeNull();
    expect(parseRealtimeEvent({ ...base, session_id: "ses_1" })).toBeNull();
    expect(parseRealtimeEvent({ ...base, data: [] })).toBeNull();
    expect(parseRealtimeEvent("{not json")).toBeNull();
    expect(parseRealtimeEvent(null)).toBeNull();
  });
});
