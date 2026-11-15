# 0012 — Auto-fix: device errors become LLM-proposed pull requests

Status: accepted (2026-11-15, owner asked for "any OpenAI-compatible endpoint takes a set of
logs and a GitHub repo, so errors trigger a workflow that fixes the issue and opens a PR").
Defaults below were posted to the owner as questions and are in effect until changed.

## Context
Boards report errors through the CLI upload path (ADR 0009). Fixing one means someone reads the
logs, finds the code and writes a patch. Decision #8 already chose the OpenAI-compatible Chat
Completions API as the one wire protocol and requires that AI **proposes, never silently
applies** changes.

## Decision
- **Per project, opt in.** An owner/admin links an OpenAI-compatible endpoint (base URL, model,
  optional API key) and a GitHub repository (`owner/name`, fine-grained token, optional base
  branch) with `PUT /projects/{id}/autofix`. Members can read the settings (never the keys),
  list runs and ask for a fix.
- **Keys live in Secrets Manager**, one secret per project named
  `builderwars/<env>/autofix/<project_id>`. The API can write them (create/put/delete under that
  prefix only) and the auto-fix worker can read them; the database only stores whether each is
  set. Cost: about $0.40 a month per configured project.
- **Trigger.** Every newly ingested `error`/`critical` log line or `error` event (MQTT worker or
  CLI upload) goes to `AutoFixTrigger`. It starts a run only when the project's settings are
  enabled with `auto_trigger` on and the level is at or above `min_level`, and it never fails
  ingest. `POST /projects/{id}/autofix/runs` starts one by hand (latest device error by default).
- **No PR spam.** Errors are grouped per project by a signature of the message with numbers,
  hex values, UUIDs and quoted values removed. One run per signature per `dedupe_hours`
  (default 24) and at most `max_runs_per_day` (default 5) runs per project per rolling day. A
  manual run skips the dedupe window but counts toward the cap.
- **The run** (a dedicated `AutoFix` SQS queue + Lambda, 10 min timeout): recent device logs are
  redacted; the model sees the repository's file list and picks up to 8 files; it then gets those
  files and answers with complete new contents, or says it has no confident fix. Changes are
  limited to files it read or new files, never `.github/`, `.git/` or lock files. The worker
  commits on a new branch `autofix/<run_id>` with the Git Data API and opens a normal PR whose
  body explains the error and the change and says it was not run or tested.
- **Never merges, never pushes to the base branch.** People review the PR (decision #8 gate).
- Deployed workers refuse endpoints that resolve to private, loopback or link-local addresses;
  local development (`APP_ENV=local`) allows them so a local Ollama works, and runs each fix in a
  background thread of the API instead of a Lambda.

## Consequences
- Device logs (redacted) and repository files are sent to whichever endpoint the project
  configured. Choosing a provider is the project admin's call.
- Logs come from boards and can contain text written to steer the model. The prompt marks them
  as data, the worker accepts only file edits within the rules above, and a human reviews every
  PR, so the worst case is a bad PR, not an action.
- The daily cap is checked then written in two steps, so two errors landing in the same instant
  can exceed it by one. Acceptable at this scale.
- A GitHub App (one install, short-lived tokens) would replace per-project personal tokens if
  this grows; the `CodeHost` port keeps that change inside `ai_platform.autofix`.
