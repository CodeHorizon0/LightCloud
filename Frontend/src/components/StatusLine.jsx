import React from "react";
import styles from "../App.module.css";

function StatusLine(props) {
  const className = [styles.status, styles[props.tone] || styles.muted].join(" ");

  return <div className={className}>{props.text}</div>;
}

export default StatusLine;
