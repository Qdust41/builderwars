import { useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import { useAsync } from "../useAsync";

export function ProjectsPage() {
  const projects = useAsync(() => api.listProjects(), []);
  const [name, setName] = useState("");

  async function create(e: FormEvent) {
    e.preventDefault();
    if (!name.trim()) return;
    await api.createProject(name.trim());
    setName("");
    projects.reload();
  }

  return (
    <section>
      <h1>Projects</h1>
      {projects.error && <p className="error">{projects.error}</p>}
      <ul>
        {projects.data?.map((p) => (
          <li key={p.id}>
            <Link to={`/projects/${p.id}`}>{p.name}</Link>
          </li>
        ))}
      </ul>
      {projects.data?.length === 0 && <p>No projects yet.</p>}
      <form onSubmit={create}>
        <input value={name} onChange={(e) => setName(e.target.value)} placeholder="Project name" />
        <button type="submit">Create project</button>
      </form>
    </section>
  );
}
