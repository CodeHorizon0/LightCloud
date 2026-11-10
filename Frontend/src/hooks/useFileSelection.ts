import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { FileInfo } from "../utils/storage";

export function useFileSelection(metadata: ReadonlyMap<string, FileInfo>) {
  const [selected, setSelected] = useState(function () {
    return new Set<string>();
  });
  const anchor = useRef<string | null>(null);
  useEffect(
    function reconcileSelection() {
      if (anchor.current !== null && !metadata.has(anchor.current))
        anchor.current = null;
      setSelected(function removeMissing(previous) {
        for (const path of previous) {
          if (!metadata.has(path)) {
            return new Set(
              Array.from(previous).filter(function exists(item) {
                return metadata.has(item);
              }),
            );
          }
        }
        return previous;
      });
    },
    [metadata],
  );

  const selectedPaths = useMemo(
    function visibleSelection() {
      return new Set(
        Array.from(selected).filter(function (path) {
          return metadata.has(path);
        }),
      );
    },
    [selected, metadata],
  );
  const updateSelection = useCallback(function updateSelection(
    paths: Iterable<string>,
    checked: boolean,
  ) {
    setSelected(function change(previous) {
      const next = new Set(previous);
      for (const path of paths) {
        if (checked) next.add(path);
        else next.delete(path);
      }
      return next;
    });
  }, []);

  const toggleFile = useCallback(
    function toggleFile(
      path: string,
      checked: boolean,
      shift: boolean,
      ordered: string[],
    ) {
      const first =
        shift && anchor.current !== null ? ordered.indexOf(anchor.current) : -1;
      const last = first >= 0 ? ordered.indexOf(path) : -1;
      updateSelection(
        last < 0
          ? [path]
          : ordered.slice(Math.min(first, last), Math.max(first, last) + 1),
        checked,
      );
      anchor.current = path;
    },
    [updateSelection],
  );

  function toggleAll() {
    anchor.current = null;
    setSelected(
      selectedPaths.size === metadata.size
        ? new Set()
        : new Set(metadata.keys()),
    );
  }

  return { selectedPaths, updateSelection, toggleFile, toggleAll };
}
