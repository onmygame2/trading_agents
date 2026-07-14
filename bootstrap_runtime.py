"""Bootstrap and diagnose a truthful local runtime without demo trades."""

from __future__ import annotations

import json
import os
from datetime import datetime
from typing import Dict, List


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
RUNTIME_DIRS = [
    "account",
    "account/paper",
    "data/kline",
    "knowledge_base",
    "knowledge_base/daily_reviews",
    "logs",
    "state",
    "state/paper_nav",
    "state/tasks",
]


def _ensure_runtime() -> Dict:
    for rel in RUNTIME_DIRS:
        os.makedirs(os.path.join(BASE_DIR, rel), exist_ok=True)

    from trade_engine_v2 import TRADE_LOG_FILE, get_account
    account = get_account()
    account.save()
    if not os.path.exists(TRADE_LOG_FILE):
        with open(TRADE_LOG_FILE, "w", encoding="utf-8") as f:
            json.dump([], f)

    from paper_trading_v2 import get_strategy_list, init_paper_accounts
    init_paper_accounts()

    from core.memory import TradingMemory
    from agent_runtime.memory_store import AgentMemoryStore
    TradingMemory()
    AgentMemoryStore()
    return {
        "account": True,
        "paper_accounts": len(get_strategy_list()),
        "memory": True,
    }


def _load_pool_codes() -> List[str]:
    path = os.path.join(BASE_DIR, "data", "stock_pool.json")
    try:
        with open(path, "r", encoding="utf-8") as f:
            pool = json.load(f)
        rows = pool if isinstance(pool, list) else pool.get("stocks", [])
        return [str(row.get("code") if isinstance(row, dict) else row) for row in rows]
    except Exception:
        return []


def diagnose() -> Dict:
    from kline_health import health_passes, summarize_kline_health
    from scheduler_status import get_scheduler_status

    codes = _load_pool_codes()
    kline = summarize_kline_health(codes) if codes else {
        "total": 0, "coverage": 0, "valid_120_coverage": 0, "fresh_coverage": 0,
    }
    account_path = os.path.join(BASE_DIR, "account", "account_state_v2.json")
    paper_dir = os.path.join(BASE_DIR, "account", "paper")
    pick_files = []
    kb_dir = os.path.join(BASE_DIR, "knowledge_base")
    if os.path.isdir(kb_dir):
        pick_files = sorted(
            f for f in os.listdir(kb_dir)
            if f.startswith("daily_pick_") and f.endswith(".json")
        )
    paper_accounts = []
    if os.path.isdir(paper_dir):
        paper_accounts = [
            f for f in os.listdir(paper_dir)
            if f.endswith(".json") and not f.endswith("_trades.json")
        ]
    try:
        from agent_runtime.orchestrator import get_latest_brief
        brief = get_latest_brief() or {}
    except Exception:
        brief = {}
    scheduler = get_scheduler_status()
    bootstrap_ready = (
        bool(codes)
        and os.path.exists(account_path)
        and len(paper_accounts) >= 6
        and kline.get("coverage", 0) >= 0.75
        and kline.get("valid_120_coverage", 0) >= 0.70
    )
    content_ready = bool(pick_files and brief)
    production_ready = (
        bootstrap_ready
        and content_ready
        and health_passes(kline, min_coverage=0.80, min_valid=0.80, min_fresh=0.75)
        and bool(scheduler.get("jobs"))
        and all(job.get("installed") for job in scheduler.get("jobs", []))
    )
    return {
        "checked_at": datetime.now().isoformat(timespec="seconds"),
        "bootstrap_ready": bootstrap_ready,
        "content_ready": content_ready,
        "production_ready": production_ready,
        "stock_pool": len(codes),
        "kline": kline,
        "account_exists": os.path.exists(account_path),
        "paper_accounts": len(paper_accounts),
        "latest_pick": pick_files[-1] if pick_files else None,
        "latest_brief_date": brief.get("date"),
        "scheduler_installed": sum(1 for j in scheduler.get("jobs", []) if j.get("installed")),
        "next_actions": _next_actions(
            codes, kline, os.path.exists(account_path), len(paper_accounts), pick_files, brief, scheduler
        ),
    }


def _next_actions(codes, kline, account_exists, paper_count, picks, brief, scheduler) -> List[str]:
    actions = []
    if not codes:
        actions.append("运行 python scripts/rebuild_stock_pool.py")
    if kline.get("coverage", 0) < 0.75:
        actions.append("运行 python update_kline.py --init-missing --backend akshare")
    if not account_exists or paper_count < 6:
        actions.append("运行 python main.py doctor --fix")
    if not picks:
        actions.append("运行 python main.py doctor --fix --run-first-day")
    if not brief:
        actions.append("运行 python main.py agent review")
    if not any(j.get("installed") for j in scheduler.get("jobs", [])):
        actions.append("安装当前平台的日频调度任务")
    return actions


def run_doctor(fix: bool = False, run_first_day: bool = False) -> Dict:
    fixes = {}
    if fix:
        fixes = _ensure_runtime()
    preview = None
    review = None
    if run_first_day:
        if not fix:
            fixes = _ensure_runtime()
        from trading_calendar import get_trading_date
        from global_stock_picker import run_picker
        from core.market_state import track_market_state
        from agent_runtime.orchestrator import run_daily_review

        date = get_trading_date()
        preview = run_picker(date=date, execute_trades=False)
        try:
            track_market_state(date)
        except Exception as exc:
            fixes["market_state_warning"] = str(exc)
        review = run_daily_review(date=date)
    result = diagnose()
    result["fixes"] = fixes
    if preview is not None:
        result["first_day"] = {
            "date": preview.get("date"),
            "execution_status": preview.get("execution_status"),
            "recommendations": len(preview.get("top_picks", [])),
            "planned_buys": len(preview.get("buy_picks", [])),
            "actual_buys": len(preview.get("buy_actions", [])),
        }
    if review is not None:
        result["agent_review"] = {
            "date": review.get("date"),
            "status": review.get("status"),
        }
    return result

