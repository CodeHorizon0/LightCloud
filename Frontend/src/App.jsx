import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";

import { useAuth } from "./auth/AuthContext";
import ControlsPanel from "./components/ControlsPanel";
import Dropzone from "./components/Dropzone";
import Header from "./components/Header";
import MetadataTable from "./components/MetadataTable";
import PreviewModal from "./components/PreviewModal";
import StatusLine from "./components/StatusLine";
import UploadQueue from "./components/UploadQueue";
import styles from "./App.module.css";
import useMetadataStream from "./hooks/useMetadataStream";
import {
  API_BASE,
  appendUploadFiles,
  buildDeleteRequestBody,
  buildDownloadUrl,
  buildPreviewUrl,
  chunkArray,
  createUploadItem,
  getFileName,
  getPreviewKind,
  isNonEmptyFile,
  mergeUniqueItems,
  normalizePath,
  traverseEntry,
} from "./utils/storage.js";

const UPLOAD_BATCH_SIZE = 8;
const UPLOAD_RETRY_COUNT = 2;
const UPLOAD_RETRY_DELAY_MS = 500;

function sleep(ms) {
  return new Promise(function(resolve) {
    setTimeout(resolve, ms);
  });
}

function getResponseMessage(xhr) {
  try {
    const data = JSON.parse(xhr.responseText || "null");
    if (Array.isArray(data)) {
      return `Ответ сервера: ${data.length} файлов`;
    }
    if (data && typeof data === "object") {
      return data.detail || data.msg || data.message || `HTTP ${xhr.status}`;
    }
  } catch (error) {
    // ignore
  }

  return xhr.statusText || `HTTP ${xhr.status}`;
}

function buildBatchProgressMap(batch) {
  let offset = 0;
  const ranges = [];

  for (let i = 0; i < batch.length; i += 1) {
    const item = batch[i];
    const size = Math.max(1, Number(item.size) || 0);
    const start = offset;
    const end = offset + size;
    ranges.push({
      id: item.id,
      start: start,
      end: end,
      size: size,
    });
    offset = end;
  }

  return {
    ranges: ranges,
    total: Math.max(1, offset),
  };
}

function App(props) {
  const fileInputRef = useRef(null);
  const folderInputRef = useRef(null);
  const isUploadingRef = useRef(false);
  const selectedItemsRef = useRef([]);
  const isMountedRef = useRef(true);
  const lastSelectedIndexRef = useRef(null);

  const auth = useAuth();
  const navigate = useNavigate();
  const username = props.username || (auth.user && auth.user.username) || "";

  const [selectedItems, setSelectedItems] = useState([]);
  const [metadata, setMetadata] = useState({});
  const [selectedMetadataPaths, setSelectedMetadataPaths] = useState([]);
  const [statusText, setStatusText] = useState("Готово к загрузке");
  const [statusTone, setStatusTone] = useState("muted");
  const [isUploading, setIsUploading] = useState(false);
  const [isDeleting, setIsDeleting] = useState(false);
  const [isDragging, setIsDragging] = useState(false);
  const [previewItem, setPreviewItem] = useState(null);

  useEffect(function() {
    selectedItemsRef.current = selectedItems;
  }, [selectedItems]);

  useEffect(function() {
    isMountedRef.current = true;

    return function() {
      isMountedRef.current = false;
    };
  }, []);

  const metadataEntries = useMemo(function() {
    return Object.entries(metadata).sort(function(a, b) {
      return a[0].localeCompare(b[0]);
    });
  }, [metadata]);

  const metadataIndexMap = useMemo(function() {
    const map = new Map();

    for (let i = 0; i < metadataEntries.length; i += 1) {
      map.set(metadataEntries[i][0], i);
    }

    return map;
  }, [metadataEntries]);

  useEffect(function() {
    const allowed = new Set(metadataEntries.map(function(entry) {
      return entry[0];
    }));

    setSelectedMetadataPaths(function(prev) {
      const next = prev.filter(function(path) {
        return allowed.has(path);
      });

      if (next.length !== prev.length) {
        return next;
      }

      for (let i = 0; i < next.length; i += 1) {
        if (next[i] !== prev[i]) {
          return next;
        }
      }

      return prev;
    });

    if (lastSelectedIndexRef.current != null && lastSelectedIndexRef.current >= metadataEntries.length) {
      lastSelectedIndexRef.current = metadataEntries.length > 0 ? metadataEntries.length - 1 : null;
    }
  }, [metadataEntries]);

  const setStatus = useCallback(function(message, tone) {
    if (!isMountedRef.current) {
      return;
    }

    setStatusText(message);
    setStatusTone(tone || "muted");
  }, []);

  const updateItem = useCallback(function(itemId, updater) {
    setSelectedItems(function(prev) {
      return prev.map(function(item) {
        return item.id === itemId ? updater(item) : item;
      });
    });
  }, []);

  const addIncomingItems = useCallback(function(incomingItems) {
    if (!incomingItems || incomingItems.length === 0) {
      setStatus("Пустые файлы и пустые папки не загружаются", "warn");
      return;
    }

    const validItems = [];

    for (let i = 0; i < incomingItems.length; i += 1) {
      const item = incomingItems[i];
      if (item && item.file && isNonEmptyFile(item.file)) {
        validItems.push(item);
      }
    }

    if (validItems.length === 0) {
      setStatus("Пустые файлы и пустые папки не загружаются", "warn");
      return;
    }

    setSelectedItems(function(prev) {
      return mergeUniqueItems(prev, validItems);
    });

    setStatus(
      validItems.length !== incomingItems.length
        ? "Пустые файлы пропущены, остальное добавлено в очередь"
        : "Файлы добавлены в очередь",
      validItems.length !== incomingItems.length ? "warn" : "ok"
    );
  }, [setStatus]);

  const clearSelection = useCallback(function() {
    if (isUploadingRef.current) {
      return;
    }

    setSelectedItems([]);
    setStatus("Очередь очищена", "muted");
  }, [setStatus]);

  const handleLogout = useCallback(function() {
    return Promise.resolve()
      .then(function() {
        return auth.logout();
      })
      .finally(function() {
        navigate("/login", { replace: true });
      });
  }, [auth, navigate]);

  const deleteFiles = useCallback(async function(paths) {
    const normalizedPaths = [];
    const seen = new Set();

    for (let i = 0; i < paths.length; i += 1) {
      const cleanPath = normalizePath(paths[i]);
      if (!cleanPath || seen.has(cleanPath)) {
        continue;
      }
      seen.add(cleanPath);
      normalizedPaths.push(cleanPath);
    }

    if (normalizedPaths.length === 0) {
      setStatus("Нечего удалять", "warn");
      return;
    }

    setIsDeleting(true);
    setStatus(`Удаление: ${normalizedPaths.length} файлов`, "muted");

    try {
      const response = await fetch(`${API_BASE}/delete`, {
        method: "DELETE",
        credentials: "include",
        headers: {
          Accept: "application/json",
          "Content-Type": "application/json",
        },
        body: JSON.stringify(buildDeleteRequestBody(normalizedPaths)),
      });

      const data = await response.json().catch(function() {
        return null;
      });

      if (!response.ok) {
        throw new Error((data && (data.detail || data.message)) || `Delete failed: ${response.status}`);
      }

      const deleted = data && Array.isArray(data.deleted) ? data.deleted : normalizedPaths;
      const missing = data && Array.isArray(data.missing) ? data.missing : [];

      setMetadata(function(prev) {
        const next = { ...prev };

        for (let i = 0; i < deleted.length; i += 1) {
          delete next[deleted[i]];
        }

        for (let j = 0; j < missing.length; j += 1) {
          delete next[missing[j]];
        }

        return next;
      });

      setSelectedMetadataPaths(function(prev) {
        const deletedSet = new Set([].concat(deleted, missing));
        return prev.filter(function(path) {
          return !deletedSet.has(path);
        });
      });

      setStatus(
        missing.length > 0
          ? `Удалено: ${deleted.length}, не найдено: ${missing.length}`
          : `Удалено: ${deleted.length}`,
        missing.length > 0 ? "warn" : "ok"
      );
    } catch (error) {
      console.error(error);
      setStatus("Не удалось удалить файлы", "danger");
    } finally {
      setIsDeleting(false);
    }
  }, [setStatus]);

  const handleDeleteAccount = useCallback(function() {
    const confirmed = window.confirm(
      "Удалить аккаунт? Это действие нельзя отменить."
    );

    if (!confirmed) {
      return;
    }

    return fetch(`${API_BASE}/auth/delete`, {
      method: "DELETE",
      credentials: "include",
      headers: {
        Accept: "application/json",
      },
    })
      .then(function(response) {
        if (!response.ok && response.status !== 404) {
          throw new Error("Delete account failed");
        }

        return auth.logout();
      })
      .then(function() {
        navigate("/login", { replace: true });
      })
      .catch(function(error) {
        console.error(error);
        setStatus("Не удалось удалить аккаунт", "danger");
      });
  }, [auth, navigate, setStatus]);

  const handlePickFiles = useCallback(function() {
    if (fileInputRef.current) {
      fileInputRef.current.click();
    }
  }, []);

  const handlePickFolder = useCallback(function() {
    if (folderInputRef.current) {
      folderInputRef.current.click();
    }
  }, []);

  const readFilesFromInput = useCallback(function(files, useRelativePath) {
    const incoming = [];

    for (let i = 0; i < files.length; i += 1) {
      const file = files[i];
      if (!isNonEmptyFile(file)) {
        continue;
      }

      const relativePath = useRelativePath
        ? file.webkitRelativePath || file.name
        : file.name;
      incoming.push(createUploadItem(file, relativePath));
    }

    return incoming;
  }, []);

  const handleFilesInputChange = useCallback(function(event) {
    const files = event.target.files;
    if (!files || files.length === 0) {
      return;
    }

    const incoming = readFilesFromInput(files, false);
    addIncomingItems(incoming);
    event.target.value = "";
  }, [addIncomingItems, readFilesFromInput]);

  const handleFolderInputChange = useCallback(function(event) {
    const files = event.target.files;
    if (!files || files.length === 0) {
      return;
    }

    const incoming = readFilesFromInput(files, true);
    addIncomingItems(incoming);
    event.target.value = "";
  }, [addIncomingItems, readFilesFromInput]);

  const uploadBatch = useCallback(function(batch, batchIndex, totalBatches) {
    return new Promise(function(resolve, reject) {
      const formData = new FormData();
      appendUploadFiles(formData, batch);

      const xhr = new XMLHttpRequest();
      xhr.open("POST", `${API_BASE}/upload`, true);
      xhr.withCredentials = true;
      xhr.setRequestHeader("Accept", "application/json");

      const batchProgress = buildBatchProgressMap(batch);

      xhr.upload.onprogress = function(progressEvent) {
        if (!progressEvent.lengthComputable) {
          return;
        }

        const loaded = Math.max(0, Math.min(progressEvent.loaded, batchProgress.total));

        for (let i = 0; i < batchProgress.ranges.length; i += 1) {
          const range = batchProgress.ranges[i];
          let progress = 0;

          if (loaded >= range.end) {
            progress = 100;
          } else if (loaded > range.start) {
            progress = ((loaded - range.start) / range.size) * 100;
          }

          updateItem(range.id, function(current) {
            return {
              ...current,
              progress: Math.max(0, Math.min(100, progress)),
              status: progress >= 100 ? "обработка" : "загрузка",
            };
          });
        }

        const percent = Math.round((loaded / batchProgress.total) * 100);
        setStatus(
          `Загрузка пакета ${batchIndex + 1}/${totalBatches}: ${percent}%`,
          "muted"
        );
      };

      xhr.upload.onload = function() {
        for (let i = 0; i < batch.length; i += 1) {
          updateItem(batch[i].id, function(current) {
            return {
              ...current,
              progress: 100,
              status: "обработка",
            };
          });
        }
      };

      xhr.onload = function() {
        if (xhr.status >= 200 && xhr.status < 300) {
          resolve(xhr.responseText);
          return;
        }

        reject(new Error(getResponseMessage(xhr)));
      };

      xhr.onerror = function() {
        reject(new Error("Network error"));
      };

      xhr.send(formData);
    });
  }, [setStatus, updateItem]);

  const uploadBatchWithRetry = useCallback(async function(batch, batchIndex, totalBatches) {
    let attempt = 0;

    while (attempt <= UPLOAD_RETRY_COUNT) {
      try {
        return await uploadBatch(batch, batchIndex, totalBatches);
      } catch (error) {
        attempt += 1;

        if (attempt > UPLOAD_RETRY_COUNT) {
          throw error;
        }

        setStatus(
          `Повтор загрузки пакета ${batchIndex + 1}/${totalBatches} через ${UPLOAD_RETRY_DELAY_MS} мс`,
          "warn"
        );
        await sleep(UPLOAD_RETRY_DELAY_MS * Math.pow(2, attempt - 1));
      }
    }

    return null;
  }, [setStatus, uploadBatch]);

  const handleUploadSelected = useCallback(async function() {
    if (isUploadingRef.current) {
      return;
    }

    const snapshot = selectedItemsRef.current.slice();
    const pendingItems = snapshot.filter(function(item) {
      return item.status !== "загрузка" && item.status !== "обработка";
    });

    if (pendingItems.length === 0) {
      setStatus("Сначала выбери файлы или папку", "warn");
      return;
    }

    const batches = chunkArray(pendingItems, UPLOAD_BATCH_SIZE);
    isUploadingRef.current = true;
    setIsUploading(true);
    setStatus(
      `Загрузка началась: ${pendingItems.length} файлов, ${batches.length} запросов`,
      "muted"
    );

    let successCount = 0;
    let errorCount = 0;

    try {
      for (let index = 0; index < batches.length; index += 1) {
        const batch = batches[index];

        for (let i = 0; i < batch.length; i += 1) {
          updateItem(batch[i].id, function(current) {
            return {
              ...current,
              progress: 0,
              status: "загрузка",
            };
          });
        }

        try {
          await uploadBatchWithRetry(batch, index, batches.length);
          successCount += batch.length;

          setSelectedItems(function(prev) {
            const batchIds = new Set(batch.map(function(item) {
              return item.id;
            }));

            return prev.filter(function(item) {
              return !batchIds.has(item.id);
            });
          });

          setStatus(
            `Загружено: ${successCount}, ошибок: ${errorCount}`,
            errorCount > 0 ? "warn" : "ok"
          );
        } catch (error) {
          errorCount += batch.length;
          console.error(error);

          for (let i = 0; i < batch.length; i += 1) {
            updateItem(batch[i].id, function(current) {
              return {
                ...current,
                progress: 0,
                status: "ошибка",
              };
            });
          }

          setStatus(
            `Ошибка в пакете ${index + 1}/${batches.length}`,
            "danger"
          );
        }

        if (!isMountedRef.current) {
          break;
        }
      }
    } finally {
      isUploadingRef.current = false;
      setIsUploading(false);

      if (successCount === 0 && errorCount === 0) {
        setStatus("Загрузка завершена", "muted");
      } else {
        setStatus(
          `Готово. Успешно: ${successCount}, ошибок: ${errorCount}`,
          errorCount > 0 ? "warn" : "ok"
        );
      }
    }
  }, [setStatus, updateItem, uploadBatchWithRetry]);

  const downloadFile = useCallback(async function(path) {
    try {
      const response = await fetch(buildDownloadUrl(path), {
        credentials: "include",
      });

      if (!response.ok) {
        throw new Error("Download failed");
      }

      const blob = await response.blob();
      const objectUrl = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = objectUrl;
      const safeName = normalizePath(path).split("/").pop() || "file";
      link.download = safeName;
      document.body.appendChild(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(objectUrl);
      setStatus(`Скачано: ${path}`, "ok");
    } catch (error) {
      console.error(error);
      setStatus(`Не удалось скачать: ${path}`, "danger");
    }
  }, [setStatus]);

  const removeFile = useCallback(function(path) {
    return deleteFiles([path]);
  }, [deleteFiles]);

  const toggleMetadataSelection = useCallback(function(path, event, index) {
    const cleanPath = normalizePath(path);
    const checked = event && event.currentTarget ? !!event.currentTarget.checked : false;
    const shiftKey = !!((event && event.shiftKey) || (event && event.nativeEvent && event.nativeEvent.shiftKey));
    const currentIndex = typeof index === "number" ? index : metadataIndexMap.get(cleanPath);

    setSelectedMetadataPaths(function(prev) {
      const orderedPaths = metadataEntries.map(function(entry) {
        return entry[0];
      });
      const selected = new Set(prev);
      const anchorIndex = lastSelectedIndexRef.current;

      if (shiftKey && anchorIndex != null && currentIndex != null) {
        const start = Math.min(anchorIndex, currentIndex);
        const end = Math.max(anchorIndex, currentIndex);

        for (let i = start; i <= end; i += 1) {
          const rangePath = orderedPaths[i];
          if (!rangePath) {
            continue;
          }

          if (checked) {
            selected.add(rangePath);
          } else {
            selected.delete(rangePath);
          }
        }
      } else if (checked) {
        selected.add(cleanPath);
      } else {
        selected.delete(cleanPath);
      }

      return orderedPaths.filter(function(itemPath) {
        return selected.has(itemPath);
      });
    });

    if (currentIndex != null) {
      lastSelectedIndexRef.current = currentIndex;
    }
  }, [metadataEntries, metadataIndexMap]);

  const selectAllMetadata = useCallback(function() {
    if (metadataEntries.length === 0) {
      return;
    }

    setSelectedMetadataPaths(function(prev) {
      if (prev.length === metadataEntries.length) {
        lastSelectedIndexRef.current = null;
        return [];
      }

      lastSelectedIndexRef.current = metadataEntries.length - 1;
      return metadataEntries.map(function(entry) {
        return entry[0];
      });
    });
  }, [metadataEntries]);

  const toggleMetadataGroup = useCallback(function(groupPaths, checked) {
    const normalized = [];
    const seen = new Set();

    for (let i = 0; i < groupPaths.length; i += 1) {
      const cleanPath = normalizePath(groupPaths[i]);
      if (!cleanPath || seen.has(cleanPath)) {
        continue;
      }
      seen.add(cleanPath);
      normalized.push(cleanPath);
    }

    if (normalized.length === 0) {
      return;
    }

    setSelectedMetadataPaths(function(prev) {
      const next = new Set(prev);

      if (checked) {
        for (let i = 0; i < normalized.length; i += 1) {
          next.add(normalized[i]);
        }
      } else {
        for (let i = 0; i < normalized.length; i += 1) {
          next.delete(normalized[i]);
        }
      }

      return metadataEntries
        .map(function(entry) {
          return entry[0];
        })
        .filter(function(path) {
          return next.has(path);
        });
    });

    const lastPath = normalized[normalized.length - 1];
    const nextIndex = metadataIndexMap.get(lastPath);
    if (typeof nextIndex === 'number') {
      lastSelectedIndexRef.current = nextIndex;
    }
  }, [metadataEntries, metadataIndexMap]);

  const deleteSelectedMetadata = useCallback(function() {
    return deleteFiles(selectedMetadataPaths);
  }, [deleteFiles, selectedMetadataPaths]);

  const canPreview = useCallback(function(path, info) {
    return getPreviewKind(path, info) != null;
  }, []);

  const handlePreview = useCallback(function(path, info) {
    const cleanPath = normalizePath(path);
    const kind = getPreviewKind(cleanPath, info);

    if (!kind) {
      setStatus("Предпросмотр недоступен для этого файла", "warn");
      return;
    }

    setPreviewItem({
      path: cleanPath,
      kind: kind,
      title: getFileName(cleanPath) || cleanPath,
      size: info && info.original_size ? info.original_size : 0,
      url: buildPreviewUrl(cleanPath),
    });
  }, [setStatus]);

  const handleClosePreview = useCallback(function() {
    setPreviewItem(null);
  }, []);

  const collectDroppedItems = useCallback(async function(dt) {
    const incomingItems = [];

    if (dt.items && dt.items.length > 0) {
      const tasks = [];

      for (let i = 0; i < dt.items.length; i += 1) {
        const dataItem = dt.items[i];
        const entry = dataItem.webkitGetAsEntry && dataItem.webkitGetAsEntry();

        if (entry) {
          tasks.push(traverseEntry(entry, ""));
          continue;
        }

        const file = dataItem.getAsFile && dataItem.getAsFile();
        if (isNonEmptyFile(file)) {
          incomingItems.push(createUploadItem(file, file.name));
        }
      }

      if (tasks.length > 0) {
        const results = await Promise.all(tasks);

        for (let i = 0; i < results.length; i += 1) {
          for (let j = 0; j < results[i].length; j += 1) {
            incomingItems.push(results[i][j]);
          }
        }
      }
    }

    if (incomingItems.length === 0 && dt.files && dt.files.length > 0) {
      for (let i = 0; i < dt.files.length; i += 1) {
        const file = dt.files[i];
        if (!isNonEmptyFile(file)) {
          continue;
        }

        incomingItems.push(
          createUploadItem(file, file.webkitRelativePath || file.name)
        );
      }
    }

    return incomingItems;
  }, []);

  const handleDrop = useCallback(async function(event) {
    event.preventDefault();
    setIsDragging(false);

    const dt = event.dataTransfer;
    if (!dt) {
      return;
    }

    const incomingItems = await collectDroppedItems(dt);
    addIncomingItems(incomingItems);
  }, [addIncomingItems, collectDroppedItems]);

  const handleDragOver = useCallback(function(event) {
    event.preventDefault();
    setIsDragging(true);
  }, []);

  const handleDragLeave = useCallback(function() {
    setIsDragging(false);
  }, []);

  const handleFilesSelected = useCallback(function(files) {
    if (!files || files.length === 0) {
      return;
    }

    const incoming = readFilesFromInput(files, false);
    addIncomingItems(incoming);
  }, [addIncomingItems, readFilesFromInput]);

  const handleFolderSelected = useCallback(function(files) {
    if (!files || files.length === 0) {
      return;
    }

    const incoming = readFilesFromInput(files, true);
    addIncomingItems(incoming);
  }, [addIncomingItems, readFilesFromInput]);

  useEffect(function() {
    if (folderInputRef.current) {
      folderInputRef.current.setAttribute("webkitdirectory", "");
      folderInputRef.current.setAttribute("directory", "");
    }
  }, []);

  useMetadataStream(API_BASE, setMetadata);

  return (
    <div className={styles.page}>
      <div className={styles.container}>
        <Header
          queueCount={selectedItems.length}
          serverCount={metadataEntries.length}
          username={username}
          onLogout={handleLogout}
          onDeleteAccount={handleDeleteAccount}
        />

        <section className={styles.panel}>
          <ControlsPanel
            fileInputRef={fileInputRef}
            folderInputRef={folderInputRef}
            onPickFiles={handlePickFiles}
            onPickFolder={handlePickFolder}
            onUpload={handleUploadSelected}
            onClear={clearSelection}
            onFilesChange={handleFilesInputChange}
            onFolderChange={handleFolderInputChange}
            isUploading={isUploading}
            disabledClear={selectedItems.length === 0 || isUploading}
            queueCount={selectedItems.length}
          />

          <StatusLine text={statusText} tone={statusTone} />

          <Dropzone
            isDragging={isDragging}
            onDragOver={handleDragOver}
            onDragLeave={handleDragLeave}
            onDrop={handleDrop}
            onFilesSelected={handleFilesSelected}
            onFolderSelected={handleFolderSelected}
          />

          <UploadQueue items={selectedItems} />
        </section>

        <MetadataTable
          entries={metadataEntries}
          selectedPaths={selectedMetadataPaths}
          onToggleSelect={toggleMetadataSelection}
          onSelectAll={selectAllMetadata}
          onDeleteSelected={deleteSelectedMetadata}
          onDownload={downloadFile}
          onDelete={removeFile}
          onPreview={handlePreview}
          onToggleGroupSelect={toggleMetadataGroup}
          canPreview={canPreview}
          isDeleting={isDeleting}
        />
      </div>

      <PreviewModal preview={previewItem} onClose={handleClosePreview} />
    </div>
  );
}

export default App;
