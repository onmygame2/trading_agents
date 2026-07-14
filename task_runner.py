"""
Dashboard 后台任务调度器

支持在 Dashboard 一键触发，无需手动 python xxx.py:
- backtest_v2   策略回测
- daily_picker  每日选股+买入
- daily_sell    早盘卖出检查
- update_kline  更新K线数据
- init_kline_missing 初始化缺失K线
- agent_review  Agent 每日复盘
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import threading
import traceback
import uuid
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TASKS_DIR = os.path.join(BASE_DIR, "state", "tasks")
VENV_PYTHON_CANDIDATES = [
    os.path.join(BASE_DIR, "venv_akshare", "Scripts", "python.exe"),
    os.path.join(BASE_DIR, "venv_akshare", "bin", "python"),
    os.path.join(BASE_DIR, ".venv", "Scripts", "python.exe"),
    os.path.join(BASE_DIR, ".venv", "bin", "python"),
]


def _python_exe() -> str:
    for candidate in VENV_PYTHON_CANDIDATES:
        if os.path.isfile(candidate):
            return candidate
    return sys.executable
os.makedirs(TASKS_DIR, exist_ok=True)

logger = logging.getLogger(__name__)

_lock = threading.Lock()
_running_types: set = set()


def _task_path(task_id: str) -> str:
    return os.path.join(TASKS_DIR, f"{task_id}.json")


def _save_task(task: Dict):
    with open(_task_path(task["id"]), "w", encoding="utf-8") as f:
        json.dump(task, f, ensure_ascii=False, indent=2)


def _load_task(task_id: str) -> Optional[Dict]:
    path = _task_path(task_id)
    if not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def list_tasks(limit: int = 20) -> List[Dict]:
    files = sorted(
        [f for f in os.listdir(TASKS_DIR) if f.endswith(".json")],
        reverse=True,
    )[:limit]
    tasks = []
    for fname in files:
        try:
            with open(os.path.join(TASKS_DIR, fname), "r", encoding="utf-8") as f:
                tasks.append(json.load(f))
        except Exception:
            pass
    return tasks


def recover_stale_tasks(max_running_minutes: int = 240):
    """Mark tasks left running by a previous Flask process as failed."""
    now = datetime.now()
    for task in list_tasks(limit=500):
        if task.get("status") not in ("pending", "running"):
            continue
        ts = task.get("started_at") or task.get("created_at")
        try:
            started = datetime.strptime(ts, "%Y-%m-%d %H:%M:%S")
        except Exception:
            started = now
        minutes = (now - started).total_seconds() / 60
        if task.get("status") == "pending" or minutes >= max_running_minutes:
            task.update({
                "status": "error",
                "progress": 100,
                "message": "任务进程已中断",
                "error": "Flask/IDE 重启后恢复为失败状态",
                "finished_at": now.strftime("%Y-%m-%d %H:%M:%S"),
            })
            _save_task(task)


def get_task(task_id: str) -> Optional[Dict]:
    return _load_task(task_id)


def _set_status(task_id: str, **kwargs):
    task = _load_task(task_id)
    if not task:
        return
    task.update(kwargs)
    _save_task(task)


def _run_backtest_v2(task_id: str, params: Dict) -> Dict:
    from backtest_v2 import run_backtest, save_reports

    start = params.get("start")
    end = params.get("end")
    if params.get("quick") and not start:
        from backtest_v2 import default_backtest_range
        _, default_end = default_backtest_range()
        end = end or default_end
        start = (datetime.strptime(end, "%Y-%m-%d") - timedelta(days=90)).strftime("%Y-%m-%d")
        params.setdefault("top_n", 3)
        params.setdefault("pool_top", 300)
    elif not start:
        from backtest_v2 import default_backtest_range
        start, end = default_backtest_range()
    else:
        end = end or datetime.now().strftime("%Y-%m-%d")
    pool_mode = params.get("pool_mode", "mainline")
    sector_top = params.get("sector_top", 10)
    per_sector = params.get("per_sector", 10)
    pool_top = params.get("pool_top", 500)
    if pool_top == 0:
        pool_top = None
    min_score = params.get("min_score", 45)
    top_n = params.get("top_n", 3)

    pool_hint = (
        "主线放量" if pool_mode == "mainline"
        else (f"板块{sector_top}x{per_sector}" if pool_mode == "sector"
              else (f"Top{pool_top}" if pool_top else "全池"))
    )
    _set_status(task_id, progress=10, message=f"加载K线 {start}~{end} ({pool_hint})...")

    def progress_cb(pct, msg):
        _set_status(task_id, progress=pct, message=msg)

    result = run_backtest(
        start=start,
        end=end,
        pool_top=pool_top,
        pool_mode=pool_mode,
        sector_top=sector_top,
        per_sector=per_sector,
        min_score=min_score,
        top_n=top_n,
    )
    strategies_snapshot = dict(result.get("strategies", {}))
    _set_status(task_id, progress=90, message="保存报告...")
    tag = datetime.now().strftime("%Y%m%d_%H%M%S")
    summary_path = save_reports(result, tag)
    ranking = sorted(strategies_snapshot.values(), key=lambda x: x.get("return_pct", 0), reverse=True)
    return {
        "summary_path": summary_path,
        "tag": tag,
        "start": start,
        "end": end,
        "pool_size": result.get("pool_size"),
        "best_strategy": ranking[0]["display_name"] if ranking else None,
        "best_return": ranking[0]["return_pct"] if ranking else 0,
    }


def _run_daily_picker(task_id: str, params: Dict) -> Dict:
    from daily_runner_v2 import run_intraday_flow
    from trading_calendar import get_trading_date

    date = params.get("date") or get_trading_date()
    pool_mode = params.get("pool_mode", "mainline")
    top_n = int(params.get("top_n", 10))
    min_score = int(params.get("min_score", 40))
    _set_status(task_id, progress=10, message=f"盘中交易 {date} ({pool_mode}, 先卖后买)...")

    result = run_intraday_flow(date, top_n=top_n, min_score=min_score, pool_mode=pool_mode)
    return {
        "date": date,
        "total_pool": result.get("total_pool", 0),
        "total_scored": result.get("total_scored", 0),
        "top_picks": len(result.get("top_picks", [])),
        "buy_actions": len(result.get("buy_actions", [])),
        "sell_actions": len(result.get("sell_actions", [])),
        "account_value": result.get("account_value", 0),
    }


def _run_daily_sell(task_id: str, params: Dict) -> Dict:
    from daily_runner_v2 import run_sell_flow
    from trading_calendar import get_trading_date

    date = params.get("date") or get_trading_date()
    _set_status(task_id, progress=30, message=f"卖出检查 {date}...")
    result = run_sell_flow(date)
    return {
        "date": date,
        "sell_count": len(result.get("sell_actions", [])),
        "account_value": result.get("account_value", 0),
        "positions": len(result.get("positions", [])),
    }


def _run_update_kline(task_id: str, params: Dict) -> Dict:
    top = params.get("top", 500)
    days = params.get("days", 30)
    backend = params.get("backend", "")
    snapshot = bool(params.get("snapshot", False))
    cmd = [_python_exe(), os.path.join(BASE_DIR, "update_kline.py"), "--top", str(top), "--days", str(days)]
    if backend:
        cmd.extend(["--backend", backend])
    if snapshot:
        cmd.append("--snapshot")
    _set_status(task_id, progress=10, message=f"更新K线 Top{top}...")
    proc = subprocess.run(
        cmd,
        cwd=BASE_DIR,
        capture_output=True,
        text=True,
        timeout=3600,
    )
    output = (proc.stdout or "") + (proc.stderr or "")
    tail = "\n".join(output.strip().splitlines()[-15:])
    if proc.returncode != 0:
        raise RuntimeError(f"K线更新失败 (code={proc.returncode})\n{tail}")
    return {"output_tail": tail, "top": top, "days": days}


def _run_init_kline_missing(task_id: str, params: Dict) -> Dict:
    top = params.get("top", 200)
    offset = params.get("offset", 0)
    days = params.get("days", params.get("init_days", 180))
    backend = params.get("backend", "akshare")
    cmd = [
        _python_exe(), os.path.join(BASE_DIR, "update_kline.py"),
        "--init-missing", "--top", str(top), "--offset", str(offset),
        "--init-days", str(days), "--backend", backend,
    ]
    _set_status(task_id, progress=10, message=f"初始化缺失K线 offset={offset} top={top}...")
    proc = subprocess.run(
        cmd,
        cwd=BASE_DIR,
        capture_output=True,
        text=True,
        timeout=7200,
    )
    output = (proc.stdout or "") + (proc.stderr or "")
    tail = "\n".join(output.strip().splitlines()[-20:])
    if proc.returncode != 0:
        raise RuntimeError(f"缺失K线初始化失败 (code={proc.returncode})\n{tail}")
    return {"output_tail": tail, "top": top, "offset": offset, "days": days, "backend": backend}


def _run_agent_review(task_id: str, params: Dict) -> Dict:
    from agent_runtime.orchestrator import run_daily_review

    date = params.get("date")
    _set_status(task_id, progress=15, message="采集并记录市场状态...")
    market_state = {}
    try:
        from core.market_state import track_market_state
        market_state = track_market_state(date)
    except Exception as e:
        logger.warning("市场状态采集跳过: %s", e)
    _set_status(task_id, progress=40, message="读取账户、选股、记忆库...")
    brief = run_daily_review(date=date)
    _set_status(task_id, progress=90, message="写入 Agent 日报和知识库文件...")
    metrics = brief.get("metrics") or {}
    return {
        "date": brief.get("date"),
        "status": brief.get("status"),
        "summary": brief.get("summary"),
        "risk_flags": brief.get("risk_flags", []),
        "action_items": brief.get("action_items", []),
        "total_equity": metrics.get("total_equity"),
        "total_return_pct": metrics.get("total_return_pct"),
        "market_sentiment": (market_state or {}).get("sentiment"),
        "review_dir": "knowledge_base/daily_reviews",
    }


def _run_bootstrap_runtime(task_id: str, params: Dict) -> Dict:
    from bootstrap_runtime import run_doctor
    _set_status(task_id, progress=20, message="初始化账户、纸面盘和记忆库...")
    result = run_doctor(
        fix=True,
        run_first_day=bool(params.get("run_first_day", True)),
    )
    return {
        "bootstrap_ready": result.get("bootstrap_ready"),
        "content_ready": result.get("content_ready"),
        "production_ready": result.get("production_ready"),
        "first_day": result.get("first_day"),
        "next_actions": result.get("next_actions", []),
    }


TASK_HANDLERS = {
    "backtest_v2": _run_backtest_v2,
    "daily_picker": _run_daily_picker,
    "daily_sell": _run_daily_sell,
    "update_kline": _run_update_kline,
    "init_kline_missing": _run_init_kline_missing,
    "agent_review": _run_agent_review,
    "bootstrap_runtime": _run_bootstrap_runtime,
}

TASK_LABELS = {
    "backtest_v2": "策略回测",
    "daily_picker": "盘中交易 (卖+买)",
    "daily_sell": "卖出检查",
    "update_kline": "更新K线",
    "init_kline_missing": "初始化缺失K线",
    "agent_review": "Agent 每日复盘",
    "bootstrap_runtime": "初始化真实运行态",
}

recover_stale_tasks()


def is_type_running(task_type: str) -> bool:
    with _lock:
        return task_type in _running_types


def submit_task(task_type: str, params: Optional[Dict] = None) -> Dict:
    if task_type not in TASK_HANDLERS:
        return {"ok": False, "error": f"未知任务类型: {task_type}"}

    with _lock:
        if task_type in _running_types:
            return {"ok": False, "error": f"{TASK_LABELS.get(task_type, task_type)} 正在运行中，请稍候"}

    params = params or {}
    task_id = datetime.now().strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:6]
    task = {
        "id": task_id,
        "type": task_type,
        "label": TASK_LABELS.get(task_type, task_type),
        "params": params,
        "status": "pending",
        "progress": 0,
        "message": "排队中...",
        "result": None,
        "error": None,
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "started_at": None,
        "finished_at": None,
    }
    _save_task(task)

    thread = threading.Thread(target=_execute, args=(task_id, task_type, params), daemon=True)
    thread.start()
    return {"ok": True, "task_id": task_id}


def _execute(task_id: str, task_type: str, params: Dict):
    with _lock:
        _running_types.add(task_type)

    _set_status(
        task_id,
        status="running",
        progress=5,
        message="启动中...",
        started_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    )
    try:
        handler = TASK_HANDLERS[task_type]
        result = handler(task_id, params)
        _set_status(
            task_id,
            status="done",
            progress=100,
            message="完成",
            result=result,
            finished_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        )
    except Exception as e:
        logger.exception("Task %s failed", task_id)
        _set_status(
            task_id,
            status="error",
            progress=100,
            message="失败",
            error=str(e),
            error_detail=traceback.format_exc()[-2000:],
            finished_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        )
    finally:
        with _lock:
            _running_types.discard(task_type)
