// PreviewModal.tsx
import { useEffect, useMemo, useRef, useState } from "react";
import { buildPreviewUrl, buildDownloadUrl } from "../utils/storage.js";
import styles from "./PreviewModal.module.css";
import JSZip from "jszip";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

interface PreviewData {
  kind: "image" | "audio" | "video" | "text" | "html" | "kra" | "md";
  path: string;
  title: string;
  size: number;
}

interface PreviewModalProps {
  preview: PreviewData | null;
  onClose: () => void;
}

function formatBytes(bytes: number): string {
  const value = Number(bytes) || 0;
  if (value === 0) {
    return "0 B";
  }
  const units = ["B", "KB", "MB", "GB", "TB"];
  const index = Math.min(Math.floor(Math.log(value) / Math.log(1024)), units.length - 1);
  const size = value / Math.pow(1024, index);
  return `${size.toFixed(size >= 100 ? 0 : size >= 10 ? 1 : 2)} ${units[index]}`;
}

function buildSafeSrcDoc(rawHtml: string): string {
  const csp = [
    "default-src 'none'",
    "img-src data: blob: https: http:",
    "media-src data: blob: https: http:",
    "style-src 'unsafe-inline'",
    "font-src data:",
    "connect-src 'none'",
    "script-src 'none'",
    "frame-src 'none'",
  ].join("; ");
  return [
    '<meta charset="utf-8">',
    `<meta http-equiv="Content-Security-Policy" content="${csp}">`,
    '<meta name="viewport" content="width=device-width, initial-scale=1">',
    '<style>html,body{margin:0;padding:0;background:#0b0f14;color:#e7eaf0;font-family:system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}</style>',
    rawHtml || "",
  ].join("");
}

function PreviewModal(props: PreviewModalProps) {
  const preview = props.preview;
  const onClose = props.onClose;

  const [content, setContent] = useState<string>("");
  const [loading, setLoading] = useState<boolean>(false);
  const [error, setError] = useState<string>("");
  const [kraImageUrl, setKraImageUrl] = useState<string>("");

  const mainVideoRef = useRef<HTMLVideoElement>(null);
  const backdropVideoRef = useRef<HTMLVideoElement>(null);
  const audioRef = useRef<HTMLAudioElement>(null);
  const syncFrameRef = useRef<number>(0);
  const lastSyncedTimeRef = useRef<number>(-1);

  const previewUrl = useMemo<string>(function() {
    if (!preview) {
      return "";
    }
    if (preview.kind === "kra") {
      return buildDownloadUrl(preview.path);
    }
    return buildPreviewUrl(preview.path);
  }, [preview]);

  function stopSyncLoop(): void {
    if (syncFrameRef.current) {
      cancelAnimationFrame(syncFrameRef.current);
      syncFrameRef.current = 0;
    }
  }

  function applyVideoSync(forceSeek: boolean): void {
    const mainVideo = mainVideoRef.current;
    const backdropVideo = backdropVideoRef.current;
    if (!mainVideo || !backdropVideo) {
      return;
    }
    backdropVideo.muted = true;
    backdropVideo.volume = 0;
    if (typeof mainVideo.playbackRate === "number" && backdropVideo.playbackRate !== mainVideo.playbackRate) {
      backdropVideo.playbackRate = mainVideo.playbackRate;
    }
    if (mainVideo.ended) {
      if (!backdropVideo.paused) {
        backdropVideo.pause();
      }
      try {
        backdropVideo.currentTime = mainVideo.currentTime;
      } catch (_) {
        // ignore
      }
      return;
    }
    if (mainVideo.paused) {
      if (!backdropVideo.paused) {
        backdropVideo.pause();
      }
      try {
        backdropVideo.currentTime = mainVideo.currentTime;
      } catch (_) {
        // ignore
      }
      return;
    }
    const drift = Math.abs((backdropVideo.currentTime || 0) - (mainVideo.currentTime || 0));
    const mustSeek = forceSeek || drift > 0.08 || lastSyncedTimeRef.current < 0;
    if (mustSeek) {
      try {
        backdropVideo.currentTime = mainVideo.currentTime;
      } catch (_) {
        // ignore
      }
    }
    lastSyncedTimeRef.current = mainVideo.currentTime;
    const playPromise = backdropVideo.play();
    if (playPromise && typeof playPromise.catch === "function") {
      playPromise.catch(function() {});
    }
  }

  function startSyncLoop(): void {
    stopSyncLoop();
    function tick(): void {
      const mainVideo = mainVideoRef.current;
      const backdropVideo = backdropVideoRef.current;
      if (!mainVideo || !backdropVideo) {
        syncFrameRef.current = 0;
        return;
      }
      if (preview && preview.kind === "video") {
        applyVideoSync(false);
        syncFrameRef.current = requestAnimationFrame(tick);
        return;
      }
      syncFrameRef.current = 0;
    }
    syncFrameRef.current = requestAnimationFrame(tick);
  }

  function handleMainVideoLoadedMetadata(): void {
    applyVideoSync(true);
  }

  function handleMainVideoLoadedData(): void {
    applyVideoSync(true);
  }

  function handleMainVideoPlay(): void {
    applyVideoSync(true);
    startSyncLoop();
  }

  function handleMainVideoPause(): void {
    applyVideoSync(true);
  }

  function handleMainVideoSeeking(): void {
    applyVideoSync(true);
  }

  function handleMainVideoSeeked(): void {
    applyVideoSync(true);
  }

  function handleMainVideoTimeUpdate(): void {
    applyVideoSync(false);
  }

  function handleMainVideoRateChange(): void {
    applyVideoSync(true);
  }

  useEffect(function() {
    function onKeyDown(event: KeyboardEvent): void {
      if (event.key === "Escape") {
        onClose();
      }
    }
    if (preview) {
      document.body.style.overflow = "hidden";
      window.addEventListener("keydown", onKeyDown);
    }
    return function() {
      document.body.style.overflow = "";
      window.removeEventListener("keydown", onKeyDown);
    };
  }, [preview, onClose]);

  useEffect(function() {
    let cancelled = false;
    const controller = new AbortController();

    if (kraImageUrl) {
      URL.revokeObjectURL(kraImageUrl);
      setKraImageUrl("");
    }

    if (!preview) {
      setContent("");
      setLoading(false);
      setError("");
      return function() {
        controller.abort();
      };
    }

    if (preview.kind === "kra") {
      setLoading(true);
      setError("");
      setContent("");

      fetch(previewUrl, {
        credentials: "include",
        headers: {
          'Accept': 'application/zip, application/octet-stream, */*'
        },
        signal: controller.signal,
      })
        .then(function(response) {
          if (!response.ok) {
            throw new Error(`Failed to fetch .kra: ${response.status}`);
          }
          return response.arrayBuffer();
        })
        .then(function(arrayBuffer) {
          if (cancelled) return;
          return JSZip.loadAsync(arrayBuffer);
        })
        .then(function(zip) {
          if (cancelled) return;
          if (!zip) {
            throw new Error("Failed to load zip archive");
          }
          const previewFile = zip.file("mergedimage.png");
          if (!previewFile) {
            throw new Error("No preview.png found in .kra archive");
          }
          return previewFile.async("blob");
        })
        .then(function(blob) {
          if (cancelled) return;
          if (!blob) {
            throw new Error("Failed to extract blob from preview.png");
          }
          const url = URL.createObjectURL(blob);
          setKraImageUrl(url);
          setLoading(false);
        })
        .catch(function(fetchError) {
          if (cancelled || fetchError.name === "AbortError") {
            return;
          }
          console.error(fetchError);
          setError("Failed to extract preview from .kra");
          setLoading(false);
        });

      return function() {
        cancelled = true;
        controller.abort();
      };
    }

    if (preview.kind !== "text" && preview.kind !== "html" && preview.kind !== "md") {
      setContent("");
      setLoading(false);
      setError("");
      return function() {
        controller.abort();
      };
    }

    setLoading(true);
    setError("");
    setContent("");

    fetch(previewUrl, {
      credentials: "include",
      signal: controller.signal,
    })
      .then(function(response) {
        if (!response.ok) {
          throw new Error(`Preview failed: ${response.status}`);
        }
        return response.text();
      })
      .then(function(text) {
        if (cancelled) {
          return;
        }
        setContent(text);
        setLoading(false);
      })
      .catch(function(fetchError) {
        if (cancelled || fetchError.name === "AbortError") {
          return;
        }
        console.error(fetchError);
        setError("Failed to load preview");
        setLoading(false);
      });

    return function() {
      cancelled = true;
      controller.abort();
    };
  }, [preview, previewUrl]);

  useEffect(function() {
    if (!preview || preview.kind !== "video") {
      stopSyncLoop();
      const backdropVideo = backdropVideoRef.current;
      if (backdropVideo) {
        backdropVideo.pause();
        try {
          backdropVideo.currentTime = 0;
        } catch (_) {
          // ignore
        }
      }
      return;
    }
    lastSyncedTimeRef.current = -1;
    applyVideoSync(true);
    function onVisibilityChange(): void {
      if (document.visibilityState === "visible") {
        applyVideoSync(true);
      }
    }
    document.addEventListener("visibilitychange", onVisibilityChange);
    return function() {
      document.removeEventListener("visibilitychange", onVisibilityChange);
      stopSyncLoop();
      const backdropVideo = backdropVideoRef.current;
      if (backdropVideo) {
        backdropVideo.pause();
      }
    };
  }, [preview, previewUrl]);

  useEffect(function() {
    if (!preview) return;
    if (preview.kind === "audio" && audioRef.current) {
      audioRef.current.volume = 0.5;
    }
    if (preview.kind === "video" && mainVideoRef.current) {
      mainVideoRef.current.volume = 0.5;
    }
  }, [preview, previewUrl]);

  const previewBody = useMemo<React.ReactNode>(function() {
    if (!preview) {
      return null;
    }

    if (preview.kind === "kra") {
      if (loading) {
        return <div className={styles.previewLoading}>Распаковка .kra...</div>;
      }
      if (error) {
        return <div className={styles.previewError}>{error}</div>;
      }
      if (!kraImageUrl) {
        return <div className={styles.previewLoading}>Миниатюра не найдена</div>;
      }

      return (
        <div className={styles.previewVisualShell}>
          <img
            className={styles.previewVisualBackdrop}
            src={kraImageUrl}
            alt=""
            aria-hidden="true"
            crossOrigin="use-credentials"
            loading="eager"
          />
          <img
            className={styles.previewImage}
            src={kraImageUrl}
            alt={preview.title}
            crossOrigin="use-credentials"
            loading="eager"
            decoding="async"
          />
        </div>
      );
    }

    if (preview.kind === "image") {
      return (
        <div className={styles.previewVisualShell}>
          <img
            className={styles.previewVisualBackdrop}
            src={previewUrl}
            alt=""
            aria-hidden="true"
            crossOrigin="use-credentials"
            loading="eager"
          />
          <img
            className={styles.previewImage}
            src={previewUrl}
            alt={preview.title}
            crossOrigin="use-credentials"
            loading="eager"
            decoding="async"
          />
        </div>
      );
    }

    if (preview.kind === "audio") {
      return (
        <div className={styles.previewAudioShell}>
          <audio
            ref={audioRef}
            className={styles.previewAudio}
            controls
            preload="metadata"
            src={previewUrl}
            crossOrigin="use-credentials"
          />
        </div>
      );
    }

    if (preview.kind === "video") {
      return (
        <div className={styles.previewVisualShell}>
          <video
            ref={backdropVideoRef}
            className={styles.previewVisualBackdropVideo}
            src={previewUrl}
            crossOrigin="use-credentials"
            muted
            playsInline
            preload="auto"
            aria-hidden="true"
            tabIndex={-1}
            controls={false}
          />
          <video
            ref={mainVideoRef}
            className={styles.previewVideo}
            controls
            preload="metadata"
            src={previewUrl}
            crossOrigin="use-credentials"
            playsInline
            onLoadedMetadata={handleMainVideoLoadedMetadata}
            onLoadedData={handleMainVideoLoadedData}
            onPlay={handleMainVideoPlay}
            onPause={handleMainVideoPause}
            onSeeking={handleMainVideoSeeking}
            onSeeked={handleMainVideoSeeked}
            onTimeUpdate={handleMainVideoTimeUpdate}
            onRateChange={handleMainVideoRateChange}
          />
        </div>
      );
    }

    if (preview.kind === "html") {
      if (loading) {
        return <div className={styles.previewLoading}>Loading HTML...</div>;
      }
      if (error) {
        return <div className={styles.previewError}>{error}</div>;
      }
      return (
        <iframe
          className={styles.previewFrame}
          title={preview.title}
          sandbox=""
          referrerPolicy="no-referrer"
          srcDoc={buildSafeSrcDoc(content)}
        />
      );
    }

    if (preview.kind === "md") {
      if (loading) {
        return <div className={styles.previewLoading}>Loading Markdown...</div>;
      }
      if (error) {
        return <div className={styles.previewError}>{error}</div>;
      }
      return (
        <div className={styles.previewTextScroll}>
          <div className={styles.previewMarkdown}>
            <ReactMarkdown remarkPlugins={[remarkGfm]}>{content}</ReactMarkdown>
          </div>
        </div>
      );
    }

    if (loading) {
      return <div className={styles.previewLoading}>Loading text...</div>;
    }
    if (error) {
      return <div className={styles.previewError}>{error}</div>;
    }
    return (
      <div className={styles.previewTextScroll}>
        <pre className={styles.previewText}>{content}</pre>
      </div>
    );
  }, [content, error, loading, preview, previewUrl, kraImageUrl]);

  if (!preview) {
    return null;
  }

  const previewBodyClassName = preview.kind === "text" || preview.kind === "md"
    ? `${styles.previewBody} ${styles.previewBodyScrollable}`
    : styles.previewBody;

  function handleOverlayClick(): void {
    onClose();
  }

  function handleModalClick(event: React.MouseEvent): void {
    event.stopPropagation();
  }

  return (
    <div className={styles.previewOverlay} onClick={handleOverlayClick} role="presentation">
      <div
        className={styles.previewModal}
        onClick={handleModalClick}
        role="dialog"
        aria-modal="true"
      >
        <div className={styles.previewHeader}>
          <div className={styles.previewMeta}>
            <div className={styles.previewTitle} title={preview.title}>
              {preview.title}
            </div>
          </div>
          <div className={styles.previewStats}>
            <span className={styles.previewBadge}>{preview.kind} {formatBytes(preview.size)}</span>
            <button type="button" className={styles.previewCloseButton} onClick={onClose}>+</button>
          </div>
        </div>
        <div className={previewBodyClassName}>{previewBody}</div>
      </div>
    </div>
  );
}

export default PreviewModal;