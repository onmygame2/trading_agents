#!/usr/bin/env python3
"""Production-readiness health check for the daily Agent quant system."""

import argparse
import json
import os
import sys
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE_DIR))


def status(ok: bool, name: str, detail: str = "") -> dict:
    mark = "OK" if ok else "WARN"
    print(f"[{mark}] {name}" + (f": {detail}" if detail else ""))
    return {"ok": ok, "name": name, "detail": detail}


def check_dependencies():
    failed = []
    for mod in ["numpy", "pandas", "flask", "yaml", "baostock", "akshare"]:
        try:
            __import__(mod)
        except Exception as exc:
            failed.append(f"{mod}: {exc}")
    return status(not failed, "dependencies", "; ".join(failed) or "all imports ok")


def load_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def check_demo_state():
    hits = []
    meta = BASE_DIR / "data" / "simulated_backfill_meta.json"
    if meta.exists():
        hits.append(str(meta.relative_to(BASE_DIR)))
    for rel in ["account/account_state_v2.json"]:
        data = load_json(BASE_DIR / rel, {})
        if data.get("source") == "simulated_backfill":
            hits.append(rel)
    latest = sorted((BASE_DIR / "knowledge_base").glob("daily_pick_*.json"))
    if latest:
        data = load_json(latest[-1], {})
        if data.get("pool_mode") == "simulated_backfill" or data.get("source") == "simulated_backfill":
            hits.append(str(latest[-1].relative_to(BASE_DIR)))
    return status(not hits, "demo data", "no simulated runtime markers" if not hits else ", ".join(hits))


def check_kline(min_coverage: float, min_fresh_coverage: float):
    pool = load_json(BASE_DIR / "data" / "stock_pool.json", [])
    pool_count = len(pool) if isinstance(pool, list) else len(pool.get("stocks", []))
    codes = [s.get("code") if isinstance(s, dict) else s for s in pool]
    from kline_health import summarize_kline_health
    summary = summarize_kline_health(codes)
    ok = (
        pool_count > 0
        and summary["coverage"] >= min_coverage
        and summary["valid_120_coverage"] >= min_coverage
        and summary["fresh_coverage"] >= min_fresh_coverage
    )
    detail = (
        f"files={summary['existing']}/{pool_count} ({summary['coverage']:.1%}), "
        f"valid120={summary['valid_rows']}/{pool_count} ({summary['valid_120_coverage']:.1%}), "
        f"fresh={summary['fresh']}/{pool_count} ({summary['fresh_coverage']:.1%}), "
        f"latest={summary['latest_date']}, thresholds=coverage/valid {min_coverage:.0%}, fresh {min_fresh_coverage:.0%}"
    )
    return status(ok, "kline coverage/freshness", detail)


def check_realtime_probe():
    try:
        from market_data import get_realtime_prices
        prices = get_realtime_prices(["600000", "000001"])
        ok = any(v and v > 0 for v in prices.values())
        return status(ok, "realtime quote", f"{prices}" if prices else "empty response")
    except Exception as exc:
        return status(False, "realtime quote", str(exc))


def check_account():
    account = load_json(BASE_DIR / "account" / "account_state_v2.json", {})
    if not account:
        return status(False, "account", "account/account_state_v2.json missing")
    positions = account.get("positions") or {}
    return status(True, "account", f"cash={account.get('cash', 0):.2f}, positions={len(positions)}")


def check_memory():
    try:
        from core.memory import TradingMemory
        summary = TradingMemory().get_memory_summary()
        detail = f"signals={summary.get('signals', 0)}, market={summary.get('market_snapshots', 0)}, lessons={summary.get('lessons', 0)}"
        return status(True, "trading memory", detail)
    except Exception as exc:
        return status(False, "trading memory", str(exc))


def check_memory_purity():
    try:
        import sqlite3
        db_path = BASE_DIR / "knowledge_base" / "trading_memory.db"
        if not db_path.exists():
            return status(False, "memory purity", "trading_memory.db missing")
        conn = sqlite3.connect(db_path)
        counts = {}
        for table in ["signals", "market_state", "strategy_perf", "lessons"]:
            try:
                counts[table] = conn.execute(
                    f"SELECT COUNT(*) FROM {table} WHERE source='simulated_backfill'"
                ).fetchone()[0]
            except Exception:
                counts[table] = 0
        conn.close()
        total = sum(counts.values())
        return status(total == 0, "memory purity", f"simulated rows={total} {counts}")
    except Exception as exc:
        return status(False, "memory purity", str(exc))


def check_agent_brief():
    try:
        from agent_runtime.orchestrator import get_latest_brief
        brief = get_latest_brief()
        return status(bool(brief), "agent brief", f"{(brief or {}).get('date', 'missing')} {(brief or {}).get('status', '')}")
    except Exception as exc:
        return status(False, "agent brief", str(exc))


def check_dashboard_api():
    try:
        from dashboard.app import app
        client = app.test_client()
        resp = client.get("/api/dashboard/workspace")
        return status(resp.status_code == 200, "dashboard api", f"/api/dashboard/workspace {resp.status_code}")
    except Exception as exc:
        return status(False, "dashboard api", str(exc))


def check_scheduler_status():
    try:
        from scheduler_status import get_scheduler_status
        data = get_scheduler_status()
        jobs = data.get("jobs") or []
        installed = [j for j in jobs if j.get("installed")]
        errors = [j for j in jobs if j.get("last_error")]
        ok = len(installed) == len(jobs) and not errors
        detail = f"installed={len(installed)}/{len(jobs)}, errors={len(errors)}, hint={data.get('install_hint', '')}"
        return status(ok, "scheduler", detail)
    except Exception as exc:
        return status(False, "scheduler", str(exc))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--min-kline-coverage", type=float, default=0.8)
    parser.add_argument("--min-kline-fresh-coverage", type=float, default=0.75)
    args = parser.parse_args()

    checks = [
        check_dependencies(),
        check_demo_state(),
        check_kline(args.min_kline_coverage, args.min_kline_fresh_coverage),
        check_realtime_probe(),
        check_account(),
        check_memory(),
        check_memory_purity(),
        check_agent_brief(),
        check_dashboard_api(),
        check_scheduler_status(),
    ]
    failed = [c for c in checks if not c["ok"]]
    print(f"\nsummary: {len(checks) - len(failed)}/{len(checks)} passed")
    if failed:
        print("not production-ready yet")
        return 1
    print("production-ready checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
