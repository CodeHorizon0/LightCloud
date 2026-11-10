import { memo, useMemo, useState } from "react";
import type { MouseEvent } from "react";

import deleteIcon from "../../assets/delete.svg";
import downloadIcon from "../../assets/download.svg";
import viewIcon from "../../assets/view.svg";
import {
  formatBytes,
  formatDisplayPath,
  getFileName,
} from "../../utils/storage";
import type { Entry, FileInfo } from "../../utils/storage";
import styles from "./MetadataTable.module.css";

interface Folder {
  path: string;
  name: string;
  folders: Map<string, Folder>;
  files: Entry[];
  paths: string[];
}

interface MetadataTableProps {
  entries: Entry[];
  selectedPaths: ReadonlySet<string>;
  onToggleGroupSelect: (paths: string[], checked: boolean) => void;
  onToggleSelect: (
    path: string,
    checked: boolean,
    shift: boolean,
    ordered: string[],
  ) => void;
  onDelete: (paths: string[]) => void;
  onDownload: (paths: string[]) => void;
  onPreview: (path: string) => void;
  onSelectAll: () => void;
  isDeleting: boolean;
  isDownloading: boolean;
}

const collator = new Intl.Collator(undefined, {
  numeric: true,
  sensitivity: "base",
});

function folder(name: string, path: string): Folder {
  return { name, path, folders: new Map(), files: [], paths: [] };
}

function buildFileTree(entries: Entry[]) {
  const root = folder("Root", "");
  for (const entry of entries) {
    const parts = entry[0].split("/");
    let current = root;
    for (const part of parts.slice(0, -1)) {
      let child = current.folders.get(part);
      if (!child) {
        child = folder(part, current.path ? `${current.path}/${part}` : part);
        current.folders.set(part, child);
      }
      current = child;
    }
    current.files.push(entry);
  }

  function sortAndCollect(node: Folder): void {
    node.files.sort(function compare(a, b) {
      return collator.compare(getFileName(a[0]), getFileName(b[0]));
    });
    const children = Array.from(node.folders).sort(function compare(a, b) {
      return collator.compare(a[0], b[0]);
    });
    node.folders = new Map(children);
    for (const [path] of node.files) node.paths.push(path);
    for (const child of node.folders.values()) {
      sortAndCollect(child);
      node.paths.push(...child.paths);
    }
  }

  sortAndCollect(root);
  return {
    root: {
      ...root,
      folders: new Map<string, Folder>(),
      paths: root.files.map(function ([path]) {
        return path;
      }),
    },
    folders: Array.from(root.folders.values()),
    paths: root.paths,
  };
}

type TableActions = Pick<
  MetadataTableProps,
  | "selectedPaths"
  | "onToggleGroupSelect"
  | "onToggleSelect"
  | "onDelete"
  | "onDownload"
  | "onPreview"
  | "isDeleting"
  | "isDownloading"
>;

type RowActions = Pick<
  TableActions,
  | "onToggleSelect"
  | "onDelete"
  | "onDownload"
  | "onPreview"
  | "isDeleting"
  | "isDownloading"
>;

const FileRow = memo(function FileRow({
  path,
  info,
  selected,
  ordered,
  onToggleSelect,
  onDelete,
  onDownload,
  onPreview,
  isDeleting,
  isDownloading,
}: RowActions & {
  path: string;
  info: FileInfo;
  selected: boolean;
  ordered: string[];
}) {
  const name = getFileName(path);

  return (
    <div
      className={`${styles.tableGroupRow} ${selected ? styles.tableRowSelected : ""}`}
    >
      <div className={styles.groupColSelect}>
        <input
          type="checkbox"
          className={styles.rowCheckbox}
          checked={selected}
          readOnly
          aria-label={`Select ${path}`}
          onClick={function select(event) {
            onToggleSelect(
              path,
              event.currentTarget.checked,
              event.shiftKey,
              ordered,
            );
          }}
        />
      </div>
      <div className={styles.groupColPath}>
        <span className={styles.groupPathMain}>{formatDisplayPath(path)}</span>
        <span className={styles.groupPathName}>{name}</span>
      </div>
      <div className={styles.groupColSize}>
        {formatBytes(info.original_size)}
      </div>
      <div className={styles.groupColCompression}>
        {info.compression_percent === null
          ? "-"
          : `${info.compression_percent} %`}
      </div>
      <div className={styles.groupColPreview}>
        <div className={styles.tableActions}>
          <button
            className={styles.smallButton}
            type="button"
            aria-label={`Download ${path}`}
            disabled={isDownloading}
            onClick={function download() {
              onDownload([path]);
            }}
          >
            <img className={styles.actionIcon} src={downloadIcon} alt="" />
          </button>
          {info.preview_kind ? (
            <button
              className={styles.smallButton}
              type="button"
              aria-label={`Preview ${path}`}
              onClick={function preview() {
                onPreview(path);
              }}
            >
              <img className={styles.actionIcon} src={viewIcon} alt="" />
            </button>
          ) : null}
        </div>
      </div>
      <div className={styles.groupColActions}>
        <div className={styles.tableActions}>
          <button
            className={styles.smallDangerButton}
            type="button"
            aria-label={`Delete ${path}`}
            disabled={isDeleting}
            onClick={function remove() {
              onDelete([path]);
            }}
          >
            <img className={styles.actionIcon} src={deleteIcon} alt="" />
          </button>
        </div>
      </div>
    </div>
  );
});

function FolderNode({
  node,
  actions,
  ordered,
}: {
  node: Folder;
  actions: TableActions;
  ordered: string[];
}) {
  const [open, setOpen] = useState(!node.path || node.paths.length === 1);
  let selected = 0;
  for (const path of node.paths)
    if (actions.selectedPaths.has(path)) selected += 1;
  const checked = selected === node.paths.length;
  const label = node.path ? formatDisplayPath(node.path) : node.name;

  function stop(event: MouseEvent<HTMLInputElement>) {
    event.stopPropagation();
  }

  return (
    <details
      className={styles.tableGroup}
      open={open}
      onToggle={function toggle(event) {
        if (event.target === event.currentTarget)
          setOpen(event.currentTarget.open);
      }}
    >
      <summary className={styles.tableGroupSummary}>
        <div className={styles.tableGroupSummaryLeft}>
          <input
            type="checkbox"
            className={styles.rowCheckbox}
            checked={checked}
            aria-label={`Select group ${label}`}
            onClick={stop}
            ref={function indeterminate(input) {
              if (input) input.indeterminate = selected > 0 && !checked;
            }}
            onChange={function select(event) {
              actions.onToggleGroupSelect(
                node.paths,
                event.currentTarget.checked,
              );
            }}
          />
          <span className={styles.tableGroupFolder}>{label}</span>
          <span className={styles.tableGroupBadge}>{node.paths.length}</span>
        </div>
        <div className={styles.tableGroupSummaryRight}>
          {selected > 0 ? (
            <span className={styles.tableGroupSelected}>
              Selected: {selected}
            </span>
          ) : (
            <span className={styles.tableGroupHint}>
              {node.path ? `Folder ${label}` : "Root folder"}
            </span>
          )}
        </div>
      </summary>
      {open ? (
        <div className={styles.tableGroupBody}>
          {node.files.map(function (entry) {
            return (
              <FileRow
                key={entry[0]}
                path={entry[0]}
                info={entry[1]}
                selected={actions.selectedPaths.has(entry[0])}
                ordered={ordered}
                onToggleSelect={actions.onToggleSelect}
                onDelete={actions.onDelete}
                onDownload={actions.onDownload}
                onPreview={actions.onPreview}
                isDeleting={actions.isDeleting}
                isDownloading={actions.isDownloading}
              />
            );
          })}
          {Array.from(node.folders.values(), function (child) {
            return (
              <FolderNode
                key={child.path}
                node={child}
                actions={actions}
                ordered={ordered}
              />
            );
          })}
        </div>
      ) : null}
    </details>
  );
}

export default function MetadataTable(props: MetadataTableProps) {
  const { root, folders, paths } = useMemo(
    function tree() {
      return buildFileTree(props.entries);
    },
    [props.entries],
  );
  const selected = props.selectedPaths.size;
  const selectedPaths = Array.from(props.selectedPaths);

  return (
    <section className={styles.tablePanel}>
      {paths.length ? (
        <>
          <div className={styles.tableToolbar}>
            <div className={styles.tableToolbarInfo}>
              Selected: {selected} of {paths.length}
            </div>
            <div className={styles.tableToolbarActions}>
              <button
                type="button"
                className={styles.ghostButton}
                onClick={props.onSelectAll}
              >
                {selected === paths.length ? "Deselect all" : "Select all"}
              </button>
              <button
                type="button"
                className={styles.smallButton}
                disabled={!selected || props.isDownloading}
                onClick={function download() {
                  props.onDownload(selectedPaths);
                }}
              >
                Download selected
              </button>
              <button
                type="button"
                className={styles.smallDangerButton}
                disabled={!selected || props.isDeleting}
                onClick={function remove() {
                  props.onDelete(selectedPaths);
                }}
              >
                Delete selected
              </button>
            </div>
          </div>
          <div className={styles.groupList}>
            {root.files.length ? (
              <FolderNode
                key="root"
                node={root}
                actions={props}
                ordered={paths}
              />
            ) : null}
            {folders.map(function (node) {
              return (
                <FolderNode
                  key={`folder/${node.path}`}
                  node={node}
                  actions={props}
                  ordered={paths}
                />
              );
            })}
          </div>
        </>
      ) : (
        <div className={styles.tableEmptyState}>No files</div>
      )}
    </section>
  );
}
