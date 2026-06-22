import { useEffect, useMemo, useRef, useState } from "react";
import { buildPreviewUrl, formatDisplayPath } from "../utils/storage.js";
import styles from "../App.module.css";

function formatBytes(bytes) {
  const value = Number(bytes) || 0;

  if (value === 0) {
    return "0 B";
  }

  const units = ["B", "KB", "MB", "GB", "TB"];
  const index = Math.min(Math.floor(Math.log(value) / Math.log(1024)), units.length - 1);
  const size = value / Math.pow(1024, index);

  return `${size.toFixed(size >= 100 ? 0 : size >= 10 ? 1 : 2)} ${units[index]}`;
}

function buildSafeSrcDoc(rawHtml) {
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

function PreviewModal(props) {
  const preview = props.preview;
  const onClose = props.onClose;

  const [content, setContent] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const mainVideoRef = useRef(null);
  const backdropVideoRef = useRef(null);
  const syncFrameRef = useRef(0);
  const lastSyncedTimeRef = useRef(-1);

  const previewUrl = useMemo(function () {
    if (!preview) {
      return "";
    }

    return buildPreviewUrl(preview.path);
  }, [preview]);

  function stopSyncLoop() {
    if (syncFrameRef.current) {
      cancelAnimationFrame(syncFrameRef.current);
      syncFrameRef.current = 0;
    }
  }

  function applyVideoSync(forceSeek) {
    const mainVideo = mainVideoRef.current;
    const backdropVideo = backdropVideoRef.current;

    if (!mainVideo || !backdropVideo) {
      return;
    }

    backdropVideo.muted = true;
    backdropVideo.defaultMuted = true;
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
      } catch (seekError) {
        void seekError;
      }

      return;
    }

    if (mainVideo.paused) {
      if (!backdropVideo.paused) {
        backdropVideo.pause();
      }

      try {
        backdropVideo.currentTime = mainVideo.currentTime;
      } catch (seekError) {
        void seekError;
      }

      return;
    }

    const drift = Math.abs((backdropVideo.currentTime || 0) - (mainVideo.currentTime || 0));
    const mustSeek = forceSeek || drift > 0.08 || lastSyncedTimeRef.current < 0;

    if (mustSeek) {
      try {
        backdropVideo.currentTime = mainVideo.currentTime;
      } catch (seekError) {
        void seekError;
      }
    }

    lastSyncedTimeRef.current = mainVideo.currentTime;

    const playPromise = backdropVideo.play();
    if (playPromise && typeof playPromise.catch === "function") {
      playPromise.catch(function () {});
    }
  }

  function startSyncLoop() {
    stopSyncLoop();

    function tick() {
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

  function handleMainVideoLoadedMetadata() {
    applyVideoSync(true);
  }

  function handleMainVideoLoadedData() {
    applyVideoSync(true);
  }

  function handleMainVideoPlay() {
    applyVideoSync(true);
    startSyncLoop();
  }

  function handleMainVideoPause() {
    applyVideoSync(true);
  }

  function handleMainVideoSeeking() {
    applyVideoSync(true);
  }

  function handleMainVideoSeeked() {
    applyVideoSync(true);
  }

  function handleMainVideoTimeUpdate() {
    applyVideoSync(false);
  }

  function handleMainVideoRateChange() {
    applyVideoSync(true);
  }

  useEffect(function () {
    function onKeyDown(event) {
      if (event.key === "Escape") {
        onClose();
      }
    }

    if (preview) {
      document.body.style.overflow = "hidden";
      window.addEventListener("keydown", onKeyDown);
    }

    return function () {
      document.body.style.overflow = "";
      window.removeEventListener("keydown", onKeyDown);
    };
  }, [preview, onClose]);

  useEffect(function () {
    let cancelled = false;
    const controller = new AbortController();

    if (!preview) {
      setContent("");
      setLoading(false);
      setError("");
      return function () {
        controller.abort();
      };
    }

    if (preview.kind !== "text" && preview.kind !== "html") {
      setContent("");
      setLoading(false);
      setError("");
      return function () {
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
      .then(function (response) {
        if (!response.ok) {
          throw new Error(`Preview failed: ${response.status}`);
        }

        return response.text();
      })
      .then(function (text) {
        if (cancelled) {
          return;
        }

        setContent(text);
        setLoading(false);
      })
      .catch(function (fetchError) {
        if (cancelled || fetchError.name === "AbortError") {
          return;
        }

        console.error(fetchError);
        setError("Не удалось загрузить предпросмотр");
        setLoading(false);
      });

    return function () {
      cancelled = true;
      controller.abort();
    };
  }, [preview, previewUrl]);

  useEffect(function () {
    if (!preview || preview.kind !== "video") {
      stopSyncLoop();

      const backdropVideo = backdropVideoRef.current;
      if (backdropVideo) {
        backdropVideo.pause();
        try {
          backdropVideo.currentTime = 0;
        } catch (seekError) {
          void seekError;
        }
      }

      return;
    }

    lastSyncedTimeRef.current = -1;
    applyVideoSync(true);

    function onVisibilityChange() {
      if (document.visibilityState === "visible") {
        applyVideoSync(true);
      }
    }

    document.addEventListener("visibilitychange", onVisibilityChange);

    return function () {
      document.removeEventListener("visibilitychange", onVisibilityChange);
      stopSyncLoop();

      const backdropVideo = backdropVideoRef.current;
      if (backdropVideo) {
        backdropVideo.pause();
      }
    };
  }, [preview, previewUrl]);

  const previewBody = useMemo(function () {
    if (!preview) {
      return null;
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
            defaultMuted
            volume={0}
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
        return <div className={styles.previewLoading}>Загрузка HTML...</div>;
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

    if (loading) {
      return <div className={styles.previewLoading}>Загрузка текста...</div>;
    }

    if (error) {
      return <div className={styles.previewError}>{error}</div>;
    }

    return (
      <div className={styles.previewTextScroll}>
        <pre className={styles.previewText}>{content}</pre>
      </div>
    );
  }, [content, error, loading, preview, previewUrl]);

  if (!preview) {
    return null;
  }

  const previewBodyClassName =
    preview.kind === "text"
      ? `${styles.previewBody} ${styles.previewBodyScrollable}`
      : styles.previewBody;

  return (
    <div className={styles.previewOverlay} onClick={onClose} role="presentation">
      <div
        className={styles.previewModal}
        onClick={function (event) {
          event.stopPropagation();
        }}
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
            <span className={styles.previewBadge}>{preview.kind}</span>
            <span className={styles.previewBadge}>{formatBytes(preview.size)}</span>
          </div>

          <button type="button" className={styles.previewCloseButton} onClick={onClose}>
            Закрыть
          </button>
        </div>

        <div className={previewBodyClassName}>{previewBody}</div>
      </div>
    </div>
  );
}

export default PreviewModal;