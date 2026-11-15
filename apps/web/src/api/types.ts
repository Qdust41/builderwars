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

// Test setup: laptop -> FREE-WILi -> up to 4 target boards, and their sensors.
export type DeviceSetup = Schemas["DeviceSetupOut"];
export type HostReport = Schemas["HostReport"];
export type BridgeReport = Schemas["BridgeReport"];
export type TargetBoard = Schemas["TargetBoardOut"];
export type TargetBoardInput = Schemas["TargetBoardIn"];
export type Sensor = Schemas["SensorOut"];
export type SensorInput = Schemas["SensorIn"];
export type SensorBus = SensorInput["bus"];
export type SensorDecode = Schemas["SensorDecode"];
export type SensorDataType = SensorDecode["data_type"];
export type SensorProtocol = SensorBus["protocol"];
export type I2CBus = Schemas["I2CBus"];
export type SPIBus = Schemas["SPIBus"];
export type UARTBus = Schemas["UARTBus"];
export type GPIOBus = Schemas["GPIOBus"];
export type SensorPreset = Schemas["SensorPreset"];

// Auto-fix: an OpenAI-compatible endpoint + GitHub repo per project; errors become PRs.
export type AutoFixSettings = Schemas["AutoFixSettingsOut"];
export type AutoFixSettingsInput = Schemas["AutoFixSettingsIn"];
export type AutoFixRun = Schemas["AutoFixRunOut"];
export type AutoFixRunStatus = Schemas["AutoFixRunStatus"];
