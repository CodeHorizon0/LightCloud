import { API_BASE, apiRequest, previewPath } from "../api";
import { readSnapshot, savedSession } from "./offlineStore";
import type { PreviewKind } from "./storage";

const MIB = 1024 ** 2;
const MAX_ITEM = 24 * MIB;
const MAX_TOTAL = 96 * MIB;
const MAX_ENTRIES = 96;
const TTL = 24 * 60 * 60 * 1000;
const STORE = "previews";

export interface PreviewResource {
  account: string;
  path: string;
  revision: string;
  kind: PreviewKind;
  language?: string | null;
}

interface CacheEntry {
  key: string;
  owner: string;
  path: string;
  revision: string;
  body: Blob;
  saved: number;
  touched: number;
}

let database: Promise<IDBDatabase> | undefined;
let generation = 0;

function openCache(): Promise<IDBDatabase> {
  if (database) return database;

  const opening = new Promise<IDBDatabase>(function (resolve, reject) {
    const request = indexedDB.open("LightCloudPreview", 1);
    let blocked = false;
    request.onupgradeneeded = function create() {
      request.result.createObjectStore(STORE, { keyPath: "key" });
    };
    request.onsuccess = function opened() {
      const connection = request.result;
      if (blocked) {
        connection.close();
        return;
      }
      connection.onversionchange = function release() {
        connection.close();
        if (database === opening) database = undefined;
      };
      resolve(connection);
    };
    request.onerror = function failed() {
      reject(request.error);
    };
    request.onblocked = function unavailable() {
      blocked = true;
      reject(new Error("Preview cache is busy"));
    };
  });
  database = opening;
  void opening.catch(function allowRetry() {
    if (database === opening) database = undefined;
  });
  return opening;
}

function ownerKey(account: string): string {
  return JSON.stringify([API_BASE, account]);
}

async function readEntry(key: string): Promise<CacheEntry | undefined> {
  try {
    const db = await openCache();
    return await new Promise(function (resolve, reject) {
      const store = db.transaction(STORE, "readonly").objectStore(STORE);
      const request = store.get(key);
      request.onsuccess = function found() {
        const entry = request.result as CacheEntry | undefined;
        resolve(entry && Date.now() - entry.saved < TTL ? entry : undefined);
      };
      request.onerror = function failed() {
        reject(request.error);
      };
    });
  } catch {
    return undefined;
  }
}

async function writeTransaction(
  update: (store: IDBObjectStore) => void,
): Promise<boolean> {
  try {
    const db = await openCache();
    await new Promise<void>(function (resolve, reject) {
      const transaction = db.transaction(STORE, "readwrite");
      transaction.oncomplete = function committed() {
        resolve();
      };
      transaction.onabort = function aborted() {
        reject(transaction.error);
      };
      update(transaction.objectStore(STORE));
    });
    return true;
  } catch {
    // The preview remains usable if local storage is unavailable or full.
    return false;
  }
}

function editEntries(
  edit: (store: IDBObjectStore, rows: CacheEntry[]) => void,
): Promise<boolean> {
  return writeTransaction(function select(store) {
    const request = store.getAll() as IDBRequest<CacheEntry[]>;
    request.onsuccess = function read() {
      edit(store, request.result);
    };
  });
}

function touchEntry(key: string, version: number): void {
  void writeTransaction(function select(store) {
    const request = store.get(key) as IDBRequest<CacheEntry | undefined>;
    request.onsuccess = function touch() {
      const entry = request.result;
      if (entry && version === generation && Date.now() - entry.saved < TTL) {
        store.put({ ...entry, touched: Date.now() });
      }
    };
  });
}

function writeEntry(entry: CacheEntry, version: number): void {
  void editEntries(function save(store, entries) {
    if (version !== generation) return;
    const now = Date.now();
    const candidates = entries.filter(function keep(previous) {
      if (previous.key === entry.key) return false;
      if (now - previous.saved >= TTL) {
        store.delete(previous.key);
        return false;
      }
      return true;
    });
    candidates.sort(function newest(a, b) {
      return b.touched - a.touched;
    });
    let bytes = entry.body.size;
    let count = 1;
    for (const row of candidates) {
      if (count >= MAX_ENTRIES || bytes + row.body.size > MAX_TOTAL) {
        store.delete(row.key);
      } else {
        bytes += row.body.size;
        count += 1;
      }
    }
    store.put(entry);
  });
}

export function clearPreviewCache(account: string): Promise<boolean> {
  generation += 1;
  window.dispatchEvent(
    new CustomEvent("lightcloud:clear-previews", { detail: account }),
  );
  const owner = ownerKey(account);
  return editEntries(function clear(store, entries) {
    for (const entry of entries)
      if (entry.owner === owner) store.delete(entry.key);
  });
}

export function prunePreviewCache(
  account: string,
  files: ReadonlyMap<string, { revision: string }>,
): void {
  const owner = ownerKey(account);
  void editEntries(function removeStale(store, entries) {
    const now = Date.now();
    for (const entry of entries) {
      if (
        now - entry.saved >= TTL ||
        (entry.owner === owner &&
          files.get(entry.path)?.revision !== entry.revision)
      ) {
        store.delete(entry.key);
      }
    }
  });
}

export function resourcePath(resource: PreviewResource, variant = ""): string {
  const params = new URLSearchParams(variant);
  params.set("rev", resource.revision);
  return `${previewPath(resource.path)}?${params}`;
}

async function checkResponse(
  response: Response,
  resource: PreviewResource,
): Promise<void> {
  if (
    response.headers.get("X-Preview-Account") !== resource.account ||
    response.headers.get("X-File-Revision") !== resource.revision ||
    response.headers.get("X-Preview-Kind") !== resource.kind
  ) {
    await response.body?.cancel();
    throw new Error("This preview changed. Reopen the file.");
  }
}

export async function fetchPreview(
  resource: PreviewResource,
  variant: string,
  signal: AbortSignal,
  offline = false,
): Promise<{ body: Blob; cached: boolean }> {
  const owner = ownerKey(resource.account);
  const key = JSON.stringify([
    owner,
    resource.path,
    resource.revision,
    resource.kind,
    variant,
  ]);
  const version = generation;
  const url = resourcePath(resource, variant);
  const hit = await readEntry(key);
  signal.throwIfAborted();
  async function cachedOffline(): Promise<{ body: Blob; cached: boolean }> {
    const snapshot = await readSnapshot(resource.account);
    signal.throwIfAborted();
    const info = snapshot?.files.get(resource.path);
    if (version !== generation || savedSession()?.user.id !== resource.account)
      throw new Error("Preview session changed.");
    if (
      !hit ||
      info?.revision !== resource.revision ||
      info.preview_kind !== resource.kind
    )
      throw new Error(
        "This preview is not saved offline. Open it while connected first.",
      );
    touchEntry(key, version);
    return { body: hit.body, cached: true };
  }
  if (offline || !navigator.onLine) return cachedOffline();
  if (hit) {
    try {
      await checkResponse(
        await apiRequest(url, { method: "HEAD", cache: "no-store", signal }),
        resource,
      );
    } catch (error) {
      if (error instanceof TypeError) return cachedOffline();
      throw error;
    }
    signal.throwIfAborted();
    if (version !== generation) throw new Error("Preview session changed.");
    touchEntry(key, version);
    return { body: hit.body, cached: true };
  }
  const response = await apiRequest(url, { cache: "no-store", signal });
  await checkResponse(response, resource);
  if (
    resource.kind === "image" &&
    (response.headers.get("X-Preview-Quality") === null ||
      response.headers.get("Content-Type") !== "image/jpeg")
  ) {
    await response.body?.cancel();
    throw new Error("Image requires the original preview stream");
  }
  const body = await response.blob();
  signal.throwIfAborted();
  if (version !== generation) throw new Error("Preview session changed.");
  if (body.size <= MAX_ITEM) {
    const now = Date.now();
    writeEntry(
      {
        key,
        owner,
        path: resource.path,
        revision: resource.revision,
        body,
        saved: now,
        touched: now,
      },
      version,
    );
  }
  return { body, cached: false };
}
