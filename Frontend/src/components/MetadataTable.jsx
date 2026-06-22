import React, { useMemo } from "react";
import deleteIcon from "../assets/delete.svg";
import viewIcon from "../assets/view.svg";
import downloadIcon from "../assets/download.svg";
import { formatDisplayPath, getFileName, normalizePath } from "../utils/storage.js";
import styles from "../App.module.css";

function formatSize(value) {
  const bytes = Number(value) || 0;

  if (bytes === 0) {
    return "0 B";
  }

  const units = ["B", "KB", "MB", "GB", "TB"];
  const index = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1);
  const size = bytes / Math.pow(1024, index);

  return `${size.toFixed(size >= 100 ? 0 : size >= 10 ? 1 : 2)} ${units[index]}`;
}

function compareNames(a, b) {
  return String(a).localeCompare(String(b), "ru", {
    numeric: true,
    sensitivity: "base",
  });
}

function createFolderNode(name, path) {
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

function buildFileTree(entries) {
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

      let nextNode = null;

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

  function sortNode(node) {
    node.folders.sort(compareNames);
    node.files.sort(function(a, b) {
      return compareNames(a.fileName, b.fileName);
    });

    for (let i = 0; i < node.folders.length; i += 1) {
      sortNode(node.folders[i]);
    }
  }

  function finalizeNode(node) {
    let allFilePaths = [];

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

function getSelectedCount(paths, selectedSet) {
  let count = 0;

  for (let i = 0; i < paths.length; i += 1) {
    if (selectedSet.has(paths[i])) {
      count += 1;
    }
  }

  return count;
}

function getFolderLabel(node) {
  if (!node.path) {
    return "Корень";
  }
  return "/" + node.path;
}

function getFolderHint(node) {
  if (!node.path) {
    return "Корневая папка";
  }
  return "Папка " + getFolderLabel(node);
}

function IconImage(props) {
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

function FolderNode(props) {
  const node = props.node;
  const selectedSet = props.selectedSet;

  const isRoot = !node.path;

  const groupSelectedCount = getSelectedCount(node.allFilePaths, selectedSet);
  const groupAllSelected =
    groupSelectedCount > 0 && groupSelectedCount === node.allFilePaths.length;

  const groupSomeSelected =
    groupSelectedCount > 0 && groupSelectedCount < node.allFilePaths.length;

  const shouldOpen =
    isRoot ||
    node.fileCount === 1 ||
    groupAllSelected ||
    groupSomeSelected;

  if (node.fileCount === 0) {
    return null;
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
            onMouseDown={function(e) {
              e.stopPropagation();
            }}
            onClick={function(e) {
              e.stopPropagation();
            }}
            onChange={function(e) {
              if (typeof props.onToggleGroupSelect === "function") {
                props.onToggleGroupSelect(
                  node.allFilePaths,
                  e.currentTarget.checked
                );
              }
            }}
            aria-label={"Выбрать группу " + getFolderLabel(node)}
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
              Выбрано: {groupSelectedCount}
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

          const canPreview =
            typeof props.canPreview === "function"
              ? props.canPreview(item.path, info)
              : false;

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
                  onClick={function(e) {
                    e.stopPropagation();
                    props.onToggleSelect(item.path, e, item.index);
                  }}
                />
              </div>

              <div className={styles.groupColPath}>
                <span className={styles.groupPathMain}>
                  {item.displayPath}
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
                    onClick={function() {
                      props.onDownload(item.path);
                    }}
                  >
                    <IconImage src={downloadIcon} />
                  </button>

                  {canPreview ? (
                    <button
                      className={styles.smallButton}
                      type="button"
                      onClick={function() {
                        props.onPreview(item.path, info);
                      }}
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
                    onClick={function() {
                      props.onDelete(item.path);
                    }}
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

function MetadataTable(props) {
  const selectedPaths = props.selectedPaths || [];

  const selectedSet = useMemo(function() {
    return new Set(selectedPaths);
  }, [selectedPaths]);

  const treeRoot = useMemo(function() {
    return buildFileTree(props.entries || []);
  }, [props.entries]);

  const selectedCount = selectedSet.size;
  const totalCount = props.entries.length;

  if (props.entries.length === 0) {
    return (
      <section className={styles.tablePanel}>
        <div className={styles.tableEmptyState}>
          Метаданные пока не загружены
        </div>
      </section>
    );
  }

  return (
    <section className={styles.tablePanel}>
      <div className={styles.tableToolbar}>
        <div className={styles.tableToolbarInfo}>
          Выбрано: {selectedCount} из {totalCount}
        </div>

        <div className={styles.tableToolbarActions}>
          <button
            className={styles.ghostButton}
            type="button"
            onClick={props.onSelectAll}
          >
            {selectedCount === totalCount
              ? "Снять выбор"
              : "Выбрать все"}
          </button>

          <button
            className={styles.smallDangerButton}
            type="button"
            onClick={props.onDeleteSelected}
            disabled={selectedCount === 0 || props.isDeleting}
          >
            Удалить выбранные
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