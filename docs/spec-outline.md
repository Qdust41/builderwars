# Spec set outline — builderwars platform

How to write the specs: each document gets **Purpose → Requirements (numbered, testable) →
Constraints → Open items → Acceptance criteria**. Requirements must be phrased so they can
become tests or contract fixtures. Decisions in `docs/open-decisions.md` (2026-11-14) are
authoritative inputs; where a spec would contradict a decision, the decision wins unless a
new ADR supersedes it.

System in one paragraph (from the decisions): a host PC running CPython ≥ 3.10 sits next to
a FREE-WILi 1-OG board (dual RP2040, `_main.uf2` apps, USB serial via the `freewili` Python
package) with a Bottlenose WiFi Orca (ESP32-C6) for connectivity. The host is the platform's
"device": it publishes telemetry/logs over MQTT/TLS to AWS IoT Core, receives commands, and
performs UF2 firmware updates. Users work together in browser sessions (shared view +
control, no concurrent editing) and with an AI assistant (OpenAI-compatible providers
incl. Bedrock, propose-only gate). MVP scale < 10 boards, telemetry batched to 1 msg/5 s
per board, us-east-1, free-tier budget.

## Suggested writing order

Dependencies flow: protocol → device → cloud → app features → ops. Write in this order;
each spec should be reviewable on its own.

| Order | Spec | Depends on |
| --- | --- | --- |
| 1 | 00 Overview & personas | — |
| 2 | 01 Device protocol v1 | 00 |
| 3 | 02 Board runtime & board I/O | 01 |
| 4 | 03 Provisioning & device identity | 01, 02 |
| 5 | 04 Cloud ingest pipeline | 01 |
| 6 | 05 Users, projects & authorization | 00 |
| 7 | 06 Realtime sessions | 05 |
| 8 | 07 Device command path | 01, 02, 05 |
| 9 | 08 AI assistant | 05, 07 |
| 10 | 09 Firmware lifecycle | 02, 05 |
| 11 | 10 Jobs & background work | 04, 09 |
| 12 | 11 Observability & operations | 04–10 |
| 13 | 12 Security & threat model | all (write late, review early) |
| 14 | 13 Environments & deployment | all |

---

## 00 — Overview & personas

- Purpose: goals, non-goals, MVP boundary, personas.
- Personas: (a) builder operating their own FREE-WILi station; (b) collaborator invited to
  a project; (c) the host-PC process (a "device", not a persona); (d) operator on-call.
- Non-goals for MVP: concurrent code editing (CRDT), orgs/teams, local-network user access,
  on-board (RP2040) Python runtime, multi-region.
- Key system diagram: host+board → IoT Core → SQS → ingest → S3/RDS; web → FastAPI(Lambda)
  → SQS jobs → workers; AppSync Events for session notifications; AI runs as jobs.
- Acceptance: a new reader can state the MVP scope and the four data paths without other docs.

## 01 — Device protocol v1

Extends `docs/device-protocol.md` from provisional to normative.

- Envelope (as implemented in `device_protocol`): `message_id` (UUID), `schema_version`,
  `device_id`, `timestamp`, `message_type`, `sequence_number`, `firmware_version`,
  `hardware_model`, `payload`. Message types: telemetry, log, status, heartbeat, event,
  command, command_result. *(Review note: the earlier `session_id`/`seq`/`ts` names were
  aligned to the scaffold's field names; a separate host `session_id` is not needed because
  `sequence_number` persists across reboots (#14), and the name would collide with
  collaboration sessions.)*
- Topics: `devices/{device_id}/telemetry|logs|status|events|responses` (device→cloud),
  `devices/{device_id}/commands` (cloud→device). QoS 1 both ways. The cloud dedupes on
  `(device_id, message_id)`; `sequence_number` is for gap detection only (dedupe on `seq`
  would wrongly drop messages if a host's sequence file were ever reset). Commands dedupe
  on `command_id`.
- **Batched telemetry (decision #6, implemented):** the telemetry payload is
  `{"samples": [{"ts", "readings"}, ...]}` — 1 to 32 samples, ordered by `ts`, flushed every
  5 s window or at 32 samples; one `sequence_number` per flushed batch. Limits apply to the
  whole message.
- Limits: ≤32 KiB message, ≤16 KiB payload (`envelopes.py:18-19`); per-board ingress rate
  limit: burst up to 10 msg/s, sustained ceiling 60 msg/min (safety net in ingest; normal is ~0.2 msg/s).
- Gap detection: `sequence_number` strictly increasing per device, persisted across host
  reboots (decision #14); gaps record a `sequence_gap` event, never reject the stream.
- Versioning: `schema_version` field; server accepts N and N-1; unknown versions are
  rejected as `unsupported_version`.
- Invalid messages (any rejection reason) are **quarantined** (raw body kept under S3
  `rejected/` + metric), never silently dropped. The DLQ is reserved for messages whose
  *processing* keeps failing (e.g. DB down), since retrying an invalid message can't help.
- Acceptance: contract fixtures (valid + invalid) pass in CI; a malformed message is
  observable end-to-end (quarantine + metric) without crashing ingest.

## 02 — Board runtime & board I/O

The CPython runtime that runs on the host PC (decision #1, #2, #14).

- Board adapter (`device/src/board_runtime/hardware/freewili.py`, `FreeWiliSensors`): wraps
  the vendor `freewili` Python package (USB serial, `pyfwfinder` auto-discovery; `onewili`
  is not on PyPI) behind the `SensorReader` protocol; pinned `freewili==0.0.51`; all USB
  access isolated in this module (no other module touches serial). This spec decides which
  readings matter (the scaffold reads GPIO levels and buttons as placeholders).
- Connectivity: `awsiotsdk` v2 over MQTT/TLS, X.509 per-device identity, client id = IoT
  thing name; exponential backoff + jitter on reconnect; `OfflineBuffer` drains in order
  after reconnect (existing scaffold modules).
- Sequence counter persisted per device to `~/.builderwars/seq/<device_id>` (implemented:
  atomic write before each number is used, so a crash can skip but never reuse a number).
- **Telemetry batching (decision #6):** accumulate readings in memory; flush to the
  telemetry topic every 5 s or when the buffer reaches 32 samples, whichever first; each
  sample keeps its own timestamp; the batch goes through the same `OfflineBuffer` as
  everything else (so offline batches replay in order).
- Command dispatch: subscribe `devices/{device_id}/commands`; dispatch by command `name` to
  an allowlist of registered handlers; every command produces a `command_result`
  (`succeeded`/`failed`/`rejected` + detail). Unknown or expired command → `rejected`, not
  silence.
- Logging: discrete `log` messages over MQTT (decision #7); log level threshold from
  config; never log credentials/cert material.
- Graceful degradation: board disconnected → runtime keeps publishing `status: degraded`,
  queues commands locally with bounded size, drops oldest with an `event`.
- Acceptance: runtime boots against a real board+host (integration test, marked), survives
  board USB unplug/replug and network loss with ordered replay after recovery.

## 03 — Provisioning & device identity

- A device = one host+board pair, one IoT thing, one X.509 certificate (IoT Core
  certificate authorizer), one `device_id` = thing name.
- Provisioning flow (MVP, manual-assisted): CLI on the host
  (`builderwars provision --board-name ... --project ...`) → requests a device from the API
  (owner-authorized) → API mints thing + cert + policy → returns bootstrap bundle → host
  stores cert in `~/.builderwars/credentials/`.
- Thing groups: one per project; per-project IoT policy scoping topics to that project's
  device ids.
- Decommission: revoke cert, mark device `revoked` in DB, keep historical data.
- Acceptance: a new host can be provisioned end-to-end with the CLI + owner credentials;
  a revoked device is rejected at the IoT Core layer, not just the API.

## 04 — Cloud ingest pipeline

- IoT Core rule(s) → SQS (telemetry/logs/status/events/responses) with a DLQ per queue. The scaffold uses one rule and one ingest queue; split per family only if volumes differ a lot.
- Ingest worker (SQS-triggered Lambda): validate against `device_protocol` schema,
  dedupe `(device_id, seq)`, write normalized row to RDS, raw envelope to S3
  `raw/{device_id}/{yyyy}/{mm}/{dd}/`; ack only after both writes (or outbox pattern —
  decide in spec).
- Rate limiting + gap detection per decision #6/#14; violations → `events` table row +
  CloudWatch metric, never data loss.
- Retention: raw S3 30/90/365 days by env (existing `infrastructure/config.py`); RDS
  retention defined in spec (recommend: status/log 90 days, telemetry 365 days, commands
  permanent).
- Acceptance: 10 boards × 1 batched msg/5 s (each batch ≤32 samples) sustained for 24 h
  (load test against prod before real users, or a local replay of recorded traffic; no
  staging, decision #12) with zero unexplained gaps; an invalid message is quarantined and a message
  whose processing keeps failing lands in the DLQ (alarm firing deferred with #13).

## 05 — Users, projects & authorization

- Cognito user pool: email + password, self sign-up with an emailed code, MFA off for the
  MVP (decision #10, ADR 0005). Owner/admin adds existing accounts by email
  (`POST /projects/{id}/members`, role admin/member/viewer; only the owner grants or removes
  admin); `DELETE /projects/{id}/members/{user_id}` removes (or leaves); the owner can't leave.
- The API verifies the bearer token itself: RS256 via the pool JWKS, issuer, expiry, and the
  app client (`client_id` on access tokens, `aud` on ID tokens). Bad/missing token → 401.
- Per-project roles owner/admin/member/viewer; role → permission matrix (names as in
  `domain/projects/authorization.py`): `project:view` and `session:join` (all roles);
  `session:start`, `job:create`, `ai:run` (member+); `project:manage`,
  `project:manage_members`, `device:register`, `device:command`, `firmware:approve`
  (owner/admin).
- Projects own: devices, code, firmware artifacts, AI runs, sessions. All data access is
  project-scoped. A **non-member** gets 404 (so project/device ids can't be probed); a
  **member lacking a permission** gets 403.
- API: FastAPI on Lambda (Mangum) behind API Gateway; Cognito authorizer (dev env:
  `dev-header` auth mode from `apps/api/src/api/settings.py`).
- Acceptance: role matrix table in spec maps 1:1 to policy tests in `tests/contract`.

## 06 — Realtime sessions

- Sessions = shared view + control (decision #4); created per project, anyone with
  `session:join` may join; presence broadcast.
- Transport: AppSync Events (notifications only — join/leave, activity, command results);
  full state always fetched via REST (events are hints, never the source of truth).
- Reconnect: client re-fetches state on reconnect; no event replay from the server (MVP).
- Session metadata (who joined when) persisted to RDS for audit.
- Acceptance: two browsers viewing one project see each other's presence and command
  results within ~2 s; killing one browser degrades the other to a presence notice, not an
  error.
- Device channel (ADR 0005, built): `projects/{project}/devices/{device}` carries
  `device.telemetry`, `device.log` and `device.command.updated` for everyone viewing a device.
  Channel ids use `-` for `_` (AppSync segments are `[A-Za-z0-9-]`). The device page loads
  `GET /devices/{id}/telemetry` and `/logs`, subscribes to the channel from
  `GET /devices/{id}/channel`, and refetches on every (re)subscribe.
- Web client (built): `apps/web/src/realtime/appsync.ts` speaks the `aws-appsync-event-ws`
  protocol (one socket, many subscriptions, keepalive timeout, resubscribe on reconnect).
  It needs the Cognito ID token from sign-in (workstream B). Locally the browser reads
  `GET /local/realtime` (server-sent events) instead.

## 07 — Device command path

- Web → API `POST /projects/{id}/devices/{device_id}/commands` (authz `device:command`) →
  validated command object (schema in `device_protocol`) → SQS `device_commands` → worker
  publishes to IoT Core topic `devices/{device_id}/commands` (QoS 1) → result arrives via
  the ingest path → broadcast to the project session.
- Per-board command queue: FIFO semantics (decision #5); max queue depth per board (e.g.
  32); commands carry `command_id` (UUID, matching the protocol's `CommandPayload`) and
  expire if unacknowledged within 30 s → `timed_out`. Implemented in the scaffold except the
  AWS adapters, the timeout sweeper and the session broadcast.
- Idempotency: `command_id` deduped; replay of a delivered command is not re-published.
- Acceptance: command sent from browser is observable on a real board (integration test)
  and its result appears in both the API and the session view.

## 08 — AI assistant

- Runs as background jobs (spec 10), not inline in the API.
- Provider (decision #8): **one client speaking the OpenAI-compatible Chat Completions
  API** (chat + tool calls), two auth modes: (a) `openai_compatible` — `base_url` + API
  key (OpenAI, Azure, local); (b) `bedrock` — Bedrock's OpenAI-compatible
  `bedrock-runtime.{region}.amazonaws.com` endpoint, AWS SigV4 auth from the worker's IAM
  role, no API key. Config per env: `AI_BASE_URL` + `AI_API_KEY` (mode a) or
  `AI_PROVIDER=bedrock` + region (mode b); model name `AI_MODEL` chosen in this spec.
  Bedrock path keeps data in the AWS boundary; API-key path goes to the configured
  external provider (allowed). Keys in Secrets Manager; the Bedrock path needs none.
- Context: project code, recent telemetry/events, session transcript — **after redaction**
  (redaction helper is mandatory; spec lists the redaction rules: credentials, personal
  data, other projects' data).
- Tools: read telemetry/events, read project code, propose code diff, propose firmware
  change request (spec 9), propose command (routed through spec 7 with the acting user's
  permissions — AI never bypasses authz).
- Gate (hard requirement): AI output is a **proposal** stored on the run; application to
  board code or firmware requires explicit human confirmation. No autonomous writes.
- Runs: persistent record (prompt ref, model, tokens, cost, tool calls, proposal, status)
  in RDS; cost metered per project.
- Acceptance: a run that proposes a firmware change cannot change anything without a
  human-confirmed apply action; redaction is tested with fixture secrets.

## 09 — Firmware lifecycle

- Artifact = `_main.uf2` (wilibsp dual-CPU build) + metadata (`FirmwareArtifact` in
  `packages/domain/src/domain/firmware/models.py`): version, sha256, S3 location,
  compatible hardware (board model + `required_extensions`, the Orca set), artifact states
  built → approved (or rejected) → revoked. "Deployed" and "rolled back" are per-device
  facts, not artifact states: they are `firmware_deploy` / `firmware_rollback` jobs and the
  device's reported `firmware_version`.
- Build: worker job runs the wilibsp toolchain (Lambda; Fargate if > 15 min); build
  inputs = project code + toolchain version, pinned; output uploaded to S3
  `firmware/{project_id}/{version}/`.
- Deploy (decision #9): job → host downloads from S3 → sha256 verify → writes UF2 to both
  CPUs over USB (fwOGAppExplorer path) → reports `deploy_result` (ok/fail + which CPU).
  Signature verification optional in MVP (`signature_reference`).
- Rollback: deploy previous approved version; N-1 always retained.
- Precondition: host online (IoT `status: online`) and board USB-connected; deploy to an
  offline host queues with a deadline.
- Acceptance: build → approve → deploy → verify → rollback all exercised in prod against a dedicated test device with a
  real board; a corrupt artifact (bad sha256) is refused by the host before flashing.

## 10 — Jobs & background work

- Single SQS job queue (`background_jobs`) + per-type handlers in `apps/workers`
  (existing scaffold); job types: ai_run, firmware_build, firmware_deploy, firmware_rollback,
  (later: data export).
- Jobs are durable: at-least-once, idempotent handlers (`job_id` dedupe), exponential
  retry with max 5, then DLQ.
- Lambda for short jobs; Fargate escalation path documented (same queue, different
  consumer) — triggered only when a build/AI run outgrows Lambda limits.
- Per-project concurrency limits: 1 active firmware_build, 1 active firmware_deploy per
  board, N=3 active ai_runs.
- Acceptance: a killed worker mid-job leaves the system in a resumable state; duplicate
  delivery causes no double side effects (verified by idempotency tests).

## 11 — Observability & operations

- Logging: structured JSON from every component (Lambda: platform logs; API/worker: own
  logger); project-scoped fields (`project_id`, `device_id`) on every line.
- Metrics: CloudWatch — ingest lag, DLQ depth, per-board msg rate, command latency
  (sent→result), job duration/failures, API 5xx rate.
- Alarms: **out of MVP scope (decision #13, 2026-11-14)** — placeholder
  `<ops-alerts@example.com>` stays; no SNS wiring. The metrics below + DLQs are the
  mechanism; alarm actions are a later one-line-each addition.
- On-call: single email (owner to supply when alarms are in scope).
- Runbook section: DLQ replay, cert revocation, device decommission, stuck deploy.
- Acceptance: each DLQ has a documented replay procedure; a chaos test (poison message)
  is quarantined, and a handler that keeps failing lands its message in the DLQ (alarm firing deferred with #13).

## 12 — Security & threat model

- Trust boundaries: user (browser) / API / cloud services / IoT Core / host runtime /
  board USB / Orca WiFi.
- Device auth: X.509 per device; cert lifecycle (renewal: MVP = re-provision; auto-renew
  later); client-id/thing-name binding; per-project topic scoping.
- Host hardening: credentials in `~/.builderwars/credentials/` (0600), never in code or
  logs; host is a semi-trusted client — all commands re-validated in the API (never trust
  the host's claim about which project a device belongs to).
- Secrets: Secrets Manager for AI keys, RDS creds; no secrets in CDK params.
- Data: project-scoped access control everywhere (spec 5); AI egress rules (spec 8);
  S3 buckets private, presigned URLs short-lived.
- Threats to name explicitly: rogue host impersonating a device; command injection via AI
  proposals; USB flash of tampered UF2 (mitigation: sha256 from S3 over TLS, never
  host-local); session hijack (Cognito token lifecycle).
- Acceptance: each named threat has a mitigation row and (where testable) a test.

## 13 — Environments & deployment

- Regions: us-east-1 only (decision #11); region always from `CDK_DEFAULT_REGION`.
- Envs: dev (local, in-memory adapters, `dev-header` auth) and prod (AWS, RDS free tier
  `db.t4g.micro`). **No deployed staging for the MVP** (decision #12): changes go local →
  prod.
- Free-tier budget plan: IoT Core 1M msg/mo, API GW 1M req, Lambda 400k GB-s, S3
  (negligible), AppSync Events free tier, RDS 750 h/mo t4g.micro. Expected usage at MVP
  scale with 5 s telemetry batching (decision #6): 10 boards × 12 msg/min ≈ **518k
  IoT msg/mo — inside the 1M free tier**; all other services fit free tier with wide
  margin. Budget alarm at $25/mo as the safety net (normal spend ≈ $0).
- CI/CD: GitHub Actions — unit + contract tests on PR;
  prod deploy manual gate.
- Acceptance: `cdk deploy -c env=prod` from a clean checkout produces the full prod environment;
  monthly cost at MVP scale < $10 (tracked by a budget alarm at $25).

---

## Cross-cutting rules for all specs

1. Every requirement numbered `R<n>-<m>` so tests can cite it.
2. Anything that would change `packages/device_protocol` schemas must update
   `contracts/` and pass `scripts/export_contracts.py` in the same PR (ADR 0002).
3. No new AWS SDK imports in `packages/domain` or `packages/application` (scaffold rule).
4. Every spec ends with the open items it still leaves, cross-referenced back into
   `docs/open-decisions.md`.
