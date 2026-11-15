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
  return (
    <AuthGate>
      <Shell />
    </AuthGate>
  );
}

function Shell() {
  const session = useSession();
  const label = session?.user.label ?? "";
  return (
    <div className="min-h-screen bg-bg">
      <header className="sticky top-0 z-20 border-b border-line bg-surface/80 backdrop-blur">
        <div className="mx-auto flex h-14 max-w-6xl items-center gap-6 px-4 sm:px-6">
          <Link to="/" aria-label="Builderwars home">
            <Logo className="text-fg" />
          </Link>
          <nav className="flex items-center gap-1 text-sm">
            <NavLink
              to="/"
              end
              className={({ isActive }) =>
                `rounded-md px-2.5 py-1.5 font-medium transition-colors ${
                  isActive ? "bg-surface-2 text-fg" : "text-muted hover:text-fg"
                }`
              }
            >
              Projects
            </NavLink>
          </nav>
          <div className="ml-auto flex items-center gap-3">
            {session?.mode === "dev-header" ? (
              <span className="rounded-full bg-warn-soft px-2.5 py-1 text-xs font-medium whitespace-nowrap text-warn">
                Local dev<span className="hidden sm:inline"> · {session.user.userId}</span>
              </span>
            ) : (
              <>
                <span className="hidden text-sm text-muted sm:inline">{label}</span>
                <span
                  className="grid size-8 place-items-center rounded-full bg-accent-soft text-xs font-semibold text-accent"
                  title={label}
                  aria-hidden="true"
                >
                  {initials(label || "?")}
                </span>
                <button
                  className="btn-ghost px-2"
                  onClick={() => void session?.signOut()}
                  title="Sign out"
                >
                  <LogOut className="size-4" aria-hidden="true" />
                  <span className="sr-only sm:not-sr-only">Sign out</span>
                </button>
              </>
            )}
          </div>
        </div>
      </header>
      <main className="mx-auto max-w-6xl px-4 py-8 sm:px-6 sm:py-10">
        <Routes>
          <Route path="/" element={<ProjectsPage />} />
          <Route path="/projects/:projectId" element={<ProjectPage />} />
          <Route path="/devices/:deviceId" element={<DevicePage />} />
          <Route path="/sessions/:sessionId" element={<SessionPage />} />
          <Route path="*" element={<NotFoundPage />} />
        </Routes>
      </main>
    </div>
  );
}
