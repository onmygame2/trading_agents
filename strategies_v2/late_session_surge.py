"""尾盘抢筹 — 强收盘放量 + 动量 (优化版)"""
from typing import Dict, List
from strategies_v2.common import (
    prepare_ranks, strong_close_signal, message_boost, make_pick, get_rank,
    is_sector_pool, pool_min_score,
)


def filter(stocks: List[Dict], sector_data: Dict = None, market_ctx: Dict = None) -> List[Dict]:
    ctx = market_ctx or {}
    pool = prepare_ranks(stocks)
    min_pos = 0.76 if is_sector_pool(ctx) else 0.80
    min_out = pool_min_score(68, 64, ctx)
    results = []
    for s in pool:
        pv = s.get("price_volume", {}) or {}
        vol_r = pv.get("vol_ratio", 1) or 1
        msg = s.get("message_score", 50) or 50

        ok, score, reason = strong_close_signal(pv, min_pos=min_pos, chg_lo=0.4, chg_hi=5.8)
        if not ok:
            continue
        if msg < 50 and vol_r < 1.1:
            continue
        if vol_r >= 1.2:
            score += 5
            reason.append(f"量{vol_r:.1f}x")
        r5 = get_rank(s, "mom_5d")
        if r5 >= 65:
            score += 3
        score, extra = message_boost(s, score, 0.26)
        reason = reason + extra
        if is_sector_pool(ctx):
            score += 3
        if score >= min_out:
            results.append(make_pick(s, score, " + ".join(reason[:4]), int(score * 0.9)))
    results.sort(key=lambda x: x["strategy_score"], reverse=True)
    return results[:10]


metadata = {
    "name": "尾盘抢筹",
    "weight": 1.05,
    "enabled": True,
    "trade_rules": "overnight",
    "market_filter": "loose",
    "max_positions": 4,
    "min_strategy_score": 68,
    "description": "强收盘放量 | 隔夜",
}
