import { useDeferredValue, useMemo, useState } from "react";
import { isRecord } from "../../api";
import { formatBytes } from "../../utils/storage";
import styles from "./AdvancedPreview.module.css";

type EntryType = "file" | "folder" | "link" | "special";
interface ArchiveEntry {
  name: string;
  size: number;
  packed: number | null;
  type: EntryType;
  encrypted: boolean;
}
interface Row extends ArchiveEntry {
  path: string;
  key: string;
}
interface IndexedEntry extends Row {
  safe: boolean;
  searchName: string;
}
const PAGE_SIZE = 100;
const sorter = new Intl.Collator(undefined, {
  numeric: true,
  sensitivity: "base",
});

function archiveData(value: unknown) {
  if (
    !isRecord(value) ||
    typeof value.format !== "string" ||
    !Array.isArray(value.entries)
  )
    return null;
  const entries: IndexedEntry[] = [];
  for (const entry of value.entries) {
    if (
      !isRecord(entry) ||
      typeof entry.name !== "string" ||
      typeof entry.size !== "number" ||
      (entry.type !== "file" &&
        entry.type !== "folder" &&
        entry.type !== "link" &&
        entry.type !== "special")
    )
      continue;
    const path = entry.name
      .replaceAll("\\", "/")
      .replace(/\/{2,}/g, "/")
      .replace(/^\.\/+|\/+$/g, "");
    const safe =
      !path.startsWith("/") &&
      !/^[A-Za-z]:/.test(path) &&
      !path.split("/").includes("..");
    entries.push({
      name: entry.name,
      size: entry.size,
      type: safe ? entry.type : "special",
      path,
      safe,
      searchName: path.toLowerCase(),
      key: String(entries.length),
      encrypted: entry.encrypted === true,
      packed: typeof entry.packed === "number" ? entry.packed : null,
    });
  }
  return { format: value.format, entries };
}

function archiveRows(
  entries: IndexedEntry[],
  current: string,
  filter: string,
): Row[] {
  const rows: Row[] = [];
  const folders = new Set<string>();
  const prefix = current ? current + "/" : "";
  for (const entry of entries) {
    const { path } = entry;
    if (filter) {
      if (entry.searchName.includes(filter))
        rows.push({ ...entry, name: path });
      continue;
    }
    if (!entry.safe) {
      if (!current) rows.push(entry);
      continue;
    }
    if (!path.startsWith(prefix)) continue;
    const relative = path.slice(prefix.length);
    if (!relative) continue;
    const [name, next] = relative.split("/", 2);
    if (next !== undefined || entry.type === "folder") {
      if (!folders.has(name)) {
        folders.add(name);
        rows.push({
          name,
          type: "folder",
          size: 0,
          packed: null,
          encrypted: false,
          path: prefix + name,
          key: "folder/" + name,
        });
      }
    } else rows.push({ ...entry, name });
  }
  return rows.sort(function order(a, b) {
    return (
      Number(b.type === "folder") - Number(a.type === "folder") ||
      sorter.compare(a.name, b.name)
    );
  });
}

export default function ArchivePreview({
  value,
  cached,
}: {
  value: unknown;
  cached: boolean;
}) {
  const data = useMemo(
    function parse() {
      return archiveData(value);
    },
    [value],
  );
  const [folder, setFolder] = useState("");
  const [query, setQuery] = useState("");
  const [page, setPage] = useState(0);
  const deferred = useDeferredValue(query.trim().toLowerCase());
  const rows = useMemo(
    function index() {
      return data ? archiveRows(data.entries, folder, deferred) : [];
    },
    [data, folder, deferred],
  );
  if (!data)
    return (
      <div className={styles.message}>Invalid archive directory response.</div>
    );

  const pages = Math.max(1, Math.ceil(rows.length / PAGE_SIZE));
  const shown = Math.min(page, pages - 1);
  const crumbs = folder ? folder.split("/") : [];
  function goTo(path: string) {
    setFolder(path);
    setQuery("");
    setPage(0);
  }

  return (
    <div className={styles.archive}>
      <div className={styles.toolbar}>
        <span className={styles.pill}>{data.format}</span>
        <span>{data.entries.length} entries</span>
        {cached ? <span className={styles.pill}>Cached</span> : null}
        <div className={styles.spacer} />
        <input
          aria-label="Search archive"
          type="search"
          placeholder="Find in archive…"
          value={query}
          onChange={function search(event) {
            setQuery(event.currentTarget.value);
            setPage(0);
          }}
        />
      </div>
      <nav className={styles.breadcrumbs} aria-label="Archive folders">
        <button
          type="button"
          onClick={function root() {
            goTo("");
          }}
        >
          Archive
        </button>
        {crumbs.map(function crumb(name, index) {
          return (
            <button
              type="button"
              key={index}
              onClick={function up() {
                goTo(crumbs.slice(0, index + 1).join("/"));
              }}
            >
              / {name}
            </button>
          );
        })}
      </nav>
      <div className={styles.directory}>
        <table>
          <thead>
            <tr>
              <th scope="col">Name</th>
              <th scope="col">Size</th>
              <th scope="col">Packed</th>
            </tr>
          </thead>
          <tbody>
            {rows
              .slice(shown * PAGE_SIZE, (shown + 1) * PAGE_SIZE)
              .map(function row(entry) {
                return (
                  <tr key={entry.key}>
                    <td title={entry.path}>
                      {entry.type === "folder" ? (
                        <button
                          type="button"
                          onClick={function enter() {
                            goTo(entry.path);
                          }}
                        >
                          ▸ {entry.name}
                        </button>
                      ) : (
                        <span>
                          {entry.name}{" "}
                          {entry.type === "link" ? <small>Link</small> : null}
                        </span>
                      )}
                      {entry.encrypted ? <small>Encrypted</small> : null}
                    </td>
                    <td>
                      {entry.type === "folder" ? "—" : formatBytes(entry.size)}
                    </td>
                    <td>
                      {entry.packed === null ? "—" : formatBytes(entry.packed)}
                    </td>
                  </tr>
                );
              })}
          </tbody>
        </table>
        {!rows.length ? (
          <div className={styles.message}>No entries here.</div>
        ) : null}
      </div>
      {pages > 1 ? (
        <div className={styles.toolbar}>
          <button
            type="button"
            disabled={!shown}
            onClick={function prev() {
              setPage(shown - 1);
            }}
          >
            Previous
          </button>
          <span>
            {shown + 1} / {pages}
          </span>
          <button
            type="button"
            disabled={shown + 1 >= pages}
            onClick={function next() {
              setPage(shown + 1);
            }}
          >
            Next
          </button>
        </div>
      ) : null}
    </div>
  );
}
