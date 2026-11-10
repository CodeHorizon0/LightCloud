import styles from "./ControlsPanel.module.css";

interface ControlsPanelProps {
  onUpload: () => void;
  onClear: () => void;
  isUploading: boolean;
  queueCount: number;
  offline: boolean;
}

export default function ControlsPanel({
  onUpload,
  onClear,
  isUploading,
  queueCount,
  offline,
}: ControlsPanelProps) {
  const disabled = isUploading || queueCount === 0;
  return (
    <div className={styles.actions}>
      <button
        className={styles.primaryButton}
        type="button"
        onClick={onUpload}
        disabled={disabled || offline}
      >
        {isUploading ? "Uploading..." : "Upload selected"}
      </button>
      <button
        className={styles.ghostButton}
        type="button"
        onClick={onClear}
        disabled={disabled}
      >
        Clear queue
      </button>
    </div>
  );
}
