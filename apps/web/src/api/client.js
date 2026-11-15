import { auth } from "../auth";
export class ApiError extends Error {
    status;
    constructor(status, message) {
        super(message);
        this.status = status;
    }
}
export const devUserAuth = (userId) => async () => ({ "X-Dev-User": userId });
/** The only module that talks HTTP to the platform API. */
export class ApiClient {
    baseUrl;
    auth;
    fetchImpl;
    /** Called on any 401, e.g. to send the user back to sign-in. */
    onUnauthorized;
    constructor(baseUrl, auth, fetchImpl = (input, init) => fetch(input, init)) {
        this.baseUrl = baseUrl;
        this.auth = auth;
        this.fetchImpl = fetchImpl;
    }
    async request(method, path, body) {
        const headers = { ...(await this.auth()) };
        if (body !== undefined)
            headers["Content-Type"] = "application/json";
        const res = await this.fetchImpl(`${this.baseUrl}${path}`, {
            method,
            headers,
            body: body === undefined ? undefined : JSON.stringify(body),
        });
        if (res.status === 401)
            this.onUnauthorized?.();
        if (!res.ok) {
            let detail = res.statusText;
            try {
                detail = JSON.stringify((await res.json()).detail);
            }
            catch {
                /* non-JSON error body */
            }
            throw new ApiError(res.status, detail);
        }
        if (res.status === 204)
            return undefined;
        return (await res.json());
    }
    health = () => this.request("GET", "/health");
    listProjects = () => this.request("GET", "/projects");
    createProject = (name) => this.request("POST", "/projects", { name });
    getProject = (id) => this.request("GET", `/projects/${encodeURIComponent(id)}`);
    listDevices = (projectId) => this.request("GET", `/projects/${encodeURIComponent(projectId)}/devices`);
    /** Defaults to a FREE-WILi 1-OG with a Bottlenose WiFi Orca (server-side defaults). */
    registerDevice = (projectId, displayName) => this.request("POST", `/projects/${encodeURIComponent(projectId)}/devices`, {
        display_name: displayName,
    });
    /** Queues a command (role-based, FIFO per device); the result arrives asynchronously. */
    sendCommand = (projectId, deviceId, name, args = {}) => this.request("POST", `/projects/${encodeURIComponent(projectId)}/devices/${encodeURIComponent(deviceId)}/commands`, { name, args });
    getCommand = (id) => this.request("GET", `/commands/${encodeURIComponent(id)}`);
    getDevice = (id) => this.request("GET", `/devices/${encodeURIComponent(id)}`);
    /** Newest `limit` samples, oldest first. */
    getTelemetry = (deviceId, limit = 300) => this.request("GET", `/devices/${encodeURIComponent(deviceId)}/telemetry?limit=${limit}`);
    /** Newest `limit` log lines and device events, oldest first. */
    getLogs = (deviceId, limit = 200) => this.request("GET", `/devices/${encodeURIComponent(deviceId)}/logs?limit=${limit}`);
    /** Realtime channel for the device (membership checked by the API). */
    getDeviceChannel = (deviceId) => this.request("GET", `/devices/${encodeURIComponent(deviceId)}/channel`);
    listSessions = (projectId) => this.request("GET", `/projects/${encodeURIComponent(projectId)}/sessions`);
    startSession = (projectId, deviceId) => this.request("POST", `/projects/${encodeURIComponent(projectId)}/sessions`, {
        device_id: deviceId ?? null,
    });
    getSession = (id) => this.request("GET", `/sessions/${encodeURIComponent(id)}`);
    getSessionChannel = (id) => this.request("GET", `/sessions/${encodeURIComponent(id)}/channel`);
    /** Laptop, FREE-WILi, target boards and sensors behind a device. */
    getDeviceSetup = (deviceId) => this.request("GET", `/devices/${encodeURIComponent(deviceId)}/setup`);
    addBoard = (deviceId, board) => this.request("POST", `/devices/${encodeURIComponent(deviceId)}/boards`, board);
    updateBoard = (deviceId, boardId, board) => this.request("PUT", `/devices/${encodeURIComponent(deviceId)}/boards/${encodeURIComponent(boardId)}`, board);
    /** Also removes the board's sensors. */
    deleteBoard = (deviceId, boardId) => this.request("DELETE", `/devices/${encodeURIComponent(deviceId)}/boards/${encodeURIComponent(boardId)}`);
    addSensor = (deviceId, sensor) => this.request("POST", `/devices/${encodeURIComponent(deviceId)}/sensors`, sensor);
    updateSensor = (deviceId, sensorId, sensor) => this.request("PUT", `/devices/${encodeURIComponent(deviceId)}/sensors/${encodeURIComponent(sensorId)}`, sensor);
    deleteSensor = (deviceId, sensorId) => this.request("DELETE", `/devices/${encodeURIComponent(deviceId)}/sensors/${encodeURIComponent(sensorId)}`);
    /** Common parts (TMP102, INA219, ...) with datasheet settings. */
    listSensorPresets = () => this.request("GET", "/sensor-presets");
    createJob = (projectId, jobType) => this.request("POST", `/projects/${encodeURIComponent(projectId)}/jobs`, {
        job_type: jobType,
    });
}
export const apiBaseUrl = import.meta.env.VITE_API_BASE_URL ?? "/api";
export const apiAuth = () => auth.apiHeaders();
export const api = new ApiClient(apiBaseUrl, apiAuth);
