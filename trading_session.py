"""A股交易时段 — 盘中买卖不限固定时点"""
from datetime import datetime, time
from typing import Optional

from trading_calendar import is_trading_day


def trade_datetime(dt: Optional[datetime] = None) -> str:
    """当前成交时间戳（用于交易日志）"""
    return (dt or datetime.now()).strftime("%Y-%m-%d %H:%M:%S")


def is_trading_session(dt: Optional[datetime] = None) -> bool:
    """是否在 A 股交易时段 (9:30-11:30, 13:00-15:00 且为交易日)"""
    dt = dt or datetime.now()
    date_str = dt.strftime("%Y-%m-%d")
    if not is_trading_day(date_str):
        return False
    t = dt.time()
    if time(9, 30) <= t <= time(11, 30):
        return True
    if time(13, 0) <= t <= time(15, 0):
        return True
    return False


def session_label(dt: Optional[datetime] = None) -> str:
    dt = dt or datetime.now()
    if not is_trading_session(dt):
        return "非交易时段"
    t = dt.time()
    if t <= time(11, 30):
        return "上午盘"
    return "下午盘"
