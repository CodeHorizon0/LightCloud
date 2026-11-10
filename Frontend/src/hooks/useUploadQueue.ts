import { accountChanged } from "../utils/accountEvents";
import { useCallback, useEffect, useRef, useState } from "react";

import { API_BASE, ApiError, parseJson, requestJson } from "../api";
import { parseLimits, splitBatches, uploadIssue } from "../utils/storage";
import type { FileInfo, UploadItem } from "../utils/storage";

export type StatusTone = "muted" | "warn" | "ok" | "danger";
type SetStatus = (message: string, tone?: StatusTone) => void;
type ReportError = (error: unknown, fallback: string) => void;

function sendBatch(
  batch: UploadItem[],
  signal: AbortSignal,
  progress: (fraction: number) => void,
): Promise<void> {
  return new Promise(function (resolve, reject) {
    if (signal.aborted) {
      reject(signal.reason);
      return;
    }

    const xhr = new XMLHttpRequest();
    const form = new FormData();
    for (const item of batch)
      form.append("files", item.file, item.relativePath);
    form.append(
      "revisions",
      JSON.stringify(
        Object.fromEntries(
          batch.map(function (item) {
            return [item.relativePath, item.baseRevision ?? null];
          }),
        ),
      ),
    );

    let frame = 0;
    let fraction = 0;

    function update() {
      frame = 0;
      progress(fraction);
    }

    function abort() {
      xhr.abort();
    }

    xhr.open("POST", `${API_BASE}/sync/upload`);
    xhr.withCredentials = true;
    xhr.setRequestHeader("Accept", "application/json");
    signal.addEventListener("abort", abort, { once: true });

    xhr.upload.onprogress = function onProgress(event) {
      if (!event.lengthComputable) return;
      fraction = Math.min(1, event.loaded / Math.max(1, event.total));
      if (!frame) frame = requestAnimationFrame(update);
    };
    xhr.upload.onload = function received() {
      cancelAnimationFrame(frame);
      fraction = 1;
      update();
    };
    xhr.onload = function uploaded() {
      if (xhr.status === 201) resolve();
      else
        reject(
          new ApiError(
            xhr.status,
            parseJson(xhr.responseText),
            xhr.getResponseHeader("Retry-After"),
          ),
        );
    };
    xhr.onerror = function failed() {
      reject(
        new Error(
          "Upload connection lost. Check the file list before retrying.",
        ),
      );
    };
    xhr.onabort = function cancelled() {
      reject(signal.reason);
    };
    xhr.onloadend = function cleanup() {
      signal.removeEventListener("abort", abort);
      cancelAnimationFrame(frame);
    };

    xhr.send(form);
  });
}

function delay(ms: number, signal: AbortSignal): Promise<void> {
  return new Promise(function (resolve, reject) {
    if (signal.aborted) {
      reject(signal.reason);
      return;
    }
    const timer = setTimeout(function done() {
      signal.removeEventListener("abort", abort);
      resolve();
    }, ms);
    function abort() {
      clearTimeout(timer);
      reject(signal.reason);
    }
    signal.addEventListener("abort", abort, { once: true });
  });
}

async function sendWithRetry(
  batch: UploadItem[],
  signal: AbortSignal,
  progress: (fraction: number) => void,
): Promise<void> {
  try {
    await sendBatch(batch, signal, progress);
  } catch (error) {
    if (!(error instanceof ApiError && error.status === 429)) throw error;
    const seconds = Number(error.retryAfter);
    await delay(Math.min(30, Math.max(1, seconds || 5)) * 1000, signal);
    await sendBatch(batch, signal, progress);
  }
}

export function useUploadQueue(
  setStatus: SetStatus,
  reportError: ReportError,
  metadata: ReadonlyMap<string, FileInfo>,
) {
  const [items, setItems] = useState<UploadItem[]>([]);
  const [uploading, setUploading] = useState(false);
  const active = useRef<AbortController | null>(null);

  useEffect(function cancelUploadOnUnmount() {
    return function cleanup() {
      active.current?.abort();
    };
  }, []);

  function add(incoming: UploadItem[]) {
    if (active.current || incoming.length === 0) return;
    setItems(function merge(previous) {
      const byPath = new Map<string, UploadItem>();
      for (const item of previous) byPath.set(item.id, item);
      for (const item of incoming)
        byPath.set(item.id, {
          ...item,
          baseRevision: metadata.get(item.relativePath)?.revision ?? null,
        });
      return Array.from(byPath.values());
    });
    setStatus("Files added to queue", "ok");
  }

  function clear() {
    if (active.current) return;
    setItems([]);
    setStatus("Queue cleared");
  }

  const discard = useCallback(function discard(id: string) {
    if (active.current) return;
    setItems(function (previous) {
      return previous.filter(function (item) {
        return item.id !== id;
      });
    });
  }, []);

  const saveCopy = useCallback(
    function saveCopy(id: string) {
      if (active.current) return;
      setItems(function (previous) {
        return previous.map(function (item) {
          if (item.id !== id || item.status !== "conflict") return item;
          const slash = item.relativePath.lastIndexOf("/");
          const directory = item.relativePath.slice(0, slash + 1);
          const name = item.relativePath.slice(slash + 1);
          const dot = name.lastIndexOf(".");
          const extension =
            dot > 0 && name.length - dot <= 32 ? name.slice(dot) : "";
          const stem = extension ? name.slice(0, dot) : name;
          const suffix = ` (copy ${crypto.randomUUID().slice(0, 8)})${extension}`;
          const encoder = new TextEncoder();
          const letters = Array.from(stem);
          while (
            letters.length &&
            encoder.encode(letters.join("") + suffix).length > 255
          )
            letters.pop();
          const path = directory + letters.join("") + suffix;
          return {
            ...item,
            id: path,
            relativePath: path,
            baseRevision: null,
            status: "in queue",
            progress: 0,
          };
        });
      });
      setStatus("Copy added to queue. Upload selected to save it.", "ok");
    },
    [setStatus],
  );

  async function upload() {
    if (active.current || !items.length) return;
    const controller = new AbortController();
    const { signal } = controller;
    active.current = controller;
    setUploading(true);
    setStatus("Checking server upload limits");

    function mark(ids: Set<string>, status: UploadItem["status"]) {
      setItems(function update(previous) {
        return previous.map(function (item) {
          return ids.has(item.id) ? { ...item, status, progress: 0 } : item;
        });
      });
    }

    try {
      const limits = parseLimits(
        await requestJson("/storage/limits", { signal }),
      );
      const issues = new Map<string, string>();
      const ready = items.filter(function (item) {
        const issue = uploadIssue(item, limits);
        if (issue) issues.set(item.id, issue);
        return !issue;
      });
      if (issues.size) mark(new Set(issues.keys()), "error");
      if (!ready.length) {
        setStatus(issues.values().next().value ?? "No valid uploads", "danger");
        return;
      }

      const batches = splitBatches(ready, limits);
      let uploaded = 0;
      let failed = issues.size;
      let failure = issues.values().next().value ?? "";
      for (const [index, batch] of batches.entries()) {
        const ids = new Set(
          batch.map(function (item) {
            return item.id;
          }),
        );
        const total = batch.reduce(function (bytes, item) {
          return bytes + Math.max(1, item.size);
        }, 0);
        const ranges = new Map<string, [number, number]>();
        let offset = 0;
        for (const item of batch) {
          const size = Math.max(1, item.size);
          ranges.set(item.id, [offset, size]);
          offset += size;
        }

        mark(ids, "uploading");
        setStatus(`Uploading batch ${index + 1}/${batches.length}`);
        try {
          await sendWithRetry(batch, signal, function showProgress(fraction) {
            setItems(function update(previous) {
              return previous.map(function (item) {
                const range = ranges.get(item.id);
                if (!range) return item;
                const progress = Math.round(
                  Math.max(
                    0,
                    Math.min(1, (fraction * total - range[0]) / range[1]),
                  ) * 100,
                );
                const status = progress === 100 ? "processing" : "uploading";
                return item.progress === progress && item.status === status
                  ? item
                  : { ...item, progress, status };
              });
            });
          });
          uploaded += batch.length;
          accountChanged();
          setItems(function remove(previous) {
            return previous.filter(function (item) {
              return !ids.has(item.id);
            });
          });
        } catch (error) {
          if (
            signal.aborted ||
            (error instanceof ApiError && error.status === 401)
          )
            throw error;
          failed += batch.length;
          failure = error instanceof Error ? error.message : "Upload failed";
          const conflict =
            error instanceof ApiError && error.code === "sync_conflict";
          mark(ids, conflict ? "conflict" : "error");
          if (conflict) accountChanged();
        }
      }
      setStatus(
        failed
          ? `Uploaded: ${uploaded}. Failed: ${failed}. ${failure}`
          : `Uploaded: ${uploaded}`,
        failed ? "warn" : "ok",
      );
    } catch (error) {
      if (!signal.aborted) reportError(error, "Upload failed");
    } finally {
      active.current = null;
      if (!signal.aborted) setUploading(false);
    }
  }

  return { items, uploading, add, clear, upload, discard, saveCopy };
}
