import { jsx as _jsx, Fragment as _Fragment, jsxs as _jsxs } from "react/jsx-runtime";
import { ChevronRight, Cpu, History, Play, Plus, X } from "lucide-react";
import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api } from "../api/client";
import { EmptyState, ErrorBanner, errorText, PageHeader, Skeleton, StatusPill, timeAgo, } from "../components/ui";
import { useAsync } from "../useAsync";
export function ProjectPage() {
    const { projectId = "" } = useParams();
    const navigate = useNavigate();
    const project = useAsync(() => api.getProject(projectId), [projectId]);
    const devices = useAsync(() => api.listDevices(projectId), [projectId]);
    const sessions = useAsync(() => api.listSessions(projectId), [projectId]);
    const [registering, setRegistering] = useState(false);
    const [sessionError, setSessionError] = useState();
    const [starting, setStarting] = useState(false);
    async function startSession() {
        setStarting(true);
        setSessionError(undefined);
        try {
            const session = await api.startSession(projectId);
            navigate(`/sessions/${session.id}`);
        }
        catch (err) {
            setSessionError(errorText(err));
            setStarting(false);
        }
    }
    if (project.error) {
        return (_jsxs(_Fragment, { children: [_jsx(PageHeader, { title: "Project", crumbs: [{ label: "Projects", to: "/" }] }), _jsx(ErrorBanner, { children: errorText(project.error) })] }));
    }
    const deviceList = devices.data ?? [];
    const online = deviceList.filter((d) => d.connection_status === "online").length;
    const sessionList = [...(sessions.data ?? [])].sort((a, b) => Date.parse(b.created_at) - Date.parse(a.created_at));
    return (_jsxs(_Fragment, { children: [_jsx(PageHeader, { crumbs: [{ label: "Projects", to: "/" }, { label: project.data?.name ?? "…" }], title: project.data?.name ?? _jsx(Skeleton, { className: "h-8 w-48" }), description: devices.data &&
                    `${deviceList.length} ${deviceList.length === 1 ? "device" : "devices"} · ${online} online`, actions: _jsxs(_Fragment, { children: [_jsxs("button", { className: "btn-secondary", onClick: startSession, disabled: starting, children: [_jsx(Play, { className: "size-4", "aria-hidden": "true" }), starting ? "Starting…" : "Start session"] }), !registering && (_jsxs("button", { className: "btn-primary", onClick: () => setRegistering(true), children: [_jsx(Plus, { className: "size-4", "aria-hidden": "true" }), "Add device"] }))] }) }), sessionError && (_jsx("div", { className: "mb-6", children: _jsx(ErrorBanner, { children: sessionError }) })), _jsxs("div", { className: "grid gap-6 lg:grid-cols-3", children: [_jsxs("section", { className: "space-y-4 lg:col-span-2", children: [registering && (_jsx(RegisterDevice, { projectId: projectId, onCancel: () => setRegistering(false), onDone: () => {
                                    setRegistering(false);
                                    devices.reload();
                                } })), _jsxs("div", { className: "card", children: [_jsx("div", { className: "card-head", children: _jsx("h2", { className: "card-title", children: "Devices" }) }), devices.error ? (_jsx("div", { className: "p-5", children: _jsx(ErrorBanner, { children: errorText(devices.error) }) })) : devices.loading && !devices.data ? (_jsxs("div", { className: "space-y-3 p-5", children: [_jsx(Skeleton, { className: "h-14" }), _jsx(Skeleton, { className: "h-14" })] })) : deviceList.length === 0 ? (_jsxs(EmptyState, { icon: _jsx(Cpu, { className: "size-5" }), title: "No devices yet", children: [_jsx("p", { children: "Add a board, then sign in to the CLI on its host to stream telemetry and logs here." }), !registering && (_jsxs("button", { className: "btn-primary mt-4", onClick: () => setRegistering(true), children: [_jsx(Plus, { className: "size-4", "aria-hidden": "true" }), "Add device"] }))] })) : (_jsx("ul", { className: "divide-y divide-line", children: deviceList.map((d) => (_jsx("li", { children: _jsxs(Link, { to: `/devices/${d.id}`, className: "group flex items-center gap-4 px-5 py-4 transition-colors hover:bg-surface-2", children: [_jsx("span", { className: "grid size-10 shrink-0 place-items-center rounded-lg border border-line bg-surface-2 text-fg-2", children: _jsx(Cpu, { className: "size-5", "aria-hidden": "true" }) }), _jsxs("span", { className: "min-w-0 flex-1", children: [_jsx("span", { className: "block truncate font-medium text-fg", children: d.display_name }), _jsxs("span", { className: "block truncate text-xs text-muted", children: [d.hardware_model, d.extensions.length ? ` + ${d.extensions.join(", ")}` : "", " \u00B7 seen", " ", timeAgo(d.last_seen_at)] })] }), _jsx(StatusPill, { status: d.connection_status }), _jsx(ChevronRight, { className: "size-4 text-muted transition group-hover:translate-x-0.5", "aria-hidden": "true" })] }) }, d.id))) }))] })] }), _jsxs("section", { className: "card h-fit", children: [_jsx("div", { className: "card-head", children: _jsx("h2", { className: "card-title", children: "Sessions" }) }), sessions.error ? (_jsx("div", { className: "p-5", children: _jsx(ErrorBanner, { children: errorText(sessions.error) }) })) : sessions.loading && !sessions.data ? (_jsx("div", { className: "p-5", children: _jsx(Skeleton, { className: "h-10" }) })) : sessionList.length === 0 ? (_jsx(EmptyState, { icon: _jsx(History, { className: "size-5" }), title: "No sessions", children: _jsx("p", { children: "Start a session to follow a build together in real time." }) })) : (_jsx("ul", { className: "divide-y divide-line", children: sessionList.map((s) => (_jsx("li", { children: _jsxs(Link, { to: `/sessions/${s.id}`, className: "flex items-center justify-between gap-3 px-5 py-3 text-sm transition-colors hover:bg-surface-2", children: [_jsxs("span", { className: "min-w-0", children: [_jsx("span", { className: "block truncate font-mono text-xs text-fg-2", children: s.id }), _jsxs("span", { className: "block text-xs text-muted", children: ["Started ", timeAgo(s.created_at)] })] }), _jsx("span", { className: `rounded-full px-2 py-0.5 text-xs font-medium capitalize ${s.status === "active" ? "bg-good-soft text-good" : "bg-surface-2 text-muted"}`, children: s.status })] }) }, s.id))) }))] })] })] }));
}
function RegisterDevice({ projectId, onCancel, onDone, }) {
    const [name, setName] = useState("");
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState();
    async function submit(e) {
        e.preventDefault();
        if (!name.trim())
            return;
        setBusy(true);
        setError(undefined);
        try {
            await api.registerDevice(projectId, name.trim());
            onDone();
        }
        catch (err) {
            setError(errorText(err));
            setBusy(false);
        }
    }
    return (_jsxs("form", { onSubmit: submit, className: "card p-5", children: [_jsxs("div", { className: "mb-4 flex items-center justify-between", children: [_jsx("h2", { className: "card-title", children: "Add a device" }), _jsx("button", { type: "button", className: "btn-ghost -mr-2 p-1.5", onClick: onCancel, "aria-label": "Cancel", children: _jsx(X, { className: "size-4" }) })] }), _jsx("label", { htmlFor: "device-name", className: "field-label", children: "Device name" }), _jsxs("div", { className: "flex flex-col gap-3 sm:flex-row", children: [_jsx("input", { id: "device-name", className: "input", autoFocus: true, maxLength: 120, value: name, onChange: (e) => setName(e.target.value), placeholder: "e.g. Bench board" }), _jsx("button", { type: "submit", className: "btn-primary", disabled: busy || !name.trim(), children: busy ? "Adding…" : "Add device" })] }), _jsx("p", { className: "mt-2 text-xs text-muted", children: "Registered as a FREE-WILi with the WiFi Orca extension." }), error && (_jsx("div", { className: "mt-3", children: _jsx(ErrorBanner, { children: error }) }))] }));
}
