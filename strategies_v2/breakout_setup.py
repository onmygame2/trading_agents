"""突破蓄势 — 消息+动量延续/60日新高 (回测冠军基线)"""
from typing import Dict, List
from strategies_v2.common import (
    prepare_ranks, momentum_continuation_signal, trend_pullback_signal,
    message_boost, make_pick, get_rank, elite_breakout_signal,
    is_sector_pool, pool_min_score, pool_rank_cut,
)


def filter(stocks: List[Dict], sector_data: Dict = None, market_ctx: Dict = None) -> List[Dict]:
    ctx = market_ctx or {}
    pool = prepare_ranks(stocks)
    min_r20 = pool_rank_cut(68, ctx, 12)
    min_out = pool_min_score(68, 64, ctx)
    results = []
    for s in pool:
        pv = s.get("price_volume", {}) or {}
        msg = s.get("message_score", 50) or 50

        ok, score, reason = momentum_continuation_signal(pv, min_r20=min_r20, stock=s)
        if not ok:
            ok2, score2, reason2 = trend_pullback_signal(
                pv, mom20_min=8, mom5_lo=-10, mom5_hi=-1, chg_lo=1.0, chg_hi=6.0,
            )
            if ok2 and pv.get("break_60d"):
                score, reason = score2 + 8, reason2 + ["60日新高"]
            else:
                continue
        elif pv.get("break_60d"):
            score += 5
            reason.append("60日新高")

        if msg < pool_min_score(48, 45, ctx):
            continue
        score, extra = message_boost(s, score, 0.24 if is_sector_pool(ctx) else 0.20)
        reason = reason + extra
        if is_sector_pool(ctx):
            score += 3
        dl = s.get("dl_score")
        if dl is not None and dl >= (0.45 if is_sector_pool(ctx) else 0.48):
            score += float(dl) * 10
        if score >= min_out:
            results.append(make_pick(s, score, " + ".join(reason[:4]), int(score * 0.9)))
    results.sort(key=lambda x: x["strategy_score"], reverse=True)
    return results[:10]


metadata = {
    "name": "突破蓄势",
    "weight": 1.15,
    "enabled": True,
    "trade_rules": "swing",
    "market_filter": "normal",
    "max_positions": 4,
    "min_strategy_score": 68,
    "description": "消息面+动量突破/新高 | 波段 (参数走 SWING_RULES)",
}
