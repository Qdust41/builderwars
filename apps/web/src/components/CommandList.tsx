import { CheckCircle2, Clock, Terminal, XCircle } from "lucide-react";
import type { DeviceCommand } from "../api/types";

const timeFmt = new Intl.DateTimeFormat(undefined, {
  hour: "2-digit",
  minute: "2-digit",
  second: "2-digit",
});

const FINAL_OK = new Set(["succeeded"]);
const FINAL_BAD = new Set(["failed", "rejected", "timed_out"]);

const TONE = {
  ok: { cls: "bg-good-soft text-good", Icon: CheckCircle2 },
  bad: { cls: "bg-bad-soft text-bad", Icon: XCircle },
  pending: { cls: "bg-warn-soft text-warn", Icon: Clock },
} as const;

/** Commands sent to this device, newest first, with their status as it changes. */
export function CommandList({ commands }: { commands: DeviceCommand[] }) {
  if (commands.length === 0) {
    return (
      <div className="flex flex-col items-center px-5 py-10 text-center text-sm text-muted">
        <Terminal className="mb-2 size-5" aria-hidden="true" />
        No commands sent yet.
      </div>
    );
  }
  return (
    <ul className="max-h-96 divide-y divide-line overflow-y-auto">
      {commands.map((c) => {
        const tone = FINAL_OK.has(c.status) ? "ok" : FINAL_BAD.has(c.status) ? "bad" : "pending";
        const { cls, Icon } = TONE[tone];
        const took =
          c.completed_at && c.created_at
            ? `${Date.parse(c.completed_at) - Date.parse(c.created_at)} ms`
            : undefined;
        const output = Object.entries(c.output)
          .map(([k, v]) => `${k}: ${String(v)}`)
          .join(", ");
        return (
          <li key={c.id} className="px-5 py-3">
            <div className="flex items-center justify-between gap-3">
              <code className="font-mono text-sm font-medium text-fg">{c.name}</code>
              <span
                className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium capitalize ${cls}`}
              >
                <Icon className={`size-3 ${tone === "pending" ? "animate-pulse" : ""}`} aria-hidden="true" />
                {c.status.replace("_", " ")}
              </span>
            </div>
            <p className="mt-1 text-xs text-muted">
              {timeFmt.format(Date.parse(c.created_at))} by {c.requested_by}
              {took ? ` · ${took}` : ""}
            </p>
            {(output || c.detail) && (
              <p className="mt-2 rounded-md bg-surface-2 px-2.5 py-1.5 font-mono text-xs break-words text-fg-2">
                {[output, c.detail].filter(Boolean).join(" · ")}
              </p>
            )}
          </li>
        );
      })}
    </ul>
  );
}
