import { AlertCircle, Loader2 } from "lucide-react";
import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import type { ConnectionStatus } from "../api/types";

/** Small product mark: a chip outline. Neutral until branding is decided. */
export function Logo({ className = "" }: { className?: string }) {
  return (
    <span className={`inline-flex items-center gap-2 font-semibold tracking-tight ${className}`}>
      <span className="grid size-7 place-items-center rounded-lg bg-accent text-accent-ink shadow-sm">
        <svg viewBox="0 0 24 24" className="size-4" fill="none" stroke="currentColor" strokeWidth="2.2">
          <rect x="6" y="6" width="12" height="12" rx="2" />
          <path d="M9 2v4M15 2v4M9 18v4M15 18v4M2 9h4M2 15h4M18 9h4M18 15h4" strokeLinecap="round" />
        </svg>
      </span>
      <span>Builderwars</span>
    </span>
  );
}

export interface Crumb {
  label: ReactNode;
  to?: string;
}

export function PageHeader({
  title,
  description,
  crumbs,
  actions,
}: {
  title: ReactNode;
  description?: ReactNode;
  crumbs?: Crumb[];
  actions?: ReactNode;
}) {
  return (
    <div className="mb-8">
      {crumbs && crumbs.length > 0 && (
        <nav aria-label="Breadcrumb" className="mb-3 flex flex-wrap items-center gap-1.5 text-sm text-muted">
          {crumbs.map((c, i) => (
            <span key={i} className="flex items-center gap-1.5">
              {i > 0 && <span aria-hidden="true">/</span>}
              {c.to ? (
                <Link to={c.to} className="hover:text-fg">
                  {c.label}
                </Link>
              ) : (
                <span className="text-fg-2">{c.label}</span>
              )}
            </span>
          ))}
        </nav>
      )}
      <div className="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
        <div className="min-w-0">
          <h1 className="truncate text-2xl font-semibold tracking-tight text-fg">{title}</h1>
          {description && <div className="mt-1 text-sm text-muted">{description}</div>}
        </div>
        {actions && <div className="flex shrink-0 flex-wrap gap-2">{actions}</div>}
      </div>
    </div>
  );
}

const STATUS_STYLE: Record<ConnectionStatus, string> = {
  online: "bg-good-soft text-good",
  offline: "bg-surface-2 text-muted",
  unknown: "bg-surface-2 text-muted",
};

export function StatusPill({ status }: { status: ConnectionStatus | undefined }) {
  const s = status ?? "unknown";
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-xs font-medium capitalize ${STATUS_STYLE[s]}`}
    >
      <span
        className={`size-1.5 rounded-full ${s === "online" ? "bg-good" : "bg-muted/60"}`}
        aria-hidden="true"
      />
      {s}
    </span>
  );
}

export function EmptyState({
  icon,
  title,
  children,
}: {
  icon: ReactNode;
  title: string;
  children?: ReactNode;
}) {
  return (
    <div className="flex flex-col items-center justify-center px-6 py-12 text-center">
      <div className="mb-3 grid size-11 place-items-center rounded-xl bg-accent-soft text-accent">{icon}</div>
      <p className="text-sm font-semibold text-fg">{title}</p>
      {children && <div className="mt-1 max-w-sm text-sm text-muted">{children}</div>}
    </div>
  );
}

export function ErrorBanner({ children }: { children: ReactNode }) {
  return (
    <div role="alert" className="flex items-start gap-2 rounded-lg border border-bad/30 bg-bad-soft px-3.5 py-2.5 text-sm text-bad">
      <AlertCircle className="mt-0.5 size-4 shrink-0" aria-hidden="true" />
      <div className="min-w-0 break-words">{children}</div>
    </div>
  );
}

export function Spinner({ label = "Loading…" }: { label?: string }) {
  return (
    <div className="flex items-center justify-center gap-2 py-10 text-sm text-muted">
      <Loader2 className="size-4 animate-spin" aria-hidden="true" />
      {label}
    </div>
  );
}

export function Skeleton({ className = "" }: { className?: string }) {
  return <div className={`animate-pulse rounded-lg bg-surface-2 ${className}`} />;
}

/** Turns an Error or ApiError into a readable line. */
export function errorText(err: unknown): string {
  const s = (err instanceof Error ? err.message : String(err)).replace(/^\w*Error:\s*/, "");
  // ApiError carries the API's JSON `detail`; a plain string detail arrives quoted.
  if (/^".*"$/.test(s)) return s.slice(1, -1);
  // A 422 detail is a list of {loc, msg}: show "bus.address: must be ≤ 127" lines.
  if (s.startsWith("[")) {
    try {
      const items = JSON.parse(s) as { loc?: (string | number)[]; msg?: string }[];
      return items
        .map((i) => {
          const where = (i.loc ?? []).filter((p) => p !== "body" && typeof p === "string");
          const msg = (i.msg ?? "").replace(/^Value error, /, "");
          return where.length ? `${where.join(".")}: ${msg}` : msg;
        })
        .join("; ");
    } catch {
      /* not JSON after all */
    }
  }
  return s;
}

const rtf = new Intl.RelativeTimeFormat(undefined, { numeric: "auto" });

/** "3 minutes ago", "yesterday", or a date for anything older than a week. */
export function timeAgo(iso: string | null | undefined, now = Date.now()): string {
  if (!iso) return "never";
  const t = Date.parse(iso);
  if (Number.isNaN(t)) return "unknown";
  const s = Math.round((t - now) / 1000);
  const abs = Math.abs(s);
  if (abs < 45) return "just now";
  if (abs < 3600) return rtf.format(Math.round(s / 60), "minute");
  if (abs < 86400) return rtf.format(Math.round(s / 3600), "hour");
  if (abs < 7 * 86400) return rtf.format(Math.round(s / 86400), "day");
  return new Date(t).toLocaleDateString();
}

export function initials(label: string): string {
  const name = label.split("@")[0];
  const parts = name.split(/[.\s_-]+/).filter(Boolean);
  const chars = parts.length > 1 ? parts[0][0] + parts[1][0] : name.slice(0, 2);
  return chars.toUpperCase();
}
