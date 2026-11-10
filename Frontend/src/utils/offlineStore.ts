import { API_BASE, isRecord } from "../api";
import { parseUser } from "../auth/user";
import type { User } from "../auth/user";
import { parseMetadata } from "./storage";
import type { FileInfo } from "./storage";

export const OFFLINE_TTL = 24 * 60 * 60 * 1000;
export const SESSION_KEY = `LightCloud.session:${API_BASE}`;
interface SavedSession {
  user: User;
  epoch: string;
  verified: number;
}
interface Snapshot {
  key: string;
  epoch: string;
  saved: number;
  files: Record<string, FileInfo>;
  cursor?: string;
}
let memory: SavedSession | null = null;
let signedOut = false;
let database: Promise<IDBDatabase> | undefined;

export function savedSession(): SavedSession | null {
  try {
    const raw: unknown = JSON.parse(
      localStorage.getItem(SESSION_KEY) || "null",
    );
    signedOut = raw === false;
    if (
      isRecord(raw) &&
      isRecord(raw.user) &&
      typeof raw.user.id === "string" &&
      typeof raw.user.username === "string" &&
      typeof raw.epoch === "string" &&
      typeof raw.verified === "number"
    ) {
      const user = parseUser(raw.user);
      memory = user ? { user, epoch: raw.epoch, verified: raw.verified } : null;
      if (
        memory &&
        Object.keys(raw.user).some(function (key) {
          return key !== "id" && key !== "username";
        })
      )
        localStorage.setItem(SESSION_KEY, JSON.stringify(memory));
    } else memory = null;
  } catch {
    /* Storage can be disabled. */
  }
  if (
    !memory ||
    Date.now() - memory.verified >= OFFLINE_TTL ||
    memory.verified > Date.now()
  )
    return null;
  return memory;
}

export function isSignedOut(): boolean {
  savedSession();
  return signedOut;
}

export function rememberSession(user: User): void {
  const previous = savedSession();
  memory = {
    user,
    epoch: previous?.user.id === user.id ? previous.epoch : crypto.randomUUID(),
    verified: Date.now(),
  };
  signedOut = false;
  try {
    localStorage.setItem(SESSION_KEY, JSON.stringify(memory));
  } catch {
    /* Online access still works. */
  }
}

export function allowSession(): void {
  memory = null;
  signedOut = false;
  try {
    localStorage.removeItem(SESSION_KEY);
  } catch {
    /* Storage can be disabled. */
  }
}

export function forgetSession(): string | undefined {
  const account = savedSession()?.user.id ?? memory?.user.id;
  memory = null;
  signedOut = true;
  try {
    localStorage.setItem(SESSION_KEY, "false");
  } catch {
    /* Keep the in-memory tombstone. */
  }
  if (account) void clearSnapshot(account);
  return account;
}

function openSnapshots(): Promise<IDBDatabase> {
  if (database) return database;
  const opening = new Promise<IDBDatabase>(function (resolve, reject) {
    const request = indexedDB.open("LightCloudOffline", 2);
    let blocked = false;
    request.onupgradeneeded = function () {
      if (!request.result.objectStoreNames.contains("snapshots")) {
        request.result.createObjectStore("snapshots", { keyPath: "key" });
        return;
      }
      const store = request.transaction?.objectStore("snapshots");
      if (!store) return;
      const cursor = store.openCursor();
      cursor.onsuccess = function cleanOldCache() {
        const row = cursor.result;
        if (!row) return;
        const value: unknown = row.value;
        if (isRecord(value) && "profile" in value) {
          delete value.profile;
          value.cursor = "";
          row.update(value);
        }
        row.continue();
      };
    };
    request.onsuccess = function () {
      const db = request.result;
      if (blocked) {
        db.close();
        return;
      }
      db.onversionchange = function () {
        db.close();
        database = undefined;
      };
      resolve(db);
    };
    request.onerror = function () {
      reject(request.error);
    };
    request.onblocked = function () {
      blocked = true;
      reject(new Error("Offline storage is busy"));
    };
  });
  database = opening;
  void opening.catch(function () {
    if (database === opening) database = undefined;
  });
  return opening;
}

function snapshotKey(account: string): string {
  return JSON.stringify([API_BASE, account]);
}

export async function saveSnapshot(
  account: string,
  files: ReadonlyMap<string, FileInfo>,
  cursor = "",
): Promise<boolean> {
  const session = savedSession();
  if (!session || session.user.id !== account) return false;
  try {
    const db = await openSnapshots();
    if (savedSession()?.epoch !== session.epoch) return false;
    await new Promise<void>(function (resolve, reject) {
      const tx = db.transaction("snapshots", "readwrite");
      tx.oncomplete = function () {
        resolve();
      };
      tx.onabort = function () {
        reject(tx.error);
      };
      tx.objectStore("snapshots").put({
        key: snapshotKey(account),
        epoch: session.epoch,
        cursor,
        saved: Date.now(),
        files: Object.fromEntries(files),
      } satisfies Snapshot);
    });
    return true;
  } catch {
    return false;
  }
}

export async function readSnapshot(account: string): Promise<{
  files: Map<string, FileInfo>;
  saved: number;
  cursor: string;
} | null> {
  const session = savedSession();
  if (!session || session.user.id !== account) return null;
  try {
    const db = await openSnapshots();
    const row = await new Promise<Snapshot | undefined>(function (
      resolve,
      reject,
    ) {
      const request = db
        .transaction("snapshots")
        .objectStore("snapshots")
        .get(snapshotKey(account)) as IDBRequest<Snapshot | undefined>;
      request.onsuccess = function () {
        resolve(request.result);
      };
      request.onerror = function () {
        reject(request.error);
      };
    });
    if (
      !row ||
      row.epoch !== session.epoch ||
      savedSession()?.epoch !== session.epoch ||
      Date.now() - row.saved >= OFFLINE_TTL
    )
      return null;
    const files = parseMetadata(row.files);
    return files
      ? {
          files,
          saved: row.saved,
          cursor:
            typeof row.cursor === "string" && /^[0-9a-f]{64}$/.test(row.cursor)
              ? row.cursor
              : "",
        }
      : null;
  } catch {
    return null;
  }
}

export async function clearSnapshot(account: string): Promise<void> {
  try {
    const db = await openSnapshots();
    await new Promise<void>(function (resolve, reject) {
      const tx = db.transaction("snapshots", "readwrite");
      tx.objectStore("snapshots").delete(snapshotKey(account));
      tx.oncomplete = function () {
        resolve();
      };
      tx.onabort = function () {
        reject(tx.error);
      };
    });
  } catch {
    /* Session tombstones also deny access to retained data. */
  }
}
