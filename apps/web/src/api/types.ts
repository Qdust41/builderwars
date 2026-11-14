// Mirrors contracts/api/openapi.json. TODO: generate these types from the OpenAPI file
// (e.g. openapi-typescript) instead of maintaining them by hand.
export type ConnectionStatus = "unknown" | "online" | "offline";
export type JobType =
  | "ai_run"
  | "firmware_build"
  | "firmware_deploy"
  | "firmware_rollback"
  | "test_run"
  | "data_analysis";
export type JobStatus = "queued" | "running" | "succeeded" | "failed" | "cancelled";

export interface Project {
  id: string;
  name: string;
  owner_user_id: string;
  created_at: string;
  updated_at: string;
}

export interface Device {
  id: string;
  project_id: string;
  display_name: string;
  hardware_model: string;
  extensions: string[];
  firmware_version: string | null;
  connection_status: ConnectionStatus;
  last_seen_at: string | null;
  created_at: string;
}

export interface Session {
  id: string;
  project_id: string;
  device_id: string | null;
  created_by: string;
  status: "active" | "ended";
  created_at: string;
}

export interface SessionChannel {
  session_id: string;
  channel: string;
  event_types: string[];
}

export interface Job {
  id: string;
  project_id: string;
  device_id: string | null;
  job_type: JobType;
  status: JobStatus;
  error_summary: string | null;
  created_at: string;
}

export type CommandStatus = "queued" | "sent" | "succeeded" | "failed" | "rejected" | "timed_out";
export type CommandArg = number | boolean | string;

export interface DeviceCommand {
  id: string;
  project_id: string;
  device_id: string;
  name: string;
  args: Record<string, CommandArg>;
  requested_by: string;
  status: CommandStatus;
  created_at: string;
  expires_at: string | null;
  completed_at: string | null;
  detail: string | null;
  output: Record<string, CommandArg>;
}
