"""K线复权断层检测与修复 — 多数据源合并时价格尺度不一致"""
from typing import Optional
import logging
import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# A股普通涨跌停约10%，创业板/科创板20%；>22% 视为尺度断层（非真实行情）
JUMP_THRESHOLD = 0.22


def _row_return(prev_close: float, cur_close: float) -> float:
    if not prev_close or prev_close <= 0 or not cur_close:
        return 0.0
    return cur_close / prev_close - 1.0


def repair_adj_discontinuities(df: pd.DataFrame, threshold: float = JUMP_THRESHOLD) -> pd.DataFrame:
    """检测 close 跳空，将断层前的 OHLC 按比率缩放到断层后尺度（前复权对齐）"""
    if df is None or df.empty or "close" not in df.columns:
        return df
    out = df.copy()
    for col in ("open", "high", "low", "close"):
        if col in out.columns:
            out[col] = pd.to_numeric(out[col], errors="coerce")
    close = out["close"].values
    fixes = 0
    for i in range(1, len(close)):
        prev_c = close[i - 1]
        cur_c = close[i]
        if not prev_c or not cur_c or np.isnan(prev_c) or np.isnan(cur_c):
            continue
        ret = _row_return(prev_c, cur_c)
        if abs(ret) <= threshold:
            continue
        ratio = cur_c / prev_c
        if ratio <= 0:
            continue
        for col in ("open", "high", "low", "close"):
            if col in out.columns:
                out.iloc[:i, out.columns.get_loc(col)] = out.iloc[:i][col] * ratio
        close = out["close"].values
        fixes += 1
        logger.debug("复权修复 %s 第%d行 ratio=%.4f ret=%.1f%%", out.iloc[i].get("date", i), i, ratio, ret * 100)
    if fixes:
        logger.info("K线复权修复 %d 处断层", fixes)
    return out


def sanitize_kline_df(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return df
    out = repair_adj_discontinuities(df)
    if "change_pct" in out.columns and "close" in out.columns:
        close = pd.to_numeric(out["close"], errors="coerce")
        prev = close.shift(1)
        out["change_pct"] = ((close / prev - 1) * 100).where(prev > 0)
    return out.sort_values("date").reset_index(drop=True)


def is_suspicious_bar(prev_close: float, open_p: float, close_p: float,
                      threshold: float = JUMP_THRESHOLD) -> bool:
    """单根 K 线是否疑似坏数据"""
    if not prev_close or prev_close <= 0:
        return False
    if abs(_row_return(prev_close, open_p)) > threshold:
        return True
    if abs(_row_return(prev_close, close_p)) > threshold:
        return True
    return False
