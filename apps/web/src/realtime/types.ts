// Mirrors contracts/realtime/event.v1.schema.json.
export type RealtimeEventType =
  | "user.joined"
  | "user.left"
  | "device.connected"
  | "device.disconnected"
  | "device.status_changed"
  | "project.activity"
  | "ai.run.started"
  | "ai.run.delta"
  | "ai.run.completed"
  | "firmware.build.started"
  | "firmware.build.completed";

export interface RealtimeEvent {
  event_id: string;
  schema_version: number;
  type: RealtimeEventType;
  project_id: string;
  session_id: string;
  actor_id: string | null;
  occurred_at: string;
  data: Record<string, unknown>;
}

export type Unsubscribe = () => void;

/**
 * Provider-agnostic realtime client. Events are notifications only: after (re)subscribing,
 * refetch authoritative state from the API. Clients never publish device commands here.
 */
export interface RealtimeClient {
  subscribe(channel: string, onEvent: (event: RealtimeEvent) => void): Promise<Unsubscribe>;
}
