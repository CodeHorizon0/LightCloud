import styles from "./Header.module.css";
import UserCard from "./UserCard";

function Header(props) {
  return (
    <header className={styles.header}>

      <div className={styles.statCard}>
        <span className={styles.statLabel}>В очереди {props.queueCount} | Загружено {props.serverCount}</span>
      </div>

      <UserCard
        username={props.username}
        onLogout={props.onLogout}
        onDeleteAccount={props.onDeleteAccount}
      />
    </header>
  );
}

export default Header;
