// RouteGuards.tsx
import React, { useEffect, useState } from "react";
import { Navigate } from "react-router-dom";
import { useAuth } from "../auth/AuthContext";
import Spinner from "./Spinner";

function FullScreenLoader() {
  return (
    <div
      style={{
        minHeight: "100vh",
        minWidth: "100vw",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        background: "#0f1115",
      }}
    >
      <Spinner />
    </div>
  );
}

export function ProtectedRoute({ children }: { children: React.ReactNode }) {
  const auth = useAuth();

  if (auth.loading) {
    return <FullScreenLoader />;
  }

  if (!auth.user) {
    return <Navigate to="/login" replace />;
  }

  return <>{children}</>;
}

export function PublicRoute({ children }: { children: React.ReactNode }) {
  const auth = useAuth();

  if (auth.loading) {
    return <FullScreenLoader />;
  }

  if (auth.user) {
    return <Navigate to="/" replace />;
  }

  return <>{children}</>;
}