import { Link } from "react-router-dom";

export function NotFoundPage() {
  return (
    <section>
      <h1>Not found</h1>
      <Link to="/">Back to projects</Link>
    </section>
  );
}
