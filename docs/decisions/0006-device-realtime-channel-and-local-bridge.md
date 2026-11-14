# 0006 — Device realtime channel and the local development bridge

Status: accepted (workstream F, web dashboard)

## Context
The device page must show a device's telemetry, logs and command results as they arrive.
Realtime events were session-scoped only (`projects/{p}/sessions/{s}`), but telemetry belongs
to a device and should reach everyone looking at it, in or out of a session. Locally, the API,
the ingest worker and the host simulator were separate processes with separate in-memory
stores, so nothing a simulated host sent could reach the browser.

## Decision
1. **Device channel.** Device events go to `projects/{project}/devices/{device}`. A
   `RealtimeEvent` names exactly one of `session_id` / `device_id`, which picks the channel.
   Three new event types: `device.telemetry` (the batch's samples), `device.log` (log lines and
   device events) and `device.command.updated` (id, status, detail, output). Ingest publishes
   them for registered devices; the command dispatcher publishes `sent` / `timed_out`. A failed
   publish is logged and never fails ingest. `GET /devices/{id}/channel` hands the channel out
   after the membership check, as `GET /sessions/{id}/channel` already did.
2. **AppSync-safe channel names.** AppSync Events channel segments allow only `[A-Za-z0-9-]`,
   so channels spell ids with `-` instead of `_` (`prj_ab12` -> `prj-ab12`). Ids are
   `<prefix>_<hex>`, so the mapping is reversible (`application.realtime.channel_segment`).
   The AppSync publisher must use `RealtimeEvent.channel` as given.
3. **Read endpoints.** `GET /devices/{id}/telemetry?limit=` and `GET /devices/{id}/logs?limit=`
   return the newest records, oldest first. `TelemetryRepository` gained `recent_telemetry`
   and `recent_logs`; the PostgreSQL adapter (workstream A) must implement them.
4. **Local bridge (LOCAL ONLY).** With the in-memory backend the API mounts `/local/*`:
   `POST /local/device-messages` (stands in for IoT Core + the ingest worker),
   `POST /local/devices/{id}/commands/next` (stands in for the dispatcher + IoT Core) and
   `GET /local/realtime?channel=` (server-sent events in place of AppSync Events). The host
   runtime reaches it with `DEVICE_TRANSPORT=local-api`. These routes are left out of the
   OpenAPI contract and cannot exist outside `APP_ENV=local|test`, because
   `validate_settings` already refuses the in-memory backend there (ADR 0003).
5. **Web types are generated.** `apps/web/src/api/schema.gen.ts` comes from
   `contracts/api/openapi.json` via `openapi-typescript`; CI fails if it is stale.

## Consequences
- One `npm run dev` + `uvicorn` + host runtime shows live telemetry locally with no AWS.
- Workstream A implements two more repository reads; workstream C's AppSync publisher only
  has to publish each `RealtimeEvent` to `"/" + event.channel` with IAM auth.
- The AppSync namespace stays `projects`; its onSubscribe membership check (TODO in
  `infrastructure/stacks/realtime.py`) must cover `devices/` channels as well as `sessions/`.
- Command results are broadcast on the device channel; broadcasting them into sessions too
  (spec 06/07) is still open.
