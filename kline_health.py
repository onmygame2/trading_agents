"""K-line coverage and freshness checks shared by health check and picker."""

from __future__ import annotations

import csv
import os
from typing import Dict, Iterable, List

from trading_calendar import count_trading_days_since, get_trading_date


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
KLINE_DIR = os.path.join(BASE_DIR, "data", "kline")


def _read_kline_meta(code: str) -> Dict:
    path = os.path.join(KLINE_DIR, f"{code}.csv")
    if not os.path.exists(path):
        return {"exists": False, "rows": 0, "latest_date": ""}
    rows = 0
    latest = ""
    try:
        with open(path, "r", encoding="utf-8", errors="ignore", newline="") as f:
            for row in csv.DictReader(f):
                d = str(row.get("date", ""))[:10]
                if d:
                    rows += 1
                    latest = max(latest, d)
    except Exception:
        return {"exists": True, "rows": 0, "latest_date": ""}
    return {"exists": True, "rows": rows, "latest_date": latest}


def summarize_kline_health(
    codes: Iterable[str],
    target_date: str = "",
    min_rows: int = 120,
    max_stale_trading_days: int = 1,
) -> Dict:
    codes = [str(c) for c in codes if c]
    target = target_date or get_trading_date()
    total = len(codes)
    existing = 0
    valid_rows = 0
    fresh = 0
    latest_dates: List[str] = []
    missing_sample: List[str] = []
    stale_sample: List[str] = []

    for code in codes:
        meta = _read_kline_meta(code)
        if not meta["exists"]:
            if len(missing_sample) < 10:
                missing_sample.append(code)
            continue
        existing += 1
        if meta["rows"] >= min_rows:
            valid_rows += 1
        latest = meta.get("latest_date") or ""
        if latest:
            latest_dates.append(latest)
            stale_days = count_trading_days_since(latest, target) if latest < target else 0
            if stale_days <= max_stale_trading_days:
                fresh += 1
            elif len(stale_sample) < 10:
                stale_sample.append(f"{code}:{latest}")

    def ratio(n: int) -> float:
        return n / total if total else 0.0

    return {
        "target_date": target,
        "total": total,
        "existing": existing,
        "valid_rows": valid_rows,
        "fresh": fresh,
        "coverage": ratio(existing),
        "valid_120_coverage": ratio(valid_rows),
        "fresh_coverage": ratio(fresh),
        "latest_date": max(latest_dates) if latest_dates else "",
        "oldest_latest_date": min(latest_dates) if latest_dates else "",
        "missing_sample": missing_sample,
        "stale_sample": stale_sample,
        "min_rows": min_rows,
        "max_stale_trading_days": max_stale_trading_days,
    }


def health_passes(summary: Dict, min_coverage: float = 0.8, min_valid: float = 0.75, min_fresh: float = 0.75) -> bool:
    return (
        summary.get("coverage", 0) >= min_coverage
        and summary.get("valid_120_coverage", 0) >= min_valid
        and summary.get("fresh_coverage", 0) >= min_fresh
    )
