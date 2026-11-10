import styles from "./PreviewModal.module.css";

export default function PreviewStatus({ error }: { error?: string }) {
  return (
    <div
      role={error ? "alert" : "status"}
      className={`${styles.previewStatus}${error ? ` ${styles.previewError}` : ""}`}
    >
      {error ? null : (
        <span className={styles.previewLoader} aria-hidden="true" />
      )}
      <p>{error ?? "Loading preview…"}</p>
    </div>
  );
}
