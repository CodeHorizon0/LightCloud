// StatusLine.tsx
import styles from "./StatusLine.module.css";

interface StatusLineProps {
  text: string;
  tone?: "muted" | "warn" | "ok" | "danger";
}

function StatusLine(props: StatusLineProps) {
  const tone = props.tone || "muted";
  const className = [styles.status, styles[tone]].join(" ");
  return (
    <div className={className} role="status">
      {props.text}
    </div>
  );
}

export default StatusLine;
