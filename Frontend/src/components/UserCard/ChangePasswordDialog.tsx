import { useEffect, useId, useRef, useState } from "react";
import type { FormEvent } from "react";
import { useAuth } from "../../auth/useAuth";
import styles from "./ChangePasswordDialog.module.css";

export default function ChangePasswordDialog({
  onClose,
}: {
  onClose: () => void;
}) {
  const auth = useAuth();
  const dialog = useRef<HTMLDialogElement>(null);
  const title = useId();
  const [current, setCurrent] = useState("");
  const [password, setPassword] = useState("");
  const [confirmation, setConfirmation] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(function open() {
    const element = dialog.current;
    element?.showModal();
    return function close() {
      element?.close();
    };
  }, []);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy || auth.offline) return;
    if (password !== confirmation) {
      setError("Passwords do not match");
      return;
    }
    if (current === password) {
      setError("Choose a different password");
      return;
    }
    setError("");
    setBusy(true);
    try {
      await auth.changePassword(current, password);
    } catch (failure) {
      setError(
        failure instanceof Error
          ? failure.message
          : "Could not change password",
      );
      setBusy(false);
    }
  }

  return (
    <dialog
      ref={dialog}
      className={styles.dialog}
      aria-labelledby={title}
      onCancel={function cancel(event) {
        event.preventDefault();
        if (!busy) onClose();
      }}
      onClick={function backdrop(event) {
        if (event.target === event.currentTarget && !busy) onClose();
      }}
    >
      <form onSubmit={submit}>
        <h2 id={title}>Change password</h2>
        <p className={styles.hint}>
          Changing your password signs out all devices.
        </p>
        <input
          type="text"
          name="username"
          autoComplete="username"
          value={auth.user?.username ?? ""}
          readOnly
          hidden
        />
        <label>
          Current password
          <input
            type="password"
            autoComplete="current-password"
            required
            maxLength={128}
            disabled={busy}
            value={current}
            onChange={function change(event) {
              setCurrent(event.target.value);
            }}
          />
        </label>
        <label>
          New password
          <input
            type="password"
            autoComplete="new-password"
            required
            minLength={8}
            maxLength={128}
            disabled={busy}
            value={password}
            onChange={function change(event) {
              setPassword(event.target.value);
            }}
          />
        </label>
        <label>
          Confirm new password
          <input
            type="password"
            autoComplete="new-password"
            required
            minLength={8}
            maxLength={128}
            disabled={busy}
            value={confirmation}
            onChange={function change(event) {
              setConfirmation(event.target.value);
            }}
          />
        </label>
        {error ? (
          <p role="alert" className={styles.error}>
            {error}
          </p>
        ) : null}
        {auth.offline ? (
          <p role="status" className={styles.hint}>
            Connect to change your password.
          </p>
        ) : null}
        <div className={styles.actions}>
          <button type="button" onClick={onClose} disabled={busy}>
            Cancel
          </button>
          <button
            type="submit"
            className={styles.submit}
            disabled={busy || auth.offline}
          >
            {busy ? "Saving..." : "Change password"}
          </button>
        </div>
      </form>
    </dialog>
  );
}
