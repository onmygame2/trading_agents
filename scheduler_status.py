"""
定时任务状态 — 供 Dashboard 展示 Cron 计划与最近执行日志
"""
from __future__ import annotations

import os
import subprocess
from datetime import datetime
from typing import Dict, List, Optional

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_DIR = os.path.join(BASE_DIR, "logs")

SCHEDULED_JOBS = [
    {
        "id": "kline_update",
        "label": "更新K线",
        "cron": "08:30 周一至周五",
        "log_file": "kline_update.log",
        "command": "update_kline.py",
    },
    {
        "id": "intraday",
        "label": "盘中交易 (先卖后买)",
        "cron": "9:30-15:00 每30分钟 周一至周五",
        "log_file": "intraday.log",
        "command": "daily_runner_v2.py",
    },
]


def _last_error_hint(filename: str) -> Optional[str]:
    tail = _tail_log(filename, 30)
    for ln in reversed(tail):
        if "Error" in ln or "失败" in ln or "Traceback" in ln or "ModuleNotFoundError" in ln:
            return ln[:200]
    return None


def _tail_log(filename: str, lines: int = 8) -> List[str]:
    path = os.path.join(LOG_DIR, filename)
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            content = f.readlines()
        return [ln.rstrip() for ln in content[-lines:]]
    except Exception:
        return []


def _log_mtime(filename: str) -> Optional[str]:
    path = os.path.join(LOG_DIR, filename)
    if not os.path.exists(path):
        return None
    try:
        ts = os.path.getmtime(path)
        return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return None


def get_cron_entries() -> List[str]:
    try:
        out = subprocess.run(
            ["crontab", "-l"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if out.returncode != 0:
            return []
        return [
            ln.strip()
            for ln in out.stdout.splitlines()
            if "workingFolder/quant" in ln or "daily_runner_v2" in ln
        ]
    except Exception:
        return []


def get_scheduler_status() -> Dict:
    from trading_calendar import is_trading_day, get_trading_date
    from trading_session import is_trading_session, session_label

    today = datetime.now().strftime("%Y-%m-%d")
    trading_today = is_trading_day(today)
    trading_date = get_trading_date()

    jobs = []
    for job in SCHEDULED_JOBS:
        jobs.append({
            **job,
            "last_run": _log_mtime(job["log_file"]),
            "log_tail": _tail_log(job["log_file"]),
            "last_error": _last_error_hint(job["log_file"]),
        })

    cron_lines = get_cron_entries()
    cron_installed = len(cron_lines) >= 2

    return {
        "today": today,
        "trading_today": trading_today,
        "trading_date": trading_date,
        "in_session": is_trading_session(),
        "session_label": session_label(),
        "cron_installed": cron_installed,
        "cron_entries": cron_lines,
        "jobs": jobs,
        "install_hint": "bash scripts/install_crontab.sh",
    }
