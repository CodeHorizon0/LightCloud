import { useEffect, useState } from "react";
import { API_BASE, ApiError, parseJson } from "../api";
import { useAuth } from "../auth/useAuth";
import { ACCOUNT_INVALIDATED } from "../utils/accountEvents";
import { readSnapshot, saveSnapshot } from "../utils/offlineStore";
import {
  fetchSync,
  reconcileMetadata,
  syncEnvelope,
  syncPatch,
  syncSnapshot,
} from "../utils/sync";
import type { SyncState } from "../utils/sync";
import type { FileInfo } from "../utils/storage";

const POLL_INTERVAL = 2000;
const STREAM_RETRY_INTERVAL = 15_000;
const STREAM_TIMEOUT = 10_000;
const SNAPSHOT_SAVE_INTERVAL = 60_000;

type StreamStatus = "connecting" | "connected" | "reconnecting" | "offline";

export default function useAccountSync() {
  const { user, clearSession, markOffline, markOnline } = useAuth();
  const account = user?.id;
  const [metadata, setMetadata] = useState(function () {
    return new Map<string, FileInfo>();
  });
  const [connection, setConnection] = useState<StreamStatus>("connecting");
  const [savedAt, setSavedAt] = useState<number | null>(null);
  const [snapshotAvailable, setSnapshotAvailable] = useState(false);

  useEffect(
    function connectSync() {
      if (!account) return;
      const owner = account;
      const controller = new AbortController();
      let active = true;
      let state: SyncState = { cursor: "", files: new Map() };
      let pendingRefresh = false;
      let source: EventSource | undefined;
      let reconnect: ReturnType<typeof setTimeout> | undefined;
      let busy = false;
      let lastMessage = Date.now();
      let lastStreamAttempt = 0;
      let delay = 1000;
      let restored = false;
      let persistAt = 0;

      function stopStream() {
        source?.close();
        source = undefined;
      }
      function healthy() {
        if (!navigator.onLine) {
          markOffline();
          setConnection("offline");
          return;
        }
        delay = 1000;
        lastMessage = Date.now();
        markOnline();
        setConnection("connected");
      }
      function persist() {
        const savedState = state;
        persistAt = Date.now();
        void saveSnapshot(owner, savedState.files, savedState.cursor).then(
          function (ok) {
            if (!active || savedState.cursor !== state.cursor) return;
            setSnapshotAvailable(ok);
            if (ok) setSavedAt(Date.now());
          },
        );
      }
      function apply(next: SyncState) {
        const changed = next.cursor !== state.cursor;
        state = {
          cursor: next.cursor,
          files: reconcileMetadata(state.files, next.files),
        };
        setMetadata(state.files);
        healthy();
        if (changed || Date.now() - persistAt > SNAPSHOT_SAVE_INTERVAL)
          persist();
      }
      function retry() {
        clearTimeout(reconnect);
        reconnect = setTimeout(function () {
          reconnect = undefined;
          void synchronize();
        }, delay);
        delay = Math.min(delay * 2, 30_000);
      }
      function connect() {
        if (!active || source || !navigator.onLine) return;
        lastStreamAttempt = Date.now();
        lastMessage = lastStreamAttempt;
        const query = state.cursor ? `?cursor=${state.cursor}` : "";
        const stream = new EventSource(`${API_BASE}/sync/stream${query}`, {
          withCredentials: true,
        });
        source = stream;
        function message(event: MessageEvent<string>) {
          if (!active || source !== stream) return;
          const data = parseJson(event.data);
          try {
            if (event.type === "sync_snapshot")
              apply(syncSnapshot(data, owner));
            else if (event.type === "sync_patch")
              apply(syncPatch(data, owner, state));
            else {
              if (!syncEnvelope(data, owner) || data.cursor !== state.cursor)
                throw new Error("Synchronization snapshot required");
              healthy();
              if (Date.now() - persistAt > SNAPSHOT_SAVE_INTERVAL) {
                persist();
              }
            }
          } catch {
            state.cursor = "";
            stopStream();
            void synchronize();
          }
        }
        stream.addEventListener("sync_snapshot", message);
        stream.addEventListener("sync_patch", message);
        stream.addEventListener("sync_ready", message);
        stream.addEventListener("close_connection", function revoked() {
          if (active && source === stream) clearSession();
        });
        stream.onerror = function disconnected() {
          if (!active || source !== stream) return;
          stopStream();
          void synchronize();
        };
      }
      async function synchronize(force = false) {
        if (!active || busy || !restored) return;
        if (!navigator.onLine) {
          markOffline();
          setConnection("offline");
          retry();
          return;
        }
        busy = true;
        clearTimeout(reconnect);
        reconnect = undefined;
        // A REST snapshot and an old stream must not race to apply different versions.
        stopStream();
        try {
          const signal = AbortSignal.any([
            controller.signal,
            AbortSignal.timeout(10_000),
          ]);
          const next = await fetchSync(owner, state, signal);
          if (!active) return;
          apply(next);
          if (force || Date.now() - lastStreamAttempt >= STREAM_RETRY_INTERVAL)
            connect();
        } catch (error) {
          if (!active || controller.signal.aborted) return;
          if (
            error instanceof ApiError &&
            (error.status === 401 || error.status === 403)
          )
            clearSession();
          else {
            markOffline();
            setConnection(navigator.onLine ? "reconnecting" : "offline");
            retry();
          }
        } finally {
          busy = false;
          if (active) {
            if (pendingRefresh) {
              pendingRefresh = false;
              requestRefresh();
            }
          }
        }
      }
      function requestRefresh() {
        if (!active) return;
        if (busy || !restored) {
          pendingRefresh = true;
          return;
        }
        void synchronize(true);
      }
      async function restore() {
        const snapshot = await readSnapshot(owner);
        if (!active) return;
        if (snapshot) {
          state = {
            cursor: snapshot.cursor,
            files: snapshot.files,
          };
          setMetadata(snapshot.files);
          setSavedAt(snapshot.saved);
          setSnapshotAvailable(true);
        }
        restored = true;
        if (navigator.onLine) requestRefresh();
        else {
          setConnection("offline");
          retry();
        }
      }
      function offline() {
        stopStream();
        markOffline();
        setConnection("offline");
        retry();
      }
      function resumed() {
        if (document.visibilityState === "visible") requestRefresh();
      }
      function online() {
        requestRefresh();
      }
      const watchdog = setInterval(function checkTransport() {
        if (!active || busy || !navigator.onLine) return;
        if (
          !reconnect &&
          (!source || Date.now() - lastMessage > STREAM_TIMEOUT)
        )
          void synchronize();
      }, POLL_INTERVAL);
      window.addEventListener(ACCOUNT_INVALIDATED, requestRefresh);
      window.addEventListener("online", online);
      window.addEventListener("offline", offline);
      window.addEventListener("focus", resumed);
      document.addEventListener("visibilitychange", resumed);
      void restore();
      return function cleanup() {
        active = false;
        controller.abort();
        stopStream();
        clearTimeout(reconnect);
        clearInterval(watchdog);
        window.removeEventListener(ACCOUNT_INVALIDATED, requestRefresh);
        window.removeEventListener("online", online);
        window.removeEventListener("offline", offline);
        window.removeEventListener("focus", resumed);
        document.removeEventListener("visibilitychange", resumed);
      };
    },
    [account, clearSession, markOffline, markOnline],
  );
  return {
    metadata,
    connection,
    savedAt,
    snapshotAvailable,
  };
}
