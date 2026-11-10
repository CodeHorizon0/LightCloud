import { isRecord } from "../api";

export type PreviewKind =
  | "image"
  | "audio"
  | "video"
  | "text"
  | "markdown"
  | "pdf"
  | "document"
  | "spreadsheet"
  | "presentation"
  | "krita"
  | "archive";

export interface FileInfo {
  original_size: number;
  compression_percent: number | null;
  preview_kind: PreviewKind | null;
  revision: string;
  mime: string;
  code_language: string | null;
}

export type Entry = [string, FileInfo];

export interface UploadLimits {
  max_file_size: number;
  max_batch_size: number;
  max_upload_files: number;
  max_filename_depth: number;
}

export interface UploadItem {
  id: string;
  file: File;
  relativePath: string;
  size: number;
  progress: number;
  baseRevision?: string | null;
  status: "in queue" | "uploading" | "processing" | "error" | "conflict";
}

const previewKinds = new Set<unknown>([
  "image",
  "audio",
  "video",
  "text",
  "markdown",
  "pdf",
  "document",
  "spreadsheet",
  "presentation",
  "krita",
  "archive",
]);
const encoder = new TextEncoder();

function previewKind(value: unknown): PreviewKind | null {
  return previewKinds.has(value) ? (value as PreviewKind) : null;
}

export function parseMetadata(value: unknown): Map<string, FileInfo> | null {
  if (!isRecord(value)) return null;
  const metadata = new Map<string, FileInfo>();
  for (const [name, item] of Object.entries(value)) {
    if (
      !isRecord(item) ||
      typeof item.original_size !== "number" ||
      !Number.isSafeInteger(item.original_size) ||
      item.original_size < 0
    )
      continue;
    metadata.set(name, {
      original_size: item.original_size,
      compression_percent:
        typeof item.compression_percent === "number" &&
        Number.isFinite(item.compression_percent)
          ? item.compression_percent
          : null,
      preview_kind: previewKind(item.preview_kind),
      code_language:
        typeof item.code_language === "string" && item.code_language.length < 32
          ? item.code_language
          : null,
      mime: typeof item.mime === "string" ? item.mime : "",
      revision: typeof item.revision === "string" ? item.revision : "",
    });
  }
  return metadata;
}

function positiveInteger(value: unknown): value is number {
  return typeof value === "number" && Number.isSafeInteger(value) && value > 0;
}

export function parseLimits(value: unknown): UploadLimits {
  if (
    !isRecord(value) ||
    !positiveInteger(value.max_file_size) ||
    !positiveInteger(value.max_batch_size) ||
    !positiveInteger(value.max_upload_files) ||
    !positiveInteger(value.max_filename_depth)
  )
    throw new Error("Invalid upload limits from server");
  return {
    max_file_size: value.max_file_size,
    max_batch_size: value.max_batch_size,
    max_upload_files: value.max_upload_files,
    max_filename_depth: value.max_filename_depth,
  };
}

export function formatDisplayPath(path: string): string {
  return `/${path}`;
}

export function getFileName(path: string): string {
  return path.split("/").at(-1) ?? path;
}

export function formatSizeMB(bytes: number): string {
  return (bytes / 1024 ** 2).toFixed(2);
}

export function formatBytes(bytes: number): string {
  if (bytes === 0) return "0 B";
  const units = ["B", "KB", "MB", "GB", "TB"];
  const index = Math.min(
    Math.floor(Math.log(bytes) / Math.log(1024)),
    units.length - 1,
  );
  const value = bytes / 1024 ** index;
  return `${value.toFixed(value >= 100 || index === 0 ? 0 : value >= 10 ? 1 : 2)} ${units[index]}`;
}

export function createUploadItem(file: File, relativePath: string): UploadItem {
  const path = relativePath.replaceAll("\\", "/").trim();
  const normalized = path
    .split("/")
    .filter(function (part) {
      return part && part !== ".";
    })
    .join("/");
  const relative = path.startsWith("/")
    ? `/${normalized}`
    : normalized || "file";
  return {
    id: relative,
    file,
    relativePath: relative,
    size: file.size,
    progress: 0,
    status: "in queue",
  };
}

export function uploadIssue(
  item: UploadItem,
  limits: UploadLimits,
): string | null {
  if (item.size > Math.min(limits.max_batch_size, limits.max_file_size))
    return "File exceeds the upload size limit";
  const path = item.relativePath;
  const parts = path.split("/");
  if (
    path.startsWith("/") ||
    parts.includes("..") ||
    Array.from(path).some(function (character) {
      const code = character.charCodeAt(0);
      return character === ":" || code < 32 || (code >= 127 && code <= 159);
    })
  )
    return "Invalid filename";
  if (
    parts.length > limits.max_filename_depth ||
    encoder.encode(path).length > 4096 ||
    parts.some(function (part) {
      return encoder.encode(part).length > 255;
    })
  ) {
    return "Filename is too long or nested too deep";
  }
  return null;
}

export function splitBatches(
  items: UploadItem[],
  limits: UploadLimits,
): UploadItem[][] {
  const batches: UploadItem[][] = [];
  let batch: UploadItem[] = [];
  let size = 0;
  for (const item of items) {
    if (
      batch.length === limits.max_upload_files ||
      size + item.size > limits.max_batch_size
    ) {
      batches.push(batch);
      batch = [];
      size = 0;
    }
    batch.push(item);
    size += item.size;
  }
  if (batch.length > 0) batches.push(batch);
  return batches;
}

function readEntries(
  reader: FileSystemDirectoryReader,
): Promise<FileSystemEntry[]> {
  return new Promise(function (resolve, reject) {
    reader.readEntries(resolve, reject);
  });
}

async function readEntry(
  entry: FileSystemEntry,
  parent: string,
  items: UploadItem[],
): Promise<void> {
  if (entry.isFile) {
    const file = await new Promise<File>(function (resolve, reject) {
      (entry as FileSystemFileEntry).file(resolve, reject);
    });
    items.push(createUploadItem(file, parent + file.name));
  } else if (entry.isDirectory) {
    const reader = (entry as FileSystemDirectoryEntry).createReader();
    let entries = await readEntries(reader);
    while (entries.length > 0) {
      for (const child of entries)
        await readEntry(child, `${parent}${entry.name}/`, items);
      entries = await readEntries(reader);
    }
  }
}

export async function droppedFiles(
  transfer: DataTransfer,
): Promise<UploadItem[]> {
  const items: UploadItem[] = [];
  const pending: Array<FileSystemEntry | File> = [];
  for (const item of Array.from(transfer.items)) {
    if (item.kind !== "file") continue;
    const file = item.webkitGetAsEntry?.() ?? item.getAsFile();
    if (file) pending.push(file);
  }
  if (!pending.length) pending.push(...Array.from(transfer.files));
  for (const file of pending) {
    if (file instanceof File)
      items.push(createUploadItem(file, file.webkitRelativePath || file.name));
    else await readEntry(file, "", items);
  }
  return items;
}
