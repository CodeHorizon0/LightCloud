import React, { useRef, useState, DragEvent, KeyboardEvent, ChangeEvent, ReactElement, MouseEvent } from "react";
import styles from "../App.module.css";

interface DropzoneProps {
  isDragging?: boolean;
  onFilesSelected?: (files: FileList | File[]) => void;
  onFolderSelected?: (files: FileList) => void;
  onDragOver?: (event: DragEvent<HTMLElement>) => void;
  onDragLeave?: (event: DragEvent<HTMLElement>) => void;
  onDrop?: (event: DragEvent<HTMLElement>) => void;
}

function Dropzone(props: DropzoneProps): ReactElement {
  const fileInputRef = useRef<HTMLInputElement>(null);
  const folderInputRef = useRef<HTMLInputElement>(null);
  const pickerOpenRef = useRef<boolean>(false);
  const [isPickerBusy, setIsPickerBusy] = useState<boolean>(false);

  async function openFilePicker(): Promise<void> {
    if (pickerOpenRef.current || isPickerBusy) {
      return;
    }

    pickerOpenRef.current = true;
    setIsPickerBusy(true);

    try {
      if ((window as any).showOpenFilePicker) {
        const handles: FileSystemFileHandle[] = await (window as any).showOpenFilePicker({ multiple: true });
        const files: File[] = await Promise.all(
          handles.map(function(handle: FileSystemFileHandle): Promise<File> {
            return handle.getFile();
          })
        );

        if (props.onFilesSelected) {
          props.onFilesSelected(files);
        }
        return;
      }

      if (fileInputRef.current) {
        fileInputRef.current.click();
      }
    } catch (error) {
      if (error && (error as Error).name !== "AbortError") {
        console.error("openFilePicker failed:", error);
        if (fileInputRef.current) {
          fileInputRef.current.click();
        }
      }
    } finally {
      pickerOpenRef.current = false;
      setIsPickerBusy(false);
    }
  }

  function openFolderPicker(): void {
    if (pickerOpenRef.current || isPickerBusy) {
      return;
    }

    pickerOpenRef.current = true;
    setIsPickerBusy(true);

    try {
      if (folderInputRef.current) {
        folderInputRef.current.click();
      }
    } finally {
      pickerOpenRef.current = false;
      setIsPickerBusy(false);
    }
  }

  function handleClick(): void {
    openFilePicker();
  }

  function handleKeyDown(event: KeyboardEvent<HTMLElement>): void {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      openFilePicker();
    }
  }

  function handleFilesChange(event: ChangeEvent<HTMLInputElement>): void {
    const files = event.target.files;
    if (files && files.length > 0 && props.onFilesSelected) {
      props.onFilesSelected(files);
    }
    event.target.value = "";
  }

  function handleFolderChange(event: ChangeEvent<HTMLInputElement>): void {
    const files = event.target.files;
    if (files && files.length > 0 && props.onFolderSelected) {
      props.onFolderSelected(files);
    }
    event.target.value = "";
  }

  function handleDragOver(event: DragEvent<HTMLElement>): void {
    event.preventDefault();

    if (props.onDragOver) {
      props.onDragOver(event);
    }
  }

  function handleDragLeave(event: DragEvent<HTMLElement>): void {
    if (props.onDragLeave) {
      props.onDragLeave(event);
    }
  }

  function handleDrop(event: DragEvent<HTMLElement>): void {
    event.preventDefault();

    if (props.onDrop) {
      props.onDrop(event);
    }
  }

  function stopAndOpenFiles(event: MouseEvent<HTMLButtonElement>): void {
    event.preventDefault();
    event.stopPropagation();
    openFilePicker();
  }

  function stopAndOpenFolder(event: MouseEvent<HTMLButtonElement>): void {
    event.preventDefault();
    event.stopPropagation();
    openFolderPicker();
  }

  return (
    <div
      className={props.isDragging ? styles.dropzoneActive : styles.dropzone}
      onClick={handleClick}
      onKeyDown={handleKeyDown}
      onDragOver={handleDragOver}
      onDragLeave={handleDragLeave}
      onDrop={handleDrop}
      role="button"
      tabIndex={0}
    >
      <input
        ref={fileInputRef}
        type="file"
        multiple
        className={styles.hiddenInput}
        onChange={handleFilesChange}
      />

      <input
        ref={folderInputRef}
        type="file"
        multiple
        className={styles.hiddenInput}
        {...({ webkitdirectory: true } as React.InputHTMLAttributes<HTMLInputElement>)}
        onChange={handleFolderChange}
      />

      <div className={styles.dropzoneTitle}>
        Drag files or folder
      </div>

      <div className={styles.dropzoneSubtitle}>
        or press for select
      </div>

      <div className={styles.dropzoneActions}>
        <button
          type="button"
          onClick={stopAndOpenFiles}
          className={styles.secondaryButton}
        >
          Files
        </button>

        <button
          type="button"
          onClick={stopAndOpenFolder}
          className={styles.secondaryButton}
        >
          Folder
        </button>
      </div>
    </div>
  );
}

export default Dropzone;