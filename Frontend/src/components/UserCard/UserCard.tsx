// UserCard.tsx
import { useState } from "react";
import styles from "./UserCard.module.css";

interface UserCardProps {
  username: string;
  offline: boolean;
  onClearCache: () => void;
  onChangePassword: () => void;
  onLogout: () => void;
  onDeleteAccount: () => void;
}

function UserCard(props: UserCardProps) {
  const [open, setOpen] = useState<boolean>(false);
  const username = props.username || "Guest";

  function toggleMenu(): void {
    setOpen(function (prev) {
      return !prev;
    });
  }

  function closeMenu(): void {
    setOpen(false);
  }

  function handleLogout(): void {
    closeMenu();
    if (typeof props.onLogout === "function") {
      props.onLogout();
    }
  }

  function handleDeleteAccount(): void {
    closeMenu();
    if (typeof props.onDeleteAccount === "function") {
      props.onDeleteAccount();
    }
  }

  return (
    <div className={styles.container}>
      <button
        type="button"
        onClick={toggleMenu}
        aria-expanded={open}
        aria-label={"Profile " + username}
        className={styles.trigger}
      >
        <span className={styles.avatar} aria-hidden="true">
          {Array.from(username)[0]?.toUpperCase()}
        </span>
        <span className={styles.username}>{username}</span>
      </button>
      {open && (
        <div className={styles.dropdown}>
          <button
            type="button"
            className={styles.dropdownButton}
            onClick={function clear() {
              closeMenu();
              props.onClearCache();
            }}
          >
            Clear preview cache
          </button>
          <button
            type="button"
            disabled={props.offline}
            className={styles.dropdownButton}
            onClick={function changePassword() {
              closeMenu();
              props.onChangePassword();
            }}
          >
            Change password
          </button>
          <button
            type="button"
            onClick={handleLogout}
            className={styles.logoutButton}
          >
            Logout account
          </button>
          <button
            type="button"
            onClick={handleDeleteAccount}
            disabled={props.offline}
            className={styles.deleteButton}
          >
            Delete account
          </button>
        </div>
      )}
    </div>
  );
}

export default UserCard;
