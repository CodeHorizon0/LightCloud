import { accountChanged } from "../utils/accountEvents";
import { useCallback, useEffect, useRef, useState } from "react";

import type { FileInfo } from "../utils/storage";
import { ApiError, deleteFileBatch, downloadFile } from "../api";
import type { StatusTone } from "./useUploadQueue";

const DELETE_BATCH = 250;

interface FileActionCallbacks {
  setStatus: (text: string, tone?: StatusTone) => void;
  reportError: (error: unknown, fallback: string) => void;
  onDeleted: (paths: string[]) => void;
  available: boolean;
  metadata: ReadonlyMap<string, FileInfo>;
}

export function useFileActions({
  setStatus,
  reportError,
  onDeleted,
  available,
  metadata,
}: FileActionCallbacks) {
  const [deleting, setDeleting] = useState(false);
  const [downloading, setDownloading] = useState(false);
  const deleteBusy = useRef(false);
  const downloadBusy = useRef(false);
  const lifetime = useRef<AbortController | null>(null);

  useEffect(function trackLifetime() {
    const controller = new AbortController();
    lifetime.current = controller;
    return function abort() {
      controller.abort();
    };
  }, []);

  const removeFiles = useCallback(
    async function removeFiles(paths: string[]) {
      if (!available) {
        setStatus("Connect to storage to delete files", "warn");
        return;
      }
      if (deleteBusy.current || paths.length === 0) return;
      const signal = lifetime.current?.signal;
      deleteBusy.current = true;
      setDeleting(true);
      const versions = new Map(metadata);
      let removed = 0;
      let missing = 0;
      try {
        for (let offset = 0; offset < paths.length; offset += DELETE_BATCH) {
          signal?.throwIfAborted();
          const filenames = paths.slice(offset, offset + DELETE_BATCH);
          const revisions = Object.fromEntries(
            filenames.map(function (path) {
              return [path, versions.get(path)?.revision ?? null];
            }),
          );
          const result = await deleteFileBatch(filenames, revisions, signal);
          removed += result.deleted.length;
          missing += result.missing.length;
          if (!signal?.aborted) {
            onDeleted(filenames);
            accountChanged();
          }
        }
        setStatus(
          missing
            ? `Deleted: ${removed}. Missing: ${missing}`
            : `Deleted: ${removed}`,
          missing ? "warn" : "ok",
        );
      } catch (error) {
        if (error instanceof ApiError && error.code === "sync_conflict")
          accountChanged();
        if (!signal?.aborted) reportError(error, "Failed to delete files");
      } finally {
        deleteBusy.current = false;
        if (!signal?.aborted) setDeleting(false);
      }
    },
    [available, metadata, onDeleted, reportError, setStatus],
  );

  const startDownloads = useCallback(
    async function startDownloads(paths: string[]) {
      if (!available) {
        setStatus("Connect to storage to download files", "warn");
        return;
      }
      if (downloadBusy.current || !paths.length) return;
      const signal = lifetime.current?.signal;
      downloadBusy.current = true;
      setDownloading(true);
      let started = 0;
      try {
        for (const path of paths) {
          await downloadFile(path, signal);
          started += 1;
        }
        setStatus(
          started === 1
            ? "Download started"
            : `Downloads requested: ${started}`,
          "ok",
        );
      } catch (error) {
        if (!signal?.aborted) reportError(error, "Failed to start download");
      } finally {
        downloadBusy.current = false;
        if (!signal?.aborted) setDownloading(false);
      }
    },
    [available, reportError, setStatus],
  );

  return { deleting, downloading, removeFiles, startDownloads };
}
