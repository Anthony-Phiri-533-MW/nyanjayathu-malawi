import { Navigate, useLocation } from "react-router-dom";
import { useAuth } from "@/auth/AuthContext";
import { LoadingRows } from "@/components/ui/States";

/** Blocks a route until a session exists; redirects to /login otherwise. */
export function RequireAuth({ children }: { children: React.ReactNode }) {
  const { user, ready } = useAuth();
  const location = useLocation();

  if (!ready) {
    return (
      <div className="mx-auto mt-24 max-w-md">
        <LoadingRows rows={3} />
      </div>
    );
  }
  if (!user) {
    return <Navigate to="/login" replace state={{ from: location.pathname }} />;
  }
  return <>{children}</>;
}

/**
 * Permission gate. Enforcement is server-side; this only avoids showing a
 * screen that would fail with 403. Users who cannot access a route are sent to
 * the overview rather than shown an error.
 */
export function RequirePermission({
  permission,
  children,
}: {
  permission: string;
  children: React.ReactNode;
}) {
  const { can } = useAuth();
  if (!can(permission)) return <Navigate to="/" replace />;
  return <>{children}</>;
}
