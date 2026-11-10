import { useState } from "react";
import { isRecord } from "../../api";
import type { PreviewResource } from "../../utils/previewCache";
import { asBlob, useObjectUrl, usePreview } from "./usePreview";
import styles from "./AdvancedPreview.module.css";

const assets = new Map([
  ["merged", "Composite"],
  ["preview", "Preview"],
  ["thumbnail", "Thumbnail"],
]);

function Artwork({
  resource,
  asset,
  onError,
}: {
  resource: PreviewResource;
  asset: string;
  onError: (error: unknown) => void;
}) {
  const result = usePreview(resource, "asset=" + asset, asBlob, onError);
  if (!result) return <div className={styles.message}>Loading artwork…</div>;
  if ("error" in result)
    return (
      <div className={styles.message} role="alert">
        {result.error}
      </div>
    );
  return (
    <ImageBody body={result.value} label={assets.get(asset) ?? "Artwork"} />
  );
}

function ImageBody({ body, label }: { body: Blob; label: string }) {
  const url = useObjectUrl(body);
  return url ? <img src={url} alt={label} className={styles.artwork} /> : null;
}

export default function KritaPreview({
  resource,
  details,
  onError,
}: {
  resource: PreviewResource;
  details: unknown;
  onError: (error: unknown) => void;
}) {
  const [chosen, setChosen] = useState<string | null>(null);
  if (
    !isRecord(details) ||
    !Array.isArray(details.assets) ||
    !Array.isArray(details.layers)
  ) {
    return <div className={styles.message}>Invalid Krita metadata.</div>;
  }
  const variants = details.assets.filter(
    function known(value): value is string {
      return typeof value === "string" && assets.has(value);
    },
  );
  const selected = chosen ?? variants[0];
  return (
    <div className={styles.krita}>
      <div className={styles.toolbar}>
        {variants.map(function option(asset) {
          return (
            <button
              type="button"
              aria-pressed={selected === asset}
              key={asset}
              onClick={function select() {
                setChosen(asset);
              }}
            >
              {assets.get(asset)}
            </button>
          );
        })}
        <div className={styles.spacer} />
        {typeof details.width === "number" &&
        typeof details.height === "number" ? (
          <span>
            {details.width} × {details.height}
          </span>
        ) : null}
        {typeof details.color_space === "string" && details.color_space ? (
          <span className={styles.pill}>{details.color_space}</span>
        ) : null}
      </div>
      <div className={styles.kritaGrid}>
        <div className={styles.artboard}>
          {selected ? (
            <Artwork
              key={selected}
              resource={resource}
              asset={selected}
              onError={onError}
            />
          ) : (
            <div className={styles.message}>
              This project has no embedded picture.
            </div>
          )}
        </div>
        <aside className={styles.layers}>
          <h3>
            Layers <small>{details.layers.length}</small>
          </h3>
          <ul>
            {details.layers.map(function layer(item, index) {
              if (!isRecord(item) || typeof item.name !== "string") return null;
              const depth =
                typeof item.depth === "number"
                  ? Math.max(0, Math.min(32, item.depth))
                  : 0;
              return (
                <li key={index} style={{ paddingInlineStart: 8 + depth * 11 }}>
                  <span className={styles.layerLabel} title={item.name}>
                    {item.visible === false ? "◌ " : "◉ "}
                    {item.name}
                  </span>
                  <small>
                    {typeof item.type === "string" ? item.type : ""}
                  </small>
                  <small>
                    {typeof item.opacity === "number"
                      ? `${Math.round((item.opacity / 255) * 100)}%`
                      : ""}
                  </small>
                </li>
              );
            })}
          </ul>
        </aside>
      </div>
    </div>
  );
}
