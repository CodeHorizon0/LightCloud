// StatusLine.tsx
import React from "react";
import styles from "../App.module.css";

interface StatusLineProps {
  text: string;
  tone?: string;
}

function StatusLine(props: StatusLineProps) {
  const tone = props.tone || "muted";
  const className = [styles.status, styles[tone]].join(" ");
  return <div className={className}>{props.text}</div>;
}

export default StatusLine;