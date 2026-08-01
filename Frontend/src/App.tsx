// App.tsx
import React, {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  ChangeEvent,
  DragEvent,
  ReactNode,
} from "react";
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
  UploadItem,
} from "./utils/storage";

interface User {
  username: string;
}

interface AuthContextType {
  user: User | null;
  logout: () => Promise<void>;
}

interface PreviewItem {
  path: string;
  kind: "image" | "audio" | "video" | "text" | "html";
  title: string;
  size: number;
  url: string;
}

type StatusTone = "muted" | "warn" | "ok" | "danger";

interface BatchRange {
  id: string;
  start: number;
  end: number;
  size: number;
}

interface BatchProgress {
  ranges: BatchRange[];
  total: number;
}

type FileInfo = Record<string, unknown>;
type Entry = [string, FileInfo];

const UPLOAD_BATCH_SIZE = 8;
const UPLOAD_RETRY_COUNT = 2;
const UPLOAD_RETRY_DELAY_MS = 500;

function sleep(ms: number): Promise<void> {
  return new Promise(function (resolve) {
    setTimeout(resolve, ms);
  });
}

function getResponseMessage(xhr: XMLHttpRequest): string {
  try {
    const data = JSON.parse(xhr.responseText || "null");
    if (Array.isArray(data)) {
      return `Server response: ${data.length} files`;
    }
    if (data && typeof data === "object") {
      return data.detail || data.msg || data.message || `HTTP ${xhr.status}`;
    }
  } catch (_) {
    // ignore
  }
  return xhr.statusText || `HTTP ${xhr.status}`;
}

function buildBatchProgressMap(batch: UploadItem[]): BatchProgress {
  let offset = 0;
  const ranges: BatchRange[] = [];

  for (let i = 0; i < batch.length; i += 1) {
    const item = batch[i];
    const size = Math.max(1, Number(item.size) || 0);
    const start = offset;
    const end = offset + size;
    ranges.push({
      id: item.id,
      start,
      end,
      size,
    });
    offset = end;
  }

  return {
    ranges,
    total: Math.max(1, offset),
  };
}

interface AppProps {
  username?: string;
}

function App(props: AppProps): ReactNode {
  const fileInputRef = useRef<HTMLInputElement>(null);
  const folderInputRef = useRef<HTMLInputElement>(null);
  const isUploadingRef = useRef<boolean>(false);
  const selectedItemsRef = useRef<UploadItem[]>([]);
  const isMountedRef = useRef<boolean>(true);
  const lastSelectedIndexRef = useRef<number | null>(null);

  const auth = useAuth() as AuthContextType;
  const navigate = useNavigate();
  const username = props.username || (auth.user && auth.user.username) || "";

  const [selectedItems, setSelectedItems] = useState<UploadItem[]>([]);
  const [metadata, setMetadata] = useState<Record<string, FileInfo>>({});
  const [selectedMetadataPaths, setSelectedMetadataPaths] = useState<string[]>([]);
  const [statusText, setStatusText] = useState<string>("Ready to upload");
  const [statusTone, setStatusTone] = useState<StatusTone>("muted");
  const [isUploading, setIsUploading] = useState<boolean>(false);
  const [isDeleting, setIsDeleting] = useState<boolean>(false);
  const [isDragging, setIsDragging] = useState<boolean>(false);
  const [previewItem, setPreviewItem] = useState<PreviewItem | null>(null);

  useEffect(function () {
    selectedItemsRef.current = selectedItems;
  }, [selectedItems]);

  useEffect(function () {
    isMountedRef.current = true;
    return function () {
      isMountedRef.current = false;
    };
  }, []);

  const metadataEntries = useMemo<Entry[]>(function () {
    return Object.entries(metadata).sort(function (a, b) {
      return a[0].localeCompare(b[0]);
    }) as Entry[];
  }, [metadata]);

  const metadataIndexMap = useMemo<Map<string, number>>(function () {
    const map = new Map<string, number>();
    for (let i = 0; i < metadataEntries.length; i += 1) {
      map.set(metadataEntries[i][0], i);
    }
    return map;
  }, [metadataEntries]);

  useEffect(function () {
    const allowed = new Set(metadataEntries.map(function (entry) {
      return entry[0];
    }));
    setSelectedMetadataPaths(function (prev: string[]) {
      const next = prev.filter(function (path) {
        return allowed.has(path);
      });
      if (next.length !== prev.length) return next;
      for (let i = 0; i < next.length; i += 1) {
        if (next[i] !== prev[i]) return next;
      }
      return prev;
    });

    if (
      lastSelectedIndexRef.current != null &&
      lastSelectedIndexRef.current >= metadataEntries.length
    ) {
      lastSelectedIndexRef.current = metadataEntries.length > 0 ? metadataEntries.length - 1 : null;
    }
  }, [metadataEntries]);

  function setStatus(message: string, tone?: StatusTone) {
    if (!isMountedRef.current) return;
    setStatusText(message);
    setStatusTone(tone || "muted");
  }

  function updateItem(itemId: string, updater: (item: UploadItem) => UploadItem) {
    setSelectedItems(function (prev: UploadItem[]) {
      return prev.map(function (item) {
        return item.id === itemId ? updater(item) : item;
      });
    });
  }

  function addIncomingItems(incomingItems: UploadItem[]) {
    if (!incomingItems || incomingItems.length === 0) {
      setStatus("Empty files and folders are not uploaded", "warn");
      return;
    }

    const validItems: UploadItem[] = [];
    for (const item of incomingItems) {
      if (item && item.file && isNonEmptyFile(item.file)) {
        validItems.push(item);
      }
    }

    if (validItems.length === 0) {
      setStatus("Empty files and folders are not uploaded", "warn");
      return;
    }

    setSelectedItems(function (prev: UploadItem[]) {
      return mergeUniqueItems(prev, validItems);
    });

    setStatus(
      validItems.length !== incomingItems.length
        ? "Empty files skipped, rest added to queue"
        : "Files added to queue",
      validItems.length !== incomingItems.length ? "warn" : "ok"
    );
  }

  function clearSelection() {
    if (isUploadingRef.current) return;
    setSelectedItems([]);
    setStatus("Queue cleared", "muted");
  }

  function handleLogout() {
    return Promise.resolve()
      .then(function () {
        return auth.logout();
      })
      .finally(function () {
        return navigate("/login", { replace: true });
      });
  }

  function deleteFiles(paths: string[]): Promise<void> {
    const normalizedPaths: string[] = [];
    const seen = new Set<string>();

    for (const p of paths) {
      const cleanPath = normalizePath(p);
      if (!cleanPath || seen.has(cleanPath)) continue;
      seen.add(cleanPath);
      normalizedPaths.push(cleanPath);
    }

    if (normalizedPaths.length === 0) {
      setStatus("Nothing to delete", "warn");
      return Promise.resolve();
    }

    setIsDeleting(true);
    setStatus(`Deleting: ${normalizedPaths.length} files`, "muted");

    return fetch(`${API_BASE}/delete`, {
      method: "DELETE",
      credentials: "include",
      headers: {
        Accept: "application/json",
        "Content-Type": "application/json",
      },
      body: JSON.stringify(buildDeleteRequestBody(normalizedPaths)),
    })
      .then(function (response) {
        return response.json().catch(function () {
          return null;
        }).then(function (data) {
          if (!response.ok) {
            throw new Error(
              (data && (data.detail || data.message)) || `Delete failed: ${response.status}`
            );
          }
          return data;
        });
      })
      .then(function (data) {
        const deleted: string[] = data && Array.isArray(data.deleted) ? data.deleted : normalizedPaths;
        const missing: string[] = data && Array.isArray(data.missing) ? data.missing : [];

        setMetadata(function (prev) {
          const next = { ...prev };
          for (const d of deleted) delete next[d];
          for (const m of missing) delete next[m];
          return next;
        });

        setSelectedMetadataPaths(function (prev: string[]) {
          const deletedSet = new Set([...deleted, ...missing]);
          return prev.filter(function (path) {
            return !deletedSet.has(path);
          });
        });

        setStatus(
          missing.length > 0
            ? `Deleted: ${deleted.length}, not found: ${missing.length}`
            : `Deleted: ${deleted.length}`,
          missing.length > 0 ? "warn" : "ok"
        );
      })
      .catch(function (error) {
        console.error(error);
        setStatus("Failed to delete files", "danger");
      })
      .finally(function () {
        setIsDeleting(false);
      });
  }

  function handleDeleteAccount() {
    const confirmed = window.confirm("Delete account? This action cannot be undone.");
    if (!confirmed) return;

    fetch(`${API_BASE}/auth/delete`, {
      method: "DELETE",
      credentials: "include",
      headers: { Accept: "application/json" },
    })
      .then(function (response) {
        if (!response.ok && response.status !== 404) {
          throw new Error("Delete account failed");
        }
        return auth.logout();
      })
      .then(function () {
        return navigate("/login", { replace: true });
      })
      .catch(function (error) {
        console.error(error);
        setStatus("Failed to delete account", "danger");
      });
  }

  function handlePickFiles() {
    fileInputRef.current?.click();
  }

  function handlePickFolder() {
    folderInputRef.current?.click();
  }

  function readFilesFromInput(files: FileList | File[], useRelativePath: boolean): UploadItem[] {
    const fileList = Array.isArray(files) ? files : Array.from(files);
    const incoming: UploadItem[] = [];
    for (const file of fileList) {
      if (!isNonEmptyFile(file)) continue;
      const relativePath = useRelativePath
        ? (file as File & { webkitRelativePath?: string }).webkitRelativePath || file.name
        : file.name;
      incoming.push(createUploadItem(file, relativePath));
    }
    return incoming;
  }

  function handleFilesInputChange(event: ChangeEvent<HTMLInputElement>) {
    const files = event.target.files;
    if (!files || files.length === 0) return;
    const incoming = readFilesFromInput(files, false);
    addIncomingItems(incoming);
    event.target.value = "";
  }

  function handleFolderInputChange(event: ChangeEvent<HTMLInputElement>) {
    const files = event.target.files;
    if (!files || files.length === 0) return;
    const incoming = readFilesFromInput(files, true);
    addIncomingItems(incoming);
    event.target.value = "";
  }

  function uploadBatch(batch: UploadItem[], batchIndex: number, totalBatches: number): Promise<string> {
    return new Promise(function (resolve, reject) {
      const formData = new FormData();
      appendUploadFiles(formData, batch);

      const xhr = new XMLHttpRequest();
      xhr.open("POST", `${API_BASE}/upload`, true);
      xhr.withCredentials = true;
      xhr.setRequestHeader("Accept", "application/json");

      const batchProgress = buildBatchProgressMap(batch);

      xhr.upload.onprogress = function (progressEvent: ProgressEvent) {
        if (!progressEvent.lengthComputable) return;

        const loaded = Math.max(0, Math.min(progressEvent.loaded, batchProgress.total));

        for (const range of batchProgress.ranges) {
          let progress = 0;
          if (loaded >= range.end) {
            progress = 100;
          } else if (loaded > range.start) {
            progress = ((loaded - range.start) / range.size) * 100;
          }
          updateItem(range.id, function (current) {
            return {
              ...current,
              progress: Math.max(0, Math.min(100, progress)),
              status: progress >= 100 ? "processing" : "uploading",
            };
          });
        }

        const percent = Math.round((loaded / batchProgress.total) * 100);
        setStatus(`Uploading batch ${batchIndex + 1}/${totalBatches}: ${percent}%`, "muted");
      };

      xhr.upload.onload = function () {
        for (const item of batch) {
          updateItem(item.id, function (current) {
            return {
              ...current,
              progress: 100,
              status: "processing",
            };
          });
        }
      };

      xhr.onload = function () {
        if (xhr.status >= 200 && xhr.status < 300) {
          resolve(xhr.responseText);
        } else {
          reject(new Error(getResponseMessage(xhr)));
        }
      };

      xhr.onerror = function () {
        reject(new Error("Network error"));
      };

      xhr.send(formData);
    });
  }

  function uploadBatchWithRetry(batch: UploadItem[], batchIndex: number, totalBatches: number): Promise<string | null> {
    let attempt = 0;
    function attemptUpload(): Promise<string | null> {
      return uploadBatch(batch, batchIndex, totalBatches)
        .catch(function (error) {
          attempt += 1;
          if (attempt > UPLOAD_RETRY_COUNT) throw error;
          setStatus(
            `Retrying upload batch ${batchIndex + 1}/${totalBatches} in ${UPLOAD_RETRY_DELAY_MS} ms`,
            "warn"
          );
          return sleep(UPLOAD_RETRY_DELAY_MS * Math.pow(2, attempt - 1))
            .then(function () {
              return attemptUpload();
            });
        });
    }
    return attemptUpload();
  }

  function handleUploadSelected() {
    if (isUploadingRef.current) return;

    const snapshot = selectedItemsRef.current.slice();
    const pendingItems: UploadItem[] = snapshot.filter(
      function (item) {
        return item.status !== "uploading" && item.status !== "processing";
      }
    );

    if (pendingItems.length === 0) {
      setStatus("Please select files or folder first", "warn");
      return;
    }

    const batches: UploadItem[][] = chunkArray(pendingItems, UPLOAD_BATCH_SIZE);
    isUploadingRef.current = true;
    setIsUploading(true);
    setStatus(
      `Upload started: ${pendingItems.length} files, ${batches.length} requests`,
      "muted"
    );

    let successCount = 0;
    let errorCount = 0;

    function processBatch(index: number): Promise<void> {
      if (index >= batches.length) return Promise.resolve();

      const batch = batches[index];

      for (const item of batch) {
        updateItem(item.id, function (current) {
          return {
            ...current,
            progress: 0,
            status: "uploading",
          };
        });
      }

      return uploadBatchWithRetry(batch, index, batches.length)
        .then(function () {
          successCount += batch.length;

          setSelectedItems(function (prev: UploadItem[]) {
            const batchIds = new Set(batch.map(function (item) {
              return item.id;
            }));
            return prev.filter(function (item) {
              return !batchIds.has(item.id);
            });
          });

          setStatus(
            `Uploaded: ${successCount}, errors: ${errorCount}`,
            errorCount > 0 ? "warn" : "ok"
          );
          return processBatch(index + 1);
        })
        .catch(function (error) {
          errorCount += batch.length;
          console.error(error);
          for (const item of batch) {
            updateItem(item.id, function (current) {
              return {
                ...current,
                progress: 0,
                status: "error",
              };
            });
          }
          setStatus(`Error in batch ${index + 1}/${batches.length}`, "danger");
          return processBatch(index + 1);
        });
    }

    processBatch(0)
      .finally(function () {
        isUploadingRef.current = false;
        setIsUploading(false);
        if (successCount === 0 && errorCount === 0) {
          setStatus("Upload finished", "muted");
        } else {
          setStatus(
            `Done. Success: ${successCount}, errors: ${errorCount}`,
            errorCount > 0 ? "warn" : "ok"
          );
        }
      });
  }

  function downloadFile(path: string): Promise<void> {
    return fetch(buildDownloadUrl(path), { credentials: "include" })
      .then(function (response) {
        if (!response.ok) throw new Error("Download failed");
        return response.blob();
      })
      .then(function (blob) {
        const objectUrl = URL.createObjectURL(blob);
        const link = document.createElement("a");
        link.href = objectUrl;
        const safeName = normalizePath(path).split("/").pop() || "file";
        link.download = safeName;
        document.body.appendChild(link);
        link.click();
        link.remove();
        URL.revokeObjectURL(objectUrl);
        setStatus(`Downloaded: ${path}`, "ok");
      })
      .catch(function (error) {
        console.error(error);
        setStatus(`Failed to download: ${path}`, "danger");
      });
  }

  function removeFile(path: string): Promise<void> {
    return deleteFiles([path]);
  }

  function toggleMetadataSelection(
    path: string,
    event?: React.MouseEvent | ChangeEvent<HTMLInputElement>,
    index?: number
  ) {
    const cleanPath = normalizePath(path);
    const checked = event && "currentTarget" in event ? !!(event.currentTarget as HTMLInputElement).checked : false;
    const shiftKey = !!(event && ((event as React.MouseEvent).shiftKey || (event as React.MouseEvent).nativeEvent?.shiftKey));
    const currentIndex = typeof index === "number" ? index : metadataIndexMap.get(cleanPath);

    setSelectedMetadataPaths(function (prev: string[]) {
      const orderedPaths = metadataEntries.map(function (entry) {
        return entry[0];
      });
      const selected = new Set(prev);
      const anchorIndex = lastSelectedIndexRef.current;

      if (shiftKey && anchorIndex != null && currentIndex != null) {
        const start = Math.min(anchorIndex, currentIndex);
        const end = Math.max(anchorIndex, currentIndex);
        for (let i = start; i <= end; i += 1) {
          const rangePath = orderedPaths[i];
          if (!rangePath) continue;
          if (checked) selected.add(rangePath);
          else selected.delete(rangePath);
        }
      } else if (checked) {
        selected.add(cleanPath);
      } else {
        selected.delete(cleanPath);
      }
      return orderedPaths.filter(function (p) {
        return selected.has(p);
      });
    });

    if (currentIndex != null) {
      lastSelectedIndexRef.current = currentIndex;
    }
  }

  function selectAllMetadata() {
    if (metadataEntries.length === 0) return;
    setSelectedMetadataPaths(function (prev: string[]) {
      if (prev.length === metadataEntries.length) {
        lastSelectedIndexRef.current = null;
        return [];
      }
      lastSelectedIndexRef.current = metadataEntries.length - 1;
      return metadataEntries.map(function (entry) {
        return entry[0];
      });
    });
  }

  function toggleMetadataGroup(groupPaths: string[], checked: boolean) {
    const normalized: string[] = [];
    const seen = new Set<string>();
    for (const p of groupPaths) {
      const cleanPath = normalizePath(p);
      if (!cleanPath || seen.has(cleanPath)) continue;
      seen.add(cleanPath);
      normalized.push(cleanPath);
    }
    if (normalized.length === 0) return;

    setSelectedMetadataPaths(function (prev: string[]) {
      const next = new Set(prev);
      for (const p of normalized) {
        if (checked) next.add(p);
        else next.delete(p);
      }
      return metadataEntries.map(function (entry) {
        return entry[0];
      }).filter(function (p) {
        return next.has(p);
      });
    });

    const lastPath = normalized[normalized.length - 1];
    const nextIndex = metadataIndexMap.get(lastPath);
    if (typeof nextIndex === "number") {
      lastSelectedIndexRef.current = nextIndex;
    }
  }

  function deleteSelectedMetadata(): Promise<void> {
    return deleteFiles(selectedMetadataPaths);
  }

  function canPreview(path: string, info?: unknown): boolean {
    return getPreviewKind(path, info) != null;
  }

  function handlePreview(path: string, info?: unknown): void {
    const cleanPath = normalizePath(path);
    const kind = getPreviewKind(cleanPath, info);
    if (!kind) {
      setStatus("Preview unavailable for this file", "warn");
      return;
    }
    setPreviewItem({
      path: cleanPath,
      kind: kind as PreviewItem["kind"],
      title: getFileName(cleanPath) || cleanPath,
      size: info && typeof info === "object" && "original_size" in info ? (info as any).original_size : 0,
      url: buildPreviewUrl(cleanPath),
    });
  }

  function handleClosePreview() {
    setPreviewItem(null);
  }

  function collectDroppedItems(dt: DataTransfer): Promise<UploadItem[]> {
    const incomingItems: UploadItem[] = [];

    if (dt.items && dt.items.length > 0) {
      const tasks: Promise<UploadItem[]>[] = [];
      for (let i = 0; i < dt.items.length; i += 1) {
        const dataItem = dt.items[i];
        const entry = dataItem.webkitGetAsEntry?.();
        if (entry) {
          tasks.push(traverseEntry(entry, ""));
          continue;
        }
        const file = dataItem.getAsFile?.();
        if (file && isNonEmptyFile(file)) {
          incomingItems.push(createUploadItem(file, file.name));
        }
      }
      if (tasks.length > 0) {
        return Promise.all(tasks).then(function (results) {
          for (const res of results) {
            incomingItems.push(...res);
          }
          return incomingItems;
        });
      }
    }

    if (incomingItems.length === 0 && dt.files && dt.files.length > 0) {
      for (let i = 0; i < dt.files.length; i += 1) {
        const file = dt.files[i];
        if (!isNonEmptyFile(file)) continue;
        incomingItems.push(
          createUploadItem(file, file.webkitRelativePath || file.name)
        );
      }
    }

    return Promise.resolve(incomingItems);
  }

  function handleDrop(event: DragEvent<HTMLElement>) {
    event.preventDefault();
    setIsDragging(false);
    const dt = event.dataTransfer;
    if (!dt) return;
    collectDroppedItems(dt).then(function (incomingItems) {
      addIncomingItems(incomingItems);
    });
  }

  function handleDragOver(event: DragEvent<HTMLElement>) {
    event.preventDefault();
    setIsDragging(true);
  }

  function handleDragLeave() {
    setIsDragging(false);
  }

  function handleFilesSelected(files: FileList | File[]) {
    if (!files || (Array.isArray(files) && files.length === 0) || (!Array.isArray(files) && files.length === 0)) return;
    const incoming = readFilesFromInput(files, false);
    addIncomingItems(incoming);
  }

  function handleFolderSelected(files: FileList | File[]) {
    if (!files || (Array.isArray(files) && files.length === 0) || (!Array.isArray(files) && files.length === 0)) return;
    const incoming = readFilesFromInput(files, true);
    addIncomingItems(incoming);
  }

  useEffect(function () {
    if (folderInputRef.current) {
      folderInputRef.current.setAttribute("webkitdirectory", "");
      folderInputRef.current.setAttribute("directory", "");
    }
  }, []);

  const handleMetadataUpdate = useCallback(function handleMetadataUpdate(metadata: Record<string, unknown>) {
    setMetadata(metadata as Record<string, FileInfo>);
  }, []);

  useMetadataStream(API_BASE, handleMetadataUpdate);

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
            {...({
              fileInputRef: fileInputRef as React.RefObject<HTMLInputElement>,
              folderInputRef: folderInputRef as React.RefObject<HTMLInputElement>,
              onPickFiles: handlePickFiles,
              onPickFolder: handlePickFolder,
              onUpload: handleUploadSelected,
              onClear: clearSelection,
              onFilesChange: handleFilesInputChange,
              onFolderChange: handleFolderInputChange,
              isUploading: isUploading,
              disabledClear: selectedItems.length === 0 || isUploading,
              queueCount: selectedItems.length,
            } as any)}
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