export const API_BASE = (import.meta.env.VITE_API_BASE || "/api").replace(
  /\/+$/,
  "",
);

export function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

export function parseJson(text: string): unknown {
  try {
    return JSON.parse(text) as unknown;
  } catch {
    return null;
  }
}

export class ApiError extends Error {
  readonly code: string | null;
  constructor(
    readonly status: number,
    payload: unknown,
    readonly retryAfter: string | null = null,
  ) {
    super(errorMessage(payload, status));
    this.name = "ApiError";
    this.code =
      isRecord(payload) && typeof payload.code === "string"
        ? payload.code
        : null;
  }
}

function errorMessage(payload: unknown, status: number): string {
  if (isRecord(payload)) {
    const detail = payload.detail ?? payload.message ?? payload.msg;
    if (typeof detail === "string") return detail;
    if (
      Array.isArray(detail) &&
      isRecord(detail[0]) &&
      typeof detail[0].msg === "string"
    ) {
      return detail[0].msg;
    }
  }
  return `HTTP ${status}`;
}

export async function apiRequest(
  path: string,
  options?: RequestInit,
): Promise<Response> {
  const response = await fetch(API_BASE + path, {
    ...options,
    credentials: "include",
  });
  if (!response.ok) {
    const payload =
      options?.method === "HEAD" ? null : parseJson(await response.text());
    throw new ApiError(
      response.status,
      payload,
      response.headers.get("Retry-After"),
    );
  }
  return response;
}

export async function requestJson(
  path: string,
  options?: RequestInit,
): Promise<unknown> {
  const headers = new Headers(options?.headers);
  headers.set("Accept", "application/json");
  if (options?.body) headers.set("Content-Type", "application/json");
  const response = await apiRequest(path, { ...options, headers });
  return parseJson(await response.text());
}

function isStringArray(value: unknown): value is string[] {
  return (
    Array.isArray(value) &&
    value.every(function isString(item) {
      return typeof item === "string";
    })
  );
}

export async function deleteFileBatch(
  filenames: string[],
  revisions: Record<string, string | null>,
  signal?: AbortSignal,
) {
  const result = await requestJson("/sync/delete", {
    method: "DELETE",
    signal,
    body: JSON.stringify({ filenames, revisions }),
  });
  if (
    !isRecord(result) ||
    !isStringArray(result.deleted) ||
    !isStringArray(result.missing)
  ) {
    throw new Error("Invalid delete response");
  }
  return { deleted: result.deleted, missing: result.missing };
}

function filePath(path: string): string {
  return path.split("/").map(encodeURIComponent).join("/");
}

export function previewPath(path: string): string {
  return `/preview/${filePath(path)}`;
}

export async function downloadFile(
  path: string,
  signal?: AbortSignal,
): Promise<void> {
  const endpoint = `/download/${filePath(path)}`;
  await apiRequest(endpoint, { method: "HEAD", signal });
  signal?.throwIfAborted();

  const link = document.createElement("a");
  link.href = API_BASE + endpoint;
  link.download = path.split("/").at(-1) || "file";
  document.body.append(link);
  link.click();
  link.remove();
}
