// Mirrors contracts/realtime/event.v1.schema.json. The event type list comes from the
// generated API schema, so a new server-side type shows up here after `npm run gen:api`.
import type {
  CommandArg,
  CommandStatus,
  RealtimeEventType,
  TelemetryValue,
} from "../api/types";

export type { RealtimeEventType };

/** Exactly one of `session_id` / `device_id` is set; it decides the channel. */
export interface RealtimeEvent {
  event_id: string;
  schema_version: number;
  type: RealtimeEventType;
  project_id: string;
  session_id: string | null;
  device_id: string | null;
  actor_id: string | null;
  occurred_at: string;
  data: Record<string, unknown>;
}

/** `data` of a `device.telemetry` event. */
export interface DeviceTelemetryData {
  samples: { ts: string; readings: Record<string, TelemetryValue> }[];
}

/** `data` of a `device.log` event (same shape as `GET /devices/{id}/logs` entries). */
export interface DeviceLogData {
  at: string;
  kind: "log" | "event";
  level: string;
  message: string;
}

/** `data` of a `device.command.updated` event. Fetch `GET /commands/{id}` for the full record. */
export interface DeviceCommandUpdatedData {
  command_id: string;
  name: string;
  status: CommandStatus;
  detail: string | null;
  output: Record<string, CommandArg>;
}

export type Unsubscribe = () => void;

export interface SubscriptionHandlers {
  /**
   * Called each time the subscription becomes active, including after a reconnect. Events may
   * have been missed while disconnected, so refetch state from the API here.
   */
  onReady?: () => void;
  /** Called when the connection drops or the subscription is refused; the client retries. */
  onError?: (error: Error) => void;
}

/**
 * Provider-agnostic realtime client. Events are notifications only: after (re)subscribing,
 * refetch authoritative state from the API. Clients never publish device commands here.
 */
export interface RealtimeClient {
  subscribe(
    channel: string,
    onEvent: (event: RealtimeEvent) => void,
    handlers?: SubscriptionHandlers,
  ): Promise<Unsubscribe>;
}

// A Record so the compiler flags any event type added to the contract but missing here.
const KNOWN: Record<RealtimeEventType, true> = {
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
const KNOWN_TYPES: ReadonlySet<string> = new Set(Object.keys(KNOWN));

/** Validates an incoming event's envelope; returns null for anything unknown or malformed. */
export function parseRealtimeEvent(raw: unknown): RealtimeEvent | null {
  let value = raw;
  if (typeof value === "string") {
    try {
      value = JSON.parse(value);
    } catch {
      return null;
    }
  }
  if (typeof value !== "object" || value === null) return null;
  const e = value as Record<string, unknown>;
  if (typeof e.type !== "string" || !KNOWN_TYPES.has(e.type)) return null;
  if (typeof e.project_id !== "string") return null;
  const session = typeof e.session_id === "string" ? e.session_id : null;
  const device = typeof e.device_id === "string" ? e.device_id : null;
  if ((session === null) === (device === null)) return null;
  if (typeof e.data !== "object" || e.data === null || Array.isArray(e.data)) return null;
  return {
    event_id: String(e.event_id ?? ""),
    schema_version: typeof e.schema_version === "number" ? e.schema_version : 1,
    type: e.type as RealtimeEventType,
    project_id: e.project_id,
    session_id: session,
    device_id: device,
    actor_id: typeof e.actor_id === "string" ? e.actor_id : null,
    occurred_at: typeof e.occurred_at === "string" ? e.occurred_at : new Date().toISOString(),
    data: e.data as Record<string, unknown>,
  };
}
