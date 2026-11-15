import { jsx as _jsx, jsxs as _jsxs, Fragment as _Fragment } from "react/jsx-runtime";
import { ArrowDown, ArrowRight, CircuitBoard, Cpu, Laptop, Pencil, Plus, Usb, } from "lucide-react";
import { timeAgo } from "../components/ui";
import { formatValue } from "./telemetry";
import { describeBus } from "./sensors";
const SOURCE_TEXT = {
    freewili: "Reading this device's sensors",
    "freewili-gpio": "No sensors defined: sending the FREE-WILi's own pins",
    simulated: "Simulated values (--simulate), no board is read",
};
/**
 * The physical chain behind a device: the laptop running the CLI, the FREE-WILi on its USB
 * port, and up to 4 target boards wired to the FREE-WILi, each with its sensors.
 */
export function SetupChain({ deviceId, setup, latest, canEdit, actions, }) {
    const host = setup?.host;
    const bridge = setup?.bridge;
    const boards = setup?.boards ?? [];
    const sensors = setup?.sensors ?? [];
    const simulated = host?.sensor_source === "simulated";
    return (_jsxs("div", { className: "grid items-stretch gap-3 p-5 lg:grid-cols-[minmax(0,1fr)_auto_minmax(0,1fr)_auto_minmax(0,1.6fr)]", children: [_jsx(Node, { icon: _jsx(Laptop, { className: "size-4" }), kind: "Laptop", title: host?.hostname ?? "Not connected yet", children: host ? (_jsxs(_Fragment, { children: [_jsx(Line, { children: host.os }), _jsxs(Line, { children: ["builderwars ", host.cli_version, " \u00B7 Python ", host.python_version] }), _jsxs(Line, { children: ["Last started ", timeAgo(setup?.reported_at)] }), host.sensor_source && (_jsx("p", { className: `mt-2 text-xs ${simulated ? "text-warn" : "text-muted"}`, children: SOURCE_TEXT[host.sensor_source] ?? host.sensor_source }))] })) : (_jsxs("p", { className: "text-xs text-muted", children: ["On the laptop the FREE-WILi is plugged into, run", " ", _jsxs("code", { className: "font-mono break-all text-fg-2", children: ["builderwars run --cloud --device-id ", deviceId] })] })) }), _jsx(Link, { label: "USB" }), _jsx(Node, { icon: _jsx(Cpu, { className: "size-4" }), kind: "FREE-WILi", title: bridge ? (bridge.serial ? `Serial ${bridge.serial}` : bridge.model) : simulated ? "Not used" : "Not seen yet", muted: !bridge, children: bridge ? (_jsxs(_Fragment, { children: [bridge.main_port && _jsxs(Line, { children: ["Main CPU ", bridge.main_port] }), bridge.display_port && _jsxs(Line, { children: ["Display CPU ", bridge.display_port] }), bridge.library_version && _jsxs(Line, { children: ["freewili ", bridge.library_version] })] })) : (_jsx("p", { className: "text-xs text-muted", children: simulated
                        ? "The last run was simulated, so no FREE-WILi was read."
                        : "Shows up here once the CLI has opened it." })) }), _jsx(Link, { label: "I2C \u00B7 SPI \u00B7 UART \u00B7 GPIO" }), _jsxs("div", { className: "flex min-w-0 flex-col gap-3", children: [_jsxs("div", { className: "flex items-center justify-between gap-2", children: [_jsxs("p", { className: "flex items-center gap-1.5 text-xs font-medium tracking-wide text-muted uppercase", children: [_jsx(CircuitBoard, { className: "size-3.5", "aria-hidden": "true" }), "Target boards \u00B7 ", boards.length, " of ", setup?.max_boards ?? 4] }), canEdit && boards.length < (setup?.max_boards ?? 4) && (_jsxs("button", { className: "btn-ghost px-2 py-1 text-xs", onClick: actions.addBoard, children: [_jsx(Plus, { className: "size-3.5", "aria-hidden": "true" }), " Add board"] }))] }), boards.length === 0 ? (_jsx("div", { className: "rounded-lg border border-dashed border-line-strong px-4 py-5 text-center text-sm text-muted", children: canEdit ? (_jsxs(_Fragment, { children: ["No target boards yet.", " ", _jsx("button", { className: "font-medium text-accent hover:underline", onClick: actions.addBoard, children: "Add the board you're testing" }), " ", "and define its sensors."] })) : ("No target boards yet. The project owner adds them.") })) : (boards.map((board) => (_jsx(BoardCard, { board: board, sensors: sensors.filter((s) => s.board_id === board.id), latest: latest, canEdit: canEdit, actions: actions }, board.id))))] })] }));
}
function BoardCard({ board, sensors, latest, canEdit, actions, }) {
    return (_jsxs("div", { className: "rounded-lg border border-line bg-surface-2/60", children: [_jsxs("div", { className: "flex items-start justify-between gap-2 px-3.5 pt-3", children: [_jsxs("div", { className: "min-w-0", children: [_jsx("p", { className: "truncate text-sm font-semibold text-fg", children: board.name }), board.notes && _jsx("p", { className: "mt-0.5 line-clamp-2 text-xs text-muted", children: board.notes })] }), canEdit && (_jsx(IconButton, { label: `Edit or remove ${board.name}`, onClick: () => actions.editBoard(board), children: _jsx(Pencil, { className: "size-3.5" }) }))] }), _jsxs("ul", { className: "mt-2 divide-y divide-line border-t border-line", children: [sensors.map((s) => (_jsx("li", { children: _jsx(SensorRow, { sensor: s, value: latest[s.key], canEdit: canEdit, onEdit: () => actions.editSensor(s) }) }, s.id))), sensors.length === 0 && _jsx("li", { className: "px-3.5 py-2.5 text-xs text-muted", children: "No sensors on this board yet." })] }), canEdit && (_jsx("div", { className: "border-t border-line px-2 py-1.5", children: _jsxs("button", { className: "btn-ghost px-2 py-1 text-xs", onClick: () => actions.addSensor(board), children: [_jsx(Plus, { className: "size-3.5", "aria-hidden": "true" }), " Add sensor"] }) }))] }));
}
function SensorRow({ sensor, value, canEdit, onEdit, }) {
    const body = (_jsxs(_Fragment, { children: [_jsxs("span", { className: "min-w-0 flex-1", children: [_jsxs("span", { className: "flex items-center gap-2", children: [_jsx("span", { className: "rounded bg-accent-soft px-1.5 py-0.5 font-mono text-[10px] font-semibold text-accent uppercase", children: sensor.protocol }), _jsx("span", { className: `truncate text-sm ${sensor.enabled ? "text-fg" : "text-muted line-through"}`, children: sensor.name })] }), _jsxs("span", { className: "mt-0.5 block truncate font-mono text-[11px] text-muted", children: [describeBus(sensor.bus), " \u00B7 every ", sensor.poll_interval_s, "s"] })] }), _jsx("span", { className: "shrink-0 text-sm font-medium tabular-nums text-fg-2", children: sensor.enabled ? formatValue(value, sensor.unit ?? "") : "off" })] }));
    return canEdit ? (_jsx("button", { className: "flex w-full items-center gap-3 px-3.5 py-2 text-left hover:bg-surface", onClick: onEdit, title: "Edit sensor", children: body })) : (_jsx("div", { className: "flex items-center gap-3 px-3.5 py-2", children: body }));
}
function Node({ icon, kind, title, muted = false, children, }) {
    return (_jsxs("div", { className: `min-w-0 self-start rounded-lg border border-line px-4 py-3.5 ${muted ? "bg-surface" : "bg-surface-2/60"}`, children: [_jsxs("p", { className: "flex items-center gap-1.5 text-xs font-medium tracking-wide text-muted uppercase", children: [_jsx("span", { "aria-hidden": "true", children: icon }), kind] }), _jsx("p", { className: `mt-1.5 truncate text-sm font-semibold ${muted ? "text-muted" : "text-fg"}`, children: title }), _jsx("div", { className: "mt-1 space-y-0.5", children: children })] }));
}
function Line({ children }) {
    return _jsx("p", { className: "truncate text-xs text-fg-2", children: children });
}
/** The cable between two nodes: an arrow across on wide screens, down on narrow ones. */
function Link({ label }) {
    return (_jsxs("div", { className: "flex items-center justify-center gap-2 text-muted lg:flex-col lg:px-1", "aria-hidden": "true", children: [_jsx(ArrowDown, { className: "size-4 lg:hidden" }), _jsx(ArrowRight, { className: "hidden size-4 lg:block" }), _jsxs("span", { className: "flex items-center gap-1 text-[10px] font-medium tracking-wide whitespace-nowrap uppercase lg:max-w-20 lg:text-center lg:whitespace-normal", children: [label === "USB" && _jsx(Usb, { className: "size-3" }), label] })] }));
}
function IconButton({ label, onClick, children }) {
    return (_jsx("button", { className: "btn-ghost size-7 p-0", "aria-label": label, title: label, onClick: onClick, children: children }));
}
