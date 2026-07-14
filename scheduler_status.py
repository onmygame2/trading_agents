"""
定时任务状态 — 供 Dashboard 展示 Cron 计划与最近执行日志
"""
from __future__ import annotations

import os
import platform
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
        "windows_task": "TradingAgents-KlineUpdate",
    },
    {
        "id": "intraday",
        "label": "盘中交易 (先卖后买)",
        "cron": "9:30-15:00 每30分钟 周一至周五",
        "log_file": "intraday.log",
        "command": "daily_runner_v2.py",
        "windows_task": "TradingAgents-DailyRun",
    },
    {
        "id": "agent_review",
        "label": "Agent 每日复盘",
        "cron": "15:15 周一至周五",
        "log_file": "agent_review.log",
        "command": "main.py agent review",
        "windows_task": "TradingAgents-AgentReview",
    },
    {
        "id": "weekly_optimize",
        "label": "周度策略优化",
        "cron": "20:00 每周五",
        "log_file": "weekly_opt.log",
        "command": "optimize_weekly.py",
        "windows_task": "TradingAgents-WeeklyOptimize",
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
        root_norm = BASE_DIR.replace("\\", "/")
        return [
            ln.strip()
            for ln in out.stdout.splitlines()
            if root_norm in ln.replace("\\", "/") or any(job["command"] in ln for job in SCHEDULED_JOBS)
        ]
    except Exception:
        return []


def get_windows_tasks(prefix: str = "TradingAgents") -> List[str]:
    if platform.system().lower() != "windows":
        return []
    try:
        out = subprocess.run(
            ["schtasks", "/Query", "/FO", "CSV", "/NH"],
            capture_output=True,
            text=True,
            timeout=8,
        )
        if out.returncode != 0:
            return []
        return [
            ln.strip()
            for ln in out.stdout.splitlines()
            if prefix in ln
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
    cron_lines = get_cron_entries()
    windows_tasks = get_windows_tasks()
    for job in SCHEDULED_JOBS:
        cron_match = any(job["command"] in ln for ln in cron_lines)
        win_match = any(job.get("windows_task", "") in ln for ln in windows_tasks)
        jobs.append({
            **job,
            "last_run": _log_mtime(job["log_file"]),
            "log_tail": _tail_log(job["log_file"]),
            "last_error": _last_error_hint(job["log_file"]),
            "installed": cron_match or win_match,
            "cron_installed": cron_match,
            "windows_installed": win_match,
        })

    cron_installed = bool(cron_lines) and all(any(job["command"] in ln for ln in cron_lines) for job in SCHEDULED_JOBS)
    windows_tasks_installed = bool(windows_tasks) and all(any(job.get("windows_task", "") in ln for ln in windows_tasks) for job in SCHEDULED_JOBS)

    return {
        "today": today,
        "trading_today": trading_today,
        "trading_date": trading_date,
        "in_session": is_trading_session(),
        "session_label": session_label(),
        "cron_installed": cron_installed,
        "cron_entries": cron_lines,
        "windows_tasks_installed": windows_tasks_installed,
        "windows_tasks": windows_tasks,
        "jobs": jobs,
        "install_hint": (
            "powershell -ExecutionPolicy Bypass -File scripts/install_windows_tasks.ps1"
            if platform.system().lower() == "windows"
            else "bash scripts/install_crontab.sh"
        ),
    }
