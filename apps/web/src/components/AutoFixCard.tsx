import { ExternalLink, GitPullRequest, Settings2, Wand2, X } from "lucide-react";
import { useState, type FormEvent, type ReactNode } from "react";
import { api, ApiError } from "../api/client";
import type { AutoFixRun, AutoFixRunStatus, AutoFixSettings } from "../api/types";
import { useAsync } from "../useAsync";
import { EmptyState, ErrorBanner, errorText, Skeleton, timeAgo } from "./ui";

/** Settings are a 404 until someone links a repository. */
async function loadSettings(projectId: string): Promise<AutoFixSettings | null> {
  try {
    return await api.getAutoFix(projectId);
  } catch (err) {
    if (err instanceof ApiError && err.status === 404) return null;
    throw err;
  }
}

const STATUS: Record<AutoFixRunStatus, { label: string; tone: string }> = {
  queued: { label: "Queued", tone: "bg-surface-2 text-muted" },
  running: { label: "Working", tone: "bg-accent-soft text-accent" },
  pr_opened: { label: "PR opened", tone: "bg-good-soft text-good" },
  no_fix: { label: "No fix", tone: "bg-warn-soft text-warn" },
  failed: { label: "Failed", tone: "bg-bad-soft text-bad" },
};

/** Auto-fix on the project page: what is linked, recent runs, and the settings form. */
export function AutoFixCard({ projectId }: { projectId: string }) {
  const settings = useAsync(() => loadSettings(projectId), [projectId]);
  const runs = useAsync(() => api.listAutoFixRuns(projectId), [projectId]);
  const [editing, setEditing] = useState(false);
  const current = settings.data ?? null;

  let body: ReactNode;
  if (settings.error) {
    body = (
      <div className="p-5">
        <ErrorBanner>{errorText(settings.error)}</ErrorBanner>
      </div>
    );
  } else if (settings.loading && settings.data === undefined) {
    body = (
      <div className="p-5">
        <Skeleton className="h-10" />
      </div>
    );
  } else if (editing) {
    body = (
      <AutoFixForm
        projectId={projectId}
        current={current}
        onCancel={() => setEditing(false)}
        onDone={() => {
          setEditing(false);
          settings.reload();
        }}
      />
    );
  } else if (!current) {
    body = (
      <EmptyState icon={<Wand2 className="size-5" />} title="Not set up">
        <p>
          Link a GitHub repo. When a board reports an error, the app's model proposes a fix as a
          pull request for you to review.
        </p>
        <button className="btn-primary mt-4" onClick={() => setEditing(true)}>
          Set up auto-fix
        </button>
      </EmptyState>
    );
  } else {
    body = (
      <>
        <div className="space-y-1 border-b border-line px-5 py-3 text-xs text-muted">
          <p>
            Pull requests go to{" "}
            <a
              className="font-medium text-accent hover:underline"
              href={`https://github.com/${current.github_repo}`}
              target="_blank"
              rel="noreferrer"
            >
              {current.github_repo}
            </a>
          </p>
          <p>
            {!current.enabled
              ? "Turned off"
              : !current.has_github_token
                ? "Needs a GitHub token"
                : current.auto_trigger
                  ? `Runs on ${current.min_level} logs · up to ${current.max_runs_per_day}/day`
                  : "Manual runs only"}
          </p>
        </div>
        <RunList runs={runs.data} error={runs.error} />
      </>
    );
  }

  return (
    <section className="card h-fit">
      <div className="card-head">
        <h2 className="card-title">Auto-fix</h2>
        {current && !editing && (
          <button
            className="btn-ghost -mr-2 p-1.5"
            onClick={() => setEditing(true)}
            aria-label="Auto-fix settings"
          >
            <Settings2 className="size-4" />
          </button>
        )}
      </div>
      {body}
    </section>
  );
}

function RunList({ runs, error }: { runs: AutoFixRun[] | undefined; error: string | undefined }) {
  if (error) {
    return (
      <div className="p-5">
        <ErrorBanner>{errorText(error)}</ErrorBanner>
      </div>
    );
  }
  if (!runs) return null;
  if (runs.length === 0) {
    return <p className="px-5 py-4 text-sm text-muted">No runs yet.</p>;
  }
  return (
    <ul className="divide-y divide-line">
      {runs.slice(0, 8).map((r) => (
        <li key={r.id} className="space-y-1 px-5 py-3 text-sm">
          <div className="flex items-center justify-between gap-3">
            <span className="min-w-0 truncate text-fg-2" title={r.error_message}>
              {r.error_message}
            </span>
            <span
              className={`shrink-0 rounded-full px-2 py-0.5 text-xs font-medium ${STATUS[r.status].tone}`}
            >
              {STATUS[r.status].label}
            </span>
          </div>
          <div className="flex items-center justify-between gap-3 text-xs text-muted">
            <span>
              {r.trigger === "manual" ? "Requested" : "From an error log"} {timeAgo(r.created_at)}
            </span>
            {r.pr_url && (
              <a
                className="inline-flex items-center gap-1 font-medium text-accent hover:underline"
                href={r.pr_url}
                target="_blank"
                rel="noreferrer"
              >
                <GitPullRequest className="size-3.5" aria-hidden="true" />#{r.pr_number}
                <ExternalLink className="size-3" aria-hidden="true" />
              </a>
            )}
          </div>
          {r.summary && r.status !== "pr_opened" && (
            <p className="line-clamp-2 text-xs text-muted">{r.summary}</p>
          )}
        </li>
      ))}
    </ul>
  );
}

function AutoFixForm({
  projectId,
  current,
  onCancel,
  onDone,
}: {
  projectId: string;
  current: AutoFixSettings | null;
  onCancel: () => void;
  onDone: () => void;
}) {
  const [repo, setRepo] = useState(current?.github_repo ?? "");
  const [token, setToken] = useState("");
  const [branch, setBranch] = useState(current?.base_branch ?? "");
  const [auto, setAuto] = useState(current?.auto_trigger ?? true);
  const [enabled, setEnabled] = useState(current?.enabled ?? true);
  const [instructions, setInstructions] = useState(current?.instructions ?? "");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string>();

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(undefined);
    try {
      await api.saveAutoFix(projectId, {
        github_repo: repo.trim(),
        base_branch: branch.trim() || null,
        enabled,
        auto_trigger: auto,
        min_level: current?.min_level ?? "error",
        max_runs_per_day: current?.max_runs_per_day ?? 5,
        dedupe_hours: current?.dedupe_hours ?? 24,
        instructions: instructions.trim() || null,
        // Blank keeps the stored token (the API never sends it back).
        github_token: token || null,
      });
      onDone();
    } catch (err) {
      setError(errorText(err));
      setBusy(false);
    }
  }

  async function disconnect() {
    setBusy(true);
    try {
      await api.deleteAutoFix(projectId);
      onDone();
    } catch (err) {
      setError(errorText(err));
      setBusy(false);
    }
  }

  const keep = (set: boolean | undefined) => (set ? "Saved. Leave blank to keep it." : undefined);

  return (
    <form onSubmit={submit} className="space-y-3 p-5">
      <div className="flex items-center justify-between">
        <p className="text-xs text-muted">Owners and admins only.</p>
        <button
          type="button"
          className="btn-ghost -mr-2 p-1.5"
          onClick={onCancel}
          aria-label="Cancel"
        >
          <X className="size-4" />
        </button>
      </div>
      <Field label="GitHub repository" hint="owner/name">
        <input
          className="input"
          value={repo}
          onChange={(e) => setRepo(e.target.value)}
          placeholder="acme/rig-firmware"
          required
        />
      </Field>
      <Field
        label="GitHub token"
        hint={
          keep(current?.has_github_token) ??
          "Fine-grained token for this repo with Contents and Pull requests: read and write."
        }
      >
        <input
          className="input"
          type="password"
          autoComplete="off"
          value={token}
          onChange={(e) => setToken(e.target.value)}
          required={!current?.has_github_token}
        />
      </Field>
      <Field label="Base branch" hint="Blank uses the repository's default branch.">
        <input className="input" value={branch} onChange={(e) => setBranch(e.target.value)} />
      </Field>
      <Field label="Notes for the model" hint="Optional, e.g. where the board code lives.">
        <textarea
          className="input min-h-16"
          maxLength={4000}
          value={instructions}
          onChange={(e) => setInstructions(e.target.value)}
        />
      </Field>
      <label className="flex items-center gap-2 text-sm text-fg-2">
        <input
          type="checkbox"
          className="size-4 accent-[var(--accent)]"
          checked={auto}
          onChange={(e) => setAuto(e.target.checked)}
        />
        Start a run when a board logs an error
      </label>
      <label className="flex items-center gap-2 text-sm text-fg-2">
        <input
          type="checkbox"
          className="size-4 accent-[var(--accent)]"
          checked={enabled}
          onChange={(e) => setEnabled(e.target.checked)}
        />
        Enabled
      </label>
      {error && <ErrorBanner>{error}</ErrorBanner>}
      <div className="flex flex-wrap items-center justify-between gap-2 border-t border-line pt-4">
        {current ? (
          <button type="button" className="btn-ghost text-bad" onClick={disconnect} disabled={busy}>
            Disconnect
          </button>
        ) : (
          <span />
        )}
        <button type="submit" className="btn-primary" disabled={busy}>
          {busy ? "Saving…" : "Save"}
        </button>
      </div>
    </form>
  );
}

function Field({ label, hint, children }: { label: string; hint?: string; children: ReactNode }) {
  return (
    <label className="block">
      <span className="field-label">{label}</span>
      {children}
      {hint && <span className="mt-1 block text-xs text-muted">{hint}</span>}
    </label>
  );
}
