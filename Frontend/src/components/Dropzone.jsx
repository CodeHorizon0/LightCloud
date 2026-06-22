import React, { useRef, useState } from "react";
import styles from "../App.module.css";

function Dropzone(props) {
  const fileInputRef = useRef(null);
  const folderInputRef = useRef(null);
  const pickerOpenRef = useRef(false);
  const [isPickerBusy, setIsPickerBusy] = useState(false);

  async function openFilePicker() {
    if (pickerOpenRef.current || isPickerBusy) {
      return;
    }

    pickerOpenRef.current = true;
    setIsPickerBusy(true);

    try {
      if (window.showOpenFilePicker) {
        const handles = await window.showOpenFilePicker({ multiple: true });
        const files = await Promise.all(
          handles.map(function(handle) {
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
      if (error && error.name !== "AbortError") {
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

  function openFolderPicker() {
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

  function handleClick() {
    openFilePicker();
  }

  function handleKeyDown(event) {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      openFilePicker();
    }
  }

  function handleFilesChange(event) {
    const files = event.target.files;
    if (files && files.length > 0 && props.onFilesSelected) {
      props.onFilesSelected(files);
    }
    event.target.value = "";
  }

  function handleFolderChange(event) {
    const files = event.target.files;
    if (files && files.length > 0 && props.onFolderSelected) {
      props.onFolderSelected(files);
    }
    event.target.value = "";
  }

  function handleDragOver(event) {
    event.preventDefault();

    if (props.onDragOver) {
      props.onDragOver(event);
    }
  }

  function handleDragLeave(event) {
    if (props.onDragLeave) {
      props.onDragLeave(event);
    }
  }

  function handleDrop(event) {
    event.preventDefault();

    if (props.onDrop) {
      props.onDrop(event);
    }
  }

  function stopAndOpenFiles(event) {
    event.preventDefault();
    event.stopPropagation();
    openFilePicker();
  }

  function stopAndOpenFolder(event) {
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
        webkitdirectory=""
        directory=""
        onChange={handleFolderChange}
      />

      <div className={styles.dropzoneTitle}>
        Перетащите файлы или папку
      </div>

      <div className={styles.dropzoneSubtitle}>
        или нажмите для выбора
      </div>

      <div className={styles.dropzoneActions}>
        <button
          type="button"
          onClick={stopAndOpenFiles}
          className={styles.secondaryButton}
        >
          Файлы
        </button>

        <button
          type="button"
          onClick={stopAndOpenFolder}
          className={styles.secondaryButton}
        >
          Папка
        </button>
      </div>
    </div>
  );
}

export default Dropzone;
