import { API_BASE, ApiError, isRecord, parseJson } from "../api";
import { parseMetadata } from "./storage";
import type { FileInfo } from "./storage";

export interface SyncState {
  cursor: string;
  files: Map<string, FileInfo>;
}

export function syncEnvelope(
  value: unknown,
  account: string,
): value is Record<string, unknown> & { cursor: string } {
  return (
    isRecord(value) &&
    value.protocol === 1 &&
    value.account === account &&
    typeof value.cursor === "string" &&
    /^[0-9a-f]{64}$/.test(value.cursor)
  );
}

function files(value: unknown): Map<string, FileInfo> {
  const parsed = parseMetadata(value);
  if (
    !isRecord(value) ||
    !parsed ||
    parsed.size !== Object.keys(value).length ||
    Array.from(parsed.values()).some(function (info) {
      return !/^[0-9a-f]{24}$/.test(info.revision);
    })
  )
    throw new Error("Invalid synchronization metadata");
  return parsed;
}

export function syncSnapshot(value: unknown, account: string): SyncState {
  if (!syncEnvelope(value, account))
    throw new Error("Invalid synchronization account or version");
  return { cursor: value.cursor, files: files(value.files) };
}

export function syncPatch(
  value: unknown,
  account: string,
  previous: SyncState,
): SyncState {
  if (
    !syncEnvelope(value, account) ||
    value.from !== previous.cursor ||
    !Array.isArray(value.deleted) ||
    !value.deleted.every(function (path) {
      return typeof path === "string";
    })
  )
    throw new Error("Synchronization history changed");
  const updates = files(value.upsert);
  const next = new Map(previous.files);
  for (const path of value.deleted) next.delete(path);
  for (const [path, info] of updates) next.set(path, info);
  return { cursor: value.cursor, files: next };
}

export async function fetchSync(
  account: string,
  current: SyncState,
  signal: AbortSignal,
): Promise<SyncState> {
  const response = await fetch(`${API_BASE}/sync`, {
    credentials: "include",
    cache: "no-store",
    signal,
    headers: current.cursor ? { "If-None-Match": `"${current.cursor}"` } : {},
  });
  if (response.status === 304) {
    if (
      !current.cursor ||
      response.headers.get("X-Sync-Account") !== account ||
      response.headers.get("ETag") !== `"${current.cursor}"`
    )
      throw new Error("Invalid synchronization response");
    return current;
  }
  const data = parseJson(await response.text());
  if (!response.ok)
    throw new ApiError(
      response.status,
      data,
      response.headers.get("Retry-After"),
    );
  return syncSnapshot(data, account);
}

export function reconcileMetadata(
  previous: Map<string, FileInfo>,
  incoming: Map<string, FileInfo>,
): Map<string, FileInfo> {
  let changed = previous.size !== incoming.size;
  const next = new Map<string, FileInfo>();
  for (const [path, info] of incoming) {
    const saved = previous.get(path);
    if (
      saved &&
      saved.revision === info.revision &&
      saved.mime === info.mime &&
      saved.original_size === info.original_size &&
      saved.preview_kind === info.preview_kind &&
      saved.code_language === info.code_language &&
      saved.compression_percent === info.compression_percent
    )
      next.set(path, saved);
    else {
      changed = true;
      next.set(path, info);
    }
  }
  return changed ? next : previous;
}
