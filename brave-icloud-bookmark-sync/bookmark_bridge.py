#!/usr/bin/env python3
"""
bookmark_bridge.py  --  fully-local two-way bookmark sync between two
Chromium browsers (by default Microsoft Edge <-> Brave) on Windows.

Why this exists
---------------
iCloud for Windows can sync Safari bookmarks with Chrome / Edge / Firefox,
but NOT with Brave (Brave-specific bug: brave/brave-browser#31443). The trick
is to let iCloud sync with a browser it *does* support -- Edge -- and then keep
Edge's bookmarks and Brave's bookmarks in lock-step. This script is that second
link, done entirely on your own machine with no cloud account:

    Brave  <--(this script)-->  Edge  <--(iCloud extension)-->  Safari / iPhone

It is the "no third-party service" fallback. The RECOMMENDED path (floccus +
iCloud-on-Edge, see README.md) is more reliable and live; use this only if you
don't want a sync backend like Google Drive or WebDAV in the loop.

How it works
------------
Edge and Brave both store bookmarks in the identical Chromium "Bookmarks" JSON
format. This script:
  1. Reads both bookmark files and a saved baseline of the last synced state.
  2. Uses set math over (root, folder-path, name, url) keys to work out what was
     added or deleted on each side since the baseline -- so deletions propagate
     correctly instead of resurrecting forever.
  3. Rebuilds each browser's tree to the merged result, reusing existing nodes
     (preserving their GUIDs / dates / favicon links) and only synthesizing new
     nodes for genuinely new bookmarks.
  4. Recomputes the Chromium MD5 checksum so the browser accepts the file
     without complaint, backs up the original, and writes atomically.

IMPORTANT LIMITATION
--------------------
A running Chromium browser keeps bookmarks in memory and overwrites its own
Bookmarks file, so this script will NOT write to a browser that is currently
running (it still reads it). Practically: changes flow into a browser the next
time that browser is closed while the script runs. Run it on a schedule and/or
when Brave exits. See Install-BridgeTask.ps1.

Usage
-----
    python bookmark_bridge.py            # sync once
    python bookmark_bridge.py --dry-run  # show what would change, write nothing
    python bookmark_bridge.py --force    # write even if a browser is running (risky)
    python bookmark_bridge.py --edge "C:\\path\\Bookmarks" --brave "C:\\path\\Bookmarks"

Exit codes: 0 = success (with or without changes), 1 = error.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path

# Chromium stores timestamps as microseconds since 1601-01-01 UTC.
WINDOWS_EPOCH_OFFSET_SECONDS = 11644473600
# Roots are encoded / checksummed in this exact order by Chromium.
ROOT_ORDER = ("bookmark_bar", "other", "synced")
# Chromium's permanent folders use these fixed ids; descendants continue from 4.
PERMANENT_IDS = {"bookmark_bar": "1", "other": "2", "synced": "3"}


def chromium_now() -> str:
    """Current time as a Chromium timestamp string."""
    return str(int((time.time() + WINDOWS_EPOCH_OFFSET_SECONDS) * 1_000_000))


# --------------------------------------------------------------------------- #
# Default file locations (Windows)
# --------------------------------------------------------------------------- #
def default_path(*parts: str) -> Path:
    local = os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local"))
    return Path(local).joinpath(*parts)


DEFAULT_EDGE = default_path("Microsoft", "Edge", "User Data", "Default", "Bookmarks")
DEFAULT_BRAVE = default_path(
    "BraveSoftware", "Brave-Browser", "User Data", "Default", "Bookmarks"
)
DEFAULT_STATE = Path(__file__).with_name("sync_state.json")

# Process names used for the "is the browser running?" guard.
EDGE_PROCESS = "msedge.exe"
BRAVE_PROCESS = "brave.exe"


# --------------------------------------------------------------------------- #
# Flattening: tree -> {key: metadata}
# --------------------------------------------------------------------------- #
# A "key" uniquely identifies a logical bookmark across browsers WITHOUT relying
# on GUIDs (which differ between browsers). Renames/moves show up as delete+add,
# which still yields the correct final set and never loses data.
#   url node:    (root_key, folder_path_tuple, "url",    name, url)
#   folder node: (root_key, folder_path_tuple, "folder", name, "")


def flatten(tree: dict) -> dict:
    """Return {key: {'node', 'root', 'path', 'name', 'url', 'type'}}."""
    result: dict = {}
    roots = tree.get("roots", {})
    for root_key in ROOT_ORDER:
        root = roots.get(root_key)
        if not root:
            continue
        _flatten_children(root.get("children", []), root_key, (), result)
    return result


def _flatten_children(children: list, root_key: str, path: tuple, out: dict) -> None:
    for node in children:
        name = node.get("name", "")
        ntype = node.get("type", "url")
        if ntype == "folder":
            key = (root_key, path, "folder", name, "")
            out.setdefault(key, {"node": node, "root": root_key, "path": path,
                                 "name": name, "url": "", "type": "folder"})
            _flatten_children(node.get("children", []), root_key, path + (name,), out)
        else:
            url = node.get("url", "")
            key = (root_key, path, "url", name, url)
            out.setdefault(key, {"node": node, "root": root_key, "path": path,
                                 "name": name, "url": url, "type": "url"})


# --------------------------------------------------------------------------- #
# Baseline (last synced state) persistence
# --------------------------------------------------------------------------- #
def load_baseline(path: Path) -> set:
    if not path.exists():
        return set()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        # keys were stored as lists (JSON has no tuples); path is a nested list.
        return {(k[0], tuple(k[1]), k[2], k[3], k[4]) for k in raw.get("keys", [])}
    except (json.JSONDecodeError, KeyError, IndexError, TypeError):
        # Corrupt/old baseline -> treat as first run (safe: merges, never deletes).
        return set()


def save_baseline(path: Path, keys: set) -> None:
    serializable = [[k[0], list(k[1]), k[2], k[3], k[4]] for k in sorted(keys)]
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps({"keys": serializable}, indent=0), encoding="utf-8")
    os.replace(tmp, path)


# --------------------------------------------------------------------------- #
# Merge (the core set math)
# --------------------------------------------------------------------------- #
def merge(baseline: set, edge_keys: set, brave_keys: set) -> set:
    added = (edge_keys - baseline) | (brave_keys - baseline)
    deleted = (baseline - edge_keys) | (baseline - brave_keys)
    return (baseline | added) - deleted


# --------------------------------------------------------------------------- #
# Rebuilding a browser tree to match the target key set
# --------------------------------------------------------------------------- #
def rebuild_tree(original: dict, target_keys: set, existing: dict) -> dict:
    """Return a new bookmark tree containing exactly `target_keys`, reusing
    existing nodes (to preserve GUIDs/dates/favicons) where a key already
    exists on this side and synthesizing new nodes otherwise."""
    orig_roots = original.get("roots", {})
    new_roots: dict = {}
    for root_key in ROOT_ORDER:
        src = orig_roots.get(root_key)
        if src is None:
            continue
        new_roots[root_key] = {
            "type": "folder",
            "name": src.get("name", root_key),
            "guid": src.get("guid", str(uuid.uuid4())),
            "date_added": src.get("date_added", chromium_now()),
            "date_modified": src.get("date_modified", "0"),
            "children": [],
        }
    # Preserve any other roots (rare) verbatim so we never drop data we don't model.
    for root_key, src in orig_roots.items():
        if root_key not in new_roots:
            new_roots[root_key] = src

    # Create parent folders before children by sorting on path depth, folders first.
    def sort_key(k):
        root_key, path, ntype, name, url = k
        return (len(path), 0 if ntype == "folder" else 1, path, name, url)

    for key in sorted(target_keys, key=sort_key):
        root_key, path, ntype, name, url = key
        if root_key not in new_roots:
            # Bookmark lives in a root this side doesn't have; create it.
            new_roots[root_key] = {"type": "folder", "name": root_key,
                                   "guid": str(uuid.uuid4()), "date_added": chromium_now(),
                                   "date_modified": "0", "children": []}
        parent_children = _ensure_path(new_roots[root_key], root_key, path, existing)
        if ntype == "folder":
            _ensure_folder(parent_children, root_key, path, name, existing)
        else:
            parent_children.append(_url_node(root_key, path, name, url, existing))

    result = dict(original)  # keep version/other top-level fields
    result["roots"] = new_roots
    result.setdefault("version", 1)
    return result


def _ensure_path(root_node: dict, root_key: str, path: tuple, existing: dict) -> list:
    """Walk/create the folder chain `path` under root_node; return the deepest
    folder's children list."""
    children = root_node["children"]
    for depth, folder_name in enumerate(path):
        parent_path = path[:depth]
        children = _ensure_folder(children, root_key, parent_path, folder_name, existing)
    return children


def _ensure_folder(children: list, root_key: str, parent_path: tuple,
                   name: str, existing: dict) -> list:
    """Return the children list of folder `name` inside `children`, creating it
    (reusing metadata from the existing tree when possible) if absent."""
    for node in children:
        if node.get("type") == "folder" and node.get("name") == name:
            return node["children"]
    key = (root_key, parent_path, "folder", name, "")
    src = existing.get(key, {}).get("node", {})
    folder = {
        "type": "folder",
        "name": name,
        "guid": src.get("guid", str(uuid.uuid4())),
        "date_added": src.get("date_added", chromium_now()),
        "date_modified": src.get("date_modified", "0"),
        "children": [],
    }
    children.append(folder)
    return folder["children"]


def _url_node(root_key: str, path: tuple, name: str, url: str, existing: dict) -> dict:
    key = (root_key, path, "url", name, url)
    src = existing.get(key, {}).get("node")
    if src is not None:
        return dict(src)  # reuse -> keeps guid, date_added, favicon association
    return {
        "type": "url",
        "name": name,
        "url": url,
        "guid": str(uuid.uuid4()),
        "date_added": chromium_now(),
        "date_last_used": "0",
    }


# --------------------------------------------------------------------------- #
# IDs + checksum (so Chromium accepts the file silently)
# --------------------------------------------------------------------------- #
def assign_ids(tree: dict) -> None:
    counter = [4]  # descendants start at 4; permanent roots keep 1/2/3

    def walk(node: dict):
        for child in node.get("children", []):
            child["id"] = str(counter[0])
            counter[0] += 1
            if child.get("type") == "folder":
                walk(child)

    roots = tree.get("roots", {})
    for root_key in ROOT_ORDER:
        root = roots.get(root_key)
        if root is None:
            continue
        root["id"] = PERMANENT_IDS[root_key]
        walk(root)
    # Any extra preserved roots: give them ids too, keep going from counter.
    for root_key, root in roots.items():
        if root_key in ROOT_ORDER:
            continue
        root["id"] = str(counter[0]); counter[0] += 1
        walk(root)


def compute_checksum(tree: dict) -> str:
    """Reproduce Chromium's BookmarkCodec checksum (see bookmark_codec.cc).
    For each node: MD5-update with id (utf-8), title (utf-16-le), the literal
    type string "url"/"folder" (utf-8), and url (utf-8) for url nodes."""
    md5 = hashlib.md5()

    def upd_utf8(s: str):
        md5.update(s.encode("utf-8"))

    def upd_utf16(s: str):
        md5.update(s.encode("utf-16-le"))

    def walk(node: dict):
        nid = str(node.get("id", ""))
        title = node.get("name", "")
        if node.get("type") == "url":
            upd_utf8(nid); upd_utf16(title); upd_utf8("url"); upd_utf8(node.get("url", ""))
        else:
            upd_utf8(nid); upd_utf16(title); upd_utf8("folder")
            for child in node.get("children", []):
                walk(child)

    roots = tree.get("roots", {})
    for root_key in ROOT_ORDER:
        root = roots.get(root_key)
        if root is not None:
            walk(root)
    return md5.hexdigest()


# --------------------------------------------------------------------------- #
# I/O helpers
# --------------------------------------------------------------------------- #
def load_bookmarks(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def backup(path: Path, keep: int = 10) -> None:
    stamp = time.strftime("%Y%m%d-%H%M%S")
    dest = path.with_name(f"{path.name}.bridge-backup-{stamp}")
    shutil.copy2(path, dest)
    backups = sorted(path.parent.glob(f"{path.name}.bridge-backup-*"))
    for old in backups[:-keep]:
        try:
            old.unlink()
        except OSError:
            pass


def write_bookmarks(path: Path, tree: dict) -> None:
    assign_ids(tree)
    tree["checksum"] = compute_checksum(tree)
    tree.setdefault("version", 1)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".bm-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(tree, fh, ensure_ascii=False, indent=3)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)
    # Drop Chromium's own stale backup so it can't override our file on launch.
    bak = path.with_name(path.name + ".bak")
    if bak.exists():
        try:
            bak.unlink()
        except OSError:
            pass


def is_running(process_name: str) -> bool:
    """Best-effort check for a running browser (Windows `tasklist`)."""
    if os.name != "nt":
        return False  # non-Windows: assume closed (script targets Windows)
    try:
        out = subprocess.run(
            ["tasklist", "/FI", f"IMAGENAME eq {process_name}", "/NH"],
            capture_output=True, text=True, timeout=15,
        ).stdout.lower()
        return process_name.lower() in out
    except (subprocess.SubprocessError, OSError, FileNotFoundError):
        return False


# --------------------------------------------------------------------------- #
# Orchestration
# --------------------------------------------------------------------------- #
def sync(edge_path: Path, brave_path: Path, state_path: Path,
         dry_run: bool = False, force: bool = False) -> int:
    for label, p in (("Edge", edge_path), ("Brave", brave_path)):
        if not p.exists():
            print(f"ERROR: {label} bookmarks file not found: {p}", file=sys.stderr)
            print("       Pass an explicit path with --edge / --brave.", file=sys.stderr)
            return 1

    edge_tree = load_bookmarks(edge_path)
    brave_tree = load_bookmarks(brave_path)
    baseline = load_baseline(state_path)

    edge_flat = flatten(edge_tree)
    brave_flat = flatten(brave_tree)
    edge_keys, brave_keys = set(edge_flat), set(brave_flat)

    final = merge(baseline, edge_keys, brave_keys)

    edge_add, edge_del = final - edge_keys, edge_keys - final
    brave_add, brave_del = final - brave_keys, brave_keys - final

    def describe(label, add, dele):
        if add or dele:
            print(f"  {label}: +{len(add)} / -{len(dele)}")
            for k in sorted(add):
                print(f"    + {k[0]}/{'/'.join(k[1])}  {k[3]}  {k[4]}".rstrip())
            for k in sorted(dele):
                print(f"    - {k[0]}/{'/'.join(k[1])}  {k[3]}  {k[4]}".rstrip())

    if not edge_add and not edge_del and not brave_add and not brave_del:
        print("Already in sync. Nothing to do.")
        # Still record baseline so a first run establishes it.
        if not dry_run and baseline != final:
            save_baseline(state_path, final)
        return 0

    print("Changes to apply:")
    describe("Edge", edge_add, edge_del)
    describe("Brave", brave_add, brave_del)

    if dry_run:
        print("\n(dry-run: no files written)")
        return 0

    edge_running = is_running(EDGE_PROCESS)
    brave_running = is_running(BRAVE_PROCESS)
    edge_written = brave_written = False

    # --- Edge ---
    if edge_add or edge_del:
        if edge_running and not force:
            print("SKIP Edge: it is running (close Edge, or use --force). "
                  "Changes will apply next run.")
        else:
            backup(edge_path)
            write_bookmarks(edge_path, rebuild_tree(edge_tree, final, edge_flat))
            edge_written = True
            print("Edge bookmarks updated.")
    else:
        edge_written = True  # already matches final

    # --- Brave ---
    if brave_add or brave_del:
        if brave_running and not force:
            print("SKIP Brave: it is running (close Brave, or use --force). "
                  "Changes will apply next run.")
        else:
            backup(brave_path)
            write_bookmarks(brave_path, rebuild_tree(brave_tree, final, brave_flat))
            brave_written = True
            print("Brave bookmarks updated.")
    else:
        brave_written = True

    # Only advance the baseline once BOTH sides reflect `final`; otherwise keep
    # the old baseline so pending changes are re-detected next run (idempotent).
    if edge_written and brave_written:
        save_baseline(state_path, final)
        print("Baseline updated.")
    else:
        print("Baseline NOT advanced (a browser was open); will retry next run.")
    return 0


def parse_args(argv=None):
    ap = argparse.ArgumentParser(description="Two-way Edge<->Brave bookmark sync.")
    ap.add_argument("--edge", type=Path, default=DEFAULT_EDGE,
                    help=f"Path to Edge Bookmarks file (default: {DEFAULT_EDGE})")
    ap.add_argument("--brave", type=Path, default=DEFAULT_BRAVE,
                    help=f"Path to Brave Bookmarks file (default: {DEFAULT_BRAVE})")
    ap.add_argument("--state", type=Path, default=DEFAULT_STATE,
                    help=f"Path to baseline state file (default: {DEFAULT_STATE})")
    ap.add_argument("--dry-run", action="store_true",
                    help="Show what would change without writing.")
    ap.add_argument("--force", action="store_true",
                    help="Write even if a browser is running (may be overwritten).")
    return ap.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    try:
        return sync(args.edge, args.brave, args.state,
                    dry_run=args.dry_run, force=args.force)
    except Exception as exc:  # noqa: BLE001 - surface any failure clearly
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
