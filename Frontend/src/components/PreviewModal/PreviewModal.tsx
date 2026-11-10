import { lazy, Suspense, useEffect, useId, useRef, useState } from "react";
import type { MouseEvent } from "react";

import { useAuth } from "../../auth/useAuth";
import { API_BASE } from "../../api";
import { resourcePath } from "../../utils/previewCache";
import type { PreviewResource } from "../../utils/previewCache";
import { asBlob, asJson, asText, useObjectUrl, usePreview } from "./usePreview";
import { formatBytes, getFileName } from "../../utils/storage";
import PreviewStatus from "./PreviewStatus";
import styles from "./PreviewModal.module.css";

const CodePreview = lazy(function loadCode() {
  return import("./CodePreview");
});

const MarkdownPreview = lazy(function loadMarkdown() {
  return import("./MarkdownPreview");
});

const PdfPreview = lazy(function loadPdf() {
  return import("./PdfPreview");
});

const OfficePreview = lazy(function loadOffice() {
  return import("./OfficePreview");
});
const ArchivePreview = lazy(function loadArchive() {
  return import("./ArchivePreview");
});
const KritaPreview = lazy(function loadKrita() {
  return import("./KritaPreview");
});

interface PreviewModalProps {
  resource: PreviewResource;
  mime: string;
  size: number;
  onClose: () => void;
  onDownload: () => void;
  onError: (error: unknown) => void;
}

type ContentProps = Pick<PreviewModalProps, "resource" | "onError">;

function TextContent({ resource, onError }: ContentProps) {
  const data = usePreview(resource, "", asText, onError);
  if (!data || "error" in data) return <PreviewStatus error={data?.error} />;
  if (resource.kind === "markdown")
    return <MarkdownPreview source={data.value} />;
  if (resource.language)
    return <CodePreview source={data.value} resource={resource} />;
  return <pre className={styles.previewText}>{data.value}</pre>;
}

function StructuredContent({ resource, onError }: ContentProps) {
  const data = usePreview(
    resource,
    resource.kind === "krita" ? "view=details" : "",
    asJson,
    onError,
  );
  if (!data || "error" in data) return <PreviewStatus error={data?.error} />;
  if (resource.kind === "krita")
    return (
      <KritaPreview
        resource={resource}
        details={data.value}
        onError={onError}
      />
    );
  return <ArchivePreview value={data.value} cached={data.cached} />;
}

function BinaryContent({ resource, onError }: ContentProps) {
  const { offline } = useAuth();
  const data = usePreview(resource, "", asBlob, onError);
  if (!offline && data && "error" in data && resource.kind === "image") {
    return <NetworkImage resource={resource} />;
  }
  if (!data || "error" in data) return <PreviewStatus error={data?.error} />;
  const kind = resource.kind;
  if (
    kind === "document" ||
    kind === "spreadsheet" ||
    kind === "presentation"
  ) {
    return <OfficePreview body={data.value} kind={kind} />;
  }
  return (
    <CachedMedia
      body={data.value}
      kind={kind}
      title={getFileName(resource.path)}
    />
  );
}

function CachedMedia({
  body,
  kind,
  title,
}: {
  body: Blob;
  kind: PreviewResource["kind"];
  title: string;
}) {
  const url = useObjectUrl(body);
  const [failed, setFailed] = useState(false);
  if (failed)
    return <PreviewStatus error="This image could not be displayed." />;
  if (!url) return <PreviewStatus />;
  if (kind === "pdf") return <PdfPreview url={url} />;
  return (
    <div className={styles.previewVisualShell}>
      <img
        className={styles.previewImage}
        src={url}
        alt={title}
        decoding="async"
        onError={function fail() {
          setFailed(true);
        }}
      />
    </div>
  );
}

function NetworkImage({ resource }: { resource: PreviewResource }) {
  const { offline } = useAuth();
  const [failed, setFailed] = useState(false);
  if (offline)
    return <PreviewStatus error="This image requires a connection." />;
  if (failed)
    return <PreviewStatus error="This image could not be displayed." />;
  return (
    <div className={styles.previewVisualShell}>
      <img
        className={styles.previewImage}
        src={API_BASE + resourcePath(resource)}
        alt={getFileName(resource.path)}
        crossOrigin="use-credentials"
        decoding="async"
        onError={function fail() {
          setFailed(true);
        }}
      />
    </div>
  );
}

export default function PreviewModal({
  resource,
  mime,
  size,
  onClose,
  onDownload,
  onError,
}: PreviewModalProps) {
  const { offline } = useAuth();
  const dialog = useRef<HTMLDialogElement>(null);
  const titleId = useId();
  const [mediaError, setMediaError] = useState(false);
  const { path, kind } = resource;
  const url = API_BASE + resourcePath(resource);
  const title = getFileName(path);
  const isText = kind === "text" || kind === "markdown";
  const cacheImage =
    kind === "image" && mime !== "image/svg+xml" && size <= 8 * 1024 ** 2;
  const cachePdf = kind === "pdf" && size <= 4 * 1024 ** 2;
  const isOffice =
    kind === "document" || kind === "spreadsheet" || kind === "presentation";

  useEffect(function openDialog() {
    const element = dialog.current;
    const overflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    element?.showModal();
    return function closeDialog() {
      document.body.style.overflow = overflow;
      element?.close();
    };
  }, []);

  function closeOnBackdrop(event: MouseEvent<HTMLDialogElement>) {
    if (event.target === event.currentTarget) onClose();
  }

  function failMedia() {
    setMediaError(true);
  }

  return (
    <dialog
      ref={dialog}
      className={styles.previewModal}
      aria-labelledby={titleId}
      onClick={closeOnBackdrop}
      onCancel={function cancel(event) {
        event.preventDefault();
        onClose();
      }}
    >
      <div className={styles.previewHeader}>
        <div className={styles.previewMeta}>
          <div className={styles.previewTitle} id={titleId} title={path}>
            {title}
          </div>
          <div className={styles.previewSubtitle}>
            {kind} · {formatBytes(size)}
          </div>
        </div>
        <div className={styles.previewStats}>
          <button
            type="button"
            className={styles.previewDownloadButton}
            onClick={onDownload}
            disabled={offline}
          >
            Download
          </button>
          <button
            type="button"
            className={styles.previewCloseButton}
            onClick={onClose}
            aria-label="Close preview"
          >
            <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true">
              <path
                d="M6 6l12 12M18 6L6 18"
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
                strokeLinecap="round"
              />
            </svg>
          </button>
        </div>
      </div>
      <div
        className={`${styles.previewBody} ${isText && !resource.language ? styles.previewBodyScrollable : ""}`}
      >
        {mediaError ? (
          <PreviewStatus error="The browser could not display this file. Download it to open locally." />
        ) : null}
        {kind === "image" && !cacheImage ? (
          <NetworkImage resource={resource} />
        ) : null}
        {offline &&
        (kind === "audio" ||
          kind === "video" ||
          (kind === "pdf" && !cachePdf)) ? (
          <PreviewStatus error="This preview requires a connection." />
        ) : null}
        {!offline && !mediaError && kind === "video" ? (
          <div className={styles.previewVisualShell}>
            <video
              className={styles.previewVideo}
              src={url}
              controls
              playsInline
              preload="metadata"
              crossOrigin="use-credentials"
              onError={failMedia}
            />
          </div>
        ) : null}
        {!offline && !mediaError && kind === "audio" ? (
          <div className={styles.previewAudioShell}>
            <audio
              className={styles.previewAudio}
              src={url}
              controls
              preload="metadata"
              crossOrigin="use-credentials"
              onError={failMedia}
            />
          </div>
        ) : null}
        <Suspense fallback={<PreviewStatus />}>
          {!offline && kind === "pdf" && !cachePdf ? (
            <PdfPreview url={url} />
          ) : null}
          {cacheImage || cachePdf || isOffice ? (
            <BinaryContent resource={resource} onError={onError} />
          ) : null}
          {isText ? (
            <TextContent resource={resource} onError={onError} />
          ) : null}
          {kind === "archive" || kind === "krita" ? (
            <StructuredContent resource={resource} onError={onError} />
          ) : null}
        </Suspense>
      </div>
    </dialog>
  );
}
