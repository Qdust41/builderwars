import { jsx as _jsx, jsxs as _jsxs, Fragment as _Fragment } from "react/jsx-runtime";
import { LogOut } from "lucide-react";
import { Link, NavLink, Route, Routes } from "react-router-dom";
import { AuthGate, useSession } from "./auth/AuthGate";
import { initials, Logo } from "./components/ui";
import { DevicePage } from "./pages/DevicePage";
import { NotFoundPage } from "./pages/NotFoundPage";
import { ProjectPage } from "./pages/ProjectPage";
import { ProjectsPage } from "./pages/ProjectsPage";
import { SessionPage } from "./pages/SessionPage";
export function App() {
    return (_jsx(AuthGate, { children: _jsx(Shell, {}) }));
}
function Shell() {
    const session = useSession();
    const label = session?.user.label ?? "";
    return (_jsxs("div", { className: "min-h-screen bg-bg", children: [_jsx("header", { className: "sticky top-0 z-20 border-b border-line bg-surface/80 backdrop-blur", children: _jsxs("div", { className: "mx-auto flex h-14 max-w-6xl items-center gap-6 px-4 sm:px-6", children: [_jsx(Link, { to: "/", "aria-label": "Builderwars home", children: _jsx(Logo, { className: "text-fg" }) }), _jsx("nav", { className: "flex items-center gap-1 text-sm", children: _jsx(NavLink, { to: "/", end: true, className: ({ isActive }) => `rounded-md px-2.5 py-1.5 font-medium transition-colors ${isActive ? "bg-surface-2 text-fg" : "text-muted hover:text-fg"}`, children: "Projects" }) }), _jsx("div", { className: "ml-auto flex items-center gap-3", children: session?.mode === "dev-header" ? (_jsxs("span", { className: "rounded-full bg-warn-soft px-2.5 py-1 text-xs font-medium whitespace-nowrap text-warn", children: ["Local dev", _jsxs("span", { className: "hidden sm:inline", children: [" \u00B7 ", session.user.userId] })] })) : (_jsxs(_Fragment, { children: [_jsx("span", { className: "hidden text-sm text-muted sm:inline", children: label }), _jsx("span", { className: "grid size-8 place-items-center rounded-full bg-accent-soft text-xs font-semibold text-accent", title: label, "aria-hidden": "true", children: initials(label || "?") }), _jsxs("button", { className: "btn-ghost px-2", onClick: () => void session?.signOut(), title: "Sign out", children: [_jsx(LogOut, { className: "size-4", "aria-hidden": "true" }), _jsx("span", { className: "sr-only sm:not-sr-only", children: "Sign out" })] })] })) })] }) }), _jsx("main", { className: "mx-auto max-w-6xl px-4 py-8 sm:px-6 sm:py-10", children: _jsxs(Routes, { children: [_jsx(Route, { path: "/", element: _jsx(ProjectsPage, {}) }), _jsx(Route, { path: "/projects/:projectId", element: _jsx(ProjectPage, {}) }), _jsx(Route, { path: "/devices/:deviceId", element: _jsx(DevicePage, {}) }), _jsx(Route, { path: "/sessions/:sessionId", element: _jsx(SessionPage, {}) }), _jsx(Route, { path: "*", element: _jsx(NotFoundPage, {}) })] }) })] }));
}
