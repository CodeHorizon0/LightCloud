#!/usr/bin/env python3
"""
Multithreaded safe cleaner for .pyc files and __pycache__ directories.
Recursively scans from the given root (default: current directory),
collects all targets, then deletes them in parallel using a thread pool.
"""

import os
import sys
import shutil
import argparse
import threading
import queue
from concurrent.futures import ThreadPoolExecutor

print_lock = threading.Lock()
counter_lock = threading.Lock()
deleted_count = 0


def safe_print(msg: str, verbose: bool = False) -> None:
    """Print a message in a thread-safe manner."""
    with print_lock:
        print(msg)


def worker(q: queue.Queue, dry_run: bool, verbose: bool) -> None:
    """
    Worker thread: takes paths from the queue and deletes them.
    Handles files and directories separately.
    """
    global deleted_count
    while True:
        try:
            path = q.get(timeout=0.5)
        except queue.Empty:
            break  

        try:
            if os.path.isdir(path):
                if not dry_run:
                    shutil.rmtree(path, ignore_errors=False)
                if verbose or dry_run:
                    safe_print(f"[{'DRY RUN ' if dry_run else ''}]Deleted directory: {path}")
            elif os.path.isfile(path):
                if not dry_run:
                    os.remove(path)
                if verbose or dry_run:
                    safe_print(f"[{'DRY RUN ' if dry_run else ''}]Deleted file: {path}")
            else:
                safe_print(f"Path does not exist (already deleted?): {path}")
                q.task_done()
                continue

            with counter_lock:
                deleted_count += 1

        except PermissionError as e:
            safe_print(f"Permission error deleting {path}: {e}")
        except FileNotFoundError:
            if verbose:
                safe_print(f"File/dir already gone: {path}")
        except Exception as e:
            safe_print(f"Unexpected error deleting {path}: {e}")
        finally:
            q.task_done()


def collect_paths(root_dir: str, q: queue.Queue, verbose: bool) -> None:
    """
    Recursively walk the directory tree, collecting absolute paths of
    .pyc files and __pycache__ directories. They are placed into the queue.
    """
    for dirpath, dirnames, filenames in os.walk(
        root_dir,
        topdown=True,
        onerror=lambda e: safe_print(f"Error walking {e.filename}: {e}", verbose)
    ):
        if os.path.basename(dirpath) == "__pycache__":
            q.put(dirpath)
            dirnames.clear()  # do not descend into it
            if verbose:
                safe_print(f"Found __pycache__: {dirpath}")
            continue

        for d in list(dirnames):
            if d == "__pycache__":
                full_path = os.path.join(dirpath, d)
                q.put(full_path)
                dirnames.remove(d)  # skip traversal
                if verbose:
                    safe_print(f"Found __pycache__: {full_path}")

        for file in filenames:
            if file.endswith(".pyc"):
                full_path = os.path.join(dirpath, file)
                q.put(full_path)
                if verbose:
                    safe_print(f"Found .pyc: {full_path}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Delete all .pyc files and __pycache__ directories recursively."
    )
    parser.add_argument(
        "root", nargs="?", default=".",
        help="Root directory to scan (default: current directory)"
    )
    parser.add_argument(
        "-j", "--jobs", type=int, default=os.cpu_count(),
        help=f"Number of worker threads (default: CPU count = {os.cpu_count()})"
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Show what would be deleted without actually deleting"
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true",
        help="Print detailed information during scanning and deletion"
    )
    parser.add_argument(
        "--yes", "-y", action="store_true",
        help="Skip confirmation prompt (use with caution)"
    )
    args = parser.parse_args()

    root = os.path.abspath(args.root)
    if not os.path.isdir(root):
        print(f"Error: '{root}' is not a valid directory.", file=sys.stderr)
        sys.exit(1)

    # Collect targets into a queue (single‑threaded walk)
    print(f"Scanning '{root}' for .pyc files and __pycache__ directories...")
    q = queue.Queue()
    collect_paths(root, q, args.verbose)

    total = q.qsize()
    if total == 0:
        print("No .pyc files or __pycache__ directories found.")
        return

    print(f"Found {total} item(s) to delete.")

    if not args.dry_run and not args.yes:
        # Ask for confirmation
        try:
            answer = input(f"Proceed with deletion of {total} item(s)? [y/N] ").strip().lower()
            if answer not in ('y', 'yes'):
                print("Aborted.")
                return
        except KeyboardInterrupt:
            print("\nAborted.")
            return

    # Launch worker threads
    with ThreadPoolExecutor(max_workers=args.jobs) as executor:
        # Submit workers
        futures = []
        for _ in range(args.jobs):
            futures.append(executor.submit(worker, q, args.dry_run, args.verbose))

        # Wait for all items in the queue to be processed
        q.join()

        # Workers will exit when queue is empty (timeout in get)
        # No need to explicitly cancel futures

    if args.dry_run:
        print(f"Dry run completed. Would have deleted {deleted_count} item(s).")
    else:
        print(f"Deleted {deleted_count} item(s).")


if __name__ == "__main__":
    main()