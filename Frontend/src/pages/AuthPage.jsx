import React, { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import {
  AuthValidationError,
  validatePassword,
  validateUsername,
  useAuth,
} from "../auth/AuthContext";

export default function AuthPage(props) {
  const mode = props.mode;
  const navigate = useNavigate();
  const auth = useAuth();

  const isLogin = mode === "login";

  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function handleSubmit(event) {
    event.preventDefault();
    setBusy(true);
    setError("");

    try {
      const safeUsername = validateUsername(username.trim());
      const safePassword = validatePassword(password);

      if (isLogin) {
        await auth.login(safeUsername, safePassword);
      } else {
        await auth.register(safeUsername, safePassword);
      }

      navigate("/", { replace: true });
    } catch (err) {
      if (err instanceof AuthValidationError) {
        setError(err.message);
      } else {
        setError((err && err.message) || "Authentication failed");
      }
    } finally {
      setBusy(false);
    }
  }

  return (
    <div
      style={{
        minHeight: "100vh",
        minWidth: "100%",
        display: "grid",
        placeItems: "center",
        background:
          "radial-gradient(circle at top, rgba(80, 120, 255, 0.16), transparent 35%), #0f1115",
        color: "#eaeef7",
        padding: 12,
        fontFamily: "system-ui, sans-serif",
      }}
    >
      <form
        onSubmit={handleSubmit}
        style={{
          width: "100%",
          maxWidth: 420,
          background: "rgba(18, 22, 31, 0.95)",
          border: "1px solid rgba(255,255,255,0.08)",
          borderRadius: 16,
          padding: 20,
          boxShadow: "0 18px 50px rgba(0,0,0,0.35)",
        }}
      >
        <div style={{ marginBottom: 20 }}>
          <h1 style={{ margin: 0, fontSize: 30, lineHeight: 1.1 }}>
            {isLogin ? "Вход" : "Регистрация"}
          </h1>
          <p style={{ margin: "8px 0 0", color: "#9aa4b2" }}>
            {isLogin
              ? "Авторизуйтесь, чтобы продолжить"
              : "Создайте аккаунт для использования"}
          </p>
        </div>

        <label style={{ display: "block", marginBottom: 14 }}>
          <div style={{ marginBottom: 6, fontSize: 13, color: "#cdd6e1" }}>
            Username
          </div>
          <input
            value={username}
            onChange={function (e) {
              setUsername(e.target.value);
            }}
            autoComplete="username"
            autoCapitalize="none"
            autoCorrect="off"
            spellCheck={false}
            inputMode="text"
            required
            minLength={3}
            maxLength={32}
            pattern="[A-Za-z0-9._]{3,32}"
            placeholder="user_name"
            title="3-32 characters: letters, numbers, dot and underscore"
            style={{
              width: "100%",
              boxSizing: "border-box",
              borderRadius: 10,
              border: "1px solid rgba(255,255,255,0.10)",
              background: "#0b0e14",
              color: "#fff",
              padding: "10px 12px",
              outline: "none",
            }}
          />
        </label>

        <label style={{ display: "block", marginBottom: 18 }}>
          <div style={{ marginBottom: 6, fontSize: 13, color: "#cdd6e1" }}>
            Password
          </div>
          <input
            type="password"
            value={password}
            onChange={function (e) {
              setPassword(e.target.value);
            }}
            autoComplete={isLogin ? "current-password" : "new-password"}
            required
            minLength={8}
            maxLength={128}
            placeholder="••••••••"
            title="8-128 characters"
            style={{
              width: "100%",
              boxSizing: "border-box",
              borderRadius: 10,
              border: "1px solid rgba(255,255,255,0.10)",
              background: "#0b0e14",
              color: "#fff",
              padding: "10px 12px",
              outline: "none",
            }}
          />
        </label>

        {error ? (
          <div
            style={{
              marginBottom: 12,
              padding: "10px 12px",
              borderRadius: 10,
              background: "rgba(255, 72, 72, 0.12)",
              border: "1px solid rgba(255, 72, 72, 0.22)",
              color: "#ffb4b4",
              fontSize: 14,
              whiteSpace: "pre-wrap",
              wordBreak: "break-word",
            }}
          >
            {error}
          </div>
        ) : null}

        <button
          type="submit"
          disabled={busy}
          style={{
            width: "100%",
            border: "none",
            borderRadius: 10,
            padding: "10px 12px",
            background: busy ? "#5c6b82" : "#5b8cff",
            color: "#fff",
            fontWeight: 700,
            cursor: busy ? "not-allowed" : "pointer",
            marginBottom: 14,
          }}
        >
          {busy ? "Подожди..." : isLogin ? "Войти" : "Создать аккаунт"}
        </button>

        <div style={{ color: "#9aa4b2", fontSize: 14 }}>
          {isLogin ? (
            <>
              Нет аккаунта?{" "}
              <Link to="/regin" style={{ color: "#8ab4ff", textDecoration: "none" }}>
                Регистрация
              </Link>
            </>
          ) : (
            <>
              Уже есть аккаунт?{" "}
              <Link to="/login" style={{ color: "#8ab4ff", textDecoration: "none" }}>
                Вход
              </Link>
            </>
          )}
        </div>
      </form>
    </div>
  );
}