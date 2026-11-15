# Web app

React + TypeScript (Vite), styled with Tailwind CSS v4 and lucide-react icons. Pages: sign-in,
projects, project (devices + sessions), device dashboard, session. Light and dark themes follow
the OS.

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
host. The local API routes that make this work (`/local/*`) only exist when the API
runs with `APP_ENV=local` or `test` (ADR 0008).

## In prod

Every merge to `main` builds the app (`scripts/build_web_prod.sh`, which reads the Cognito and
AppSync ids from the deployed stacks) and serves it from CloudFront at
<https://builderwars.jimweaver.com>, with `/api/*` routed to the HTTP API. To run the dev server
against prod instead, see step 8 of the [deployment guide](../../docs/deployment-guide.md).

Boards feed the device page through the `builderwars` CLI (`builderwars run --cloud`, see the
root [README](../../README.md#the-builderwars-cli)). Locally you can do the same against the
local API: `uv run builderwars login --api http://localhost:8000`, then
`uv run builderwars run --cloud --device-id <dev_...>`.

## Sign-in

`VITE_AUTH_MODE=dev-header` (default, local only) sends `VITE_DEV_USER` as `X-Dev-User`.
`VITE_AUTH_MODE=cognito` shows an email + password sign-in page (with account creation and
the emailed verification code) against the user pool, using Amplify Auth (SRP). Set
`VITE_COGNITO_USER_POOL_ID` and `VITE_COGNITO_CLIENT_ID` from the CDK outputs `UserPoolId` and
`UserPoolClientId`, and run the API with `AUTH_MODE=cognito`. The API gets the access token;
AppSync Events gets the ID token. Admin-created accounts are asked for a new password on first
sign-in. Password reset and MFA are not built yet.

## Layout

- `src/api/client.ts` — the only module that calls the HTTP API. Auth headers come from
  `src/auth/` (`X-Dev-User` locally, `Authorization: Bearer <access token>` with Cognito).
- `src/auth/` — `AuthGate` (sign-in page until signed in), dev and Cognito auth services.
- `src/api/types.ts` — names for the generated `schema.gen.ts` types (from
  `contracts/api/openapi.json`). Never edit `schema.gen.ts` by hand.
- `src/realtime/` — `RealtimeClient` interface, chosen by `VITE_REALTIME_PROVIDER`:
  `local` (default; the local API's event stream), `memory` (in-browser bus for tests) or
  `appsync` (AWS AppSync Events WebSocket with the Cognito ID token; needs
  `VITE_AUTH_MODE=cognito` plus `VITE_APPSYNC_EVENTS_HTTP_DNS` / `VITE_APPSYNC_EVENTS_REALTIME_DNS`).
- `src/device/` — the device page's data: `useDeviceLive` (load, subscribe, refetch on every
  reconnect) and pure telemetry helpers.
- `src/components/` — `MetricChart` (one SVG chart per reading), `LogStream`, `CommandList`, and
  shared pieces in `ui.tsx` (page header, status pill, empty state, error banner).
- `src/styles.css` — design tokens (CSS variables for light and dark) exposed to Tailwind as
  `bg-surface`, `text-fg`, `text-muted`, `border-line`, `bg-accent` and so on, plus the `btn-*`,
  `input` and `card` component classes. Change the palette here, not in components.
- The browser never publishes device commands or realtime events.
