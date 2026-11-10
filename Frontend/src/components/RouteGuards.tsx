// RouteGuards.tsx
import { Fragment } from "react";
import type { ReactNode } from "react";
import { Navigate } from "react-router-dom";
import { useAuth } from "../auth/useAuth";
import Spinner from "./Spinner/Spinner";

function FullScreenLoader() {
  return (
    <div
      style={{
        minHeight: "100vh",
        minWidth: "100vw",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        background: "var(--bg)",
      }}
    >
      <Spinner />
    </div>
  );
}

export function ProtectedRoute({ children }: { children: ReactNode }) {
  const auth = useAuth();

  if (auth.loading) {
    return <FullScreenLoader />;
  }

  if (!auth.user) {
    return <Navigate to="/login" replace />;
  }

  return <Fragment key={auth.user.id}>{children}</Fragment>;
}

export function PublicRoute({ children }: { children: ReactNode }) {
  const auth = useAuth();

  if (auth.loading) {
    return <FullScreenLoader />;
  }

  if (auth.user) {
    return <Navigate to="/" replace />;
  }

  return <>{children}</>;
}
