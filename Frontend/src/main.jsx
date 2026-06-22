import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";

import App from "./App";
import { AuthProvider } from "./auth/AuthContext";
import { ProtectedRoute, PublicRoute } from "./components/RouteGuards";
import AuthPage from "./pages/AuthPage";
import "./index.css";

createRoot(document.getElementById("root")).render(
  <StrictMode>
    <BrowserRouter>
      <AuthProvider>
        <Routes>
          <Route
            path="/login"
            element={
              <PublicRoute>
                <AuthPage mode="login" />
              </PublicRoute>
            }
          />
          <Route
            path="/regin"
            element={
              <PublicRoute>
                <AuthPage mode="register" />
              </PublicRoute>
            }
          />
          <Route path="/register" element={<Navigate to="/regin" replace />} />
          <Route
            path="/"
            element={
              <ProtectedRoute>
                <App />
              </ProtectedRoute>
            }
          />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </AuthProvider>
    </BrowserRouter>
  </StrictMode>,
);