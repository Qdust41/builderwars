import type {
  CommandArg,
  Device,
  DeviceCommand,
  Job,
  JobType,
  Project,
  Session,
  SessionChannel,
} from "./types";

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
  constructor(
    private readonly baseUrl: string,
    private readonly auth: AuthHeaderProvider,
    private readonly fetchImpl: Fetch = (input, init) => fetch(input, init),
  ) {}

  private async request<T>(method: "GET" | "POST", path: string, body?: unknown): Promise<T> {
    const headers: Record<string, string> = { ...(await this.auth()) };
    if (body !== undefined) headers["Content-Type"] = "application/json";
    const res = await this.fetchImpl(`${this.baseUrl}${path}`, {
      method,
      headers,
      body: body === undefined ? undefined : JSON.stringify(body),
    });
    if (!res.ok) {
      let detail = res.statusText;
      try {
        detail = JSON.stringify((await res.json()).detail);
      } catch {
        /* non-JSON error body */
      }
      throw new ApiError(res.status, detail);
    }
    return (await res.json()) as T;
  }

  health = () => this.request<{ status: string; environment: string }>("GET", "/health");
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
  revokeDevice = (id: string) =>
    this.request<Device>("POST", `/devices/${encodeURIComponent(id)}/revoke`);
  listSessions = (projectId: string) =>
    this.request<Session[]>("GET", `/projects/${encodeURIComponent(projectId)}/sessions`);
  startSession = (projectId: string, deviceId?: string) =>
    this.request<Session>("POST", `/projects/${encodeURIComponent(projectId)}/sessions`, {
      device_id: deviceId ?? null,
    });
  getSession = (id: string) => this.request<Session>("GET", `/sessions/${encodeURIComponent(id)}`);
  getSessionChannel = (id: string) =>
    this.request<SessionChannel>("GET", `/sessions/${encodeURIComponent(id)}/channel`);
  createJob = (projectId: string, jobType: JobType) =>
    this.request<Job>("POST", `/projects/${encodeURIComponent(projectId)}/jobs`, {
      job_type: jobType,
    });
}

export const api = new ApiClient(
  import.meta.env.VITE_API_BASE_URL ?? "/api",
  devUserAuth(import.meta.env.VITE_DEV_USER ?? "dev-user"),
);
