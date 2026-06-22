import styles from "../App.module.css";

function ControlsPanel(props) {
  return (
    <div className={styles.actions}>
      <button
        className={styles.primaryButton}
        type="button"
        onClick={props.onUpload}
        disabled={props.isUploading || props.queueCount === 0}
      >
        {props.isUploading ? "Загрузка..." : "Загрузить выбранное"}
      </button>

      <button
        className={styles.ghostButton}
        type="button"
        onClick={props.onClear}
        disabled={props.disabledClear}
      >
        Очистить очередь
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
