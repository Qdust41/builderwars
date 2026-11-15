# 0009 — Board data reaches the cloud through the signed-in CLI, not IoT certificates

Status: accepted (2026-11-15, owner decision: "the board does not need to be certified for now;
the logs will be uploaded by the user via the CLI after they log in")

## Context
The dashboard updated live only in local development: in AWS, device data was meant to arrive
over MQTT from boards holding AWS IoT X.509 certificates (ADR 0004), and the ingest worker did
not publish realtime events. Provisioning a certificate per board is manual (deployment guide
step 11) and the board itself is currently unreliable. The owner chose to skip device
certificates for now.

## Decision
1. **Upload endpoint.** `POST /devices/{device_id}/messages` takes up to 200
   `{topic, payload}` messages, exactly what the board would publish over MQTT. The caller is a
   signed-in user (Cognito JWT, as for every API route) with the new `device:upload`
   permission on the device's project (members, admins, owners; not viewers). Every topic must
   name the URL's device and the ingest pipeline checks the envelope against the topic, so an
   upload can never write into another device. Messages then go through the same
   `DeviceMessageIngestService` as MQTT (validation, quarantine, idempotency on
   `(device_id, message_id)`, sequence gaps), synchronously in the API Lambda, storing raw
   bodies in PostgreSQL. Per-message results are returned; one bad message does not fail the rest.
2. **Live fan-out.** Ingest's device events (`device.telemetry`, `device.log`,
   `device.command.updated`) are collected during the request and published to AppSync Events on
   `projects/{p}/devices/{d}` afterwards, up to 5 per publish call. The ingest and
   command-dispatch workers now publish the same events too (`EVENTS_HTTP_DNS` + publish grant),
   so MQTT boards will also be live when certificates come back.
3. **CLI sign-in.** `builderwars login` reads `GET /client-config` (public; region, pool and
   client ids only) and signs in to Cognito with `USER_PASSWORD_AUTH`, enabled on the existing
   web client so the API and AppSync keep one token audience. The password goes to Cognito only;
   the CLI stores the refresh and ID tokens in `<state-dir>/account.json` (0600) and refreshes
   the one-hour ID token itself. Against a local API (`auth_mode: dev-header`) it stores a dev
   user name instead.
4. **CLI commands.** `builderwars run --cloud` streams through `DEVICE_TRANSPORT=cloud`
   (`CloudApiTransport`: outages keep messages in the runtime's offline buffer; messages the API
   refuses as invalid are dropped). `builderwars upload <file>` sends saved JSON lines or the
   log CSV, re-addressed to the target device. `builderwars devices` lists ids.

## Consequences
- Any member can stream data as any device in their project: identity is "this person says
  this is their board", not a hardware credential. Fine for the MVP's trust model; device
  certificates (ADR 0004, PR #4) remain the path for unattended boards.
- Dashboard commands do not reach a CLI-connected board yet (they go out over IoT only). A
  polling endpoint like the local bridge's `commands/next` would close that gap.
- Each upload request costs one API Lambda invocation plus a few database round trips per
  message; `run --cloud` sends one request per message (telemetry is batched every 5 s), which
  is well inside the free tier for a handful of boards.
- Still open from ADR 0008: the AppSync `onSubscribe` membership check. Until it exists, any
  signed-in account that learns a device's channel name could subscribe to it.
