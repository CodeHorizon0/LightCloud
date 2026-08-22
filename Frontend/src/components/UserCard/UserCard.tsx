// UserCard.tsx
import React, { useState } from "react";
import Avatar from "boring-avatars";
import styles from "./UserCard.module.css";

interface UserCardProps {
  username: string;
  onLogout: () => void;
  onDeleteAccount: () => void;
}

function UserCard(props: UserCardProps) {
  const [open, setOpen] = useState<boolean>(false);
  const username = props.username || "Guest";

  function toggleMenu(): void {
    setOpen(function(prev) {
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
        <Avatar name={username} variant="beam" size={26} />
        <span className={styles.username}>{username}</span>
      </button>
      {open && (
        <div className={styles.dropdown}>
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