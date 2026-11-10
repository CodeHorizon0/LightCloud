#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import shutil
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path


def collect_paths(root: Path) -> list[Path]:
    paths: list[Path] = []
    for parent, dirs, files in os.walk(root):
        base = Path(parent)
        if base.name == "__pycache__":
            paths.append(base)
            dirs.clear()
            continue
        if "__pycache__" in dirs:
            paths.append(base / "__pycache__")
            dirs.remove("__pycache__")
        paths.extend(base / name for name in files if name.endswith(".pyc"))
    return paths


def remove_cache(path: Path) -> bool:
    try:
        if not path.is_symlink() and path.is_dir():
            shutil.rmtree(path)
        else:
            path.unlink()
        return True
    except FileNotFoundError:
        return False
    except OSError as exc:
        print(f"Could not delete {path}: {exc}", file=sys.stderr)
        return False


def main() -> None:
    parser = argparse.ArgumentParser(description="Delete Python bytecode caches.")
    parser.add_argument("root", nargs="?", type=Path, default=Path.cwd())
    parser.add_argument("-j", "--jobs", type=int, default=min(32, os.cpu_count() or 1))
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("-v", "--verbose", action="store_true")
    parser.add_argument("-y", "--yes", action="store_true")
    args = parser.parse_args()
    if args.jobs < 1:
        parser.error("--jobs must be positive")
    if not args.root.is_dir():
        parser.error("Root must be a directory")

    paths = collect_paths(args.root.absolute())
    if not paths:
        print("No Python bytecode caches found.")
        return
    if args.dry_run:
        for path in paths:
            print(path)
        print(f"Would delete {len(paths)} item(s).")
        return
    if not args.yes:
        try:
            if input(f"Delete {len(paths)} item(s)? [y/N] ").strip().lower() not in {"y", "yes"}:
                return
        except (EOFError, KeyboardInterrupt):
            return

    count = 0
    with ThreadPoolExecutor(max_workers=min(args.jobs, len(paths))) as executor:
        for path, removed in zip(paths, executor.map(remove_cache, paths), strict=True):
            if removed:
                count += 1
                if args.verbose:
                    print(f"Deleted {path}")
    print(f"Deleted {count} item(s).")


if __name__ == "__main__":
    main()
