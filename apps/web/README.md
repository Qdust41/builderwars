# Web app

React + TypeScript (Vite). Pages: projects, project (devices + sessions), device dashboard,
session.

```bash
npm install
npm run dev        # http://localhost:5173, proxies /api -> http://localhost:8000
npm run typecheck
npm test
npm run build
npm run gen:api    # regenerate src/api/schema.gen.ts after scripts/export_contracts.py
npm run check:api  # CI: fail if schema.gen.ts is stale
```

## See a device update live (no AWS)

```bash
# 1. API with in-memory data (from the repo root)
uv run uvicorn api.main:app --reload
# 2. Web app: open http://localhost:5173, create a project, register a device, open it
cd apps/web && npm run dev
# 3. Host runtime with simulated sensors, sending to the local API (repo root).
#    Use the device id shown in the device page's URL. A 2 s batch window makes the chart
#    move faster than the real 5 s default.
DEVICE_ID=<dev_...> DEVICE_TRANSPORT=local-api DEVICE_BATCH_WINDOW_S=2 \
  BUILDERWARS_STATE_DIR=/tmp/bw-state uv run python -m board_runtime.main
```

Telemetry, logs and command results then arrive live; **Send ping** round-trips through the
host. The local API routes that make this work (`/local/*`) only exist with the in-memory
backend (ADR 0006).

## Layout

- `src/api/client.ts` — the only module that calls the HTTP API. Auth headers come from an
  `AuthHeaderProvider` (local: `X-Dev-User`; Cognito later).
- `src/api/types.ts` — names for the generated `schema.gen.ts` types (from
  `contracts/api/openapi.json`). Never edit `schema.gen.ts` by hand.
- `src/realtime/` — `RealtimeClient` interface, chosen by `VITE_REALTIME_PROVIDER`:
  `local` (default; the local API's event stream), `memory` (in-browser bus for tests) or
  `appsync` (AWS AppSync Events WebSocket; needs the Cognito ID token, not wired until
  sign-in lands, plus `VITE_APPSYNC_EVENTS_HTTP_DNS` / `VITE_APPSYNC_EVENTS_REALTIME_DNS`).
- `src/device/` — the device page's data: `useDeviceLive` (load, subscribe, refetch on every
  reconnect) and pure telemetry helpers.
- `src/components/` — `MetricChart` (one SVG chart per reading), `LogStream`, `CommandList`.
- The browser never publishes device commands or realtime events.
