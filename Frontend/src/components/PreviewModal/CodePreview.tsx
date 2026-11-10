import { useEffect, useMemo, useRef, useState } from "react";
import type { CSSProperties } from "react";
import type { PreviewResource } from "../../utils/previewCache";
import type { CodeLine, CodeResult } from "./codeTypes";
import styles from "./CodePreview.module.css";

interface CachedCode {
  account: string;
  size: number;
  lines: CodeLine[];
}
const cache = new Map<string, CachedCode>();
let cacheGeneration = 0;
const LINE_HEIGHT = 22;
const OVERSCAN = 8;

window.addEventListener("lightcloud:clear-previews", function clear(event) {
  cacheGeneration += 1;
  const account = (event as CustomEvent<unknown>).detail;
  for (const [key, value] of cache)
    if (value.account === account) cache.delete(key);
});

function saveCode(key: string, value: CachedCode) {
  cache.delete(key);
  cache.set(key, value);
  let size = 0;
  for (const entry of cache.values()) size += entry.size;
  while (cache.size > 4 || size > 600000) {
    const oldest = cache.entries().next().value;
    if (!oldest) break;
    size -= oldest[1].size;
    cache.delete(oldest[0]);
  }
}

export default function CodePreview({
  source,
  resource,
}: {
  source: string;
  resource: PreviewResource;
}) {
  const viewport = useRef<HTMLDivElement>(null);
  const [highlighted, setHighlighted] = useState<CodeLine[] | null>(null);
  const [range, setRange] = useState({ top: 0, height: 600 });
  const [copyState, setCopyState] = useState<"idle" | "done" | "error">("idle");
  const language = resource.language ?? "";
  const account = resource.account;
  const key = JSON.stringify([
    account,
    resource.path,
    resource.revision,
    language,
  ]);
  const plain = useMemo(
    function splitLines() {
      return source.split(/\r\n?|\n/);
    },
    [source],
  );
  const columns = useMemo(
    function measure() {
      let longest = 1;
      for (const line of plain) {
        let width = line.length;
        for (const char of line) if (char === "\t") width += 3;
        longest = Math.max(longest, width);
      }
      return longest;
    },
    [plain],
  );

  useEffect(
    function highlight() {
      setHighlighted(null);
      const saved = cache.get(key);
      if (saved) {
        cache.delete(key);
        cache.set(key, saved);
        setHighlighted(saved.lines);
        return;
      }
      if (source.length > 256000 || plain.length > 20000 || columns > 30000)
        return;
      let active = true;
      const generation = cacheGeneration;
      let worker: Worker;
      try {
        worker = new Worker(new URL("./code.worker.ts", import.meta.url), {
          type: "module",
        });
      } catch {
        return;
      }
      const timeout = setTimeout(function expire() {
        worker.terminate();
      }, 2500);
      function stop() {
        clearTimeout(timeout);
        worker.terminate();
      }
      worker.onmessage = function receive(event: MessageEvent<CodeResult>) {
        if (active && generation === cacheGeneration && event.data.lines) {
          saveCode(key, {
            account,
            size: source.length,
            lines: event.data.lines,
          });
          setHighlighted(event.data.lines);
        }
        stop();
      };
      worker.onerror = stop;
      worker.postMessage({ source: source.replace(/\r\n?/g, "\n"), language });
      return function cleanup() {
        active = false;
        stop();
      };
    },
    [key, account, source, language, plain.length, columns],
  );

  useEffect(function observe() {
    const element = viewport.current;
    if (!element) return;
    let frame = 0;
    function update() {
      frame = 0;
      if (element)
        setRange({ top: element.scrollTop, height: element.clientHeight });
    }
    function schedule() {
      if (!frame) frame = requestAnimationFrame(update);
    }
    const observer = new ResizeObserver(schedule);
    observer.observe(element);
    element.addEventListener("scroll", schedule, { passive: true });
    update();
    return function cleanup() {
      cancelAnimationFrame(frame);
      observer.disconnect();
      element.removeEventListener("scroll", schedule);
    };
  }, []);

  const first = Math.max(0, Math.floor(range.top / LINE_HEIGHT) - OVERSCAN);
  const last = Math.min(
    plain.length,
    Math.ceil((range.top + range.height) / LINE_HEIGHT) + OVERSCAN,
  );
  const visible = plain.slice(first, last);
  async function copy() {
    try {
      await navigator.clipboard.writeText(source);
      setCopyState("done");
    } catch {
      setCopyState("error");
    }
  }

  const gutter = Math.max(3, String(plain.length).length) + 2;
  const codeStyle: CSSProperties & {
    "--code-gutter-width": string;
    "--code-line-height": string;
  } = {
    "--code-gutter-width": `${gutter}ch`,
    "--code-line-height": `${LINE_HEIGHT}px`,
  };
  return (
    <div className={styles.code} style={codeStyle}>
      <div className={styles.toolbar}>
        <span>
          {language}
          <span className={styles.lineCount}>
            {" "}
            · {plain.length.toLocaleString()} lines
          </span>
        </span>
        <button type="button" onClick={copy}>
          {copyState === "done"
            ? "Copied"
            : copyState === "error"
              ? "Copy failed"
              : "Copy code"}
        </button>
      </div>
      <div
        ref={viewport}
        className={styles.viewport}
        role="region"
        aria-label="Code preview"
        tabIndex={0}
      >
        <div
          className={styles.lines}
          style={{
            height: plain.length * LINE_HEIGHT,
            minWidth: `calc(${columns + gutter}ch + 1rem)`,
          }}
        >
          <div style={{ transform: `translateY(${first * LINE_HEIGHT}px)` }}>
            {visible.map(function line(text, index) {
              const number = first + index;
              const tokens = highlighted?.[number];
              return (
                <div key={number} className={styles.line}>
                  <span className={styles.number} aria-hidden="true">
                    {number + 1}
                  </span>
                  <code>
                    {tokens
                      ? tokens.map(function token(part, tokenIndex) {
                          return (
                            <span key={tokenIndex} className={part.classes}>
                              {part.text}
                            </span>
                          );
                        })
                      : text || "\u00a0"}
                  </code>
                </div>
              );
            })}
          </div>
        </div>
      </div>
    </div>
  );
}
