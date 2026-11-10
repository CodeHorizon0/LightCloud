// Header.tsx
import styles from "./Header.module.css";
import UserCard from "../UserCard/UserCard";

interface HeaderProps {
  queueCount: number;
  serverCount: number;
  username: string;
  offline: boolean;
  onClearCache: () => void;
  onChangePassword: () => void;
  onLogout: () => void;
  onDeleteAccount: () => void;
}

function Header(props: HeaderProps) {
  return (
    <header className={styles.header}>
      <div className={styles.statCard}>
        <span className={styles.statLabel}>
          In queue: {props.queueCount} | Uploaded: {props.serverCount}
        </span>
      </div>
      <UserCard
        username={props.username}
        offline={props.offline}
        onClearCache={props.onClearCache}
        onChangePassword={props.onChangePassword}
        onLogout={props.onLogout}
        onDeleteAccount={props.onDeleteAccount}
      />
    </header>
  );
}

export default Header;
