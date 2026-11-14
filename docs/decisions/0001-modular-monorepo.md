# 0001 — Modular monorepo with a uv workspace

Status: accepted (scaffold)

## Context
API, workers, board runtime and infrastructure share a device protocol and domain model, and a
small team needs one place to change them together.

## Decision
One repository. Python packages are uv workspace members with explicit dependencies
(`packages/*`, `apps/api`, `apps/workers`, `device`). Package names are prefixed `bw-` to avoid
PyPI collisions; import names follow the plan (`api`, `domain`, `device_protocol`, …,
`ai_platform`). The CDK app lives outside the workspace with its own `requirements.txt` so
application images don't pull in `aws-cdk-lib`. The frontend is a separate npm project.

## Consequences
- One lockfile (`uv.lock`) for all Python apps; `uv sync` gives a working dev env.
- Layering is enforced by package dependencies (domain has none; device only depends on the
  protocol). An import-linter check could be added later.
