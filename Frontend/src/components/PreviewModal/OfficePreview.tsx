import { useEffect, useRef, useState } from "react";
import type { PreviewKind } from "../../utils/storage";
import PreviewStatus from "./PreviewStatus";
import styles from "./AdvancedPreview.module.css";

type OfficeKind = Extract<
  PreviewKind,
  "document" | "spreadsheet" | "presentation"
>;

interface Viewer {
  destroy(): void;
  zoomIn(): void | Promise<void>;
  zoomOut(): void | Promise<void>;
  fitPage(): void | Promise<void>;
  fitWidth(): void | Promise<void>;
  setScale(scale: number): void | Promise<void>;
}

interface Navigation {
  index: number;
  count: number;
  complete: boolean;
}

const resources = {
  maxArchiveEntries: 4096,
  maxArchiveEntryBytes: 24 * 1024 ** 2,
  maxTotalInflatedBytes: 96 * 1024 ** 2,
};

export default function OfficePreview({
  body,
  kind,
}: {
  body: Blob;
  kind: OfficeKind;
}) {
  const viewport = useRef<HTMLDivElement>(null);
  const viewer = useRef<Viewer | null>(null);
  const fitMode = useRef<"width" | "page" | null>(
    kind === "document" ? "width" : kind === "presentation" ? "page" : null,
  );
  const mounted = useRef(false);
  const actionBusy = useRef(false);
  const [busy, setBusy] = useState(false);
  const move = useRef<((index: number) => Promise<void>) | null>(null);
  const [navigation, setNavigation] = useState<Navigation>({
    index: 0,
    count: 0,
    complete: false,
  });
  const [sheets, setSheets] = useState<string[]>([]);
  const [ready, setReady] = useState(false);
  const [error, setError] = useState("");

  useEffect(
    function renderOffice() {
      const host = viewport.current;
      if (!host) return;
      mounted.current = true;
      setReady(false);
      setError("");
      fitMode.current =
        kind === "document" ? "width" : kind === "presentation" ? "page" : null;
      const mount = document.createElement("div");
      mount.className = styles.officeMount;
      const canvas = document.createElement("canvas");
      canvas.setAttribute("aria-label", "Office preview canvas");
      if (kind === "spreadsheet") {
        canvas.style.width = "100%";
        canvas.style.height = "100%";
      }
      mount.append(canvas);
      host.replaceChildren(mount);
      let active = true;

      function failure(error: unknown) {
        if (active)
          setError(
            error instanceof Error
              ? error.message
              : "This Office file could not be rendered.",
          );
      }

      function update(index: number, count: number, complete = true) {
        if (active) setNavigation({ index, count, complete });
      }

      const options = {
        mode:
          typeof OffscreenCanvas === "function"
            ? ("worker" as const)
            : ("main" as const),
        enableHyperlinks: false,
        resourceLimits: resources,
        onError: failure,
        zoomMax: 2,
      };

      async function open() {
        try {
          const bytes = await body.arrayBuffer();
          if (!active || !host) return;
          if (kind === "document") {
            const { DocxViewer } = await import("@silurus/ooxml/docx");
            if (!active) return;
            const document = new DocxViewer(canvas, {
              ...options,
              container: mount,
              onPageChange: update,
              enableTextSelection: true,
            });
            viewer.current = document;
            move.current = document.goToPage.bind(document);
            await document.load(bytes);
            if (active) await document.fitWidth();
          } else if (kind === "presentation") {
            const { PptxViewer } = await import("@silurus/ooxml/pptx");
            if (!active) return;
            const deck = new PptxViewer(canvas, {
              ...options,
              onSlideChange: update,
              enableMediaPlayback: false,
            });
            viewer.current = deck;
            move.current = deck.goToSlide.bind(deck);
            await deck.load(bytes);
            if (active) await deck.fitPage();
          } else {
            const { XlsxSheetViewer } = await import("@silurus/ooxml/xlsx");
            if (!active) return;
            const sheet = new XlsxSheetViewer(canvas, {
              ...options,
              onSheetChange: update,
              onReady(names) {
                if (active) setSheets(names);
              },
            });
            viewer.current = sheet;
            move.current = sheet.goToSheet.bind(sheet);
            const format = body.type.startsWith("text/csv")
              ? "csv"
              : body.type.startsWith("text/tab-separated-values")
                ? "tsv"
                : "xlsx";
            await sheet.load(bytes, { format });
            if (active) {
              setSheets(sheet.sheetNames);
              update(sheet.sheetIndex, sheet.sheetCount);
            }
          }
          if (active) setReady(true);
        } catch (error) {
          failure(error);
        }
      }

      void open();
      return function close() {
        active = false;
        mounted.current = false;
        viewer.current?.destroy();
        viewer.current = null;
        move.current = null;
        mount.remove();
      };
    },
    [body, kind],
  );

  useEffect(
    function resizeViewer() {
      const element = viewport.current;
      if (!ready || !element) return;
      let active = true;
      let timeout = 0;
      let previousWidth = element.clientWidth;
      let previousHeight = element.clientHeight;
      async function fit() {
        if (!active || !fitMode.current || !viewer.current) return;
        if (actionBusy.current) {
          timeout = window.setTimeout(function retry() {
            void fit();
          }, 100);
          return;
        }
        actionBusy.current = true;
        try {
          if (fitMode.current === "width") await viewer.current.fitWidth();
          else await viewer.current.fitPage();
        } catch (failure) {
          if (active)
            setError(
              failure instanceof Error
                ? failure.message
                : "Could not resize preview.",
            );
        } finally {
          actionBusy.current = false;
        }
      }
      const observer = new ResizeObserver(function resize() {
        if (
          element.clientWidth === previousWidth &&
          element.clientHeight === previousHeight
        )
          return;
        previousWidth = element.clientWidth;
        previousHeight = element.clientHeight;
        clearTimeout(timeout);
        timeout = window.setTimeout(function update() {
          void fit();
        }, 100);
      });
      observer.observe(element);
      return function cleanup() {
        active = false;
        observer.disconnect();
        clearTimeout(timeout);
      };
    },
    [ready],
  );

  async function action(control: () => void | Promise<void>) {
    if (actionBusy.current || !mounted.current) return;
    actionBusy.current = true;
    setBusy(true);
    try {
      await control();
    } catch (failure) {
      if (mounted.current)
        setError(
          failure instanceof Error ? failure.message : "Rendering failed.",
        );
    } finally {
      actionBusy.current = false;
      if (mounted.current) setBusy(false);
    }
  }

  async function navigate(index: number) {
    await action(async function change() {
      await move.current?.(index);
      if (fitMode.current === "width") await viewer.current?.fitWidth();
      else if (fitMode.current === "page") await viewer.current?.fitPage();
    });
  }

  const unit = kind === "document" ? "Page" : "Slide";
  const disabled = !ready || busy;
  return (
    <div
      className={`${styles.office} ${kind === "spreadsheet" ? styles.sheet : ""}`}
    >
      <div
        className={styles.toolbar}
        role="toolbar"
        aria-label="Office preview controls"
        aria-hidden={!ready}
      >
        <div className={styles.controlGroup}>
          {kind === "spreadsheet" && sheets.length ? (
            <select
              aria-label="Worksheet"
              value={navigation.index}
              disabled={disabled}
              onChange={function select(event) {
                void navigate(Number(event.currentTarget.value));
              }}
            >
              {sheets.map(function name(sheet, index) {
                return (
                  <option key={index} value={index}>
                    {sheet}
                  </option>
                );
              })}
            </select>
          ) : kind !== "spreadsheet" ? (
            <>
              <button
                type="button"
                aria-label={`Previous ${unit.toLowerCase()}`}
                disabled={disabled || navigation.index <= 0}
                onClick={function previous() {
                  void navigate(navigation.index - 1);
                }}
              >
                ‹
              </button>
              <span className={styles.pagePosition} aria-live="polite">
                {unit} {navigation.count ? navigation.index + 1 : "-"} of{" "}
                {navigation.count || "-"}
                {navigation.complete ? "" : "+"}
              </span>
              <button
                type="button"
                aria-label={`Next ${unit.toLowerCase()}`}
                disabled={disabled || navigation.index + 1 >= navigation.count}
                onClick={function next() {
                  void navigate(navigation.index + 1);
                }}
              >
                ›
              </button>
            </>
          ) : null}
        </div>
        <div className={styles.spacer} />
        <div className={styles.controlGroup}>
          <button
            type="button"
            aria-label="Zoom out"
            disabled={disabled}
            onClick={function zoomOut() {
              fitMode.current = null;
              void action(function change() {
                return viewer.current?.zoomOut();
              });
            }}
          >
            −
          </button>
          {kind === "spreadsheet" ? (
            <button
              type="button"
              className={styles.fitButton}
              disabled={disabled}
              onClick={function resetZoom() {
                void action(function reset() {
                  return viewer.current?.setScale(1);
                });
              }}
            >
              100%
            </button>
          ) : (
            <>
              <button
                type="button"
                className={styles.fitButton}
                disabled={disabled}
                aria-pressed={fitMode.current === "width"}
                onClick={function fitWidth() {
                  fitMode.current = "width";
                  void action(function change() {
                    return viewer.current?.fitWidth();
                  });
                }}
              >
                Fit width
              </button>
              <button
                type="button"
                className={styles.fitButton}
                disabled={disabled}
                aria-pressed={fitMode.current === "page"}
                onClick={function fitPage() {
                  fitMode.current = "page";
                  void action(function change() {
                    return viewer.current?.fitPage();
                  });
                }}
              >
                Fit page
              </button>
            </>
          )}
          <button
            type="button"
            aria-label="Zoom in"
            disabled={disabled}
            onClick={function zoomIn() {
              fitMode.current = null;
              void action(function change() {
                return viewer.current?.zoomIn();
              });
            }}
          >
            +
          </button>
        </div>
      </div>
      {ready && error ? (
        <div className={styles.message} role="alert">
          {error} Download the original to open it locally.
        </div>
      ) : null}
      <div
        className={styles.officeViewport}
        ref={viewport}
        aria-busy={disabled}
        aria-hidden={!ready}
      />
      {!ready ? (
        <PreviewStatus
          error={
            error
              ? `${error} Download the original to open it locally.`
              : undefined
          }
        />
      ) : null}
    </div>
  );
}
