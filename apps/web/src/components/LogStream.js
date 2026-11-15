import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { useEffect, useRef } from "react";
const timeFmt = new Intl.DateTimeFormat(undefined, {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
});
function levelClass(level) {
    const l = level.toLowerCase();
    if (l === "error" || l === "critical" || l === "fatal")
        return "text-red-400";
    if (l === "warning" || l === "warn")
        return "text-amber-300";
    if (l === "debug")
        return "text-console-muted";
    return "text-sky-300";
}
/** Device logs and events, oldest at the top; follows new lines unless the reader scrolled up. */
export function LogStream({ entries }) {
    const box = useRef(null);
    const follow = useRef(true);
    useEffect(() => {
        const el = box.current;
        if (el && follow.current)
            el.scrollTop = el.scrollHeight;
    }, [entries]);
    return (_jsx("div", { ref: box, className: "h-72 overflow-y-auto bg-console lg:h-96 px-4 py-3 font-mono text-xs leading-relaxed text-console-fg", role: "log", "aria-live": "polite", onScroll: (e) => {
            const el = e.currentTarget;
            follow.current = el.scrollHeight - el.scrollTop - el.clientHeight < 24;
        }, children: entries.length === 0 ? (_jsx("p", { className: "text-console-muted", children: "Waiting for log lines\u2026" })) : (_jsx("ol", { children: entries.map((e, i) => (_jsxs("li", { className: "flex gap-3 py-0.5", children: [_jsx("time", { dateTime: e.at, className: "shrink-0 text-console-muted", children: timeFmt.format(Date.parse(e.at)) }), _jsx("span", { className: `w-14 shrink-0 uppercase ${levelClass(e.level)}`, children: e.kind === "event" ? "event" : e.level }), _jsx("span", { className: "min-w-0 break-words whitespace-pre-wrap", children: e.message })] }, `${e.at}-${i}`))) })) }));
}
