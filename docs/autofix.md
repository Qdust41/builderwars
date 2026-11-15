# Auto-fix: turn board errors into pull requests

When a board logs an error, builderwars can send the error, the device's recent logs and the
relevant files from the project's GitHub repository to an LLM, and open a pull request with the
fix it proposes. You review and merge it; nothing is merged or pushed to your main branch for you.
Design and limits: [ADR 0012](decisions/0012-autofix-pull-requests.md).

Two pieces of setup:

- **The model is app-wide** and set once, in GitHub Actions (step 1).
- **The GitHub repository is per project** and set on each project page (step 2).

## 1. Set the model (once, in GitHub Actions)

Any server that speaks the OpenAI Chat Completions API. The base URL is everything before
`/chat/completions`:

| Provider | Base URL |
| --- | --- |
| OpenAI | `https://api.openai.com/v1` |
| OpenRouter | `https://openrouter.ai/api/v1` |
| Groq | `https://api.groq.com/openai/v1` |
| Together | `https://api.together.xyz/v1` |
| Ollama (local dev only) | `http://localhost:11434/v1` |

In this repository, Settings → Secrets and variables → Actions:

| Name | Kind | Example |
| --- | --- | --- |
| `AUTOFIX_LLM_BASE_URL` | Variable | `https://api.openai.com/v1` |
| `AUTOFIX_LLM_MODEL` | Variable | `gpt-4.1` |
| `AUTOFIX_LLM_API_KEY` | Secret | `sk-...` (leave unset if the endpoint needs no key) |

Then redeploy (merge to `main`, or Actions → Deploy prod → Run workflow). The deploy passes them
to the Workers stack as parameters; the key goes in as a NoEcho parameter and is stored in Secrets
Manager (`builderwars/prod/autofix-llm`), so it never appears in the template, the console or the
log. A deploy that leaves one unset keeps the value from the last deploy. To rotate the key,
update the secret and redeploy. Until a base URL and model are set, runs end as `failed` with a
message saying so.

Deployed environments only call public endpoints. Use a model that is good at code; it gets up
to ~180 KB of source per run.

## 2. Link a repository to the project

Make a GitHub token for the repository: GitHub → Settings → Developer settings → Fine-grained
tokens → Generate new token, with **Repository access** set to that repository and
**Permissions** Contents: *Read and write* and Pull requests: *Read and write*. Nothing else (in
particular not Workflows: auto-fix never edits `.github/`).

On the project page, **Auto-fix → Set up auto-fix** (owners and admins), or with the API:

```bash
curl -X PUT "$API/projects/$PROJECT_ID/autofix" -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" -d '{
    "github_repo": "acme/rig-firmware",
    "github_token": "github_pat_...",
    "instructions": "Host code is in host/, board scripts in scripts/wili_code/"
  }'
```

| Field | Default | Meaning |
| --- | --- | --- |
| `github_repo` | required | `owner/name` |
| `github_token` | — | Write-only. Leave out to keep the saved one, `""` to clear it |
| `base_branch` | repo default | Branch the PR targets |
| `enabled` | `true` | Off stops all runs, manual ones too |
| `auto_trigger` | `true` | Start runs from uploaded error logs; `false` = manual only |
| `min_level` | `error` | `critical` to react only to critical logs |
| `max_runs_per_day` | `5` | Per project, rolling 24 h |
| `dedupe_hours` | `24` | The same error starts at most one run in this window |
| `instructions` | none | Notes for the model, e.g. where the board code lives |

For the MVP the token is stored in the project's row of the `autofix_settings` table (no
separate secrets store). The API never returns it: `GET .../autofix` shows `has_github_token` and
`ready` (enabled and has a token) instead. `DELETE .../autofix` unlinks the repository and
deletes the token.

## 3. Watch runs

- `GET /projects/{id}/autofix/runs`: the latest 50, newest first (also on the project page).
- `POST /projects/{id}/autofix/runs` with `{"device_id": "..."}`: fix that device's latest
  error now (or pass `"message"`). Members and up.

Each run ends as `pr_opened` (with `pr_url`), `no_fix` (the model was not confident; `summary`
says why) or `failed` (no model set, bad token, unreachable endpoint, unusable answer; `summary`
says which).

## Try it locally

```bash
AUTOFIX_LLM_BASE_URL=http://localhost:11434/v1 AUTOFIX_LLM_MODEL=qwen2.5-coder \
  APP_ENV=local uv run uvicorn api.main:app --reload
```

Locally, runs execute in a background thread of the API (no queue or Lambda). Set
`AUTOFIX_LLM_API_KEY` too if the endpoint needs one. Localhost endpoints such as Ollama are
allowed here and nowhere else.
