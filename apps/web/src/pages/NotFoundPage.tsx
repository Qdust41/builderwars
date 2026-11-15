import { Compass } from "lucide-react";
import { Link } from "react-router-dom";
import { EmptyState } from "../components/ui";

export function NotFoundPage() {
  return (
    <div className="card">
      <EmptyState icon={<Compass className="size-5" />} title="Page not found">
        <p>That link doesn't go anywhere.</p>
        <Link to="/" className="btn-secondary mt-4">
          Back to projects
        </Link>
      </EmptyState>
    </div>
  );
}
