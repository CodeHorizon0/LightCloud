const API_BASE = import.meta.env.VITE_API_BASE || "http://localhost:3000";

function normalizePath(path) {
  return String(path || "").replace(/^\/+/, "");
}

function getFileName(path) {
  const cleanPath = normalizePath(path);
  const parts = cleanPath.split("/");
  return parts[parts.length - 1] || "";
}

function formatDisplayPath(path) {
  const cleanPath = normalizePath(path);
  if (!cleanPath) {
    return "/";
  }

  return `/${cleanPath}`;
}

function getFileExtension(path) {
  const name = getFileName(path).toLowerCase();
  const index = name.lastIndexOf(".");

  if (index < 0) {
    return "";
  }

  return name.slice(index + 1);
}

function formatSizeMB(bytes) {
  return (Number(bytes) / 1024 / 1024).toFixed(2);
}

function createFingerprint(file, relativePath) {
  return [normalizePath(relativePath), file.size, file.lastModified].join("::");
}

function createUploadItem(file, relativePath) {
  const cleanPath = normalizePath(relativePath || file.name);

  return {
    id: createFingerprint(file, cleanPath),
    file: file,
    relativePath: cleanPath,
    size: file.size,
    progress: 0,
    status: "в очереди",
  };
}

function mergeUniqueItems(existingItems, incomingItems) {
  const map = new Map();

  for (let i = 0; i < existingItems.length; i += 1) {
    map.set(existingItems[i].id, existingItems[i]);
  }

  for (let j = 0; j < incomingItems.length; j += 1) {
    map.set(incomingItems[j].id, incomingItems[j]);
  }

  return Array.from(map.values());
}

function chunkArray(items, chunkSize) {
  const size = Math.max(1, Number(chunkSize) || 1);
  const result = [];

  for (let index = 0; index < items.length; index += size) {
    result.push(items.slice(index, index + size));
  }

  return result;
}

function buildDownloadUrl(path) {
  const cleanPath = normalizePath(path);
  return `${API_BASE}/download/${encodeURIComponent(cleanPath)}`;
}

function buildPreviewUrl(path) {
  const cleanPath = normalizePath(path);
  return `${API_BASE}/preview/${encodeURIComponent(cleanPath)}`;
}

function buildDeleteRequestBody(paths) {
  const filenames = [];
  const seen = new Set();

  for (let i = 0; i < paths.length; i += 1) {
    const cleanPath = normalizePath(paths[i]);
    if (!cleanPath || seen.has(cleanPath)) {
      continue;
    }
    seen.add(cleanPath);
    filenames.push(cleanPath);
  }

  return { filenames: filenames };
}

function appendUploadFiles(formData, items) {
  for (let i = 0; i < items.length; i += 1) {
    const item = items[i];
    const filename = item.relativePath || item.file.name;
    formData.append("files", item.file, filename);
  }
  return formData;
}

function readEntries(reader) {
  return new Promise(function(resolve) {
    reader.readEntries(function(entries) {
      resolve(entries);
    });
  });
}

async function readAllDirectoryEntries(reader) {
  let entries = [];
  let batch = await readEntries(reader);

  while (batch.length > 0) {
    entries = entries.concat(batch);
    batch = await readEntries(reader);
  }

  return entries;
}

function isPreviewableTextExtension(ext) {
  return [
    "txt",
    "md",
    "json",
    "xml",
    "csv",
    "tsv",
    "log",
    "yml",
    "yaml",
    "js",
    "jsx",
    "ts",
    "tsx",
    "css",
    "scss",
    "sass",
    "less",
    "html",
    "htm",
    "svg",
    "py",
    "java",
    "c",
    "cpp",
    "h",
    "hpp",
    "rs",
    "go",
    "sh",
    "bash",
    "ini",
    "toml",
    "sql",
    "env",
  ].indexOf(String(ext || "").toLowerCase()) >= 0;
}

function isPreviewableImageExtension(ext) {
  return ["png", "jpg", "jpeg", "gif", "webp", "bmp", "avif", "ico", "svg"].indexOf(String(ext || "").toLowerCase()) >= 0;
}

function isPreviewableAudioExtension(ext) {
  return ["mp3", "wav", "ogg", "flac", "m4a", "aac", "opus"].indexOf(String(ext || "").toLowerCase()) >= 0;
}

function isPreviewableVideoExtension(ext) {
  return ["mp4", "webm", "ogv", "mov", "m4v", "mkv", "avi"].indexOf(String(ext || "").toLowerCase()) >= 0;
}

function getPreviewKind(path, info) {
  const mime = String(
    (info && (info.mime_type || info.mime || info.content_type)) || ""
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

function traverseEntry(entry, parentPath) {
  if (entry.isFile) {
    return new Promise(function(resolve) {
      entry.file(function(file) {
        if (!file || Number(file.size) <= 0) {
          resolve([]);
          return;
        }

        resolve([createUploadItem(file, parentPath + file.name)]);
      });
    });
  }

  if (entry.isDirectory) {
    const reader = entry.createReader();
    return readAllDirectoryEntries(reader).then(function(children) {
      let results = [];

      return children.reduce(function(chain, child) {
        return chain.then(function() {
          return traverseEntry(child, parentPath + entry.name + "/").then(function(childResults) {
            results = results.concat(childResults);
          });
        });
      }, Promise.resolve()).then(function() {
        return results;
      });
    });
  }

  return Promise.resolve([]);
}

function isNonEmptyFile(file) {
  return !!file && Number(file.size) > 0;
}

export {
  API_BASE,
  appendUploadFiles,
  buildDeleteRequestBody,
  buildDownloadUrl,
  buildPreviewUrl,
  chunkArray,
  createUploadItem,
  formatSizeMB,
  getFileExtension,
  getFileName,
  formatDisplayPath,
  getPreviewKind,
  isNonEmptyFile,
  mergeUniqueItems,
  normalizePath,
  traverseEntry,
};
