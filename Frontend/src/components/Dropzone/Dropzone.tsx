import { useRef, useState } from "react";
import type { ChangeEvent, DragEvent, MouseEvent } from "react";

import { createUploadItem, droppedFiles } from "../../utils/storage";
import type { UploadItem } from "../../utils/storage";
import styles from "./Dropzone.module.css";

interface DropzoneProps {
  disabled: boolean;
  onFiles: (items: UploadItem[]) => void;
  onError: (error: unknown) => void;
}

export default function Dropzone({
  disabled,
  onFiles,
  onError,
}: DropzoneProps) {
  const fileInput = useRef<HTMLInputElement>(null);
  const folderInput = useRef<HTMLInputElement>(null);
  const dragDepth = useRef(0);
  const [dragging, setDragging] = useState(false);

  function openFiles() {
    if (!disabled) fileInput.current?.click();
  }

  function pickFiles(event: MouseEvent<HTMLButtonElement>) {
    event.stopPropagation();
    openFiles();
  }

  function pickFolder(event: MouseEvent<HTMLButtonElement>) {
    event.stopPropagation();
    folderInput.current?.click();
  }

  function readFiles(event: ChangeEvent<HTMLInputElement>) {
    const { files } = event.currentTarget;
    if (files && !disabled) {
      onFiles(
        Array.from(files, function (file) {
          return createUploadItem(file, file.webkitRelativePath || file.name);
        }),
      );
    }
    event.currentTarget.value = "";
  }

  function dragEnter(event: DragEvent<HTMLDivElement>) {
    event.preventDefault();
    dragDepth.current += 1;
    if (!disabled) setDragging(true);
  }

  function dragOver(event: DragEvent<HTMLDivElement>) {
    event.preventDefault();
    event.dataTransfer.dropEffect = disabled ? "none" : "copy";
  }

  function dragLeave() {
    dragDepth.current = Math.max(0, dragDepth.current - 1);
    if (!dragDepth.current) setDragging(false);
  }

  function drop(event: DragEvent<HTMLDivElement>) {
    event.preventDefault();
    dragDepth.current = 0;
    setDragging(false);
    if (!disabled) void droppedFiles(event.dataTransfer).then(onFiles, onError);
  }

  function bindFolderInput(input: HTMLInputElement | null) {
    folderInput.current = input;
    if (input) input.webkitdirectory = true;
  }

  function stopClick(event: MouseEvent<HTMLInputElement>) {
    event.stopPropagation();
  }

  return (
    <div
      className={dragging ? styles.dropzoneActive : styles.dropzone}
      onClick={openFiles}
      onDragEnter={dragEnter}
      onDragOver={dragOver}
      onDragLeave={dragLeave}
      onDrop={drop}
    >
      <input
        ref={fileInput}
        type="file"
        multiple
        className={styles.hiddenInput}
        onClick={stopClick}
        onChange={readFiles}
      />
      <input
        ref={bindFolderInput}
        type="file"
        multiple
        className={styles.hiddenInput}
        onClick={stopClick}
        onChange={readFiles}
      />
      <div className={styles.dropzoneTitle}>Drag files or folder</div>
      <div className={styles.dropzoneSubtitle}>or choose below</div>
      <div className={styles.dropzoneActions}>
        <button
          type="button"
          onClick={pickFiles}
          className={styles.secondaryButton}
          disabled={disabled}
        >
          Files
        </button>
        <button
          type="button"
          onClick={pickFolder}
          className={styles.secondaryButton}
          disabled={disabled}
        >
          Folder
        </button>
      </div>
    </div>
  );
}
