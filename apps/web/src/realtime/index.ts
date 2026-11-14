import { apiAuth, apiBaseUrl } from "../api/client";
import { AppSyncEventsClient } from "./appsync";
import { LocalApiRealtimeClient } from "./localApi";
import { InMemoryRealtimeClient } from "./memory";
import type { RealtimeClient } from "./types";

/**
 * - `local` (default): the local API's event stream (API must run with APP_ENV=local).
 * - `memory`: in-browser bus only; nothing arrives unless the page emits it.
 * - `appsync`: AWS AppSync Events. Needs Cognito sign-in for the token (not wired yet).
 */
export function createRealtimeClient(): RealtimeClient {
  switch (import.meta.env.VITE_REALTIME_PROVIDER ?? "local") {
    case "appsync":
      return new AppSyncEventsClient({
        httpDomain: import.meta.env.VITE_APPSYNC_EVENTS_HTTP_DNS ?? "",
        realtimeDomain: import.meta.env.VITE_APPSYNC_EVENTS_REALTIME_DNS ?? "",
        // TODO (workstream B): return { Authorization: <Cognito ID token> } once sign-in lands.
        auth: async () => {
          throw new Error("AppSync realtime needs Cognito sign-in, which is not wired yet");
        },
      });
    case "memory":
      return new InMemoryRealtimeClient();
    default:
      return new LocalApiRealtimeClient(apiBaseUrl, apiAuth);
  }
}

export const realtime = createRealtimeClient();

export { parseRealtimeEvent } from "./types";
export type {
  DeviceCommandUpdatedData,
  DeviceLogData,
  DeviceTelemetryData,
  RealtimeClient,
  RealtimeEvent,
} from "./types";
