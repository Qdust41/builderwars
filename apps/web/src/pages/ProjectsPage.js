import { jsx as _jsx, jsxs as _jsxs, Fragment as _Fragment } from "react/jsx-runtime";
import { ArrowRight, FolderKanban, Plus, X } from "lucide-react";
import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api } from "../api/client";
import { EmptyState, ErrorBanner, errorText, PageHeader, Skeleton, timeAgo } from "../components/ui";
import { useAsync } from "../useAsync";
export function ProjectsPage() {
    const projects = useAsync(() => api.listProjects(), []);
    const [creating, setCreating] = useState(false);
    const list = projects.data ?? [];
    return (_jsxs(_Fragment, { children: [_jsx(PageHeader, { title: "Projects", description: "Each project groups the boards, people and sessions you build with.", actions: !creating && (_jsxs("button", { className: "btn-primary", onClick: () => setCreating(true), children: [_jsx(Plus, { className: "size-4", "aria-hidden": "true" }), "New project"] })) }), creating && _jsx(CreateProject, { onCancel: () => setCreating(false) }), projects.error && (_jsx("div", { className: "mb-6", children: _jsx(ErrorBanner, { children: errorText(projects.error) }) })), projects.loading && !projects.data ? (_jsx("div", { className: "grid gap-4 sm:grid-cols-2 lg:grid-cols-3", children: [0, 1, 2].map((i) => (_jsx(Skeleton, { className: "h-28" }, i))) })) : list.length === 0 && !projects.error ? (!creating && (_jsx("div", { className: "card", children: _jsxs(EmptyState, { icon: _jsx(FolderKanban, { className: "size-5" }), title: "No projects yet", children: [_jsx("p", { children: "Create a project to register your first board and start streaming its data." }), _jsxs("button", { className: "btn-primary mt-4", onClick: () => setCreating(true), children: [_jsx(Plus, { className: "size-4", "aria-hidden": "true" }), "New project"] })] }) }))) : (_jsx("ul", { className: "grid gap-4 sm:grid-cols-2 lg:grid-cols-3", children: list.map((p) => (_jsx("li", { children: _jsxs(Link, { to: `/projects/${p.id}`, className: "card group flex h-full flex-col p-5 transition hover:border-accent/50 hover:shadow-md", children: [_jsxs("div", { className: "flex items-start justify-between gap-3", children: [_jsx("span", { className: "grid size-10 place-items-center rounded-lg bg-accent-soft text-sm font-semibold text-accent", children: p.name.slice(0, 1).toUpperCase() }), _jsx(ArrowRight, { className: "size-4 text-muted opacity-0 transition group-hover:translate-x-0.5 group-hover:opacity-100", "aria-hidden": "true" })] }), _jsx("p", { className: "mt-4 truncate font-semibold text-fg", children: p.name }), _jsxs("p", { className: "mt-0.5 text-xs text-muted", children: ["Created ", timeAgo(p.created_at)] })] }) }, p.id))) }))] }));
}
function CreateProject({ onCancel }) {
    const navigate = useNavigate();
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
            const project = await api.createProject(name.trim());
            navigate(`/projects/${project.id}`);
        }
        catch (err) {
            setError(errorText(err));
            setBusy(false);
        }
    }
    return (_jsxs("form", { onSubmit: submit, className: "card mb-6 p-5", children: [_jsxs("div", { className: "mb-4 flex items-center justify-between", children: [_jsx("h2", { className: "card-title", children: "New project" }), _jsx("button", { type: "button", className: "btn-ghost -mr-2 p-1.5", onClick: onCancel, "aria-label": "Cancel", children: _jsx(X, { className: "size-4" }) })] }), _jsx("label", { htmlFor: "project-name", className: "field-label", children: "Project name" }), _jsxs("div", { className: "flex flex-col gap-3 sm:flex-row", children: [_jsx("input", { id: "project-name", className: "input", autoFocus: true, maxLength: 120, value: name, onChange: (e) => setName(e.target.value), placeholder: "e.g. Greenhouse monitor" }), _jsx("button", { type: "submit", className: "btn-primary", disabled: busy || !name.trim(), children: busy ? "Creating…" : "Create project" })] }), error && (_jsx("div", { className: "mt-3", children: _jsx(ErrorBanner, { children: error }) }))] }));
}
