#!/usr/bin/env python3
"""Backup and reset simulated backfill runtime state.

Default mode is dry-run. Use --apply to move demo runtime files into a timestamped
backup folder. Source code and configuration files are never removed.
"""

import argparse
import json
import os
import shutil
from datetime import datetime
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parents[1]
BACKUP_ROOT = BASE_DIR / "data" / "backups" / "demo_state"

RUNTIME_PATHS = [
    "data/simulated_backfill_meta.json",
    "account/account_state_v2.json",
    "account/trade_log_v2.json",
    "account/paper",
    "state/paper_nav",
    "knowledge_base/daily_reviews",
]

DAILY_PICK_GLOBS = [
    "knowledge_base/daily_pick_2026-06-*.json",
    "knowledge_base/daily_pick_2026-06-*.md",
    "knowledge_base/daily_pick_2026-07-*.json",
    "knowledge_base/daily_pick_2026-07-*.md",
]


def _contains_simulated(path: Path) -> bool:
    if path.is_dir():
        for child in path.rglob("*"):
            if child.is_file() and _contains_simulated(child):
                return True
        return False
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
        return "simulated_backfill" in text
    except Exception:
        return False


def collect_demo_paths():
    paths = []
    for rel in RUNTIME_PATHS:
        path = BASE_DIR / rel
        if path.exists() and (rel == "data/simulated_backfill_meta.json" or _contains_simulated(path)):
            paths.append(path)
    for pattern in DAILY_PICK_GLOBS:
        for path in BASE_DIR.glob(pattern):
            if _contains_simulated(path):
                paths.append(path)
    return sorted(set(paths))


def backup_path(path: Path, backup_dir: Path) -> Path:
    rel = path.relative_to(BASE_DIR)
    return backup_dir / rel


def main():
    parser = argparse.ArgumentParser(description="Backup/reset simulated backfill runtime state")
    parser.add_argument("--apply", action="store_true", help="move matched demo files to backup")
    args = parser.parse_args()

    paths = collect_demo_paths()
    print(f"matched demo paths: {len(paths)}")
    for path in paths:
        print(f"  {path.relative_to(BASE_DIR)}")

    if not args.apply:
        print("\ndry-run only. Re-run with --apply to move these files into data/backups/demo_state/.")
        return

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_dir = BACKUP_ROOT / stamp
    manifest = []
    for path in paths:
        target = backup_path(path, backup_dir)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(path), str(target))
        manifest.append({
            "source": str(path.relative_to(BASE_DIR)),
            "backup": str(target.relative_to(BASE_DIR)),
        })

    account_dir = BASE_DIR / "account"
    account_dir.mkdir(parents=True, exist_ok=True)
    clean_account = {
        "cash": 100000.0,
        "initial_cash": 100000.0,
        "positions": {},
        "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "source": "live",
    }
    (account_dir / "account_state_v2.json").write_text(
        json.dumps(clean_account, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (account_dir / "trade_log_v2.json").write_text("[]\n", encoding="utf-8")

    backup_dir.mkdir(parents=True, exist_ok=True)
    (backup_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"\nbackup complete: {backup_dir.relative_to(BASE_DIR)}")


if __name__ == "__main__":
    main()
