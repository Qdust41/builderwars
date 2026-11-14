import { AppSyncEventsClient } from "./appsync";
import { LocalRealtimeClient } from "./local";
import type { RealtimeClient } from "./types";

export function createRealtimeClient(): RealtimeClient {
  if (import.meta.env.VITE_REALTIME_PROVIDER === "appsync") {
    return new AppSyncEventsClient(import.meta.env.VITE_APPSYNC_EVENTS_ENDPOINT ?? "");
  }
  return new LocalRealtimeClient();
}

export type { RealtimeClient, RealtimeEvent } from "./types";
