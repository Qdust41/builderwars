/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_API_BASE_URL?: string;
  readonly VITE_DEV_USER?: string;
  readonly VITE_REALTIME_PROVIDER?: "local" | "memory" | "appsync";
  /** AppSync Events HTTP domain (CDK output EventsHttpDns). */
  readonly VITE_APPSYNC_EVENTS_HTTP_DNS?: string;
  /** AppSync Events realtime domain (CDK output EventsRealtimeDns). */
  readonly VITE_APPSYNC_EVENTS_REALTIME_DNS?: string;
}
