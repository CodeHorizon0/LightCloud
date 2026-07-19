/// <reference types="vite/client" />

export interface UploadItem {
  id: string;
  file: File;
  relativePath: string;
  size: number;
  progress: number;
  status: string;
}

export const API_BASE: string =
  import.meta.env.VITE_API_BASE || "http://localhost:3000";

export function normalizePath(path: string | undefined | null): string {
  return String(path || "").replace(/^\/+/, "");
}

export function getFileName(path: string): string {
  const cleanPath = normalizePath(path);
  const parts = cleanPath.split("/");
  return parts[parts.length - 1] || "";
}

export function formatDisplayPath(path: string): string {
  const cleanPath = normalizePath(path);
  return cleanPath ? `/${cleanPath}` : "/";
}

export function getFileExtension(path: string): string {
  const name = getFileName(path).toLowerCase();
  const index = name.lastIndexOf(".");
  return index < 0 ? "" : name.slice(index + 1);
}

export function formatSizeMB(bytes: number): string {
  return (Number(bytes) / 1024 / 1024).toFixed(2);
}

export function createFingerprint(file: File, relativePath: string): string {
  const cleanPath = normalizePath(relativePath);
  return [cleanPath, file.size, file.lastModified].join("::");
}

export function createUploadItem(file: File, relativePath: string): UploadItem {
  const cleanPath = normalizePath(relativePath || file.name);
  return {
    id: createFingerprint(file, cleanPath),
    file,
    relativePath: cleanPath,
    size: file.size,
    progress: 0,
    status: "in queue",
  };
}

export function mergeUniqueItems(
  existingItems: readonly UploadItem[],
  incomingItems: readonly UploadItem[]
): UploadItem[] {
  const map = new Map<string, UploadItem>();
  for (const item of existingItems) {
    map.set(item.id, item);
  }
  for (const item of incomingItems) {
    map.set(item.id, item);
  }
  return Array.from(map.values());
}

export function chunkArray<T>(items: readonly T[], chunkSize: number): T[][] {
  const size = Math.max(1, Number(chunkSize) || 1);
  const result: T[][] = [];
  for (let i = 0; i < items.length; i += size) {
    result.push(items.slice(i, i + size) as T[]);
  }
  return result;
}

export function buildDownloadUrl(path: string): string {
  const cleanPath = normalizePath(path);
  return `${API_BASE}/download/${encodeURIComponent(cleanPath)}`;
}

export function buildPreviewUrl(path: string): string {
  const cleanPath = normalizePath(path);
  return `${API_BASE}/preview/${encodeURIComponent(cleanPath)}`;
}

export function buildDeleteRequestBody(paths: readonly string[]): { filenames: string[] } {
  const filenames: string[] = [];
  const seen = new Set<string>();
  for (const p of paths) {
    const cleanPath = normalizePath(p);
    if (cleanPath && !seen.has(cleanPath)) {
      seen.add(cleanPath);
      filenames.push(cleanPath);
    }
  }
  return { filenames };
}

export function appendUploadFiles(formData: FormData, items: readonly UploadItem[]): FormData {
  for (const item of items) {
    const filename = item.relativePath || item.file.name;
    formData.append("files", item.file, filename);
  }
  return formData;
}

function readEntries(reader: FileSystemDirectoryReader): Promise<FileSystemEntry[]> {
  return new Promise((resolve) => {
    reader.readEntries((entries) => resolve(entries));
  });
}

async function readAllDirectoryEntries(reader: FileSystemDirectoryReader): Promise<FileSystemEntry[]> {
  let entries: FileSystemEntry[] = [];
  let batch = await readEntries(reader);
  while (batch.length > 0) {
    entries = entries.concat(batch);
    batch = await readEntries(reader);
  }
  return entries;
}

function isPreviewableTextExtension(ext: string): boolean {
  const textExts = [
    "txt", "md", "json", "xml", "csv", "tsv", "log",
    "yml", "yaml", "js", "jsx", "ts", "tsx", "css",
    "scss", "sass", "less", "html", "htm", "svg",
    "py", "java", "c", "cpp", "h", "hpp", "rs",
    "go", "sh", "bash", "ini", "toml", "sql", "env",
  ];
  return textExts.includes(ext.toLowerCase());
}

function isPreviewableImageExtension(ext: string): boolean {
  const imgExts = ["png", "jpg", "jpeg", "gif", "webp", "bmp", "avif", "ico", "svg"];
  return imgExts.includes(ext.toLowerCase());
}

function isPreviewableAudioExtension(ext: string): boolean {
  const audioExts = ["mp3", "wav", "ogg", "flac", "m4a", "aac", "opus"];
  return audioExts.includes(ext.toLowerCase());
}

function isPreviewableVideoExtension(ext: string): boolean {
  const videoExts = ["mp4", "webm", "ogv", "mov", "m4v", "mkv", "avi"];
  return videoExts.includes(ext.toLowerCase());
}

export function getPreviewKind(path: string, info?: unknown): string | null {
  const mime = String(
    (info && typeof info === "object" && (
      (info as any).mime_type ||
      (info as any).mime ||
      (info as any).content_type
    )) || ""
  ).toLowerCase();
  const ext = getFileExtension(path);

  if (mime.startsWith("image/") || isPreviewableImageExtension(ext)) {
    return "image";
  }
  if (mime.startsWith("audio/") || isPreviewableAudioExtension(ext)) {
    return "audio";
  }
  if (mime.startsWith("video/") || isPreviewableVideoExtension(ext)) {
    return "video";
  }
  if (mime.includes("html") || ext === "html" || ext === "htm") {
    return "html";
  }
  if (mime.startsWith("text/") || isPreviewableTextExtension(ext)) {
    return "text";
  }
  return null;
}

export function traverseEntry(
  entry: FileSystemEntry,
  parentPath: string
): Promise<UploadItem[]> {
  if (entry.isFile) {
    return new Promise((resolve) => {
      (entry as FileSystemFileEntry).file((file) => {
        if (!file || file.size <= 0) {
          resolve([]);
          return;
        }
        resolve([createUploadItem(file, parentPath + file.name)]);
      });
    });
  }

  if (entry.isDirectory) {
    const reader = (entry as FileSystemDirectoryEntry).createReader();
    return readAllDirectoryEntries(reader).then((children) => {
      let results: UploadItem[] = [];
      return children.reduce(
        (chain, child) =>
          chain.then(() =>
            traverseEntry(child, parentPath + entry.name + "/").then((childResults) => {
              results = results.concat(childResults);
            })
          ),
        Promise.resolve()
      ).then(() => results);
    });
  }

  return Promise.resolve([]);
}

export function isNonEmptyFile(file: File | null | undefined): file is File {
  return !!file && file.size > 0;
}