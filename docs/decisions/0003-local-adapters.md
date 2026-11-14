# 0003 — In-memory adapters are local/test only

Status: accepted (scaffold)

## Context
The scaffold must run without AWS, but fakes must never quietly back a deployed environment.

## Decision
Ports live in `application.ports`. In-memory implementations live in
`application.adapters.memory`, labelled LOCAL/TEST ONLY. The API validates settings at startup
and refuses `REPOSITORY_BACKEND=memory` or `AUTH_MODE=dev-header` outside `APP_ENV=local|test`.
Worker Lambda handlers raise `NotImplementedError` rather than fall back to memory.

When RDS is disabled for cost (dev, and staging per decision #12), there is no persistent store
yet; we will not substitute a different production data model without a new ADR. In-memory
adapters therefore cannot back a deployed staging environment (open follow-up on #12).

## Consequences
Deployed environments cannot start until real adapters exist — intended.
