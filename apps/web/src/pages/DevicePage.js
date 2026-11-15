import { jsx as _jsx, Fragment as _Fragment, jsxs as _jsxs } from "react/jsx-runtime";
import { Activity, BarChart3, Network, Radio, Table2, Timer } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { useParams } from "react-router-dom";
import { api } from "../api/client";
import { CommandList } from "../components/CommandList";
import { LogStream } from "../components/LogStream";
import { MetricChart } from "../components/MetricChart";
import { EmptyState, ErrorBanner, errorText, PageHeader, Skeleton, StatusPill, timeAgo, } from "../components/ui";
import { useSession } from "../auth/AuthGate";
import { SetupChain } from "../device/SetupChain";
import { BoardDialog, SensorDialog } from "../device/SetupDialogs";
import { describeMetric, effectiveStatus, formatValue, toSeries, } from "../device/telemetry";
import { useDeviceLive } from "../device/useDeviceLive";
import { useAsync } from "../useAsync";
const LIVE = {
    connecting: { text: "Connecting…", dot: "bg-warn", chip: "bg-warn-soft text-warn" },
    reconnecting: { text: "Reconnecting…", dot: "bg-warn", chip: "bg-warn-soft text-warn" },
    offline: { text: "Live updates unavailable", dot: "bg-muted", chip: "bg-surface-2 text-muted" },
};
/** "Live" only while the board is actually streaming; otherwise say why not. */
function liveChip(live, board) {
    if (live !== "live")
        return LIVE[live];
    if (board === "online")
        return { text: "Live", dot: "bg-good live-pulse", chip: "bg-good-soft text-good" };
    return {
        text: board === "unknown" ? "Waiting for the board" : "Board not connected",
        dot: "bg-muted",
        chip: "bg-surface-2 text-muted",
        title: "Start `builderwars run --cloud` on the laptop the FREE-WILi is plugged into",
    };
}
/** Re-renders every `ms` so time-based state (a board going silent) updates on its own. */
function useNow(ms) {
    const [now, setNow] = useState(() => Date.now());
    useEffect(() => {
        const t = window.setInterval(() => setNow(Date.now()), ms);
        return () => window.clearInterval(t);
    }, [ms]);
    return now;
}
/** How often the setup (laptop/FREE-WILi report, boards, sensors) is refetched. */
const SETUP_REFRESH_MS = 30_000;
export function DevicePage() {
    const { deviceId = "" } = useParams();
    const state = useDeviceLive(deviceId);
    const { device: d, samples } = state;
    const [asTable, setAsTable] = useState(false);
    const project = useAsync(() => (d ? api.getProject(d.project_id) : Promise.resolve(undefined)), [d?.project_id]);
    const now = useNow(5_000);
    const board = effectiveStatus(d, now);
    const session = useSession();
    const setup = useAsync(() => api.getDeviceSetup(deviceId), [deviceId]);
    const reloadSetup = setup.reload;
    useEffect(() => {
        const timer = window.setInterval(reloadSetup, SETUP_REFRESH_MS);
        return () => window.clearInterval(timer);
    }, [reloadSetup]);
    const [dialog, setDialog] = useState();
    // Boards and sensors are owner-only for now (the owner will open it to members later).
    const canEdit = !!project.data && project.data.owner_user_id === session?.user.userId;
    const series = useMemo(() => toSeries(samples), [samples]);
    const latest = useMemo(() => Object.fromEntries(series.map((s) => [s.name, s.latest])), [series]);
    const meta = useMemo(() => {
        const out = {};
        for (const s of setup.data?.sensors ?? [])
            out[s.key] = { label: s.name, unit: s.unit ?? "" };
        return out;
    }, [setup.data]);
    const charted = series.filter((s) => s.kind !== "text");
    const domain = samples.length
        ? [Date.parse(samples[0].ts), Date.parse(samples[samples.length - 1].ts)]
        : [0, 0];
    const crumbs = [
        { label: "Projects", to: "/" },
        ...(d ? [{ label: project.data?.name ?? "Project", to: `/projects/${d.project_id}` }] : []),
        { label: d?.display_name ?? "Device" },
    ];
    if (state.error) {
        return (_jsxs(_Fragment, { children: [_jsx(PageHeader, { title: "Device", crumbs: crumbs }), _jsx(ErrorBanner, { children: errorText(state.error) })] }));
    }
    const live = liveChip(state.live, board);
    return (_jsxs(_Fragment, { children: [_jsx(PageHeader, { crumbs: crumbs, title: d ? (_jsxs("span", { className: "flex items-center gap-3", children: [_jsx("span", { className: "truncate", children: d.display_name }), _jsx(StatusPill, { status: board })] })) : (_jsx(Skeleton, { className: "h-8 w-56" })), description: d && (_jsxs(_Fragment, { children: [d.hardware_model, d.extensions.length ? ` + ${d.extensions.join(", ")}` : "", " \u00B7 firmware", " ", d.firmware_version ?? "unknown", " \u00B7 last seen ", timeAgo(d.last_seen_at)] })), actions: _jsxs("span", { className: `inline-flex items-center gap-2 rounded-full px-3 py-1.5 text-xs font-medium ${live.chip}`, title: state.liveError ?? live.title, children: [_jsx("span", { className: `size-2 rounded-full ${live.dot}`, "aria-hidden": "true" }), live.text] }) }), _jsxs("section", { className: "card mb-6", children: [_jsxs("div", { className: "card-head", children: [_jsxs("h2", { className: "card-title flex items-center gap-2", children: [_jsx(Network, { className: "size-4 text-muted", "aria-hidden": "true" }), "Test setup"] }), !canEdit && project.data && (_jsx("span", { className: "text-xs text-muted", children: "Only the project owner can change boards and sensors." }))] }), setup.error ? (_jsx("div", { className: "p-5", children: _jsx(ErrorBanner, { children: errorText(setup.error) }) })) : (_jsx(SetupChain, { deviceId: deviceId, setup: setup.data, latest: latest, canEdit: canEdit, actions: {
                            addBoard: () => setDialog({ kind: "board" }),
                            editBoard: (board) => setDialog({ kind: "board", board }),
                            addSensor: (board) => setDialog({ kind: "sensor", boardId: board.id }),
                            editSensor: (sensor) => setDialog({ kind: "sensor", boardId: sensor.board_id, sensor }),
                        } }))] }), dialog?.kind === "board" && (_jsx(BoardDialog, { deviceId: deviceId, board: dialog.board, sensorCount: (setup.data?.sensors ?? []).filter((s) => s.board_id === dialog.board?.id).length, onClose: () => setDialog(undefined), onSaved: reloadSetup })), dialog?.kind === "sensor" && setup.data && (_jsx(SensorDialog, { deviceId: deviceId, boards: setup.data.boards, boardId: dialog.boardId, sensor: dialog.sensor, onClose: () => setDialog(undefined), onSaved: reloadSetup })), series.length > 0 && (_jsx("dl", { className: "mb-6 grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4", children: series.slice(0, 8).map((s) => {
                    const { label, unit } = describeMetric(s.name, meta);
                    return (_jsxs("div", { className: "card px-4 py-3.5", children: [_jsx("dt", { className: "truncate text-xs font-medium text-muted", children: label }), _jsx("dd", { className: "mt-1 truncate text-xl font-semibold tabular-nums tracking-tight text-fg", children: formatValue(s.latest, s.kind === "number" ? unit : "") })] }, s.name));
                }) })), _jsxs("section", { className: "card mb-6", children: [_jsxs("div", { className: "card-head", children: [_jsxs("h2", { className: "card-title flex items-center gap-2", children: [_jsx(Activity, { className: "size-4 text-muted", "aria-hidden": "true" }), "Telemetry"] }), series.length > 0 && (_jsxs("div", { className: "flex rounded-lg border border-line bg-surface-2 p-0.5 text-xs font-medium", role: "group", children: [_jsxs("button", { className: `flex items-center gap-1.5 rounded-md px-2.5 py-1 ${!asTable ? "bg-surface text-fg shadow-sm" : "text-muted"}`, "aria-pressed": !asTable, onClick: () => setAsTable(false), children: [_jsx(BarChart3, { className: "size-3.5", "aria-hidden": "true" }), " Charts"] }), _jsxs("button", { className: `flex items-center gap-1.5 rounded-md px-2.5 py-1 ${asTable ? "bg-surface text-fg shadow-sm" : "text-muted"}`, "aria-pressed": asTable, onClick: () => setAsTable(true), children: [_jsx(Table2, { className: "size-3.5", "aria-hidden": "true" }), " Table"] })] }))] }), series.length === 0 ? (_jsx(EmptyState, { icon: _jsx(Radio, { className: "size-5" }), title: "Waiting for telemetry", children: _jsxs("p", { children: ["Sign in to the CLI on the laptop the FREE-WILi is plugged into and run", " ", _jsxs("code", { className: "font-mono text-xs", children: ["builderwars run --cloud --device-id ", deviceId] }), ". It reads the sensors defined above (add ", _jsx("code", { className: "font-mono text-xs", children: "--simulate" }), " without a board)."] }) })) : asTable ? (_jsx(TelemetryTable, { samples: samples, names: series.map((s) => s.name), meta: meta })) : (_jsxs("div", { className: "p-5", children: [charted.length > 0 ? (_jsx("div", { className: "grid gap-x-8 gap-y-6 md:grid-cols-2", children: charted.map((s) => (_jsx(MetricChart, { series: s, domain: domain, meta: meta }, s.name))) })) : (_jsx("p", { className: "text-sm text-muted", children: "This device only reports text readings (shown above)." })), _jsxs("p", { className: "mt-5 flex items-center gap-1.5 text-xs text-muted", children: [_jsx(Timer, { className: "size-3.5", "aria-hidden": "true" }), samples.length, " samples \u00B7 ", new Date(domain[0]).toLocaleTimeString(), " to", " ", new Date(domain[1]).toLocaleTimeString()] })] }))] }), _jsxs("div", { className: "grid gap-6 lg:grid-cols-5", children: [_jsxs("section", { className: "card lg:col-span-2", children: [_jsxs("div", { className: "card-head", children: [_jsx("h2", { className: "card-title", children: "Commands" }), _jsxs("div", { className: "flex gap-2", children: [_jsx("button", { className: "btn-primary px-3 py-1.5", onClick: () => state.sendCommand("ping"), disabled: !d, children: "Send ping" }), _jsx("button", { className: "btn-secondary px-3 py-1.5", onClick: () => state.sendCommand("get_uptime"), disabled: !d, children: "Get uptime" })] })] }), board !== "online" && d && (_jsx("p", { className: "border-b border-line px-5 py-2.5 text-xs text-muted", children: "The board isn't connected. A command waits 30 s for it, then times out." })), state.commandError && (_jsx("div", { className: "px-5 pt-4", children: _jsx(ErrorBanner, { children: errorText(state.commandError) }) })), _jsx(CommandList, { commands: state.commands })] }), _jsxs("section", { className: "card overflow-hidden lg:col-span-3", children: [_jsxs("div", { className: "card-head", children: [_jsx("h2", { className: "card-title", children: "Logs" }), _jsxs("span", { className: "text-xs text-muted", children: [state.logs.length, " lines"] })] }), _jsx(LogStream, { entries: state.logs })] })] })] }));
}
function TelemetryTable({ samples, names, meta, }) {
    const rows = samples.slice(-100).reverse();
    return (_jsxs("div", { children: [_jsx("div", { className: "max-h-[28rem] overflow-auto", children: _jsxs("table", { className: "w-full text-left text-sm tabular-nums", children: [_jsx("thead", { className: "sticky top-0 bg-surface-2 text-xs font-medium text-muted", children: _jsxs("tr", { children: [_jsx("th", { className: "px-5 py-2.5 font-medium", children: "Time" }), names.map((n) => {
                                        const { label, unit } = describeMetric(n, meta);
                                        return (_jsx("th", { className: "px-4 py-2.5 font-medium whitespace-nowrap", children: unit ? `${label} (${unit})` : label }, n));
                                    })] }) }), _jsx("tbody", { className: "divide-y divide-line", children: rows.map((s) => (_jsxs("tr", { className: "hover:bg-surface-2", children: [_jsx("td", { className: "px-5 py-2 whitespace-nowrap text-muted", children: new Date(s.ts).toLocaleTimeString() }), names.map((n) => (_jsx("td", { className: "px-4 py-2 whitespace-nowrap text-fg", children: formatValue(s.readings[n]) }, n)))] }, s.ts))) })] }) }), samples.length > 100 && (_jsxs("p", { className: "border-t border-line px-5 py-2.5 text-xs text-muted", children: ["Newest 100 of ", samples.length, "."] }))] }));
}
