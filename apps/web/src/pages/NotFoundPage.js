import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { Compass } from "lucide-react";
import { Link } from "react-router-dom";
import { EmptyState } from "../components/ui";
export function NotFoundPage() {
    return (_jsx("div", { className: "card", children: _jsxs(EmptyState, { icon: _jsx(Compass, { className: "size-5" }), title: "Page not found", children: [_jsx("p", { children: "That link doesn't go anywhere." }), _jsx(Link, { to: "/", className: "btn-secondary mt-4", children: "Back to projects" })] }) }));
}
