import { apiAuth, apiBaseUrl } from "../api/client";
import { auth } from "../auth";
import { AppSyncEventsClient } from "./appsync";
import { LocalApiRealtimeClient } from "./localApi";
import { InMemoryRealtimeClient } from "./memory";
/**
 * - `local` (default): the local API's event stream (API must run with APP_ENV=local).
 * - `memory`: in-browser bus only; nothing arrives unless the page emits it.
 * - `appsync`: AWS AppSync Events, authorised with the Cognito ID token
 *   (`VITE_AUTH_MODE=cognito`).
 */
export function createRealtimeClient() {
    switch (import.meta.env.VITE_REALTIME_PROVIDER ?? "local") {
        case "appsync":
            return new AppSyncEventsClient({
                httpDomain: import.meta.env.VITE_APPSYNC_EVENTS_HTTP_DNS ?? "",
                realtimeDomain: import.meta.env.VITE_APPSYNC_EVENTS_REALTIME_DNS ?? "",
                auth: () => auth.realtimeHeaders(),
            });
        case "memory":
            return new InMemoryRealtimeClient();
        default:
            return new LocalApiRealtimeClient(apiBaseUrl, apiAuth);
    }
}
export const realtime = createRealtimeClient();
export { parseRealtimeEvent } from "./types";
