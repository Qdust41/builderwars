import { useEffect, useRef } from "react";
import type { DeviceLogEntry } from "../api/types";

const timeFmt = new Intl.DateTimeFormat(undefined, {
  hour: "2-digit",
  minute: "2-digit",
  second: "2-digit",
});

/** Device logs and events, oldest at the top; follows new lines unless the reader scrolled up. */
export function LogStream({ entries }: { entries: DeviceLogEntry[] }) {
  const box = useRef<HTMLDivElement>(null);
  const follow = useRef(true);

  useEffect(() => {
    const el = box.current;
    if (el && follow.current) el.scrollTop = el.scrollHeight;
  }, [entries]);

  return (
    <div
      ref={box}
      className="log-stream"
      role="log"
      aria-live="polite"
      onScroll={(e) => {
        const el = e.currentTarget;
        follow.current = el.scrollHeight - el.scrollTop - el.clientHeight < 24;
      }}
    >
      {entries.length === 0 ? (
        <p className="muted">No log lines yet.</p>
      ) : (
        <ol>
          {entries.map((e, i) => (
            <li key={`${e.at}-${i}`} className={`log-${e.level}`}>
              <time dateTime={e.at}>{timeFmt.format(Date.parse(e.at))}</time>
              <span className={`level level-${e.level}`}>
                {e.kind === "event" ? `event · ${e.level}` : e.level}
              </span>
              <span className="log-message">{e.message}</span>
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}
