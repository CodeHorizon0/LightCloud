import { useEffect, useState } from "react";
import { useAuth } from "../../auth/useAuth";
import { fetchPreview } from "../../utils/previewCache";
import type { PreviewResource } from "../../utils/previewCache";

export type PreviewData<T> =
  { value: T; cached: boolean } | { error: string } | null;

export function usePreview<T>(
  resource: PreviewResource,
  variant: string,
  decode: (body: Blob) => Promise<T>,
  onError: (error: unknown) => void,
): PreviewData<T> {
  const { offline } = useAuth();
  const { account, path, revision, kind } = resource;
  const key = JSON.stringify([account, path, revision, kind, variant]);
  const [result, setResult] = useState<{
    key: string;
    data: PreviewData<T>;
  } | null>(null);
  useEffect(
    function load() {
      const controller = new AbortController();
      async function read() {
        try {
          const { body, cached } = await fetchPreview(
            { account, path, revision, kind },
            variant,
            controller.signal,
            offline,
          );
          const value = await decode(body);
          if (!controller.signal.aborted)
            setResult({ key, data: { value, cached } });
        } catch (error) {
          if (controller.signal.aborted) return;
          setResult({
            key,
            data: {
              error:
                error instanceof Error ? error.message : "Preview unavailable",
            },
          });
          onError(error);
        }
      }
      void read();
      return function cancel() {
        controller.abort();
      };
    },
    [account, path, revision, kind, variant, key, decode, onError, offline],
  );
  return result?.key === key ? result.data : null;
}

export async function asBlob(body: Blob): Promise<Blob> {
  return body;
}

export async function asText(body: Blob): Promise<string> {
  if (!body.type.startsWith("text/plain"))
    throw new Error("Unexpected preview response");
  return body.text();
}

export async function asJson(body: Blob): Promise<unknown> {
  if (!body.type.startsWith("application/json"))
    throw new Error("Unexpected preview response");
  return JSON.parse(await body.text()) as unknown;
}

export function useObjectUrl(blob: Blob): string | null {
  const [resource, setResource] = useState<{ blob: Blob; url: string } | null>(
    null,
  );
  useEffect(
    function create() {
      const objectUrl = URL.createObjectURL(blob);
      setResource({ blob, url: objectUrl });
      return function release() {
        URL.revokeObjectURL(objectUrl);
      };
    },
    [blob],
  );
  return resource?.blob === blob ? resource.url : null;
}
