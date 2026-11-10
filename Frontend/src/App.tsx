import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { ApiError, requestJson } from "./api";
import { useAuth } from "./auth/useAuth";
import ControlsPanel from "./components/ControlsPanel/ControlsPanel";
import Dropzone from "./components/Dropzone/Dropzone";
import ChangePasswordDialog from "./components/UserCard/ChangePasswordDialog";
import Header from "./components/Header/Header";
import MetadataTable from "./components/MetadataTable/MetadataTable";
import PreviewModal from "./components/PreviewModal/PreviewModal";
import StatusLine from "./components/StatusLine/StatusLine";
import UploadQueue from "./components/UploadQueue/UploadQueue";
import { useFileActions } from "./hooks/useFileActions";
import { useFileSelection } from "./hooks/useFileSelection";
import useAccountSync from "./hooks/useAccountSync";
import { useUploadQueue } from "./hooks/useUploadQueue";
import type { StatusTone } from "./hooks/useUploadQueue";
import { clearPreviewCache, prunePreviewCache } from "./utils/previewCache";
import type { Entry, FileInfo } from "./utils/storage";
import styles from "./App.module.css";

function UploadPanel({
  setStatus,
  reportError,
  setQueueCount,
  status,
  readOnly,
  metadata,
}: {
  setStatus: (message: string, tone?: StatusTone) => void;
  reportError: (error: unknown, fallback: string) => void;
  setQueueCount: (count: number) => void;
  status: { text: string; tone: StatusTone };
  readOnly: boolean;
  metadata: ReadonlyMap<string, FileInfo>;
}) {
  const queue = useUploadQueue(setStatus, reportError, metadata);
  const count = queue.items.length;
  useEffect(
    function updateQueueCount() {
      setQueueCount(count);
    },
    [count, setQueueCount],
  );

  return (
    <section className={styles.panel}>
      <ControlsPanel
        onUpload={queue.upload}
        onClear={queue.clear}
        isUploading={queue.uploading}
        offline={readOnly}
        queueCount={queue.items.length}
      />
      <StatusLine text={status.text} tone={status.tone} />
      <Dropzone
        disabled={queue.uploading || readOnly}
        onFiles={queue.add}
        onError={function fail(error) {
          reportError(error, "Failed to read dropped files");
        }}
      />
      <UploadQueue
        items={queue.items}
        onSaveCopy={queue.saveCopy}
        onDiscard={queue.discard}
      />
    </section>
  );
}

export default function App() {
  const auth = useAuth();
  const { clearSession } = auth;
  const { metadata, connection, savedAt, snapshotAvailable } = useAccountSync();
  const readOnly = auth.offline || connection !== "connected";
  const [status, setStatusState] = useState<{ text: string; tone: StatusTone }>(
    { text: "Ready to upload", tone: "muted" },
  );
  const [queueCount, setQueueCount] = useState(0);
  const [previewPath, setPreviewPath] = useState<string | null>(null);
  const accountBusy = useRef(false);
  const [changingPassword, setChangingPassword] = useState(false);
  const { selectedPaths, updateSelection, toggleFile, toggleAll } =
    useFileSelection(metadata);

  const entries = useMemo<Entry[]>(
    function buildEntries() {
      return Array.from(metadata.entries());
    },
    [metadata],
  );
  const preview = previewPath === null ? undefined : metadata.get(previewPath);
  const account = auth.user?.id;
  useEffect(
    function prune() {
      if (account && connection === "connected")
        prunePreviewCache(account, metadata);
    },
    [account, connection, metadata],
  );

  const setStatus = useCallback(function setStatus(
    text: string,
    tone: StatusTone = "muted",
  ) {
    setStatusState({ text, tone });
  }, []);

  const reportError = useCallback(
    function reportError(error: unknown, fallback: string) {
      if (error instanceof ApiError && error.status === 401) clearSession();
      else
        setStatus(error instanceof Error ? error.message : fallback, "danger");
    },
    [clearSession, setStatus],
  );

  const previewError = useCallback(
    function previewError(error: unknown) {
      if (error instanceof ApiError && error.status === 401) clearSession();
    },
    [clearSession],
  );

  const onDeleted = useCallback(
    function onDeleted(paths: string[]) {
      updateSelection(paths, false);
    },
    [updateSelection],
  );
  const { deleting, downloading, removeFiles, startDownloads } = useFileActions(
    {
      setStatus,
      reportError,
      onDeleted,
      available: !readOnly,
      metadata,
    },
  );

  async function handleLogout() {
    if (accountBusy.current) return;
    accountBusy.current = true;
    try {
      await auth.logout();
    } catch (error) {
      reportError(error, "Failed to sign out");
    } finally {
      accountBusy.current = false;
    }
  }

  async function deleteAccount() {
    if (
      readOnly ||
      accountBusy.current ||
      !window.confirm("Delete account? This action cannot be undone.")
    )
      return;
    accountBusy.current = true;
    try {
      await requestJson("/auth/delete", { method: "DELETE" });
      clearSession();
    } catch (error) {
      reportError(error, "Failed to delete account");
    } finally {
      accountBusy.current = false;
    }
  }

  async function clearCache() {
    if (!account) return;
    if (await clearPreviewCache(account))
      setStatus("Local preview cache cleared", "ok");
    else setStatus("Local preview cache is unavailable", "warn");
  }

  function closePreview() {
    setPreviewPath(null);
  }

  return (
    <div className={styles.page}>
      <div className={styles.container}>
        <Header
          queueCount={queueCount}
          serverCount={metadata.size}
          username={auth.user?.username ?? ""}
          onClearCache={clearCache}
          onChangePassword={function openPassword() {
            setChangingPassword(true);
          }}
          onLogout={handleLogout}
          onDeleteAccount={deleteAccount}
          offline={readOnly}
        />
        <UploadPanel
          setStatus={setStatus}
          reportError={reportError}
          setQueueCount={setQueueCount}
          status={status}
          readOnly={readOnly}
          metadata={metadata}
        />
        {readOnly ? (
          <StatusLine
            text={
              auth.offline ||
              connection === "offline" ||
              connection === "reconnecting"
                ? `Offline mode. ${snapshotAvailable && savedAt ? `Saved list: ${new Date(savedAt).toLocaleString()}.` : "No saved list is available."} Only saved previews can be opened. Changes and downloads require a connection.`
                : "Loading files..."
            }
            tone="warn"
          />
        ) : !snapshotAvailable ? (
          <StatusLine
            text="The file list could not be saved for offline access. Check browser storage."
            tone="warn"
          />
        ) : null}
        <MetadataTable
          entries={entries}
          selectedPaths={selectedPaths}
          onToggleSelect={toggleFile}
          onToggleGroupSelect={updateSelection}
          onSelectAll={toggleAll}
          onDelete={removeFiles}
          onDownload={startDownloads}
          onPreview={setPreviewPath}
          isDeleting={deleting || readOnly}
          isDownloading={downloading || readOnly}
        />
      </div>
      {changingPassword ? (
        <ChangePasswordDialog
          onClose={function closePassword() {
            setChangingPassword(false);
          }}
        />
      ) : null}
      {account && previewPath !== null && preview?.preview_kind ? (
        <PreviewModal
          key={JSON.stringify([
            previewPath,
            preview.preview_kind,
            preview.revision,
            preview.code_language,
          ])}
          resource={{
            account,
            path: previewPath,
            kind: preview.preview_kind,
            revision: preview.revision,
            language: preview.code_language,
          }}
          mime={preview.mime}
          size={preview.original_size}
          onClose={closePreview}
          onDownload={function downloadPreview() {
            void startDownloads([previewPath]);
          }}
          onError={previewError}
        />
      ) : null}
    </div>
  );
}
