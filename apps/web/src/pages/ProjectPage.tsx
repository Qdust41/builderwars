import { ChevronRight, Cpu, History, Play, Plus, X } from "lucide-react";
import { useState, type FormEvent } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api } from "../api/client";
import {
  EmptyState,
  ErrorBanner,
  errorText,
  PageHeader,
  Skeleton,
  StatusPill,
  timeAgo,
} from "../components/ui";
import { useAsync } from "../useAsync";

export function ProjectPage() {
  const { projectId = "" } = useParams();
  const navigate = useNavigate();
  const project = useAsync(() => api.getProject(projectId), [projectId]);
  const devices = useAsync(() => api.listDevices(projectId), [projectId]);
  const sessions = useAsync(() => api.listSessions(projectId), [projectId]);
  const [registering, setRegistering] = useState(false);
  const [sessionError, setSessionError] = useState<string>();
  const [starting, setStarting] = useState(false);

  async function startSession() {
    setStarting(true);
    setSessionError(undefined);
    try {
      const session = await api.startSession(projectId);
      navigate(`/sessions/${session.id}`);
    } catch (err) {
      setSessionError(errorText(err));
      setStarting(false);
    }
  }

  if (project.error) {
    return (
      <>
        <PageHeader title="Project" crumbs={[{ label: "Projects", to: "/" }]} />
        <ErrorBanner>{errorText(project.error)}</ErrorBanner>
      </>
    );
  }

  const deviceList = devices.data ?? [];
  const online = deviceList.filter((d) => d.connection_status === "online").length;
  const sessionList = [...(sessions.data ?? [])].sort(
    (a, b) => Date.parse(b.created_at) - Date.parse(a.created_at),
  );

  return (
    <>
      <PageHeader
        crumbs={[{ label: "Projects", to: "/" }, { label: project.data?.name ?? "…" }]}
        title={project.data?.name ?? <Skeleton className="h-8 w-48" />}
        description={
          devices.data &&
          `${deviceList.length} ${deviceList.length === 1 ? "device" : "devices"} · ${online} online`
        }
        actions={
          <>
            <button className="btn-secondary" onClick={startSession} disabled={starting}>
              <Play className="size-4" aria-hidden="true" />
              {starting ? "Starting…" : "Start session"}
            </button>
            {!registering && (
              <button className="btn-primary" onClick={() => setRegistering(true)}>
                <Plus className="size-4" aria-hidden="true" />
                Add device
              </button>
            )}
          </>
        }
      />

      {sessionError && (
        <div className="mb-6">
          <ErrorBanner>{sessionError}</ErrorBanner>
        </div>
      )}

      <div className="grid gap-6 lg:grid-cols-3">
        <section className="space-y-4 lg:col-span-2">
          {registering && (
            <RegisterDevice
              projectId={projectId}
              onCancel={() => setRegistering(false)}
              onDone={() => {
                setRegistering(false);
                devices.reload();
              }}
            />
          )}

          <div className="card">
            <div className="card-head">
              <h2 className="card-title">Devices</h2>
            </div>
            {devices.error ? (
              <div className="p-5">
                <ErrorBanner>{errorText(devices.error)}</ErrorBanner>
              </div>
            ) : devices.loading && !devices.data ? (
              <div className="space-y-3 p-5">
                <Skeleton className="h-14" />
                <Skeleton className="h-14" />
              </div>
            ) : deviceList.length === 0 ? (
              <EmptyState icon={<Cpu className="size-5" />} title="No devices yet">
                <p>Add a board, then sign in to the CLI on its host to stream telemetry and logs here.</p>
                {!registering && (
                  <button className="btn-primary mt-4" onClick={() => setRegistering(true)}>
                    <Plus className="size-4" aria-hidden="true" />
                    Add device
                  </button>
                )}
              </EmptyState>
            ) : (
              <ul className="divide-y divide-line">
                {deviceList.map((d) => (
                  <li key={d.id}>
                    <Link
                      to={`/devices/${d.id}`}
                      className="group flex items-center gap-4 px-5 py-4 transition-colors hover:bg-surface-2"
                    >
                      <span className="grid size-10 shrink-0 place-items-center rounded-lg border border-line bg-surface-2 text-fg-2">
                        <Cpu className="size-5" aria-hidden="true" />
                      </span>
                      <span className="min-w-0 flex-1">
                        <span className="block truncate font-medium text-fg">{d.display_name}</span>
                        <span className="block truncate text-xs text-muted">
                          {d.hardware_model}
                          {d.extensions.length ? ` + ${d.extensions.join(", ")}` : ""} · seen{" "}
                          {timeAgo(d.last_seen_at)}
                        </span>
                      </span>
                      <StatusPill status={d.connection_status} />
                      <ChevronRight
                        className="size-4 text-muted transition group-hover:translate-x-0.5"
                        aria-hidden="true"
                      />
                    </Link>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </section>

        <section className="card h-fit">
          <div className="card-head">
            <h2 className="card-title">Sessions</h2>
          </div>
          {sessions.error ? (
            <div className="p-5">
              <ErrorBanner>{errorText(sessions.error)}</ErrorBanner>
            </div>
          ) : sessions.loading && !sessions.data ? (
            <div className="p-5">
              <Skeleton className="h-10" />
            </div>
          ) : sessionList.length === 0 ? (
            <EmptyState icon={<History className="size-5" />} title="No sessions">
              <p>Start a session to follow a build together in real time.</p>
            </EmptyState>
          ) : (
            <ul className="divide-y divide-line">
              {sessionList.map((s) => (
                <li key={s.id}>
                  <Link
                    to={`/sessions/${s.id}`}
                    className="flex items-center justify-between gap-3 px-5 py-3 text-sm transition-colors hover:bg-surface-2"
                  >
                    <span className="min-w-0">
                      <span className="block truncate font-mono text-xs text-fg-2">{s.id}</span>
                      <span className="block text-xs text-muted">Started {timeAgo(s.created_at)}</span>
                    </span>
                    <span
                      className={`rounded-full px-2 py-0.5 text-xs font-medium capitalize ${
                        s.status === "active" ? "bg-good-soft text-good" : "bg-surface-2 text-muted"
                      }`}
                    >
                      {s.status}
                    </span>
                  </Link>
                </li>
              ))}
            </ul>
          )}
        </section>
      </div>
    </>
  );
}

function RegisterDevice({
  projectId,
  onCancel,
  onDone,
}: {
  projectId: string;
  onCancel: () => void;
  onDone: () => void;
}) {
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string>();

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (!name.trim()) return;
    setBusy(true);
    setError(undefined);
    try {
      await api.registerDevice(projectId, name.trim());
      onDone();
    } catch (err) {
      setError(errorText(err));
      setBusy(false);
    }
  }

  return (
    <form onSubmit={submit} className="card p-5">
      <div className="mb-4 flex items-center justify-between">
        <h2 className="card-title">Add a device</h2>
        <button type="button" className="btn-ghost -mr-2 p-1.5" onClick={onCancel} aria-label="Cancel">
          <X className="size-4" />
        </button>
      </div>
      <label htmlFor="device-name" className="field-label">
        Device name
      </label>
      <div className="flex flex-col gap-3 sm:flex-row">
        <input
          id="device-name"
          className="input"
          autoFocus
          maxLength={120}
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="e.g. Bench board"
        />
        <button type="submit" className="btn-primary" disabled={busy || !name.trim()}>
          {busy ? "Adding…" : "Add device"}
        </button>
      </div>
      <p className="mt-2 text-xs text-muted">Registered as a FREE-WILi with the WiFi Orca extension.</p>
      {error && (
        <div className="mt-3">
          <ErrorBanner>{error}</ErrorBanner>
        </div>
      )}
    </form>
  );
}
