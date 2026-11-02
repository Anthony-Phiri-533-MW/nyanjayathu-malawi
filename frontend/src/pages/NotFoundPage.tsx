import { Link } from "react-router-dom";
import { Card } from "@/components/ui/Card";
import { EmptyState } from "@/components/ui/States";

export function NotFoundPage() {
  return (
    <Card>
      <EmptyState
        title="Page not found"
        description="The address you opened does not match any screen in this console."
        action={
          <Link to="/" className="btn-secondary px-3 py-1.5 text-sm">
            Back to dashboard
          </Link>
        }
      />
    </Card>
  );
}
