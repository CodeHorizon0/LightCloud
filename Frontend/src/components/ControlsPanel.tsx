import React from "react";
import styles from "../App.module.css";

interface ControlsPanelProps {
  onUpload: () => void;
  isUploading: boolean;
  queueCount: number;
  onClear: () => void;
  disabledClear: boolean;
  fileInputRef: React.RefObject<HTMLInputElement>;
  folderInputRef: React.RefObject<HTMLInputElement>;
  onFilesChange: (event: React.ChangeEvent<HTMLInputElement>) => void;
  onFolderChange: (event: React.ChangeEvent<HTMLInputElement>) => void;
}

function ControlsPanel(props: ControlsPanelProps) {
  return (
    <div className={styles.actions}>
      <button
        className={styles.primaryButton}
        type="button"
        onClick={props.onUpload}
        disabled={props.isUploading || props.queueCount === 0}
      >
        {props.isUploading ? "Uploading..." : "Upload selected"}
      </button>

      <button
        className={styles.ghostButton}
        type="button"
        onClick={props.onClear}
        disabled={props.disabledClear}
      >
        Clear queue
      </button>

      <input
        ref={props.fileInputRef}
        className={styles.hiddenInput}
        type="file"
        multiple
        onChange={props.onFilesChange}
      />

      <input
        ref={props.folderInputRef}
        className={styles.hiddenInput}
        type="file"
        multiple
        onChange={props.onFolderChange}
      />
    </div>
  );
}

export default ControlsPanel;