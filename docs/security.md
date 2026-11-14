# Security model (scaffold)

This describes intended controls and which ones exist today. Stubs are not security; nothing
here is production-ready.

## Identities

| Who | Mechanism | State |
| --- | --- | --- |
| Humans | Cognito user pool; API Gateway JWT authoriser + in-app verification | Pool/authoriser in CDK; in-app verification TODO. Local uses `X-Dev-User` header. |
| Devices | One X.509 certificate per board, attached to an IoT thing + `DevicePolicy` | Policy in CDK; provisioning TODO. |
| Backend | IAM roles per function, least privilege | API: send to jobs queue, read artifacts. Ingest: put `raw/*`. Jobs: artifacts r/w. |

The two identity systems are separate: a user can never act as a device and vice versa.

## Guard rails in code

- `api.settings.validate_settings` refuses `AUTH_MODE=dev-header` and `REPOSITORY_BACKEND=memory`
  unless `APP_ENV` is `local`/`test`, so local shortcuts can't silently reach a deployed env.
- Project membership is checked on every project-scoped operation (`Authorizer`); non-members get
  404 so ids can't be probed. Role matrix: `domain/projects/authorization.py`.
- Device messages: identity from topic, strict schema, size limits, idempotency.
- Realtime events reject secret-looking keys and `command` fields, and are size-limited. Only the
  backend (IAM) may publish to AppSync Events.
- Board commands are an allowlist of named functions; unknown or expired commands are rejected.

## Secrets

- Never commit secrets, certificates or private keys. `.gitignore` blocks common key/cert
  extensions, `.env`, `certs/`, `secrets/`.
- Device config references certificate *paths* only; code never logs or stores their contents.
- No account ids, credentials or certificates are hard-coded in CDK (a synth test checks for
  12-digit account ids). RDS credentials are generated into Secrets Manager.
- Never store device private keys in database rows.

## AI controls (`packages/ai`)

- Allowlisted tools only; there is no shell, exec, flash or deploy tool.
- Tools are classed `read_only`, `proposal`, `privileged`. Only read-only tools run without
  approval. Privileged tools (build/test jobs) need approval from a role with
  `firmware:approve`.
- The model never has more access than the human it acts for (permission checked per call).
- Every gate decision is audit-logged; `AiRun` records inputs/outputs by reference, tool calls and
  approvals.
- `redact()` strips secret-looking keys, PEM blocks and AWS key ids from context (defence in
  depth). Whether project data may go to an external model provider is open decision #8.
- Generated firmware is never flashed or deployed automatically.

## Firmware

Model only. Before any deployment exists: signed artifacts, checksum + signature verification
on the board, hardware compatibility checks, staged rollout, failure reporting and rollback
(open decision #9).

## Known gaps (must close before real users)

1. Cognito JWT verification in the API.
2. AppSync subscribe-time membership check (`onSubscribe` handler).
3. Device provisioning flow and certificate rotation/revocation.
4. Reject messages from unregistered device ids.
5. Rate limiting (API Gateway throttling, per-device message quotas).
6. Audit log persistence and retention policy.
7. CORS restricted to the deployed web origin.
8. Alarm actions (SNS → on-call).
