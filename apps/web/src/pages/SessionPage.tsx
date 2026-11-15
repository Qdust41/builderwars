import { Radio, Users } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { api } from "../api/client";
import { createRealtimeClient, type RealtimeEvent } from "../realtime";
import { EmptyState, ErrorBanner, errorText, PageHeader, timeAgo } from "../components/ui";
import { useAsync } from "../useAsync";
import { useParams } from "react-router-dom";

const timeFmt = new Intl.DateTimeFormat(undefined, {
  hour: "2-digit",
  minute: "2-digit",
  second: "2-digit",
});

export function SessionPage() {
  const { sessionId = "" } = useParams();
  const session = useAsync(() => api.getSession(sessionId), [sessionId]);
  const channel = useAsync(() => api.getSessionChannel(sessionId), [sessionId]);
  const realtime = useMemo(() => createRealtimeClient(), []);
  const [events, setEvents] = useState<RealtimeEvent[]>([]);
  const [realtimeError, setRealtimeError] = useState<string>();

  useEffect(() => {
    if (!channel.data) return;
    let unsubscribe: (() => void) | undefined;
    realtime
      .subscribe(channel.data.channel, (e) => setEvents((prev) => [...prev, e]))
      .then((u) => (unsubscribe = u))
      .catch((err: unknown) => setRealtimeError(String(err)));
    return () => unsubscribe?.();
  }, [channel.data, realtime]);

  const s = session.data;
  const project = useAsync(
    () => (s ? api.getProject(s.project_id) : Promise.resolve(undefined)),
    [s?.project_id],
  );
  const crumbs = [
    { label: "Projects", to: "/" },
    ...(s ? [{ label: project.data?.name ?? "Project", to: `/projects/${s.project_id}` }] : []),
    { label: "Session" },
  ];

  return (
    <>
      <PageHeader
        crumbs={crumbs}
        title="Session"
        description={
          s && (
            <>
              Started {timeAgo(s.created_at)} ·{" "}
              <span className="font-mono text-xs">{s.id}</span>
            </>
          )
        }
        actions={
          s && (
            <span
              className={`rounded-full px-3 py-1.5 text-xs font-medium capitalize ${
                s.status === "active" ? "bg-good-soft text-good" : "bg-surface-2 text-muted"
              }`}
            >
              {s.status}
            </span>
          )
        }
      />
      <div className={channel.error || realtimeError ? "mb-6 space-y-4" : ""}>
        {channel.error && <ErrorBanner>{errorText(channel.error)}</ErrorBanner>}
        {realtimeError && <ErrorBanner>{errorText(realtimeError)}</ErrorBanner>}
      </div>

      <div className="grid gap-6 lg:grid-cols-3">
        <section className="card lg:col-span-2">
          <div className="card-head">
            <h2 className="card-title">Activity</h2>
            {channel.data && (
              <code className="truncate font-mono text-xs text-muted" title="Realtime channel">
                {channel.data.channel}
              </code>
            )}
          </div>
          {events.length === 0 ? (
            <EmptyState icon={<Radio className="size-5" />} title="No live events yet">
              <p>Events from this session show up here as they happen.</p>
            </EmptyState>
          ) : (
            <ol className="divide-y divide-line">
              {[...events].reverse().map((e) => (
                <li key={e.event_id} className="flex items-center gap-4 px-5 py-3 text-sm">
                  <time className="w-20 shrink-0 text-xs tabular-nums text-muted" dateTime={e.occurred_at}>
                    {timeFmt.format(Date.parse(e.occurred_at))}
                  </time>
                  <code className="font-mono text-xs text-fg-2">{e.type}</code>
                </li>
              ))}
            </ol>
          )}
        </section>
        <section className="card h-fit">
          <div className="card-head">
            <h2 className="card-title">Coming soon</h2>
          </div>
          <EmptyState icon={<Users className="size-5" />} title="Presence and shared tools">
            <p>Who's here, the session's device panel and AI runs will appear in this space.</p>
          </EmptyState>
        </section>
      </div>
    </>
  );
}
