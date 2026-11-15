# Auto-fix: turn board errors into pull requests

When a board logs an error, builderwars can send the error, the device's recent logs and the
relevant files from your GitHub repository to an LLM, and open a pull request with the fix it
proposes. You review and merge it; nothing is merged or pushed to your main branch for you.
Design and limits: [ADR 0012](decisions/0012-autofix-pull-requests.md).

## 1. Make a GitHub token

GitHub → Settings → Developer settings → Fine-grained tokens → Generate new token:

- **Repository access:** only the repository with your board code.
- **Permissions:** Contents: *Read and write*, Pull requests: *Read and write*. Nothing else
  (in particular not Workflows: auto-fix never edits `.github/`).

## 2. Pick a model endpoint

Any server that speaks the OpenAI Chat Completions API. The base URL is everything before
`/chat/completions`:

| Provider | Base URL |
| --- | --- |
| OpenAI | `https://api.openai.com/v1` |
| OpenRouter | `https://openrouter.ai/api/v1` |
| Groq | `https://api.groq.com/openai/v1` |
| Together | `https://api.together.xyz/v1` |
| Ollama (local dev only) | `http://localhost:11434/v1` |

Deployed environments only call public endpoints. Use a model that is good at code; it gets
up to ~180 KB of source per run.

## 3. Link them to the project

On the project page, **Auto-fix → Set up auto-fix** (owners and admins), or with the API:

```bash
curl -X PUT "$API/projects/$PROJECT_ID/autofix" -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" -d '{
    "llm_base_url": "https://api.openai.com/v1",
    "llm_model": "gpt-4.1",
    "llm_api_key": "sk-...",
    "github_repo": "acme/rig-firmware",
    "github_token": "github_pat_...",
    "instructions": "Host code is in host/, board scripts in scripts/wili_code/"
  }'
```

| Field | Default | Meaning |
| --- | --- | --- |
| `enabled` | `true` | Off stops all runs, manual ones too |
| `auto_trigger` | `true` | Start runs from uploaded error logs; `false` = manual only |
| `min_level` | `error` | `critical` to react only to critical logs |
| `base_branch` | repo default | Branch the PR targets |
| `max_runs_per_day` | `5` | Per project, rolling 24 h |
| `dedupe_hours` | `24` | The same error starts at most one run in this window |
| `instructions` | none | Notes for the model, e.g. where the board code lives |
| `llm_api_key`, `github_token` | — | Write-only. Leave out to keep, `""` to clear |

`GET .../autofix` shows the settings with `has_llm_api_key` / `has_github_token` instead of the
keys. `DELETE .../autofix` unlinks everything and deletes the stored keys.

## 4. Watch runs

- `GET /projects/{id}/autofix/runs`: the latest 50, newest first (also on the project page).
- `POST /projects/{id}/autofix/runs` with `{"device_id": "..."}`: fix that device's latest
  error now (or pass `"message"`). Members and up.

Each run ends as `pr_opened` (with `pr_url`), `no_fix` (the model was not confident; `summary`
says why) or `failed` (bad token, unreachable endpoint, unusable answer; `summary` says which).

## Try it locally

```bash
APP_ENV=local uv run uvicorn api.main:app --reload
```

Locally, runs execute in a background thread of the API (no queue or Lambda) and keys stay in
memory. Localhost endpoints such as Ollama are allowed here and nowhere else.
