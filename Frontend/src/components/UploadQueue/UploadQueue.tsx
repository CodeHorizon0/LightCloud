// UploadQueue.tsx
import { memo } from "react";
import styles from "./UploadQueue.module.css";
import { formatSizeMB } from "../../utils/storage";

interface UploadItemData {
  id: string | number;
  relativePath: string;
  size: number;
  status: string;
  progress: number;
}

interface UploadItemProps {
  item: UploadItemData;
  onSaveCopy: (id: string) => void;
  onDiscard: (id: string) => void;
}

function UploadItem(props: UploadItemProps) {
  const item = props.item;
  return (
    <div className={styles.uploadItem}>
      <div className={styles.uploadItemTop}>
        <div className={styles.uploadItemName} title={item.relativePath}>
          {item.relativePath}
        </div>
        <div className={styles.uploadItemMeta}>
          {formatSizeMB(item.size)} MB ·{" "}
          {item.status === "uploading"
            ? `${Math.round(item.progress)}%`
            : item.status}
        </div>
      </div>
      {item.status === "conflict" ? (
        <div className={styles.conflict}>
          <span>
            Another device changed this file or another file in this batch.
          </span>
          <button
            type="button"
            onClick={function () {
              props.onSaveCopy(String(item.id));
            }}
          >
            Upload as copy
          </button>
          <button
            type="button"
            onClick={function () {
              props.onDiscard(String(item.id));
            }}
          >
            Keep server version
          </button>
        </div>
      ) : null}
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

interface UploadQueueProps {
  items: UploadItemData[];
  onSaveCopy: (id: string) => void;
  onDiscard: (id: string) => void;
}

function UploadQueue(props: UploadQueueProps) {
  if (props.items.length === 0) {
    return <div className={styles.emptyState}>Files not selected</div>;
  }
  return (
    <div className={styles.uploadList}>
      {props.items.map(function (item) {
        return (
          <MemoUploadItem
            key={item.id}
            item={item}
            onSaveCopy={props.onSaveCopy}
            onDiscard={props.onDiscard}
          />
        );
      })}
    </div>
  );
}

export default UploadQueue;
