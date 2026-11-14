# Product decisions

Answers recorded 2026-11-14 from the project owner. Status: **DECIDED** = confirmed by the
owner (or settled by the board's documented design); **RECOMMENDED** = proposed, changeable
before the matching spec is written. Where a decision changes scaffold assumptions, the
delta is called out.

## Context that drives most answers

- **The board** is a **FREE-WILi 1-OG** (FreeWili 1 / Classic): dual **RP2040** (main CPU +
  display CPU), iCE40 FPGA, CC1101 sub-GHz radio, SD card, USB. Apps ship as a single
  `_main.uf2` flashed to **both** CPUs (fwOGAppExplorer does this). Per the vendor docs the
  OGs are "deliberately simple terminals: all game logic, filtering and the agents run on
  the laptop" — on-device user code is WASM guests (C/Rust) in the board's interpreter.
  Sources: freewili.com/specs/rp2350.html (2-board context), docs.freewili.com/hardware/,
  docs.freewili.com/files-and-apps/running-apps/, github.com/freewili/fwOGAppExplorer,
  github.com/freewili/onewili (python package: "your PC / USB serial via pyfwfinder").
- **The standard extension** is the **Bottlenose WiFi Orca** (ESP32-C6, 2.4 GHz dual-mode
  WiFi AP/STA, Bluetooth, USB-C, Qwiic; 20-pin Orca connector with EEPROM auto-detect).
  Sources: shop.freewili.com/products/humpback-orca-copy, docs.freewili.com/hardware/orca-modules/.
- **Topology (owner-decided):** a **host PC sits next to the board**. The host runs the
  CPython board runtime, talks to the board over USB serial using the `onewili` Python
  package (3.10+), and holds the internet connection. The platform's "device" is the
  **host+board pair**; the board never touches the cloud directly.
- **Scale (owner-decided):** MVP < 10 boards concurrently, sampled ~1/s but **batched on the wire to 1 MQTT message per 5 s** per board (decision #6, confirmed 2026-11-14).
- **Budget (owner-decided):** us-east-1, hackathon project — free tier / very cheap.

## Decisions

| # | Question | Decision | Status & rationale |
| --- | --- | --- | --- |
| 1 | Exact board hardware, OS, Python version, hardware interfaces? | Board: FREE-WILi 1-OG (dual RP2040, iCE40 FPGA, CC1101, SD, USB; `_main.uf2` dual-CPU apps). Extension: Bottlenose WiFi Orca (ESP32-C6). Runtime: **CPython ≥ 3.10 on the host PC** (not on the RP2040); board I/O through the `FreeWiliSensors` adapter (`device/src/board_runtime/hardware/freewili.py`) wrapping the vendor's `freewili` Python package (PyPI; `onewili` is not published there, see note below) behind `SensorReader`; MQTT via `awsiotsdk` v2. | **DECIDED.** Changes the scaffold: `device/src/board_runtime` now targets the host; add `board_io` adapter; ADR 0002's MicroPython contingency stays documented but is not the primary path (no pydantic port needed). |
| 2 | Board connects directly to AWS, or via a local gateway? | Direct: the **host** connects to IoT Core over MQTT/TLS with per-device X.509 identity (one thing per host+board pair). No Greengrass, no local gateway. The Orca is only a network adapter. | **DECIDED.** Scaffold assumption holds; client id = IoT thing name as in `device/src/board_runtime/connectivity/mqtt_client.py`. |
| 3 | Do users also connect to the board over USB / local network? | USB is the **local provisioning path only**: the host PC is physically wired to the board (onewili serial + UF2 flashing). No local network interface is exposed to users; all user interaction is through the cloud. | **DECIDED.** Refines the scaffold's "not supported": USB exists by hardware necessity, just not as a user-facing platform feature. |
| 4 | "Multiplayer" = shared viewing/control, simultaneous code editing, or both? | **Shared viewing + control.** Sessions stream activity; no concurrent code editing; AppSync Events carries notifications only; CRDT layer deferred. | **DECIDED by owner (2026-11-14).** Scaffold assumption holds. |
| 5 | Can several users control one board at once? Locking? | **Role-based, no lock.** Any user with `device:command` may send commands; commands queue per board (worker side); results broadcast to the session. Add lock/lease only if conflicts become a real problem. | **DECIDED by owner (2026-11-14).** Supersedes "owners/admins only": the role that holds `device:command` is owner/admin by default, but the mechanism is role-based with a queue, not a lock. |
| 6 | Number of boards, message rates, payload sizes, retention? | MVP: < 10 boards concurrent. Telemetry is **batched host-side: 1 MQTT message per 5 s window or 32 samples, whichever first** (each sample keeps its own timestamp). Payloads well under 16 KiB. Keep protocol limits ≤32 KiB message / ≤16 KiB payload (`packages/device_protocol/src/device_protocol/envelopes.py:18-19`). Keep raw retention 30/365 days (dev/prod; no staging, see #12) — at this volume S3 cost is negligible (order 0.1 GB/month). Wire volume: 10 boards × 12 msg/min ≈ 518k messages/month, inside the IoT Core 1M free tier. | **DECIDED.** Scaffold values stand; batching confirmed by owner 2026-11-14. Rate limiting spec item: per-board burst up to 10 msg/s, sustained ceiling 60 msg/min (ingress safety net, ~5× above the normal ~12 msg/min). *(Reworded 2026-11-14: the earlier "10 msg/s ceiling, 60/min burst" had burst below the sustained rate.)* |
| 7 | Logs: continuous streams, periodic telemetry, events, or file uploads? | Discrete `log` messages over MQTT (scaffold `device/src/board_runtime/logging/forwarder.py`); telemetry batched at 5 s / 32 samples (see #6); no continuous streams; crash-dump file uploads deferred until actually needed. | **DECIDED.** Scaffold assumption holds; batching per #6. |
| 8 | AI provider/model, privacy requirements, may project data go to external providers? | **External providers allowed.** One wire protocol for all providers: the **OpenAI-compatible Chat Completions API**, with two auth modes — (a) `openai_compatible`: any `base_url` + API key (OpenAI, Azure OpenAI, local Ollama/LM Studio); (b) `bedrock`: Amazon Bedrock's OpenAI-compatible `bedrock-runtime.{region}.amazonaws.com` endpoint with **AWS SigV4 auth via the worker's IAM role** (no API key) — the "stays in AWS" option. So the owner's "OpenAI-compatible or AWS" are the **same bucket**: one client, two auth modes (if "AWS Kira" meant **Kiro**, note: Kiro is AWS's agentic IDE — a dev-time tool, not a backend LLM provider). Default model name + auth mode chosen when spec 8 is written. Redaction helper must run before any project data leaves; hard gate: AI **proposes, never silently applies** changes to board code or firmware. | **DECIDED by owner (2026-11-14)**: provider class + "same bucket" resolution; model name deferred to spec 8. |
| 9 | Firmware toolchain, signing, update mechanism, rollback? | "Firmware" = `_main.uf2` (wilibsp build, dual-CPU). OTA: job queue → host downloads artifact from S3 → **sha256 verify** → writes UF2 to the board over USB (same path as fwOGAppExplorer). Cryptographic signature optional for MVP, recorded in `FirmwareArtifact.signature_reference`. Rollback = redeploy the previous version (keep N-1). Precondition: host powered and USB-connected. Toolchain runs in a worker (Lambda for small builds, Fargate if the build outgrows 15 min). | **DECIDED** (follows from #1/#2; signing depth is the one RECOMMENDED part — sha256 mandatory, signature optional). |
| 10 | User roles, project sharing, org/team boundaries? | Per-project roles owner/admin/member/viewer. No orgs for MVP. Sharing = owner/admin adds an existing account by email (only the owner grants admin); no public invite links. Sign-in: Cognito email + password, **self sign-up on** (email verification code), **MFA off** for the MVP. See ADR 0005. | **DECIDED** (owner, 2026-11-14). |
| 11 | Region, environment strategy, budget, data residency? | **us-east-1**, local dev + prod (no deployed staging, see #12), **AWS free tier / minimal spend**: IoT Core free tier (1M msg/mo), API GW 1M req, Lambda free tier, S3 negligible, AppSync Events free tier, RDS free tier `db.t4g.micro` (12 mo). Region stays `CDK_DEFAULT_REGION`-driven — set it in the deploy env, no code change. No data-residency constraints. | **DECIDED by owner (2026-11-14).** |
| 12 | Is RDS acceptable cost-wise for the first shared environment, or should dev use something else? | **RDS free tier (`db.t4g.micro`) for prod only.** Dev is local with the in-memory adapters. **No deployed staging for the MVP:** changes go local → prod. (In-memory adapters can't back a deployed environment, so the original "staging on in-memory" answer was replaced.) | **DECIDED by owner (2026-11-14).** Revisit if prod needs a pre-release AWS environment (options: shared prod RDS with its own schema, or a separate instance at ~$12–15/month). |
| 13 | Who receives operational alarms? | **Out of MVP scope.** Placeholder `<ops-alerts@example.com>` stays in CDK config; no SNS wiring for now. DLQs still exist as the failure mechanism; adding alarm actions is later work (one config change each). | **DEFERRED by owner (2026-11-14).** |
| 14 | Should the device sequence number persist across reboots (gap detection)? | **Yes.** Persist the per-device sequence counter in a small file on the host (e.g. `~/.builderwars/seq/<device_id>`), written atomically with each batch flush. Makes "message lost" distinguishable from "device restarted" in the ingest pipeline's gap detection. | **DECIDED** (technical; cheap and strictly better for gap detection). |

## Notes from the scaffold review (2026-11-14)

- **`onewili` vs `freewili`.** `github.com/freewili/onewili` is referenced above, but no
  `onewili` package is published on PyPI. The vendor's published library is `freewili`
  (github.com/freewili/freewili-python, Python 3.10+, MIT), which has the same
  `pyfwfinder` discovery and a `FreeWili` serial device API (`find_first`, `open`, `get_io`,
  `read_all_buttons`, `reset_to_uf2_bootloader`, ...). The adapter uses `freewili==0.0.51`.
  It is installed on the host only, not locked in `uv.lock`, because it pins
  `typing-extensions` exactly and would downgrade pydantic for the whole workspace.
- **Staging (#12)** as first written (in-memory on AWS) couldn't work; the owner then chose
  no deployed staging for the MVP.
- **Python 3.10 on the host (#1)** means `packages/device_protocol` and `device/` must stay
  3.10-compatible. A CI job now runs their tests on 3.10. Cloud code stays on 3.12.

## What the scaffold now implements per decision

| # | Implemented | Still TODO |
| --- | --- | --- |
| 1 | Host runtime targets CPython 3.10+; `FreeWiliSensors` adapter (GPIO + buttons as placeholder readings); `DEVICE_SENSORS=freewili`; `BoardUnavailableError` → `status: degraded` + `board_disconnected` event | Pick the real sensor set (spec 02); run against a real board |
| 2 | `MqttTransport` on `awsiotsdk` (mTLS, client id = thing name, QoS 1); `mqtt` extra | Exercise against a dev IoT endpoint; provisioning (spec 03) |
| 4 | Unchanged (notifications only, no CRDT) | Presence, session broadcast of command results |
| 5 | Command path: `POST /projects/{id}/devices/{device_id}/commands`, `GET /commands/{id}`, per-device bound of 32 pending, 30 s expiry, dispatcher worker, results applied by ingest (a device can't complete another device's command) | AWS adapters, timeout sweeper, session broadcast |
| 6/7 | Telemetry payload is now `{"samples": [{"ts", "readings"}]}` (1–32 samples); host batches per 5 s window or 32 samples; new `event` message type on `devices/{id}/events` | Ingest rate limiting |
| 8 | `ai_platform.providers.ProviderConfig` (`openai_compatible` / `bedrock`, `AI_MODEL` required), client stub; new `ai:run` permission (member+) | Client implementation and default model (spec 08) |
| 9 | `JobType.FIRMWARE_DEPLOY/ROLLBACK`; artifact `required_extensions`; host `verify_sha256`; UF2 flasher stub | Build/deploy executors, dual-CPU flashing |
| 10 | `AUTH_MODE=cognito` verifies JWTs (JWKS, issuer, client, expiry); `GET/POST /projects/{id}/members`, `DELETE /projects/{id}/members/{user_id}`; Cognito pool: self sign-up, email + password, MFA off | Role change, ownership transfer, SES email sender, hosted UI domain (spec 06) |
| 11/12 | CDK envs are `dev` (synth/sandbox) and `prod`; no staging. RDS only in prod, 20 GB with no storage autoscaling (free tier); commands queue + DLQ | Budget alarm needs an address (#13) |
| 13 | `ops_alert_email` placeholder in `infrastructure/config.py`, not wired | — |
| 14 | `FileSequenceStore` (`~/.builderwars/seq/<device_id>`, atomic write before use); ingest records a `sequence_gap` event and never rejects | — |

## Follow-ups (not blockers)

- Wire operational alarms + a real address once in scope (closes #13).
- Pick the default AI model name and auth mode (API key vs Bedrock) when writing spec 8.
- The FREE-WILi adapter (spec 02) is pinned to `freewili==0.0.51`; it still needs a check
  against a real board, marked as an integration test.
- If a FREE-WILi 2 board ever enters the fleet (RP2350, optional RPi CM0 headless Linux),
  specs 2/3 must be re-checked — the CM0 variant would run CPython on-board.
