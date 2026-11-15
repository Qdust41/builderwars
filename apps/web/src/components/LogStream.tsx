import { useEffect, useRef } from "react";
import type { DeviceLogEntry } from "../api/types";

const timeFmt = new Intl.DateTimeFormat(undefined, {
  hour: "2-digit",
  minute: "2-digit",
  second: "2-digit",
});

function levelClass(level: string): string {
  const l = level.toLowerCase();
  if (l === "error" || l === "critical" || l === "fatal") return "text-red-400";
  if (l === "warning" || l === "warn") return "text-amber-300";
  if (l === "debug") return "text-console-muted";
  return "text-sky-300";
}

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
      className="h-72 overflow-y-auto bg-console lg:h-96 px-4 py-3 font-mono text-xs leading-relaxed text-console-fg"
      role="log"
      aria-live="polite"
      onScroll={(e) => {
        const el = e.currentTarget;
        follow.current = el.scrollHeight - el.scrollTop - el.clientHeight < 24;
      }}
    >
      {entries.length === 0 ? (
        <p className="text-console-muted">Waiting for log lines…</p>
      ) : (
        <ol>
          {entries.map((e, i) => (
            <li key={`${e.at}-${i}`} className="flex gap-3 py-0.5">
              <time dateTime={e.at} className="shrink-0 text-console-muted">
                {timeFmt.format(Date.parse(e.at))}
              </time>
              <span className={`w-14 shrink-0 uppercase ${levelClass(e.level)}`}>
                {e.kind === "event" ? "event" : e.level}
              </span>
              <span className="min-w-0 break-words whitespace-pre-wrap">{e.message}</span>
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}
