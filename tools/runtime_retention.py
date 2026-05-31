#!/usr/bin/env python3
"""Safe runtime retention utility. Dry-run is the default."""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Set


MAX_APPEND_MB = 100
LOG_TAIL_MAX_AGE_DAYS = 7
PROBE_BACKUP_MAX_AGE_DAYS = 3
PROTECTED_NAMES = {
    ".env",
    "risk_state.json",
    "trades.csv",
    "trades_state.json",
}
PROTECTED_RUNTIME_NAMES = {
    "advisor_access_keys.json",
    "advisor_device_bindings.json",
    "post_close_cooldown_state.json",
    "watchlist_cache.json",
}


@dataclass
class Action:
    kind: str
    path: Path
    detail: str


def tracked_files(root: Path) -> Set[str]:
    try:
        out = subprocess.check_output(
            ["git", "-C", str(root), "ls-files"],
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        return {line.strip().replace("\\", "/") for line in out.splitlines() if line.strip()}
    except Exception:
        return set()


def rel(root: Path, path: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def is_protected(root: Path, path: Path, tracked: Set[str]) -> bool:
    name = path.name
    if name in PROTECTED_NAMES or name in PROTECTED_RUNTIME_NAMES:
        return True
    return rel(root, path) in tracked


def mb(value: int) -> float:
    return value / (1024 * 1024)


def old_enough(path: Path, days: int, now: float) -> bool:
    return now - path.stat().st_mtime >= days * 86400


def collect_actions(root: Path) -> List[Action]:
    now = time.time()
    runtime = root / "_runtime"
    backups = root / "backups"
    tracked = tracked_files(root)
    max_bytes = MAX_APPEND_MB * 1024 * 1024
    actions: List[Action] = []

    if runtime.exists():
        for path in runtime.glob("*.jsonl"):
            if path.is_file() and path.stat().st_size > max_bytes and not is_protected(root, path, tracked):
                actions.append(Action("truncate_tail", path, f"{mb(path.stat().st_size):.1f}MB -> <= {MAX_APPEND_MB}MB"))

        tails = runtime / "log_tails"
        if tails.exists():
            for path in tails.iterdir():
                if path.is_file() and old_enough(path, LOG_TAIL_MAX_AGE_DAYS, now) and not is_protected(root, path, tracked):
                    actions.append(Action("delete", path, f"older than {LOG_TAIL_MAX_AGE_DAYS} days"))

    for name in ("server.log", "vortex.log"):
        path = root / name
        if path.exists() and path.is_file() and path.stat().st_size > max_bytes and not is_protected(root, path, tracked):
            actions.append(Action("truncate_tail", path, f"{mb(path.stat().st_size):.1f}MB -> <= {MAX_APPEND_MB}MB"))

    if backups.exists():
        for path in backups.glob("futures_pipeline_probe_*"):
            if path.is_dir() and old_enough(path, PROBE_BACKUP_MAX_AGE_DAYS, now):
                actions.append(Action("delete_tree", path, f"older than {PROBE_BACKUP_MAX_AGE_DAYS} days"))

    return actions


def retain_tail(path: Path, max_bytes: int) -> None:
    size = path.stat().st_size
    if size <= max_bytes:
        return
    with path.open("rb") as fp:
        fp.seek(max(0, size - max_bytes))
        data = fp.read()
    first_newline = data.find(b"\n")
    if first_newline >= 0:
        data = data[first_newline + 1 :]
    tmp = path.with_suffix(path.suffix + ".retention.tmp")
    with tmp.open("wb") as fp:
        fp.write(data)
        fp.flush()
        os.fsync(fp.fileno())
    tmp.replace(path)


def apply_actions(root: Path, actions: Iterable[Action]) -> None:
    max_bytes = MAX_APPEND_MB * 1024 * 1024
    tracked = tracked_files(root)
    for action in actions:
        if is_protected(root, action.path, tracked):
            raise RuntimeError(f"protected path refused: {rel(root, action.path)}")
        if action.kind == "truncate_tail":
            retain_tail(action.path, max_bytes)
        elif action.kind == "delete":
            action.path.unlink(missing_ok=True)
        elif action.kind == "delete_tree":
            shutil.rmtree(action.path)
        else:
            raise RuntimeError(f"unsupported action: {action.kind}")


def main() -> int:
    parser = argparse.ArgumentParser(description="VORTEX safe runtime retention")
    parser.add_argument("--root", default=".", help="repository root")
    parser.add_argument("--dry-run", action="store_true", help="show actions only; this is also the default")
    parser.add_argument("--apply", action="store_true", help="apply retention actions explicitly")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    if not (root / "main.py").exists():
        raise SystemExit("ERROR: project root must contain main.py")
    if args.apply and args.dry_run:
        raise SystemExit("ERROR: choose either --dry-run or --apply")

    dry_run = not args.apply
    actions = collect_actions(root)
    print(f"RUNTIME_RETENTION dry_run={str(dry_run).lower()}")
    for action in actions:
        prefix = "would_" if dry_run else ""
        print(f"{prefix}{action.kind}: {rel(root, action.path)} | {action.detail}")
    if args.apply:
        apply_actions(root, actions)
    print(f"actions={len(actions)}")
    print("result: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
