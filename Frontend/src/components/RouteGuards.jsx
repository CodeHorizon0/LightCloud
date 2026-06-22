import React from "react";
import { Navigate } from "react-router-dom";
import { useAuth } from "../auth/AuthContext";

function FullScreenLoader() {
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
      Проверка сессии...
    </div>
  );
}

export function ProtectedRoute(props) {
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

export function PublicRoute(props) {
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
