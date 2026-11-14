import type { DeviceCommand } from "../api/types";

const timeFmt = new Intl.DateTimeFormat(undefined, {
  hour: "2-digit",
  minute: "2-digit",
  second: "2-digit",
});

const FINAL_OK = new Set(["succeeded"]);
const FINAL_BAD = new Set(["failed", "rejected", "timed_out"]);

/** Commands sent to this device, newest first, with their status as it changes. */
export function CommandList({ commands }: { commands: DeviceCommand[] }) {
  if (commands.length === 0) return <p className="muted">No commands sent yet.</p>;
  return (
    <ul className="commands">
      {commands.map((c) => {
        const tone = FINAL_OK.has(c.status) ? "ok" : FINAL_BAD.has(c.status) ? "bad" : "pending";
        const took =
          c.completed_at && c.created_at
            ? `${Date.parse(c.completed_at) - Date.parse(c.created_at)} ms`
            : undefined;
        const output = Object.entries(c.output)
          .map(([k, v]) => `${k}: ${String(v)}`)
          .join(", ");
        return (
          <li key={c.id}>
            <code>{c.name}</code>
            <span className={`status status-${tone}`}>{c.status.replace("_", " ")}</span>
            <span className="muted">
              {timeFmt.format(Date.parse(c.created_at))} by {c.requested_by}
              {took ? ` · ${took}` : ""}
            </span>
            {(output || c.detail) && (
              <span className="command-output">{[output, c.detail].filter(Boolean).join(" · ")}</span>
            )}
          </li>
        );
      })}
    </ul>
  );
}
