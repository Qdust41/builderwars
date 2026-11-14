import { useEffect, useMemo, useState } from "react";
import { useParams } from "react-router-dom";
import { api } from "../api/client";
import { createRealtimeClient, type RealtimeEvent } from "../realtime";
import { useAsync } from "../useAsync";

export function SessionPage() {
  const { sessionId = "" } = useParams();
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

  if (channel.error) return <p className="error">{channel.error}</p>;
  return (
    <section>
      <h1>Session</h1>
      <p>
        Channel: <code>{channel.data?.channel ?? "…"}</code>
      </p>
      {realtimeError && <p className="error">{realtimeError}</p>}
      <h2>Activity</h2>
      {events.length === 0 ? (
        <p>No live events yet.</p>
      ) : (
        <ul>
          {events.map((e) => (
            <li key={e.event_id}>
              {e.occurred_at} {e.type}
            </li>
          ))}
        </ul>
      )}
      <p className="todo">
        TODO: presence, device panel, AI run stream. Simultaneous code editing needs a separate
        CRDT layer (see docs/open-decisions.md).
      </p>
    </section>
  );
}
