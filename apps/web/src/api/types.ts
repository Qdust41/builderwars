// API types, taken from the generated `schema.gen.ts` (from contracts/api/openapi.json).
// Regenerate with `npm run gen:api` after `scripts/export_contracts.py`; never edit by hand.
import type { components } from "./schema.gen";

type Schemas = components["schemas"];

export type ConnectionStatus = Schemas["ConnectionStatus"];
export type JobType = Schemas["JobType"];
export type JobStatus = Schemas["JobStatus"];
export type CommandStatus = Schemas["CommandStatus"];
export type SessionStatus = Schemas["SessionStatus"];
export type RealtimeEventType = Schemas["RealtimeEventType"];

export type Health = Schemas["HealthOut"];
export type Project = Schemas["ProjectOut"];
export type Device = Schemas["DeviceOut"];
export type Session = Schemas["SessionOut"];
export type SessionChannel = Schemas["SessionChannelOut"];
export type DeviceChannel = Schemas["DeviceChannelOut"];
export type Job = Schemas["JobOut"];
export type DeviceCommand = Schemas["CommandOut"];
export type CommandArg = DeviceCommand["args"][string];
export type TelemetrySample = Schemas["TelemetrySampleOut"];
export type TelemetryValue = TelemetrySample["readings"][string];
export type DeviceLogEntry = Schemas["DeviceLogEntryOut"];
