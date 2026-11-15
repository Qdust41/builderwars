-- 0004: auto-fix (ADR 0012). A GitHub repository linked per project; error logs start runs
-- that propose a fix as a pull request. The model is app-wide (deploy-time settings).
-- MVP: the project's GitHub token is stored here (owner decision 2026-11-15); the API never
-- returns it. Move it to a secrets store / GitHub App before real users.
CREATE TABLE autofix_settings (
    project_id        text PRIMARY KEY REFERENCES projects (id) ON DELETE CASCADE,
    github_repo       text        NOT NULL,
    github_token      text,
    base_branch       text,
    enabled           boolean     NOT NULL,
    auto_trigger      boolean     NOT NULL,
    min_level         text        NOT NULL CHECK (min_level IN ('error', 'critical')),
    max_runs_per_day  integer     NOT NULL CHECK (max_runs_per_day BETWEEN 1 AND 50),
    dedupe_hours      integer     NOT NULL CHECK (dedupe_hours BETWEEN 1 AND 720),
    instructions      text,
    updated_by        text        NOT NULL,
    updated_at        timestamptz NOT NULL
);

CREATE TABLE autofix_runs (
    id            text PRIMARY KEY,
    project_id    text        NOT NULL REFERENCES projects (id) ON DELETE CASCADE,
    device_id     text REFERENCES devices (id) ON DELETE SET NULL,
    trigger       text        NOT NULL CHECK (trigger IN ('error_log', 'manual')),
    signature     text        NOT NULL,
    error_level   text        NOT NULL,
    error_message text        NOT NULL,
    requested_by  text,
    status        text        NOT NULL
        CHECK (status IN ('queued', 'running', 'pr_opened', 'no_fix', 'failed')),
    created_at    timestamptz NOT NULL,
    started_at    timestamptz,
    completed_at  timestamptz,
    model         text,
    github_repo   text,
    branch        text,
    pr_number     integer,
    pr_url        text,
    summary       text,
    files_changed text[]      NOT NULL DEFAULT '{}'
);
CREATE INDEX autofix_runs_project_idx ON autofix_runs (project_id, created_at DESC);

-- Last time each distinct error (see domain.autofix.error_signature) started a run.
CREATE TABLE autofix_signatures (
    project_id  text        NOT NULL REFERENCES projects (id) ON DELETE CASCADE,
    signature   text        NOT NULL,
    last_run_at timestamptz NOT NULL,
    PRIMARY KEY (project_id, signature)
);
