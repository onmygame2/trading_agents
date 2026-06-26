"""A-share trading calendar helpers."""

from datetime import datetime, timedelta
from typing import List, Optional

# 2025-2026 A股休市日 (上交所)
HOLIDAYS = {
    "2025-01-01",
    "2025-01-28", "2025-01-29", "2025-01-30", "2025-01-31",
    "2025-02-01", "2025-02-02", "2025-02-03", "2025-02-04",
    "2025-04-04", "2025-04-05", "2025-04-06",
    "2025-05-01", "2025-05-02", "2025-05-03", "2025-05-04", "2025-05-05",
    "2025-05-31", "2025-06-01", "2025-06-02",
    "2025-10-01", "2025-10-02", "2025-10-03", "2025-10-04",
    "2025-10-05", "2025-10-06", "2025-10-07", "2025-10-08",
    "2026-01-01", "2026-01-02", "2026-01-03",
    "2026-02-15", "2026-02-16", "2026-02-17", "2026-02-18",
    "2026-02-19", "2026-02-20", "2026-02-21", "2026-02-22", "2026-02-23",
    "2026-04-04", "2026-04-05", "2026-04-06",
    "2026-05-01", "2026-05-02", "2026-05-03", "2026-05-04", "2026-05-05",
    "2026-06-19", "2026-06-20", "2026-06-21",
    "2026-09-25", "2026-09-26", "2026-09-27",
    "2026-10-01", "2026-10-02", "2026-10-03", "2026-10-04",
    "2026-10-05", "2026-10-06", "2026-10-07",
}


def is_trading_day(date_str: str) -> bool:
    dt = datetime.strptime(date_str, "%Y-%m-%d")
    if dt.weekday() >= 5:
        return False
    return date_str not in HOLIDAYS


def get_trading_date(reference: Optional[datetime] = None) -> str:
    """Return the latest trading day on or before reference date."""
    ref = reference or datetime.now()
    for _ in range(10):
        date_str = ref.strftime("%Y-%m-%d")
        if is_trading_day(date_str):
            return date_str
        ref -= timedelta(days=1)
    return ref.strftime("%Y-%m-%d")


def next_trading_day(date_str: str) -> str:
    dt = datetime.strptime(date_str, "%Y-%m-%d") + timedelta(days=1)
    for _ in range(10):
        candidate = dt.strftime("%Y-%m-%d")
        if is_trading_day(candidate):
            return candidate
        dt += timedelta(days=1)
    return dt.strftime("%Y-%m-%d")


def count_trading_days_since(buy_date: str, current_date: str) -> int:
    """买入日之后到 current_date（含）之间的交易日数；买入当日不计入。"""
    if not buy_date or buy_date >= current_date:
        return 0
    days = 0
    dt = datetime.strptime(buy_date, "%Y-%m-%d") + timedelta(days=1)
    end = datetime.strptime(current_date, "%Y-%m-%d")
    while dt <= end:
        if is_trading_day(dt.strftime("%Y-%m-%d")):
            days += 1
        dt += timedelta(days=1)
    return days
