"""板块驱动选股池 — 热门板块 Top N × 每板块 Top M"""
import logging
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from factor_data import (
    SectorFactors,
    load_kline,
    _liquidity_series,
    get_stock_pool,
)

logger = logging.getLogger(__name__)


def load_code_industry_map() -> Dict[str, str]:
    return SectorFactors._load_industry_map()


def build_industry_groups(codes: List[str]) -> Dict[str, List[str]]:
    """行业名 -> 成分股列表"""
    ind_map = load_code_industry_map()
    allowed = set(codes)
    groups: Dict[str, List[str]] = {}
    for code in allowed:
        industry = ind_map.get(code) or ""
        if not industry:
            continue
        groups.setdefault(industry, []).append(code)
    return groups


def _score_stock_for_sector(code: str, quote: Optional[Dict] = None) -> float:
    """板块内个股排序: 流动性为主 + 动量/当日涨幅加权"""
    df = load_kline(code, days=35)
    if df.empty or len(df) < 20:
        return 0.0
    liq = _liquidity_series(df, 20)
    if liq <= 0:
        return 0.0
    close = df["close"].values
    mom20 = (close[-1] / close[-21] - 1) * 100 if len(close) >= 21 else 0.0
    chg = float(df.iloc[-1].get("change_pct", 0) or 0)
    if quote:
        chg = float(quote.get("change_pct", chg) or chg)
    # 热门板块内优先：活跃 + 强势
    return liq * (1.0 + max(0.0, mom20) / 80.0) + liq * max(0.0, chg) * 0.02


def pick_top_in_sector(
    codes: List[str],
    per_sector: int,
    quote_map: Optional[Dict[str, Dict]] = None,
) -> List[Dict]:
    """单板块内取 Top M"""
    quote_map = quote_map or {}
    ranked = []
    for code in codes:
        sc = _score_stock_for_sector(code, quote_map.get(code))
        if sc > 0:
            ranked.append((code, sc))
    ranked.sort(key=lambda x: x[1], reverse=True)
    out = []
    for code, sc in ranked[:per_sector]:
        q = quote_map.get(code, {})
        out.append({
            "code": code,
            "sector_score": round(sc, 2),
            "change_pct": q.get("change_pct"),
            "price": q.get("close") or q.get("price"),
        })
    return out


def select_sector_pool(
    full_pool: Optional[List[str]] = None,
    top_sectors: int = 10,
    per_sector: int = 10,
    hot_sectors: Optional[List[Dict]] = None,
) -> Tuple[List[str], Dict]:
    """
    热门板块 Top10，每板块个股 Top10，合计约 100 只候选。

    Returns:
        codes: 去重后的股票代码列表
        meta: 选股元数据（板块明细、模式说明）
    """
    full_pool = full_pool or get_stock_pool()
    allowed = set(full_pool)
    groups = build_industry_groups(full_pool)

    if hot_sectors is None:
        hot_sectors = SectorFactors.get_hot_sectors(top_sectors)
    else:
        hot_sectors = hot_sectors[:top_sectors]

    quote_map: Dict[str, Dict] = {}
    try:
        from market_data import get_market_data_provider
        qdf = get_market_data_provider().get_realtime_quotes()
        if qdf is not None and not qdf.empty:
            for _, row in qdf.iterrows():
                c = str(row.get("code", ""))
                if c in allowed:
                    quote_map[c] = row.to_dict()
    except Exception as e:
        logger.warning("板块选股: 实时行情不可用 %s", e)

    sector_picks: Dict[str, List[Dict]] = {}
    seen = set()
    ordered_codes: List[str] = []

    for sec in hot_sectors:
        name = sec.get("name", "")
        if not name:
            continue
        members = groups.get(name, [])
        if len(members) < 2:
            continue
        picks = pick_top_in_sector(members, per_sector, quote_map)
        if not picks:
            continue
        sector_picks[name] = picks
        for p in picks:
            code = p["code"]
            if code in seen:
                continue
            seen.add(code)
            ordered_codes.append(code)

    # 热门板块成分不足时，用流动性补齐到 top_sectors * per_sector
    target = top_sectors * per_sector
    if len(ordered_codes) < target:
        from factor_data import select_pool_top_liquidity
        extra = select_pool_top_liquidity(
            [c for c in full_pool if c not in seen],
            target - len(ordered_codes),
        )
        for code in extra:
            if code not in seen:
                seen.add(code)
                ordered_codes.append(code)
        if extra:
            sector_picks["_流动性补齐"] = [{"code": c} for c in extra]

    meta = {
        "pool_mode": "sector",
        "top_sectors": top_sectors,
        "per_sector": per_sector,
        "hot_sectors": hot_sectors,
        "sector_picks": sector_picks,
        "sector_counts": {k: len(v) for k, v in sector_picks.items()},
        "candidate_total": len(ordered_codes),
    }
    logger.info(
        "板块选股: %d 个热门板块 -> %d 只候选 (目标 %d)",
        len(sector_picks), len(ordered_codes), target,
    )
    return ordered_codes, meta


def _liquidity_at_idx(df: pd.DataFrame, idx: int, tail: int = 20) -> float:
    if idx < 5:
        return 0.0
    sub = df.iloc[max(0, idx - tail + 1): idx + 1]
    if "amount" in sub.columns:
        s = pd.to_numeric(sub["amount"], errors="coerce")
        if s.notna().any() and float(s.fillna(0).sum()) > 0:
            return float(s.mean())
    if "volume" in sub.columns and "close" in sub.columns:
        est = pd.to_numeric(sub["volume"], errors="coerce").fillna(0) * pd.to_numeric(
            sub["close"], errors="coerce"
        ).fillna(0)
        if float(est.sum()) > 0:
            return float(est.mean())
    return 0.0


def _score_stock_historical(df: pd.DataFrame, idx: int) -> float:
    """回测用：截至 idx 日的板块内个股得分"""
    if idx < 20:
        return 0.0
    liq = _liquidity_at_idx(df, idx, 20)
    if liq <= 0:
        return 0.0
    close = df["close"].values[: idx + 1]
    mom20 = (close[-1] / close[-21] - 1) * 100 if len(close) >= 21 else 0.0
    row = df.iloc[idx]
    chg = float(row.get("change_pct", 0) or 0)
    if not chg and idx >= 1:
        prev = float(df.iloc[idx - 1]["close"])
        if prev > 0:
            chg = (float(row["close"]) / prev - 1) * 100
    return liq * (1.0 + max(0.0, mom20) / 80.0) + liq * max(0.0, chg) * 0.02


def select_sector_pool_for_date(
    all_codes: List[str],
    kline_data: Dict[str, pd.DataFrame],
    date_idx: Dict[str, Dict[str, int]],
    date: str,
    industry_map: Dict[str, str],
    hot_sectors: Optional[List[Dict]] = None,
    top_sectors: int = 10,
    per_sector: int = 10,
) -> List[str]:
    """回测：当日热门板块 Top N × 每板块 Top M"""
    groups: Dict[str, List[str]] = {}
    for code in all_codes:
        ind = industry_map.get(code, "")
        if ind:
            groups.setdefault(ind, []).append(code)

    if not hot_sectors:
        from collections import defaultdict
        industry_changes: Dict[str, List[float]] = defaultdict(list)
        for code, df in kline_data.items():
            idx = date_idx.get(code, {}).get(date)
            if idx is None:
                continue
            ind = industry_map.get(code, "")
            if not ind:
                continue
            chg = float(df.iloc[idx].get("change_pct", 0) or 0)
            if not chg and idx >= 1:
                prev = float(df.iloc[idx - 1]["close"])
                if prev > 0:
                    chg = (float(df.iloc[idx]["close"]) / prev - 1) * 100
            industry_changes[ind].append(chg)
        hot_sectors = []
        for name, changes in industry_changes.items():
            if len(changes) >= 2:
                hot_sectors.append({"name": name, "change_pct": float(np.mean(changes))})
        hot_sectors.sort(key=lambda x: x["change_pct"], reverse=True)
        hot_sectors = hot_sectors[:top_sectors]

    seen: List[str] = []
    seen_set = set()
    for sec in hot_sectors[:top_sectors]:
        name = sec.get("name", "")
        members = groups.get(name, [])
        ranked = []
        for code in members:
            idx = date_idx.get(code, {}).get(date)
            df = kline_data.get(code)
            if idx is None or df is None:
                continue
            sc = _score_stock_historical(df, idx)
            if sc > 0:
                ranked.append((code, sc))
        ranked.sort(key=lambda x: x[1], reverse=True)
        for code, _ in ranked[:per_sector]:
            if code not in seen_set:
                seen_set.add(code)
                seen.append(code)

    target = top_sectors * per_sector
    if len(seen) < target:
        liq_ranked = []
        for code in all_codes:
            if code in seen_set:
                continue
            idx = date_idx.get(code, {}).get(date)
            df = kline_data.get(code)
            if idx is None or df is None:
                continue
            liq = _liquidity_at_idx(df, idx, 20)
            if liq > 0:
                liq_ranked.append((code, liq))
        liq_ranked.sort(key=lambda x: x[1], reverse=True)
        for code, _ in liq_ranked[: target - len(seen)]:
            if code not in seen_set:
                seen_set.add(code)
                seen.append(code)
    return seen
