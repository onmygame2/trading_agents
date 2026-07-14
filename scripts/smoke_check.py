#!/usr/bin/env python3
"""Minimal regression smoke checks for Agent + Dashboard APIs."""

import json
import os
import py_compile
import sys
import importlib

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)


PY_FILES = [
    "agent_runtime/agents/reviewer.py",
    "agent_runtime/memory_store.py",
    "agent_runtime/orchestrator.py",
    "agent_runtime/trading_memory_bridge.py",
    "backtest_v2.py",
    "core/memory.py",
    "daily_runner_v2.py",
    "global_stock_picker.py",
    "kline_health.py",
    "scheduler_status.py",
    "trade_engine_v2.py",
    "task_runner.py",
    "dashboard/app.py",
]


def compile_check():
    for rel in PY_FILES:
        py_compile.compile(os.path.join(BASE_DIR, rel), doraise=True)
    print(f"py_compile: {len(PY_FILES)} files ok")


def dependency_check():
    modules = ["numpy", "pandas", "flask", "yaml", "baostock", "akshare"]
    failed = []
    for name in modules:
        try:
            importlib.import_module(name)
        except Exception as exc:
            failed.append(f"{name}: {exc}")
    if failed:
        hint = "Run: powershell -ExecutionPolicy Bypass -File scripts/setup_windows.ps1"
        raise RuntimeError("dependency import failed:\n" + "\n".join(failed) + "\n" + hint)
    print(f"dependencies: {len(modules)} modules ok")


def dashboard_api_check():
    from dashboard.app import app

    client = app.test_client()
    paths = [
        "/api/agent/daily_brief",
        "/api/dashboard/workspace",
        "/api/dashboard/strategy_center",
        "/api/dashboard/memory_center",
        "/api/memory/health",
    ]
    for path in paths:
        resp = client.get(path)
        if resp.status_code >= 500:
            raise RuntimeError(f"{path} failed: {resp.status_code} {resp.get_data(as_text=True)[:200]}")
        data = resp.get_json(silent=True)
        if data is None:
            raise RuntimeError(f"{path} did not return JSON")
        print(f"{path}: {resp.status_code} {sorted(data.keys())}")


def agent_read_check():
    from agent_runtime.orchestrator import get_latest_brief

    brief = get_latest_brief()
    print("agent latest brief:", json.dumps({
        "exists": bool(brief),
        "date": (brief or {}).get("date"),
        "status": (brief or {}).get("status"),
    }, ensure_ascii=False))


def trading_rule_check():
    from trade_engine_v2 import evaluate_sell_decision, is_limit_up_move, resolve_trade_rules

    rules = resolve_trade_rules("composite")
    pos = {"avg_price": 10.0, "high_price": 10.0, "hold_days": 1}
    if "硬止损" not in evaluate_sell_decision(pos, 9.1, rules):
        raise RuntimeError("sell rule check failed: stop loss")
    pos = {"avg_price": 10.0, "high_price": 12.0, "hold_days": 5}
    if "移动止盈" not in evaluate_sell_decision(pos, 10.4, rules):
        raise RuntimeError("sell rule check failed: trailing stop")
    if not is_limit_up_move("600000", 9.6):
        raise RuntimeError("sell rule check failed: main-board limit up")
    if is_limit_up_move("688001", 9.8):
        raise RuntimeError("sell rule check failed: STAR-board limit up")
    print("trading rules: ok")


def kline_coverage_check():
    pool_path = os.path.join(BASE_DIR, "data", "stock_pool.json")
    kline_dir = os.path.join(BASE_DIR, "data", "kline")
    if not os.path.exists(pool_path):
        print("kline coverage: stock_pool missing")
        return
    with open(pool_path, "r", encoding="utf-8") as f:
        pool = json.load(f)
    pool_count = len(pool) if isinstance(pool, list) else len(pool.get("stocks", []))
    kline_count = len([f for f in os.listdir(kline_dir) if f.endswith(".csv")]) if os.path.isdir(kline_dir) else 0
    print(f"kline coverage: {kline_count}/{pool_count}")


def memory_bridge_check():
    from agent_runtime.trading_memory_bridge import _signal_strategy

    if _signal_strategy({"strategy_id": "demo"}) != "demo":
        raise RuntimeError("memory bridge strategy mapping failed")
    print("memory bridge: ok")


def main():
    dependency_check()
    compile_check()
    trading_rule_check()
    memory_bridge_check()
    kline_coverage_check()
    agent_read_check()
    dashboard_api_check()


if __name__ == "__main__":
    main()
