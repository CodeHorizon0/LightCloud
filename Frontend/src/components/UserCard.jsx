import React, { useState } from "react";
import Avatar from "boring-avatars";
import styles from "./UserCard.module.css";

function UserCard(props) {
  const [open, setOpen] = useState(false);
  const username = props.username || "Guest";

  function toggleMenu() {
    setOpen(function(prev) {
      return !prev;
    });
  }

  function closeMenu() {
    setOpen(false);
  }

  function handleLogout() {
    closeMenu();
    if (typeof props.onLogout === "function") {
      props.onLogout();
    }
  }

  function handleDeleteAccount() {
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
        aria-label={"Профиль " + username}
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
            Выйти из аккаунта
          </button>

          <button
            type="button"
            onClick={handleDeleteAccount}
            className={styles.deleteButton}
          >
            Удалить аккаунт
          </button>
        </div>
      )}
    </div>
  );
}

export default UserCard;
