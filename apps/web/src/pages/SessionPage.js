import { jsx as _jsx, Fragment as _Fragment, jsxs as _jsxs } from "react/jsx-runtime";
import { Radio, Users } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { api } from "../api/client";
import { createRealtimeClient } from "../realtime";
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
    const [events, setEvents] = useState([]);
    const [realtimeError, setRealtimeError] = useState();
    useEffect(() => {
        if (!channel.data)
            return;
        let unsubscribe;
        realtime
            .subscribe(channel.data.channel, (e) => setEvents((prev) => [...prev, e]))
            .then((u) => (unsubscribe = u))
            .catch((err) => setRealtimeError(String(err)));
        return () => unsubscribe?.();
    }, [channel.data, realtime]);
    const s = session.data;
    const project = useAsync(() => (s ? api.getProject(s.project_id) : Promise.resolve(undefined)), [s?.project_id]);
    const crumbs = [
        { label: "Projects", to: "/" },
        ...(s ? [{ label: project.data?.name ?? "Project", to: `/projects/${s.project_id}` }] : []),
        { label: "Session" },
    ];
    return (_jsxs(_Fragment, { children: [_jsx(PageHeader, { crumbs: crumbs, title: "Session", description: s && (_jsxs(_Fragment, { children: ["Started ", timeAgo(s.created_at), " \u00B7", " ", _jsx("span", { className: "font-mono text-xs", children: s.id })] })), actions: s && (_jsx("span", { className: `rounded-full px-3 py-1.5 text-xs font-medium capitalize ${s.status === "active" ? "bg-good-soft text-good" : "bg-surface-2 text-muted"}`, children: s.status })) }), _jsxs("div", { className: channel.error || realtimeError ? "mb-6 space-y-4" : "", children: [channel.error && _jsx(ErrorBanner, { children: errorText(channel.error) }), realtimeError && _jsx(ErrorBanner, { children: errorText(realtimeError) })] }), _jsxs("div", { className: "grid gap-6 lg:grid-cols-3", children: [_jsxs("section", { className: "card lg:col-span-2", children: [_jsxs("div", { className: "card-head", children: [_jsx("h2", { className: "card-title", children: "Activity" }), channel.data && (_jsx("code", { className: "truncate font-mono text-xs text-muted", title: "Realtime channel", children: channel.data.channel }))] }), events.length === 0 ? (_jsx(EmptyState, { icon: _jsx(Radio, { className: "size-5" }), title: "No live events yet", children: _jsx("p", { children: "Events from this session show up here as they happen." }) })) : (_jsx("ol", { className: "divide-y divide-line", children: [...events].reverse().map((e) => (_jsxs("li", { className: "flex items-center gap-4 px-5 py-3 text-sm", children: [_jsx("time", { className: "w-20 shrink-0 text-xs tabular-nums text-muted", dateTime: e.occurred_at, children: timeFmt.format(Date.parse(e.occurred_at)) }), _jsx("code", { className: "font-mono text-xs text-fg-2", children: e.type })] }, e.event_id))) }))] }), _jsxs("section", { className: "card h-fit", children: [_jsx("div", { className: "card-head", children: _jsx("h2", { className: "card-title", children: "Coming soon" }) }), _jsx(EmptyState, { icon: _jsx(Users, { className: "size-5" }), title: "Presence and shared tools", children: _jsx("p", { children: "Who's here, the session's device panel and AI runs will appear in this space." }) })] })] })] }));
}
