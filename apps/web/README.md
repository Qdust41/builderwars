# Web app

React + TypeScript (Vite). Placeholder pages only: projects, project (devices + sessions),
device, session.

```bash
npm install
npm run dev        # http://localhost:5173, proxies /api -> http://localhost:8000
npm run typecheck
npm test
npm run build
```

- `src/api/client.ts` — the only module that calls the HTTP API. Auth headers come from an
  `AuthHeaderProvider` (local: `X-Dev-User`; Cognito later).
- `src/realtime/` — `RealtimeClient` interface; `local.ts` in-browser bus; `appsync.ts` stub for
  AWS AppSync Events. Provider chosen by `VITE_REALTIME_PROVIDER`.
- Types mirror `contracts/api/openapi.json` and `contracts/realtime/event.v1.schema.json`
  (TODO: generate them).
- The browser never publishes device commands or realtime events.
