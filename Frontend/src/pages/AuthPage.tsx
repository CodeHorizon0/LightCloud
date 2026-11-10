import { useState } from "react";
import type { FormEvent, ChangeEvent, ReactElement } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useAuth } from "../auth/useAuth";
import styles from "./AuthPage.module.css";

interface AuthPageProps {
  mode: "login" | "register";
}

export default function AuthPage(props: AuthPageProps): ReactElement {
  const mode = props.mode;
  const navigate = useNavigate();
  const auth = useAuth();

  const isLogin: boolean = mode === "login";

  const [username, setUsername] = useState<string>("");
  const [password, setPassword] = useState<string>("");
  const [busy, setBusy] = useState<boolean>(false);
  const [error, setError] = useState<string>("");

  async function handleSubmit(
    event: FormEvent<HTMLFormElement>,
  ): Promise<void> {
    event.preventDefault();
    setBusy(true);
    setError("");

    try {
      if (isLogin) {
        await auth.login(username, password);
      } else {
        await auth.register(username, password);
      }

      navigate("/", { replace: true });
    } catch (err) {
      if (err instanceof Error) {
        setError(err.message);
      } else {
        setError("Authentication failed");
      }
    } finally {
      setBusy(false);
    }
  }

  function onUsernameChange(event: ChangeEvent<HTMLInputElement>): void {
    setUsername(event.target.value);
  }

  function onPasswordChange(event: ChangeEvent<HTMLInputElement>): void {
    setPassword(event.target.value);
  }

  return (
    <div className={styles.container}>
      <form onSubmit={handleSubmit} className={styles.form}>
        <div className={styles.header}>
          <h1 className={styles.title}>{isLogin ? "Sign In" : "Sign Up"}</h1>
          <p className={styles.subtitle}>
            {isLogin
              ? "Please sign in to use storage"
              : "Create an account to get started"}
          </p>
        </div>

        {isLogin && auth.passwordChanged ? (
          <p role="status" className={styles.notice}>
            Password changed. Sign in with your new password.
          </p>
        ) : null}
        {auth.offline ? (
          <p role="status" className={styles.subtitle}>
            Connect to sign in. Offline access is available only after signing
            in on this device.
          </p>
        ) : null}
        <label className={styles.field}>
          <div className={styles.fieldLabel}>Username</div>
          <input
            value={username}
            onChange={onUsernameChange}
            autoComplete="username"
            autoCapitalize="none"
            autoCorrect="off"
            spellCheck={false}
            inputMode="text"
            required
            minLength={isLogin ? 1 : 3}
            placeholder="user_name"
            className={styles.input}
          />
        </label>

        <label className={styles.field}>
          <div className={styles.fieldLabel}>Password</div>
          <input
            type="password"
            value={password}
            onChange={onPasswordChange}
            autoComplete={isLogin ? "current-password" : "new-password"}
            required
            minLength={8}
            placeholder="••••••••"
            maxLength={128}
            title="8-128 characters"
            className={styles.input}
          />
        </label>

        {error ? (
          <div className={styles.error} role="alert">
            {error}
          </div>
        ) : null}

        <button
          type="submit"
          disabled={busy}
          className={`${styles.button} ${busy ? styles.buttonBusy : ""}`}
        >
          {busy ? "Please wait..." : isLogin ? "Sign In" : "Create Account"}
        </button>

        <div className={styles.footer}>
          {isLogin ? (
            <>
              Don't have an account?{" "}
              <Link to="/register" className={styles.link}>
                Sign Up
              </Link>
            </>
          ) : (
            <>
              Already have an account?{" "}
              <Link to="/login" className={styles.link}>
                Sign In
              </Link>
            </>
          )}
        </div>
      </form>
    </div>
  );
}
