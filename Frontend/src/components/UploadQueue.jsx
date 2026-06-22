import React, { memo } from "react";
import styles from "../App.module.css";
import { formatSizeMB } from "../utils/storage.js";

function UploadItem(props) {
  const item = props.item;

  return (
    <div className={styles.uploadItem}>
      <div className={styles.uploadItemTop}>
        <div className={styles.uploadItemName} title={item.relativePath}>
          {item.relativePath}
        </div>

        <div className={styles.uploadItemMeta}>
          {formatSizeMB(item.size)} MB · {item.status === "загрузка" ? `${Math.round(item.progress)}%` : item.status}
        </div>
      </div>

      <div className={styles.progressWrapper}>
        <div
          className={styles.progressBar}
          style={{ width: `${Math.max(0, Math.min(100, item.progress))}%` }}
        />
      </div>
    </div>
  );
}

const MemoUploadItem = memo(UploadItem);

function UploadQueue(props) {
  if (props.items.length === 0) {
    return <div className={styles.emptyState}>Файлы не выбраны</div>;
  }

  return (
    <div className={styles.uploadList}>
      {props.items.map(function(item) {
        return <MemoUploadItem key={item.id} item={item} />;
      })}
    </div>
  );
}

export default UploadQueue;
