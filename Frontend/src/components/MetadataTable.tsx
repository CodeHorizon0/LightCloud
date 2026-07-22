// MetadataTable.tsx
import React, { useMemo, useRef } from "react";
import deleteIcon from "../assets/delete.svg";
import viewIcon from "../assets/view.svg";
import downloadIcon from "../assets/download.svg";
import { formatDisplayPath, getFileName, normalizePath } from "../utils/storage.js";
import styles from "./MetadataTable.module.css";

interface FileInfo {
  original_size?: number;
  compression_percent?: number | null;
  [key: string]: unknown;
}

type Entry = [string, FileInfo];

interface FileItem {
  path: string;
  info: FileInfo;
  index: number;
  displayPath: string;
  fileName: string;
}

interface FolderNodeType {
  key: string;
  name: string;
  path: string;
  folders: FolderNodeType[];
  files: FileItem[];
  allFilePaths: string[];
  fileCount: number;
}

interface MetadataTableProps {
  entries: Entry[];
  selectedPaths: string[];
  onToggleGroupSelect: (paths: string[], checked: boolean) => void;
  onToggleSelect: (path: string, event: React.MouseEvent, index: number) => void;
  onDelete: (path: string) => void;
  onDownload: (path: string) => void;
  onPreview: (path: string, info: FileInfo) => void;
  canPreview: (path: string, info: FileInfo) => boolean;
  onSelectAll: () => void;
  onDeleteSelected: () => void;
  isDeleting: boolean;
}

function formatSize(value: unknown): string {
  const bytes = Number(value) || 0;
  if (bytes === 0) {
    return "0 B";
  }
  const units = ["B", "KB", "MB", "GB", "TB"];
  const index = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1);
  const size = bytes / Math.pow(1024, index);
  return `${size.toFixed(size >= 100 ? 0 : size >= 10 ? 1 : 2)} ${units[index]}`;
}

function compareNames(a: string, b: string): number {
  return String(a).localeCompare(String(b), "ru", {
    numeric: true,
    sensitivity: "base",
  });
}

function createFolderNode(name: string, path: string): FolderNodeType {
  return {
    key: path || "__root__",
    name: name || "",
    path: path || "",
    folders: [],
    files: [],
    allFilePaths: [],
    fileCount: 0,
  };
}

function buildFileTree(entries: Entry[]): FolderNodeType {
  const root = createFolderNode("", "");
  for (let index = 0; index < entries.length; index += 1) {
    const entry = entries[index];
    const path = normalizePath(entry[0]);
    const info = entry[1] || {};
    const parts = path.split("/").filter(Boolean);
    const fileName = parts.length > 0 ? parts[parts.length - 1] : path;
    const folderParts = parts.slice(0, Math.max(parts.length - 1, 0));
    let current = root;
    let currentPath = "";
    for (let folderIndex = 0; folderIndex < folderParts.length; folderIndex += 1) {
      const folderName = folderParts[folderIndex];
      currentPath = currentPath ? currentPath + "/" + folderName : folderName;
      let nextNode: FolderNodeType | null = null;
      for (let i = 0; i < current.folders.length; i += 1) {
        if (current.folders[i].name === folderName) {
          nextNode = current.folders[i];
          break;
        }
      }
      if (!nextNode) {
        nextNode = createFolderNode(folderName, currentPath);
        current.folders.push(nextNode);
      }
      current = nextNode;
    }
    current.files.push({
      path: path,
      info: info,
      index: index,
      displayPath: formatDisplayPath(path),
      fileName: fileName || getFileName(path),
    });
  }
  function sortNode(node: FolderNodeType): void {
    node.folders.sort(function(a: FolderNodeType, b: FolderNodeType) {
      return compareNames(a.name, b.name);
    });
    node.files.sort(function(a: FileItem, b: FileItem) {
      return compareNames(a.fileName, b.fileName);
    });
    for (let i = 0; i < node.folders.length; i += 1) {
      sortNode(node.folders[i]);
    }
  }
  function finalizeNode(node: FolderNodeType): void {
    let allFilePaths: string[] = [];
    for (let i = 0; i < node.folders.length; i += 1) {
      finalizeNode(node.folders[i]);
      allFilePaths = allFilePaths.concat(node.folders[i].allFilePaths);
    }
    for (let i = 0; i < node.files.length; i += 1) {
      allFilePaths.push(node.files[i].path);
    }
    node.allFilePaths = allFilePaths;
    node.fileCount = allFilePaths.length;
  }
  sortNode(root);
  finalizeNode(root);
  return root;
}

function getSelectedCount(paths: string[], selectedSet: Set<string>): number {
  let count = 0;
  for (let i = 0; i < paths.length; i += 1) {
    if (selectedSet.has(paths[i])) {
      count += 1;
    }
  }
  return count;
}

function getFolderLabel(node: FolderNodeType): string {
  if (!node.path) {
    return "Root";
  }
  return "/" + node.path;
}

function getFolderHint(node: FolderNodeType): string {
  if (!node.path) {
    return "Root folder";
  }
  return "Folder " + getFolderLabel(node);
}

interface IconImageProps {
  src: string;
}

function IconImage(props: IconImageProps) {
  return (
    <img
      src={props.src}
      alt=""
      aria-hidden="true"
      draggable="false"
      style={{
        width: "18px",
        height: "18px",
        display: "block",
        pointerEvents: "none",
        userSelect: "none",
      }}
    />
  );
}

interface FolderNodeProps {
  node: FolderNodeType;
  selectedSet: Set<string>;
  onToggleGroupSelect: (paths: string[], checked: boolean) => void;
  onToggleSelect: (path: string, event: React.MouseEvent, index: number) => void;
  onDelete: (path: string) => void;
  onDownload: (path: string) => void;
  onPreview: (path: string, info: FileInfo) => void;
  canPreview: (path: string, info: FileInfo) => boolean;
}

function FolderNode(props: FolderNodeProps) {
  const node = props.node;
  const selectedSet = props.selectedSet;
  const isRoot = !node.path;
  const groupSelectedCount = getSelectedCount(node.allFilePaths, selectedSet);
  const groupAllSelected = groupSelectedCount > 0 && groupSelectedCount === node.allFilePaths.length;
  const groupSomeSelected = groupSelectedCount > 0 && groupSelectedCount < node.allFilePaths.length;
  const shouldOpen = isRoot || node.fileCount === 1 || groupAllSelected || groupSomeSelected;
  if (node.fileCount === 0) {
    return null;
  }
  const checkboxRef = useRef<HTMLInputElement>(null);
  function handleGroupChange(e: React.ChangeEvent<HTMLInputElement>) {
    if (typeof props.onToggleGroupSelect === "function") {
      props.onToggleGroupSelect(node.allFilePaths, e.currentTarget.checked);
    }
  }
  function handleCheckboxMouseDown(e: React.MouseEvent) {
    e.stopPropagation();
  }
  function handleCheckboxClick(e: React.MouseEvent) {
    e.stopPropagation();
  }
  return (
    <details className={styles.tableGroup} open={shouldOpen}>
      <summary className={styles.tableGroupSummary}>
        <div className={styles.tableGroupSummaryLeft}>
          <input
            type="checkbox"
            className={styles.rowCheckbox}
            checked={groupAllSelected}
            ref={function(el) {
              if (el) {
                el.indeterminate = groupSomeSelected;
              }
            }}
            onMouseDown={handleCheckboxMouseDown}
            onClick={handleCheckboxClick}
            onChange={handleGroupChange}
            aria-label={"Select group " + getFolderLabel(node)}
          />
          <span className={styles.tableGroupFolder}>
            {getFolderLabel(node)}
          </span>
          <span className={styles.tableGroupBadge}>
            {node.fileCount}
          </span>
        </div>
        <div className={styles.tableGroupSummaryRight}>
          {groupSelectedCount > 0 ? (
            <span className={styles.tableGroupSelected}>
              Selected: {groupSelectedCount}
            </span>
          ) : (
            <span className={styles.tableGroupHint}>
              {getFolderHint(node)}
            </span>
          )}
        </div>
      </summary>
      <div className={styles.tableGroupBody}>
        {node.folders.map(function(childNode) {
          return (
            <FolderNode
              key={childNode.key}
              node={childNode}
              selectedSet={selectedSet}
              onToggleGroupSelect={props.onToggleGroupSelect}
              onToggleSelect={props.onToggleSelect}
              onDelete={props.onDelete}
              onDownload={props.onDownload}
              onPreview={props.onPreview}
              canPreview={props.canPreview}
            />
          );
        })}
        {node.files.map(function(item) {
          const info = item.info;
          const isSelected = selectedSet.has(item.path);
          const canPreview = typeof props.canPreview === "function"
            ? props.canPreview(item.path, info)
            : false;
          function handleToggleSelect(e: React.MouseEvent) {
            e.stopPropagation();
            props.onToggleSelect(item.path, e, item.index);
          }
          function handleDownload() {
            props.onDownload(item.path);
          }
          function handlePreview() {
            props.onPreview(item.path, info);
          }
          function handleDelete() {
            props.onDelete(item.path);
          }
          return (
            <div
              key={item.path}
              className={[
                styles.tableGroupRow,
                isSelected ? styles.tableRowSelected : "",
              ].join(" ")}
            >
              <div className={styles.groupColSelect}>
                <input
                  type="checkbox"
                  className={styles.rowCheckbox}
                  checked={isSelected}
                  readOnly
                  onMouseDown={function(e) {
                    e.stopPropagation();
                  }}
                  onClick={handleToggleSelect}
                />
              </div>
              <div className={styles.groupColPath}>
                <span className={styles.groupPathMain}>
                  {item.displayPath}
                </span>
                <span className={styles.groupPathName}>
                  {item.fileName}
                </span>
              </div>
              <div className={styles.groupColSize}>
                {formatSize(info.original_size)}
              </div>
              <div className={styles.groupColCompression}>
                {info.compression_percent != null
                  ? `${info.compression_percent} %`
                  : "-"}
              </div>
              <div className={styles.groupColPreview}>
                <div className={styles.tableActions}>
                  <button
                    className={styles.smallButton}
                    type="button"
                    onClick={handleDownload}
                  >
                    <IconImage src={downloadIcon} />
                  </button>
                  {canPreview ? (
                    <button
                      className={styles.smallButton}
                      type="button"
                      onClick={handlePreview}
                    >
                      <IconImage src={viewIcon} />
                    </button>
                  ) : null}
                </div>
              </div>
              <div className={styles.groupColActions}>
                <div className={styles.tableActions}>
                  <button
                    className={styles.smallDangerButton}
                    type="button"
                    onClick={handleDelete}
                  >
                    <IconImage src={deleteIcon} />
                  </button>
                </div>
              </div>
            </div>
          );
        })}
      </div>
    </details>
  );
}

function MetadataTable(props: MetadataTableProps) {
  const selectedPaths = props.selectedPaths || [];
  const selectedSet = useMemo<Set<string>>(function() {
    return new Set(selectedPaths);
  }, [selectedPaths]);
  const treeRoot = useMemo<FolderNodeType>(function() {
    return buildFileTree(props.entries || []);
  }, [props.entries]);
  const selectedCount = selectedSet.size;
  const totalCount = props.entries.length;
  if (props.entries.length === 0) {
    return (
      <section className={styles.tablePanel}>
        <div className={styles.tableEmptyState}>
          Metadata not loaded yet
        </div>
      </section>
    );
  }
  function handleSelectAll() {
    props.onSelectAll();
  }
  function handleDeleteSelected() {
    props.onDeleteSelected();
  }
  return (
    <section className={styles.tablePanel}>
      <div className={styles.tableToolbar}>
        <div className={styles.tableToolbarInfo}>
          Selected: {selectedCount} of {totalCount}
        </div>
        <div className={styles.tableToolbarActions}>
          <button
            className={styles.ghostButton}
            type="button"
            onClick={handleSelectAll}
          >
            {selectedCount === totalCount
              ? "Deselect all"
              : "Select all"}
          </button>
          <button
            className={styles.smallDangerButton}
            type="button"
            onClick={handleDeleteSelected}
            disabled={selectedCount === 0 || props.isDeleting}
          >
            Delete selected
          </button>
        </div>
      </div>
      <div className={styles.groupList}>
        {treeRoot.files.length > 0 && (
          <FolderNode
            node={{
              key: "__root_files__",
              name: "",
              path: "",
              folders: [],
              files: treeRoot.files,
              allFilePaths: treeRoot.files.map(function(i) {
                return i.path;
              }),
              fileCount: treeRoot.files.length,
            }}
            selectedSet={selectedSet}
            onToggleGroupSelect={props.onToggleGroupSelect}
            onToggleSelect={props.onToggleSelect}
            onDelete={props.onDelete}
            onDownload={props.onDownload}
            onPreview={props.onPreview}
            canPreview={props.canPreview}
          />
        )}
        {treeRoot.folders.map(function(folderNode) {
          return (
            <FolderNode
              key={folderNode.key}
              node={folderNode}
              selectedSet={selectedSet}
              onToggleGroupSelect={props.onToggleGroupSelect}
              onToggleSelect={props.onToggleSelect}
              onDelete={props.onDelete}
              onDownload={props.onDownload}
              onPreview={props.onPreview}
              canPreview={props.canPreview}
            />
          );
        })}
      </div>
    </section>
  );
}

export default MetadataTable;