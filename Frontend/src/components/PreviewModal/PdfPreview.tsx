import { useEffect, useRef, useState } from "react";
import { getDocument, GlobalWorkerOptions } from "pdfjs-dist";
import type { PDFDocumentProxy, RenderTask } from "pdfjs-dist";
import worker from "pdfjs-dist/build/pdf.worker.min.mjs?url";
import PreviewStatus from "./PreviewStatus";
import styles from "./PreviewModal.module.css";

GlobalWorkerOptions.workerSrc = worker;

export default function PdfPreview({ url }: { url: string }) {
  const [document, setDocument] = useState<PDFDocumentProxy | null>(null);
  const [pageNumber, setPageNumber] = useState(1);
  const [zoom, setZoom] = useState(1);
  const [width, setWidth] = useState(0);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(true);
  const [hasRendered, setHasRendered] = useState(false);
  const canvas = useRef<HTMLCanvasElement>(null);
  const surface = useRef<HTMLDivElement>(null);
  const currentRender = useRef<RenderTask | null>(null);

  useEffect(function measure() {
    const element = surface.current;
    if (!element) return;
    let frame = 0;
    function update() {
      frame = 0;
      if (!element) return;
      const style = getComputedStyle(element);
      setWidth(
        Math.max(
          1,
          Math.floor(
            element.clientWidth -
              parseFloat(style.paddingLeft) -
              parseFloat(style.paddingRight),
          ),
        ),
      );
    }
    function schedule() {
      if (!frame) frame = requestAnimationFrame(update);
    }
    const observer = new ResizeObserver(schedule);
    observer.observe(element);
    update();
    return function cleanup() {
      observer.disconnect();
      cancelAnimationFrame(frame);
    };
  }, []);

  useEffect(
    function openPdf() {
      let active = true;
      setDocument(null);
      setHasRendered(false);
      setPageNumber(1);
      setZoom(1);
      setError("");
      setBusy(true);
      const loading = getDocument({
        url,
        withCredentials: true,
        enableXfa: false,
        useWasm: false,
        maxImageSize: 16000000,
        canvasMaxAreaInBytes: 16 * 1024 ** 2,
      });
      void loading.promise.then(
        function opened(file) {
          if (active) setDocument(file);
        },
        function failed() {
          if (active) {
            setError("Could not open this PDF. Download it to view locally.");
            setBusy(false);
          }
        },
      );
      return function close() {
        active = false;
        currentRender.current?.cancel();
        void loading.destroy().catch(function ignoreCancelledWorker() {});
      };
    },
    [url],
  );

  useEffect(
    function renderPage() {
      const target = canvas.current;
      if (!document || !target || !width) return;
      let active = true;
      let rendering: RenderTask | undefined;
      setError("");
      setBusy(true);
      async function draw() {
        try {
          const previous = currentRender.current;
          if (previous) {
            previous.cancel();
            try {
              await previous.promise;
            } catch {
              /* A replaced render was cancelled. */
            }
          }
          if (!active) return;
          const page = await document?.getPage(pageNumber);
          if (!active || !page || !target) return;
          const original = page.getViewport({ scale: 1 });
          if (!(
            original.width > 0 &&
            original.height > 0 &&
            Number.isFinite(original.width) &&
            Number.isFinite(original.height)
          ))
            throw new Error("Invalid page size");
          const desired =
            ((width * zoom) / original.width) *
            Math.min(window.devicePixelRatio || 1, 2);
          const scale = Math.min(
            desired,
            4096 / original.width,
            4096 / original.height,
            Math.sqrt(12000000 / (original.width * original.height)),
          );
          const viewport = page.getViewport({ scale });
          target.width = Math.max(1, Math.floor(viewport.width));
          target.height = Math.max(1, Math.floor(viewport.height));
          rendering = page.render({ canvas: target, viewport });
          currentRender.current = rendering;
          await rendering.promise;
          page.cleanup();
          if (active) setHasRendered(true);
        } catch {
          if (active)
            setError(
              "Could not render this PDF page. Download the file to view it locally.",
            );
        } finally {
          if (currentRender.current === rendering) currentRender.current = null;
          if (active) setBusy(false);
        }
      }
      void draw();
      return function cancel() {
        active = false;
        rendering?.cancel();
      };
    },
    [document, pageNumber, zoom, width],
  );

  return (
    <div className={styles.pdfPreview}>
      <div
        className={styles.pdfControls}
        role="toolbar"
        aria-label="PDF controls"
        aria-hidden={!hasRendered}
      >
        <div className={styles.controlGroup}>
          <button
            type="button"
            className={styles.previewDownloadButton}
            aria-label="Previous page"
            disabled={!document || pageNumber === 1}
            onClick={function previous() {
              setPageNumber(function (number) {
                return Math.max(1, number - 1);
              });
            }}
          >
            ‹
          </button>
          <span className={styles.pagePosition} aria-live="polite">
            {document ? `Page ${pageNumber} of ${document.numPages}` : "PDF"}
          </span>
          <button
            type="button"
            className={styles.previewDownloadButton}
            aria-label="Next page"
            disabled={!document || pageNumber === document.numPages}
            onClick={function next() {
              setPageNumber(function (number) {
                return Math.min(document?.numPages ?? 1, number + 1);
              });
            }}
          >
            ›
          </button>
        </div>
        <div className={styles.controlGroup}>
          <button
            type="button"
            className={styles.previewDownloadButton}
            aria-label="Zoom out"
            disabled={!document || zoom <= 0.5}
            onClick={function out() {
              setZoom(function (value) {
                return Math.max(0.5, value - 0.25);
              });
            }}
          >
            −
          </button>
          <button
            type="button"
            className={styles.previewDownloadButton}
            disabled={!document}
            onClick={function fit() {
              setZoom(1);
            }}
          >
            Fit width
          </button>
          <button
            type="button"
            className={styles.previewDownloadButton}
            aria-label="Zoom in"
            disabled={!document || zoom >= 3}
            onClick={function zoomIn() {
              setZoom(function (value) {
                return Math.min(3, value + 0.25);
              });
            }}
          >
            +
          </button>
          <span className={styles.zoomValue}>{Math.round(zoom * 100)}%</span>
        </div>
      </div>
      <div className={styles.pdfSurface} ref={surface} aria-busy={busy}>
        {hasRendered && error ? <PreviewStatus error={error} /> : null}
        <canvas
          ref={canvas}
          hidden={!hasRendered || Boolean(error)}
          aria-label={`PDF page ${pageNumber}`}
          className={styles.pdfCanvas}
          style={{ width: `${Math.max(1, width) * zoom}px` }}
        />
      </div>
      {!hasRendered ? <PreviewStatus error={error || undefined} /> : null}
    </div>
  );
}
