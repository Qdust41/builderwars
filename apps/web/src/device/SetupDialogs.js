import { jsx as _jsx, jsxs as _jsxs, Fragment as _Fragment } from "react/jsx-runtime";
import { BookOpen, Plus, Search, Trash2, X } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { api } from "../api/client";
import { ErrorBanner, errorText, Spinner } from "../components/ui";
import { useAsync } from "../useAsync";
import { DATA_TYPES, decodePreview, DraftError, draftFrom, emptyDraft, parseBytes, PROTOCOLS, slugKey, toSensorInput, } from "./sensors";
/** A centred dialog over a dimmed page; Escape or the backdrop closes it. */
function Modal({ title, onClose, wide = false, children, }) {
    useEffect(() => {
        const onKey = (e) => e.key === "Escape" && onClose();
        window.addEventListener("keydown", onKey);
        return () => window.removeEventListener("keydown", onKey);
    }, [onClose]);
    return (_jsx("div", { className: "fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-black/40 px-4 py-8 sm:py-14", onMouseDown: (e) => e.target === e.currentTarget && onClose(), children: _jsxs("div", { role: "dialog", "aria-modal": "true", "aria-label": title, className: `card w-full ${wide ? "max-w-3xl" : "max-w-lg"} shadow-xl`, children: [_jsxs("div", { className: "card-head", children: [_jsx("h2", { className: "card-title", children: title }), _jsx("button", { className: "btn-ghost size-8 p-0", "aria-label": "Close", onClick: onClose, children: _jsx(X, { className: "size-4" }) })] }), children] }) }));
}
function Field({ label, hint, error, children, className = "", }) {
    return (_jsxs("label", { className: `block min-w-0 ${className}`, children: [_jsx("span", { className: `field-label ${error ? "text-bad" : ""}`, children: label }), children, hint && _jsx("span", { className: "mt-1 block text-xs text-muted", children: hint })] }));
}
/** Delete needs a second click within a few seconds. */
function DeleteButton({ label, onDelete, busy }) {
    const [armed, setArmed] = useState(false);
    useEffect(() => {
        if (!armed)
            return;
        const t = window.setTimeout(() => setArmed(false), 4000);
        return () => window.clearTimeout(t);
    }, [armed]);
    return (_jsxs("button", { type: "button", className: `btn ${armed ? "bg-bad text-white hover:opacity-90" : "text-bad hover:bg-bad-soft"}`, disabled: busy, onClick: () => (armed ? onDelete() : setArmed(true)), children: [_jsx(Trash2, { className: "size-4", "aria-hidden": "true" }), armed ? "Click again to confirm" : label] }));
}
// -- target board -------------------------------------------------------------------------------
export function BoardDialog({ deviceId, board, sensorCount, onClose, onSaved, }) {
    const [name, setName] = useState(board?.name ?? "");
    const [notes, setNotes] = useState(board?.notes ?? "");
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState();
    const run = async (work) => {
        setBusy(true);
        setError(undefined);
        try {
            await work();
            onSaved();
            onClose();
        }
        catch (err) {
            setError(errorText(err));
        }
        finally {
            setBusy(false);
        }
    };
    const submit = (e) => {
        e.preventDefault();
        const body = { name: name.trim(), notes };
        void run(() => (board ? api.updateBoard(deviceId, board.id, body) : api.addBoard(deviceId, body)));
    };
    return (_jsx(Modal, { title: board ? "Edit target board" : "Add a target board", onClose: onClose, children: _jsxs("form", { onSubmit: submit, className: "space-y-4 p-5", children: [_jsx("p", { className: "text-sm text-muted", children: "A board under test, wired to this device's FREE-WILi. One FREE-WILi drives up to 4." }), _jsx(Field, { label: "Name", children: _jsx("input", { className: "input", value: name, onChange: (e) => setName(e.target.value), placeholder: "Motor controller rev B", maxLength: 120, required: true, autoFocus: true }) }), _jsx(Field, { label: "Notes", hint: "Optional: wiring, revision, what's being tested.", children: _jsx("textarea", { className: "input min-h-20", value: notes, onChange: (e) => setNotes(e.target.value), maxLength: 2000, placeholder: "TMP102 on I2C0, ADC on SPI1 CS0" }) }), error && _jsx(ErrorBanner, { children: error }), _jsxs("div", { className: "flex flex-wrap items-center justify-between gap-2 pt-1", children: [board ? (_jsx(DeleteButton, { label: sensorCount ? `Remove board and its ${sensorCount} sensor(s)` : "Remove board", busy: busy, onDelete: () => void run(() => api.deleteBoard(deviceId, board.id)) })) : (_jsx("span", {})), _jsxs("div", { className: "flex gap-2", children: [_jsx("button", { type: "button", className: "btn-secondary", onClick: onClose, children: "Cancel" }), _jsx("button", { className: "btn-primary", disabled: busy || !name.trim(), children: board ? "Save" : "Add board" })] })] })] }) }));
}
// -- sensor -------------------------------------------------------------------------------------
export function SensorDialog({ deviceId, boards, boardId, sensor, onClose, onSaved, }) {
    const [draft, setDraft] = useState(() => sensor ? draftFrom(sensor, sensor.board_id) : emptyDraft(boardId));
    const [picking, setPicking] = useState(!sensor);
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState();
    const [badField, setBadField] = useState();
    const set = (key, value) => setDraft((d) => ({ ...d, [key]: value }));
    const setName = (name) => setDraft((d) => ({ ...d, name, key: d.keyEdited ? d.key : slugKey(name) }));
    const usePreset = (preset) => {
        setDraft({ ...draftFrom(preset.sensor, draft.boardId), keyEdited: true });
        setPicking(false);
    };
    const run = async (work) => {
        setBusy(true);
        setError(undefined);
        try {
            await work();
            onSaved();
            onClose();
        }
        catch (err) {
            setError(errorText(err));
        }
        finally {
            setBusy(false);
        }
    };
    const submit = (e) => {
        e.preventDefault();
        let body;
        try {
            body = toSensorInput(draft);
        }
        catch (err) {
            if (err instanceof DraftError) {
                setBadField(err.field);
                setError(err.message);
                return;
            }
            throw err;
        }
        setBadField(undefined);
        void run(() => (sensor ? api.updateSensor(deviceId, sensor.id, body) : api.addSensor(deviceId, body)));
    };
    const bad = (field) => badField === field;
    const raw = draft.protocol === "i2c" || draft.protocol === "spi";
    return (_jsx(Modal, { title: sensor ? `Edit ${sensor.name}` : "Add a sensor", onClose: onClose, wide: true, children: picking ? (_jsx(PresetPicker, { onPick: usePreset, onSkip: () => setPicking(false) })) : (_jsxs("form", { onSubmit: submit, className: "space-y-6 p-5", children: [!sensor && (_jsxs("button", { type: "button", className: "btn-secondary text-xs", onClick: () => setPicking(true), children: [_jsx(BookOpen, { className: "size-3.5", "aria-hidden": "true" }), " Start from a common part"] })), _jsxs("fieldset", { className: "grid gap-4 sm:grid-cols-2", children: [_jsx(Field, { label: "Name", error: bad("name"), children: _jsx("input", { className: "input", value: draft.name, onChange: (e) => setName(e.target.value), placeholder: "Board temperature", maxLength: 80, autoFocus: true }) }), _jsx(Field, { label: "Reading name", error: bad("key"), hint: "How it appears in telemetry and CSVs. Unique on this device.", children: _jsx("input", { className: "input font-mono", value: draft.key, onChange: (e) => setDraft((d) => ({ ...d, key: e.target.value, keyEdited: true })), placeholder: "board_temp_c", maxLength: 64 }) }), _jsx(Field, { label: "Target board", children: _jsx("select", { className: "input", value: draft.boardId, onChange: (e) => set("boardId", e.target.value), children: boards.map((b) => (_jsx("option", { value: b.id, children: b.name }, b.id))) }) }), _jsxs("div", { className: "grid grid-cols-2 gap-4", children: [_jsx(Field, { label: "Unit", children: _jsx("input", { className: "input", value: draft.unit, onChange: (e) => set("unit", e.target.value), placeholder: "\u00B0C", maxLength: 16 }) }), _jsx(Field, { label: "Poll every (s)", error: bad("pollInterval"), children: _jsx("input", { className: "input", inputMode: "decimal", value: draft.pollInterval, onChange: (e) => set("pollInterval", e.target.value) }) })] })] }), _jsxs("fieldset", { children: [_jsx("legend", { className: "field-label", children: "Protocol" }), _jsx("div", { className: "grid grid-cols-2 gap-2 sm:grid-cols-4", role: "radiogroup", children: PROTOCOLS.map((p) => (_jsxs("button", { type: "button", role: "radio", "aria-checked": draft.protocol === p.value, onClick: () => set("protocol", p.value), className: `rounded-lg border px-3 py-2 text-left ${draft.protocol === p.value
                                    ? "border-accent bg-accent-soft"
                                    : "border-line hover:bg-surface-2"}`, children: [_jsx("span", { className: "block text-sm font-semibold text-fg", children: p.label }), _jsx("span", { className: "block text-[11px] leading-snug text-muted", children: p.hint })] }, p.value))) })] }), _jsx(BusFields, { draft: draft, set: set, bad: bad }), draft.protocol !== "gpio" && (_jsxs("fieldset", { className: "space-y-4", children: [_jsx("legend", { className: "field-label", children: "Turn the answer into a number" }), _jsxs("div", { className: "grid gap-4 sm:grid-cols-3", children: [raw && (_jsxs(_Fragment, { children: [_jsx(Field, { label: "Data type", className: "sm:col-span-3", children: _jsx("select", { className: "input", value: draft.dataType, onChange: (e) => set("dataType", e.target.value), children: DATA_TYPES.map((t) => (_jsx("option", { value: t.value, children: t.label }, t.value))) }) }), _jsx(Field, { label: "Bit mask", error: bad("bitMask"), hint: "Optional, e.g. 0x0FFF", children: _jsx("input", { className: "input font-mono", value: draft.bitMask, onChange: (e) => set("bitMask", e.target.value) }) }), _jsx(Field, { label: "Shift right (bits)", error: bad("bitShift"), children: _jsx("input", { className: "input", inputMode: "numeric", value: draft.bitShift, onChange: (e) => set("bitShift", e.target.value) }) }), _jsx("span", { className: "hidden sm:block" })] })), _jsx(Field, { label: "Multiply by", error: bad("scale"), children: _jsx("input", { className: "input", inputMode: "decimal", value: draft.scale, onChange: (e) => set("scale", e.target.value) }) }), _jsx(Field, { label: "Then add", error: bad("offset"), children: _jsx("input", { className: "input", inputMode: "decimal", value: draft.offset, onChange: (e) => set("offset", e.target.value) }) }), _jsx(Field, { label: "Round to (decimals)", error: bad("decimals"), children: _jsx("input", { className: "input", inputMode: "numeric", value: draft.decimals, onChange: (e) => set("decimals", e.target.value), placeholder: "no rounding" }) })] }), raw && _jsx(DecodeTry, { draft: draft, set: set })] })), _jsxs("label", { className: "flex items-center gap-2 text-sm text-fg-2", children: [_jsx("input", { type: "checkbox", className: "size-4 accent-[var(--accent)]", checked: draft.enabled, onChange: (e) => set("enabled", e.target.checked) }), "Read this sensor (untick to keep the definition but stop reading it)"] }), error && _jsx(ErrorBanner, { children: error }), _jsxs("div", { className: "flex flex-wrap items-center justify-between gap-2 border-t border-line pt-4", children: [sensor ? (_jsx(DeleteButton, { label: "Remove sensor", busy: busy, onDelete: () => void run(() => api.deleteSensor(deviceId, sensor.id)) })) : (_jsx("span", { className: "text-xs text-muted", children: "A running CLI picks up changes within 30 seconds." })), _jsxs("div", { className: "flex gap-2", children: [_jsx("button", { type: "button", className: "btn-secondary", onClick: onClose, children: "Cancel" }), _jsx("button", { className: "btn-primary", disabled: busy, children: sensor ? "Save" : "Add sensor" })] })] })] })) }));
}
function BusFields({ draft, set, bad }) {
    if (draft.protocol === "i2c") {
        const writes = draft.setupWrites;
        const setWrite = (i, change) => set("setupWrites", writes.map((w, j) => (j === i ? { ...w, ...change } : w)));
        return (_jsxs("fieldset", { className: "space-y-4", children: [_jsxs("div", { className: "grid gap-4 sm:grid-cols-3", children: [_jsx(Field, { label: "Chip address", error: bad("address"), hint: "7-bit, e.g. 0x48", children: _jsx("input", { className: "input font-mono", value: draft.address, onChange: (e) => set("address", e.target.value) }) }), _jsx(Field, { label: "Register", error: bad("reg"), children: _jsx("input", { className: "input font-mono", value: draft.reg, onChange: (e) => set("reg", e.target.value) }) }), _jsx(Field, { label: "Bytes to read", error: bad("length"), children: _jsx("input", { className: "input", inputMode: "numeric", value: draft.length, onChange: (e) => set("length", e.target.value) }) })] }), _jsxs("div", { children: [_jsx("p", { className: "field-label", children: "Setup writes" }), _jsx("p", { className: "mb-2 text-xs text-muted", children: "Written before every read, in order: wake the chip, pick a channel, start a conversion." }), _jsx("div", { className: "space-y-2", children: writes.map((w, i) => (_jsxs("div", { className: "flex items-center gap-2", children: [_jsx("span", { className: "w-8 shrink-0 text-xs text-muted", children: "reg" }), _jsx("input", { className: `input w-24 font-mono ${bad(`setup-${i}`) ? "border-bad" : ""}`, value: w.reg, onChange: (e) => setWrite(i, { reg: e.target.value }), "aria-label": `Setup write ${i + 1} register` }), _jsx("span", { className: "shrink-0 text-xs text-muted", children: "bytes" }), _jsx("input", { className: `input font-mono ${bad(`setup-${i}`) ? "border-bad" : ""}`, value: w.data, onChange: (e) => setWrite(i, { data: e.target.value }), placeholder: "C2 83", "aria-label": `Setup write ${i + 1} bytes` }), _jsx("button", { type: "button", className: "btn-ghost size-9 shrink-0 p-0", "aria-label": `Remove setup write ${i + 1}`, onClick: () => set("setupWrites", writes.filter((_, j) => j !== i)), children: _jsx(X, { className: "size-4" }) })] }, i))) }), writes.length < 8 && (_jsxs("button", { type: "button", className: "btn-ghost mt-1 px-2 py-1 text-xs", onClick: () => set("setupWrites", [...writes, { reg: "0x01", data: "" }]), children: [_jsx(Plus, { className: "size-3.5", "aria-hidden": "true" }), " Add setup write"] }))] })] }));
    }
    if (draft.protocol === "spi") {
        return (_jsxs("fieldset", { className: "grid gap-4 sm:grid-cols-3", children: [_jsx(Field, { label: "Bytes to send", error: bad("write"), hint: "Hex. Pad with 00 to clock the reply in.", className: "sm:col-span-3", children: _jsx("input", { className: "input font-mono", value: draft.write, onChange: (e) => set("write", e.target.value) }) }), _jsx(Field, { label: "Keep from byte", error: bad("readOffset"), hint: "0 = first byte back", children: _jsx("input", { className: "input", inputMode: "numeric", value: draft.readOffset, onChange: (e) => set("readOffset", e.target.value) }) }), _jsx(Field, { label: "Bytes to keep", error: bad("spiLength"), children: _jsx("input", { className: "input", inputMode: "numeric", value: draft.spiLength, onChange: (e) => set("spiLength", e.target.value) }) }), _jsx(Field, { label: "Mode", hint: "Set on the FREE-WILi; noted here", children: _jsx("select", { className: "input", value: draft.mode, onChange: (e) => set("mode", e.target.value), children: [0, 1, 2, 3].map((m) => (_jsxs("option", { value: m, children: ["Mode ", m] }, m))) }) })] }));
    }
    if (draft.protocol === "uart") {
        return (_jsxs("fieldset", { className: "grid gap-4 sm:grid-cols-3", children: [_jsx(Field, { label: "Command to send", hint: "Empty: just listen", className: "sm:col-span-2", children: _jsx("input", { className: "input font-mono", value: draft.command, onChange: (e) => set("command", e.target.value), placeholder: "READ?", maxLength: 64 }) }), _jsx(Field, { label: "Line ending", children: _jsxs("select", { className: "input", value: JSON.stringify(draft.lineEnding), onChange: (e) => set("lineEnding", JSON.parse(e.target.value)), children: [_jsx("option", { value: JSON.stringify("\n"), children: "LF (\\n)" }), _jsx("option", { value: JSON.stringify("\r\n"), children: "CRLF (\\r\\n)" }), _jsx("option", { value: JSON.stringify("\r"), children: "CR (\\r)" }), _jsx("option", { value: JSON.stringify(""), children: "None" })] }) }), _jsx(Field, { label: "Find the value with", hint: "Optional regex; its group (or the whole match) is the number. Default: the first number.", className: "sm:col-span-3", children: _jsx("input", { className: "input font-mono", value: draft.pattern, onChange: (e) => set("pattern", e.target.value), placeholder: "T=([-0-9.]+)" }) }), _jsx(Field, { label: "Wait for reply (s)", error: bad("timeout"), children: _jsx("input", { className: "input", inputMode: "decimal", value: draft.timeout, onChange: (e) => set("timeout", e.target.value) }) }), _jsx(Field, { label: "Baud rate", error: bad("baud"), hint: "Set on the FREE-WILi; noted here", children: _jsx("input", { className: "input", inputMode: "numeric", value: draft.baud, onChange: (e) => set("baud", e.target.value), placeholder: "115200" }) })] }));
    }
    return (_jsxs("fieldset", { className: "grid gap-4 sm:grid-cols-3", children: [_jsx(Field, { label: "FREE-WILi GPIO", error: bad("pin"), hint: "e.g. 26 (the header's input pin)", children: _jsx("input", { className: "input", inputMode: "numeric", value: draft.pin, onChange: (e) => set("pin", e.target.value) }) }), _jsx("p", { className: "self-center text-sm text-muted sm:col-span-2", children: "Reads 1 when the pin is high, 0 when low." })] }));
}
/** Type the bytes a sensor would answer and see the value this definition makes of them. */
function DecodeTry({ draft, set }) {
    let result;
    let ok = false;
    try {
        const decode = toSensorInput({ ...draft, name: draft.name || "x", key: draft.key || "x" }).decode;
        const bytes = parseBytes(draft.sampleBytes);
        if (!draft.sampleBytes.trim())
            result = "type example bytes to check the maths";
        else if (!bytes)
            result = "enter hex bytes, e.g. 19 00";
        else {
            result = `= ${decodePreview(bytes, decode)}${draft.unit ? ` ${draft.unit}` : ""}`;
            ok = true;
        }
    }
    catch (err) {
        result = err instanceof Error ? err.message : String(err);
    }
    return (_jsxs("div", { className: "flex flex-wrap items-center gap-3 rounded-lg bg-surface-2 px-3.5 py-2.5 text-sm", children: [_jsx("span", { className: "text-muted", children: "Try it: bytes" }), _jsx("input", { className: "input w-36 py-1 font-mono", value: draft.sampleBytes, onChange: (e) => set("sampleBytes", e.target.value), placeholder: "19 00", "aria-label": "Example bytes" }), _jsx("span", { className: ok ? "font-semibold tabular-nums text-fg" : "text-xs text-muted", children: result })] }));
}
/** The table of common parts (from the API), filterable. */
function PresetPicker({ onPick, onSkip }) {
    const presets = useAsync(() => api.listSensorPresets(), []);
    const [query, setQuery] = useState("");
    const [protocol, setProtocol] = useState("all");
    const searchRef = useRef(null);
    useEffect(() => searchRef.current?.focus(), []);
    const rows = useMemo(() => {
        const q = query.trim().toLowerCase();
        return (presets.data ?? []).filter((p) => (protocol === "all" || p.sensor.bus.protocol === protocol) &&
            (!q || `${p.part} ${p.manufacturer} ${p.measures}`.toLowerCase().includes(q)));
    }, [presets.data, query, protocol]);
    return (_jsxs("div", { children: [_jsxs("div", { className: "flex flex-col gap-3 border-b border-line p-5 sm:flex-row sm:items-center", children: [_jsxs("div", { className: "relative flex-1", children: [_jsx(Search, { className: "pointer-events-none absolute top-2.5 left-3 size-4 text-muted", "aria-hidden": "true" }), _jsx("input", { ref: searchRef, className: "input pl-9", value: query, onChange: (e) => setQuery(e.target.value), placeholder: "Search parts: TMP102, current, accelerometer\u2026", "aria-label": "Search common parts" })] }), _jsxs("select", { className: "input sm:w-36", value: protocol, onChange: (e) => setProtocol(e.target.value), "aria-label": "Protocol", children: [_jsx("option", { value: "all", children: "All protocols" }), PROTOCOLS.map((p) => (_jsx("option", { value: p.value, children: p.label }, p.value)))] })] }), presets.loading ? (_jsx(Spinner, { label: "Loading common parts\u2026" })) : presets.error ? (_jsx("div", { className: "p-5", children: _jsx(ErrorBanner, { children: errorText(presets.error) }) })) : (_jsx("div", { className: "max-h-[26rem] overflow-auto", children: _jsxs("table", { className: "w-full text-left text-sm", children: [_jsx("thead", { className: "sticky top-0 bg-surface-2 text-xs text-muted", children: _jsxs("tr", { children: [_jsx("th", { className: "px-5 py-2 font-medium", children: "Part" }), _jsx("th", { className: "px-3 py-2 font-medium", children: "Measures" }), _jsx("th", { className: "hidden px-3 py-2 font-medium sm:table-cell", children: "Bus" }), _jsx("th", { className: "hidden px-3 py-2 font-medium md:table-cell", children: "Notes" })] }) }), _jsxs("tbody", { className: "divide-y divide-line", children: [rows.map((p) => (_jsxs("tr", { className: "cursor-pointer align-top hover:bg-accent-soft/60", onClick: () => onPick(p), onKeyDown: (e) => (e.key === "Enter" || e.key === " ") && onPick(p), tabIndex: 0, children: [_jsxs("td", { className: "px-5 py-2.5", children: [_jsx("span", { className: "font-medium text-fg", children: p.part }), _jsx("span", { className: "block text-xs text-muted", children: p.manufacturer })] }), _jsxs("td", { className: "px-3 py-2.5 text-fg-2", children: [p.measures, p.sensor.unit && _jsxs("span", { className: "text-muted", children: [" (", p.sensor.unit, ")"] })] }), _jsx("td", { className: "hidden px-3 py-2.5 sm:table-cell", children: _jsx("span", { className: "rounded bg-accent-soft px-1.5 py-0.5 font-mono text-[10px] font-semibold text-accent uppercase", children: p.sensor.bus.protocol }) }), _jsxs("td", { className: "hidden max-w-xs px-3 py-2.5 text-xs text-muted md:table-cell", children: [p.notes, p.datasheet && (_jsxs(_Fragment, { children: [" ", _jsx("a", { href: p.datasheet, target: "_blank", rel: "noreferrer", className: "text-accent hover:underline", onClick: (e) => e.stopPropagation(), children: "Datasheet" })] }))] })] }, p.id))), rows.length === 0 && (_jsx("tr", { children: _jsx("td", { colSpan: 4, className: "px-5 py-6 text-center text-muted", children: "No common part matches. Define it yourself instead." }) }))] })] }) })), _jsxs("div", { className: "flex items-center justify-between gap-3 border-t border-line px-5 py-3.5", children: [_jsx("span", { className: "text-xs text-muted", children: "Every field stays editable after you pick a part." }), _jsx("button", { type: "button", className: "btn-secondary", onClick: onSkip, children: "Define it myself" })] })] }));
}
