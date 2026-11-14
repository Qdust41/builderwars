import { NavLink, Route, Routes } from "react-router-dom";
import { DevicePage } from "./pages/DevicePage";
import { NotFoundPage } from "./pages/NotFoundPage";
import { ProjectPage } from "./pages/ProjectPage";
import { ProjectsPage } from "./pages/ProjectsPage";
import { SessionPage } from "./pages/SessionPage";

export function App() {
  return (
    <div className="shell">
      <header>
        <strong>Builderwars</strong>
        <nav>
          <NavLink to="/">Projects</NavLink>
        </nav>
        <span className="badge">local dev</span>
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
