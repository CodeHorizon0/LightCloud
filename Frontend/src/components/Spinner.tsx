// Spinner.tsx
import React from "react";
import styles from "./Spinner.module.css";

export default function Spinner() {
    return (
    <div className={styles.SpinnerContainer}>
        <div className={styles.spinner} />
    </div>
    );
}