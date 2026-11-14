import { NavLink, Route, Routes } from "react-router-dom";
import { AuthGate, useSession } from "./auth/AuthGate";
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
  return (
    <div className="shell">
      <header>
        <strong>Builderwars</strong>
        <nav>
          <NavLink to="/">Projects</NavLink>
        </nav>
        <span className="header-user">
          {session?.mode === "dev-header" ? (
            <span className="badge">local dev · {session.user.userId}</span>
          ) : (
            <>
              <span className="muted">{session?.user.label}</span>
              <button className="link" onClick={() => void session?.signOut()}>
                Sign out
              </button>
            </>
          )}
        </span>
      </header>
      <main>
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
