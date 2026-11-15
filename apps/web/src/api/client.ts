import type {
  CommandArg,
  Device,
  DeviceChannel,
  DeviceCommand,
  DeviceLogEntry,
  Health,
  Job,
  JobType,
  Project,
  Sensor,
  SensorInput,
  SensorPreset,
  Session,
  SessionChannel,
  TargetBoard,
  TargetBoardInput,
  TelemetrySample,
  DeviceSetup,
} from "./types";

import { auth } from "../auth";

export class ApiError extends Error {
  constructor(
    readonly status: number,
    message: string,
  ) {
    super(message);
  }
}

/** Supplies auth headers. Local dev uses X-Dev-User; Cognito tokens replace it later. */
export type AuthHeaderProvider = () => Promise<Record<string, string>>;

export const devUserAuth =
  (userId: string): AuthHeaderProvider =>
  async () => ({ "X-Dev-User": userId });

export type Fetch = (input: string, init?: RequestInit) => Promise<Response>;

/** The only module that talks HTTP to the platform API. */
export class ApiClient {
  /** Called on any 401, e.g. to send the user back to sign-in. */
  onUnauthorized: (() => void) | undefined;

  constructor(
    private readonly baseUrl: string,
    private readonly auth: AuthHeaderProvider,
    private readonly fetchImpl: Fetch = (input, init) => fetch(input, init),
  ) {}

  private async request<T>(
    method: "GET" | "POST" | "PUT" | "DELETE",
    path: string,
    body?: unknown,
  ): Promise<T> {
    const headers: Record<string, string> = { ...(await this.auth()) };
    if (body !== undefined) headers["Content-Type"] = "application/json";
    const res = await this.fetchImpl(`${this.baseUrl}${path}`, {
      method,
      headers,
      body: body === undefined ? undefined : JSON.stringify(body),
    });
    if (res.status === 401) this.onUnauthorized?.();
    if (!res.ok) {
      let detail = res.statusText;
      try {
        detail = JSON.stringify((await res.json()).detail);
      } catch {
        /* non-JSON error body */
      }
      throw new ApiError(res.status, detail);
    }
    if (res.status === 204) return undefined as T;
    return (await res.json()) as T;
  }

  health = () => this.request<Health>("GET", "/health");
  listProjects = () => this.request<Project[]>("GET", "/projects");
  createProject = (name: string) => this.request<Project>("POST", "/projects", { name });
  getProject = (id: string) => this.request<Project>("GET", `/projects/${encodeURIComponent(id)}`);
  listDevices = (projectId: string) =>
    this.request<Device[]>("GET", `/projects/${encodeURIComponent(projectId)}/devices`);
  /** Defaults to a FREE-WILi 1-OG with a Bottlenose WiFi Orca (server-side defaults). */
  registerDevice = (projectId: string, displayName: string) =>
    this.request<Device>("POST", `/projects/${encodeURIComponent(projectId)}/devices`, {
      display_name: displayName,
    });
  /** Queues a command (role-based, FIFO per device); the result arrives asynchronously. */
  sendCommand = (
    projectId: string,
    deviceId: string,
    name: string,
    args: Record<string, CommandArg> = {},
  ) =>
    this.request<DeviceCommand>(
      "POST",
      `/projects/${encodeURIComponent(projectId)}/devices/${encodeURIComponent(deviceId)}/commands`,
      { name, args },
    );
  getCommand = (id: string) =>
    this.request<DeviceCommand>("GET", `/commands/${encodeURIComponent(id)}`);
  getDevice = (id: string) => this.request<Device>("GET", `/devices/${encodeURIComponent(id)}`);
  /** Newest `limit` samples, oldest first. */
  getTelemetry = (deviceId: string, limit = 300) =>
    this.request<TelemetrySample[]>(
      "GET",
      `/devices/${encodeURIComponent(deviceId)}/telemetry?limit=${limit}`,
    );
  /** Newest `limit` log lines and device events, oldest first. */
  getLogs = (deviceId: string, limit = 200) =>
    this.request<DeviceLogEntry[]>(
      "GET",
      `/devices/${encodeURIComponent(deviceId)}/logs?limit=${limit}`,
    );
  /** Realtime channel for the device (membership checked by the API). */
  getDeviceChannel = (deviceId: string) =>
    this.request<DeviceChannel>("GET", `/devices/${encodeURIComponent(deviceId)}/channel`);
  listSessions = (projectId: string) =>
    this.request<Session[]>("GET", `/projects/${encodeURIComponent(projectId)}/sessions`);
  startSession = (projectId: string, deviceId?: string) =>
    this.request<Session>("POST", `/projects/${encodeURIComponent(projectId)}/sessions`, {
      device_id: deviceId ?? null,
    });
  getSession = (id: string) => this.request<Session>("GET", `/sessions/${encodeURIComponent(id)}`);
  getSessionChannel = (id: string) =>
    this.request<SessionChannel>("GET", `/sessions/${encodeURIComponent(id)}/channel`);
  /** Laptop, FREE-WILi, target boards and sensors behind a device. */
  getDeviceSetup = (deviceId: string) =>
    this.request<DeviceSetup>("GET", `/devices/${encodeURIComponent(deviceId)}/setup`);
  addBoard = (deviceId: string, board: TargetBoardInput) =>
    this.request<TargetBoard>("POST", `/devices/${encodeURIComponent(deviceId)}/boards`, board);
  updateBoard = (deviceId: string, boardId: string, board: TargetBoardInput) =>
    this.request<TargetBoard>(
      "PUT",
      `/devices/${encodeURIComponent(deviceId)}/boards/${encodeURIComponent(boardId)}`,
      board,
    );
  /** Also removes the board's sensors. */
  deleteBoard = (deviceId: string, boardId: string) =>
    this.request<void>(
      "DELETE",
      `/devices/${encodeURIComponent(deviceId)}/boards/${encodeURIComponent(boardId)}`,
    );
  addSensor = (deviceId: string, sensor: SensorInput) =>
    this.request<Sensor>("POST", `/devices/${encodeURIComponent(deviceId)}/sensors`, sensor);
  updateSensor = (deviceId: string, sensorId: string, sensor: SensorInput) =>
    this.request<Sensor>(
      "PUT",
      `/devices/${encodeURIComponent(deviceId)}/sensors/${encodeURIComponent(sensorId)}`,
      sensor,
    );
  deleteSensor = (deviceId: string, sensorId: string) =>
    this.request<void>(
      "DELETE",
      `/devices/${encodeURIComponent(deviceId)}/sensors/${encodeURIComponent(sensorId)}`,
    );
  /** Common parts (TMP102, INA219, ...) with datasheet settings. */
  listSensorPresets = () => this.request<SensorPreset[]>("GET", "/sensor-presets");
  createJob = (projectId: string, jobType: JobType) =>
    this.request<Job>("POST", `/projects/${encodeURIComponent(projectId)}/jobs`, {
      job_type: jobType,
    });
}

export const apiBaseUrl = import.meta.env.VITE_API_BASE_URL ?? "/api";
export const apiAuth: AuthHeaderProvider = () => auth.apiHeaders();
export const api = new ApiClient(apiBaseUrl, apiAuth);
