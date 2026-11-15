import { ArrowRight, FolderKanban, Plus, X } from "lucide-react";
import { useState, type FormEvent } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api } from "../api/client";
import { EmptyState, ErrorBanner, errorText, PageHeader, Skeleton, timeAgo } from "../components/ui";
import { useAsync } from "../useAsync";

export function ProjectsPage() {
  const projects = useAsync(() => api.listProjects(), []);
  const [creating, setCreating] = useState(false);
  const list = projects.data ?? [];

  return (
    <>
      <PageHeader
        title="Projects"
        description="Each project groups the boards, people and sessions you build with."
        actions={
          !creating && (
            <button className="btn-primary" onClick={() => setCreating(true)}>
              <Plus className="size-4" aria-hidden="true" />
              New project
            </button>
          )
        }
      />

      {creating && <CreateProject onCancel={() => setCreating(false)} />}
      {projects.error && (
        <div className="mb-6">
          <ErrorBanner>{errorText(projects.error)}</ErrorBanner>
        </div>
      )}

      {projects.loading && !projects.data ? (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {[0, 1, 2].map((i) => (
            <Skeleton key={i} className="h-28" />
          ))}
        </div>
      ) : list.length === 0 && !projects.error ? (
        !creating && (
          <div className="card">
            <EmptyState icon={<FolderKanban className="size-5" />} title="No projects yet">
              <p>Create a project to register your first board and start streaming its data.</p>
              <button className="btn-primary mt-4" onClick={() => setCreating(true)}>
                <Plus className="size-4" aria-hidden="true" />
                New project
              </button>
            </EmptyState>
          </div>
        )
      ) : (
        <ul className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {list.map((p) => (
            <li key={p.id}>
              <Link
                to={`/projects/${p.id}`}
                className="card group flex h-full flex-col p-5 transition hover:border-accent/50 hover:shadow-md"
              >
                <div className="flex items-start justify-between gap-3">
                  <span className="grid size-10 place-items-center rounded-lg bg-accent-soft text-sm font-semibold text-accent">
                    {p.name.slice(0, 1).toUpperCase()}
                  </span>
                  <ArrowRight
                    className="size-4 text-muted opacity-0 transition group-hover:translate-x-0.5 group-hover:opacity-100"
                    aria-hidden="true"
                  />
                </div>
                <p className="mt-4 truncate font-semibold text-fg">{p.name}</p>
                <p className="mt-0.5 text-xs text-muted">Created {timeAgo(p.created_at)}</p>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </>
  );
}

function CreateProject({ onCancel }: { onCancel: () => void }) {
  const navigate = useNavigate();
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string>();

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (!name.trim()) return;
    setBusy(true);
    setError(undefined);
    try {
      const project = await api.createProject(name.trim());
      navigate(`/projects/${project.id}`);
    } catch (err) {
      setError(errorText(err));
      setBusy(false);
    }
  }

  return (
    <form onSubmit={submit} className="card mb-6 p-5">
      <div className="mb-4 flex items-center justify-between">
        <h2 className="card-title">New project</h2>
        <button type="button" className="btn-ghost -mr-2 p-1.5" onClick={onCancel} aria-label="Cancel">
          <X className="size-4" />
        </button>
      </div>
      <label htmlFor="project-name" className="field-label">
        Project name
      </label>
      <div className="flex flex-col gap-3 sm:flex-row">
        <input
          id="project-name"
          className="input"
          autoFocus
          maxLength={120}
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="e.g. Greenhouse monitor"
        />
        <button type="submit" className="btn-primary" disabled={busy || !name.trim()}>
          {busy ? "Creating…" : "Create project"}
        </button>
      </div>
      {error && (
        <div className="mt-3">
          <ErrorBanner>{error}</ErrorBanner>
        </div>
      )}
    </form>
  );
}
