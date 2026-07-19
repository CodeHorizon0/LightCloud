// RouteGuards.tsx
import React from "react";
import { Navigate } from "react-router-dom";
import { useAuth } from "../auth/AuthContext";

interface FullScreenLoaderProps {}

function FullScreenLoader(props: FullScreenLoaderProps) {
  return (
    <div
      style={{
        minHeight: "100vh",
        minWidth: "100vw",
        display: "grid",
        placeItems: "center",
        fontFamily: "system-ui, sans-serif",
        fontSize: 16,
        color: "#666",
        background: "#0f1115",
      }}
    >
      Session check...
    </div>
  );
}

interface ProtectedRouteProps {
  children: React.ReactNode;
}

export function ProtectedRoute(props: ProtectedRouteProps) {
  const children = props.children;
  const auth = useAuth();
  if (auth.loading) {
    return <FullScreenLoader />;
  }
  if (!auth.user) {
    return <Navigate to="/login" replace />;
  }
  return children;
}

interface PublicRouteProps {
  children: React.ReactNode;
}

export function PublicRoute(props: PublicRouteProps) {
  const children = props.children;
  const auth = useAuth();
  if (auth.loading) {
    return <FullScreenLoader />;
  }
  if (auth.user) {
    return <Navigate to="/" replace />;
  }
  return children;
}