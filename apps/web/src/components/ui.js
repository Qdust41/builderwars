import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { AlertCircle, Loader2 } from "lucide-react";
import { Link } from "react-router-dom";
/** Small product mark: a chip outline. Neutral until branding is decided. */
export function Logo({ className = "" }) {
    return (_jsxs("span", { className: `inline-flex items-center gap-2 font-semibold tracking-tight ${className}`, children: [_jsx("span", { className: "grid size-7 place-items-center rounded-lg bg-accent text-accent-ink shadow-sm", children: _jsxs("svg", { viewBox: "0 0 24 24", className: "size-4", fill: "none", stroke: "currentColor", strokeWidth: "2.2", children: [_jsx("rect", { x: "6", y: "6", width: "12", height: "12", rx: "2" }), _jsx("path", { d: "M9 2v4M15 2v4M9 18v4M15 18v4M2 9h4M2 15h4M18 9h4M18 15h4", strokeLinecap: "round" })] }) }), _jsx("span", { children: "Builderwars" })] }));
}
export function PageHeader({ title, description, crumbs, actions, }) {
    return (_jsxs("div", { className: "mb-8", children: [crumbs && crumbs.length > 0 && (_jsx("nav", { "aria-label": "Breadcrumb", className: "mb-3 flex flex-wrap items-center gap-1.5 text-sm text-muted", children: crumbs.map((c, i) => (_jsxs("span", { className: "flex items-center gap-1.5", children: [i > 0 && _jsx("span", { "aria-hidden": "true", children: "/" }), c.to ? (_jsx(Link, { to: c.to, className: "hover:text-fg", children: c.label })) : (_jsx("span", { className: "text-fg-2", children: c.label }))] }, i))) })), _jsxs("div", { className: "flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between", children: [_jsxs("div", { className: "min-w-0", children: [_jsx("h1", { className: "truncate text-2xl font-semibold tracking-tight text-fg", children: title }), description && _jsx("div", { className: "mt-1 text-sm text-muted", children: description })] }), actions && _jsx("div", { className: "flex shrink-0 flex-wrap gap-2", children: actions })] })] }));
}
const STATUS_STYLE = {
    online: "bg-good-soft text-good",
    offline: "bg-surface-2 text-muted",
    unknown: "bg-surface-2 text-muted",
};
export function StatusPill({ status }) {
    const s = status ?? "unknown";
    return (_jsxs("span", { className: `inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-xs font-medium capitalize ${STATUS_STYLE[s]}`, children: [_jsx("span", { className: `size-1.5 rounded-full ${s === "online" ? "bg-good" : "bg-muted/60"}`, "aria-hidden": "true" }), s] }));
}
export function EmptyState({ icon, title, children, }) {
    return (_jsxs("div", { className: "flex flex-col items-center justify-center px-6 py-12 text-center", children: [_jsx("div", { className: "mb-3 grid size-11 place-items-center rounded-xl bg-accent-soft text-accent", children: icon }), _jsx("p", { className: "text-sm font-semibold text-fg", children: title }), children && _jsx("div", { className: "mt-1 max-w-sm text-sm text-muted", children: children })] }));
}
export function ErrorBanner({ children }) {
    return (_jsxs("div", { role: "alert", className: "flex items-start gap-2 rounded-lg border border-bad/30 bg-bad-soft px-3.5 py-2.5 text-sm text-bad", children: [_jsx(AlertCircle, { className: "mt-0.5 size-4 shrink-0", "aria-hidden": "true" }), _jsx("div", { className: "min-w-0 break-words", children: children })] }));
}
export function Spinner({ label = "Loading…" }) {
    return (_jsxs("div", { className: "flex items-center justify-center gap-2 py-10 text-sm text-muted", children: [_jsx(Loader2, { className: "size-4 animate-spin", "aria-hidden": "true" }), label] }));
}
export function Skeleton({ className = "" }) {
    return _jsx("div", { className: `animate-pulse rounded-lg bg-surface-2 ${className}` });
}
/** Turns an Error or ApiError into a readable line. */
export function errorText(err) {
    const s = (err instanceof Error ? err.message : String(err)).replace(/^\w*Error:\s*/, "");
    // ApiError carries the API's JSON `detail`; a plain string detail arrives quoted.
    if (/^".*"$/.test(s))
        return s.slice(1, -1);
    // A 422 detail is a list of {loc, msg}: show "bus.address: must be ≤ 127" lines.
    if (s.startsWith("[")) {
        try {
            const items = JSON.parse(s);
            return items
                .map((i) => {
                const where = (i.loc ?? []).filter((p) => p !== "body" && typeof p === "string");
                const msg = (i.msg ?? "").replace(/^Value error, /, "");
                return where.length ? `${where.join(".")}: ${msg}` : msg;
            })
                .join("; ");
        }
        catch {
            /* not JSON after all */
        }
    }
    return s;
}
const rtf = new Intl.RelativeTimeFormat(undefined, { numeric: "auto" });
/** "3 minutes ago", "yesterday", or a date for anything older than a week. */
export function timeAgo(iso, now = Date.now()) {
    if (!iso)
        return "never";
    const t = Date.parse(iso);
    if (Number.isNaN(t))
        return "unknown";
    const s = Math.round((t - now) / 1000);
    const abs = Math.abs(s);
    if (abs < 45)
        return "just now";
    if (abs < 3600)
        return rtf.format(Math.round(s / 60), "minute");
    if (abs < 86400)
        return rtf.format(Math.round(s / 3600), "hour");
    if (abs < 7 * 86400)
        return rtf.format(Math.round(s / 86400), "day");
    return new Date(t).toLocaleDateString();
}
export function initials(label) {
    const name = label.split("@")[0];
    const parts = name.split(/[.\s_-]+/).filter(Boolean);
    const chars = parts.length > 1 ? parts[0][0] + parts[1][0] : name.slice(0, 2);
    return chars.toUpperCase();
}
