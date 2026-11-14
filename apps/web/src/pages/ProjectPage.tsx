import { useState, type FormEvent } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api } from "../api/client";
import { useAsync } from "../useAsync";

export function ProjectPage() {
  const { projectId = "" } = useParams();
  const navigate = useNavigate();
  const project = useAsync(() => api.getProject(projectId), [projectId]);
  const devices = useAsync(() => api.listDevices(projectId), [projectId]);
  const sessions = useAsync(() => api.listSessions(projectId), [projectId]);
  const [deviceName, setDeviceName] = useState("");

  async function register(e: FormEvent) {
    e.preventDefault();
    if (!deviceName.trim()) return;
    // TODO: hardware model picker once supported boards are decided.
    await api.registerDevice(projectId, deviceName.trim(), "unknown");
    setDeviceName("");
    devices.reload();
  }

  async function startSession() {
    const session = await api.startSession(projectId);
    navigate(`/sessions/${session.id}`);
  }

  if (project.error) return <p className="error">{project.error}</p>;
  return (
    <section>
      <h1>{project.data?.name ?? "…"}</h1>

      <h2>Devices</h2>
      <ul>
        {devices.data?.map((d) => (
          <li key={d.id}>
            <Link to={`/devices/${d.id}`}>{d.display_name}</Link> — {d.connection_status}
          </li>
        ))}
      </ul>
      <form onSubmit={register}>
        <input
          value={deviceName}
          onChange={(e) => setDeviceName(e.target.value)}
          placeholder="Device name"
        />
        <button type="submit">Register device</button>
      </form>

      <h2>Sessions</h2>
      <ul>
        {sessions.data?.map((s) => (
          <li key={s.id}>
            <Link to={`/sessions/${s.id}`}>{s.id}</Link> ({s.status})
          </li>
        ))}
      </ul>
      <button onClick={startSession}>Start session</button>
    </section>
  );
}
