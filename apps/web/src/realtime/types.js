// A Record so the compiler flags any event type added to the contract but missing here.
const KNOWN = {
    "user.joined": true,
    "user.left": true,
    "device.connected": true,
    "device.disconnected": true,
    "device.status_changed": true,
    "project.activity": true,
    "ai.run.started": true,
    "ai.run.delta": true,
    "ai.run.completed": true,
    "firmware.build.started": true,
    "firmware.build.completed": true,
    "device.telemetry": true,
    "device.log": true,
    "device.command.updated": true,
};
const KNOWN_TYPES = new Set(Object.keys(KNOWN));
/** Validates an incoming event's envelope; returns null for anything unknown or malformed. */
export function parseRealtimeEvent(raw) {
    let value = raw;
    if (typeof value === "string") {
        try {
            value = JSON.parse(value);
        }
        catch {
            return null;
        }
    }
    if (typeof value !== "object" || value === null)
        return null;
    const e = value;
    if (typeof e.type !== "string" || !KNOWN_TYPES.has(e.type))
        return null;
    if (typeof e.project_id !== "string")
        return null;
    const session = typeof e.session_id === "string" ? e.session_id : null;
    const device = typeof e.device_id === "string" ? e.device_id : null;
    if ((session === null) === (device === null))
        return null;
    if (typeof e.data !== "object" || e.data === null || Array.isArray(e.data))
        return null;
    return {
        event_id: String(e.event_id ?? ""),
        schema_version: typeof e.schema_version === "number" ? e.schema_version : 1,
        type: e.type,
        project_id: e.project_id,
        session_id: session,
        device_id: device,
        actor_id: typeof e.actor_id === "string" ? e.actor_id : null,
        occurred_at: typeof e.occurred_at === "string" ? e.occurred_at : new Date().toISOString(),
        data: e.data,
    };
}
