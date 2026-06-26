"""板块龙头 — 仅超强热点板块 + 突破信号"""
from typing import Dict, List
from strategies_v2.common import (
    prepare_ranks, elite_breakout_signal, momentum_continuation_signal,
    message_boost, make_pick, tradable_today, is_sector_pool, pool_rank_cut, pool_min_score,
)


def filter(stocks: List[Dict], sector_data: Dict = None, market_ctx: Dict = None) -> List[Dict]:
    ctx = market_ctx or {}
    if not sector_data:
        return []
    if is_sector_pool(ctx):
        hot = sector_data.get("hot_sectors", [])[:10]
        min_chg = 0.3
        min_out = pool_min_score(76, 68, ctx)
        min_r20_elite = pool_rank_cut(75, ctx, 12)
        min_r20_mom = pool_rank_cut(80, ctx, 15)
    else:
        hot = [x for x in sector_data.get("hot_sectors", [])[:2]
               if (x.get("change_pct", 0) or 0) > 1.2]
        min_chg = 1.2
        min_out = 76
        min_r20_elite = 75
        min_r20_mom = 80
    hot = [x for x in hot if (x.get("change_pct", 0) or 0) > min_chg]
    hot_names = {x.get("name") for x in hot}
    if not hot_names:
        return []

    pool = prepare_ranks(stocks)
    by_ind: Dict[str, list] = {}
    for s in pool:
        ind = s.get("industry", "")
        if ind not in hot_names:
            continue
        pv = s.get("price_volume", {}) or {}
        if not tradable_today(pv):
            continue
        if (s.get("message_score", 50) or 50) < pool_min_score(54, 48, ctx):
            continue
        ok, score, reason = elite_breakout_signal(pv, s, min_r20=min_r20_elite)
        if not ok:
            ok, score, reason = momentum_continuation_signal(
                pv, min_r20=min_r20_mom, stock=s, chg_hi=5.5,
            )
            if not ok or not pv.get("break_60d"):
                continue
        score += 5
        score, extra = message_boost(s, score, 0.18)
        reason = [ind, f"板块+{(hot[0].get('change_pct') if hot else 0):.1f}%"] + reason + extra
        by_ind.setdefault(ind, []).append((s, score, reason))

    results = []
    for group in by_ind.values():
        group.sort(key=lambda x: x[1], reverse=True)
        s, score, reason = group[0]
        if is_sector_pool(ctx):
            score += 4
        if score >= min_out:
            results.append(make_pick(s, score, " + ".join(reason[:4]), int(score * 0.9)))
    results.sort(key=lambda x: x["strategy_score"], reverse=True)
    return results[:8 if is_sector_pool(ctx) else 5]


metadata = {
    "name": "板块龙头跟随",
    "weight": 1.0,
    "enabled": True,
    "trade_rules": "swing",
    "market_filter": "normal",
    "max_positions": 2,
    "min_strategy_score": 76,
    "description": "板块日涨>1.2%时做龙头突破",
}
