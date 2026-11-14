/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_API_BASE_URL?: string;
  readonly VITE_DEV_USER?: string;
  readonly VITE_REALTIME_PROVIDER?: "local" | "appsync";
  readonly VITE_APPSYNC_EVENTS_ENDPOINT?: string;
}
