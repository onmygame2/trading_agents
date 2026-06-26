"""超跌企稳 — 消息面+龙回头 (2024-2025主线池回测验证)"""
from typing import Dict, List
from strategies_v2.common import (
    prepare_ranks, get_rank, make_pick, tradable_today,
    trend_pullback_signal, message_boost,
)
from theme_engine import classify_industry, is_star_board


def filter(stocks: List[Dict], sector_data: Dict = None, market_ctx: Dict = None) -> List[Dict]:
    ctx = market_ctx or {}
    pool = prepare_ranks(stocks)
    results = []

    for s in pool:
        code = s.get("code", "")
        pv = s.get("price_volume", {}) or {}
        if not tradable_today(pv, code):
            continue

        ok, score, reason = trend_pullback_signal(
            pv,
            mom20_min=3,
            mom5_lo=-14,
            mom5_hi=-1.5,
            chg_lo=0.8,
            chg_hi=7.0,
            rsi_max=62,
            code=code,
        )
        if not ok:
            continue

        # 涨停基因硬门槛: 回测数据显示无基因股票胜率仅11%、净亏4.3万，
        # 有基因股票胜率42%、净盈4.7万 → 设为必要条件而非加分项
        if not pv.get("has_limit_up_180d"):
            continue

        score, extra = message_boost(s, score, 0.22)
        reason = reason + extra

        r20 = get_rank(s, "mom_20d")
        if r20 >= 55:
            score += 4
        score += 5
        reason.append("涨停基因")

        vol_r = pv.get("vol_ratio", 1) or 1
        if 1.0 <= vol_r <= 2.5:
            score += 3

        tc = (sector_data or {}).get("theme_ctx") or ctx.get("theme_ctx") or {}
        keywords = tc.get("keywords") or (sector_data or {}).get("keywords") or []
        ind = s.get("industry", "") or (s.get("fundamental") or {}).get("industry", "")
        label, _ = classify_industry(ind)
        if keywords and any(k in ind or k in label for k in keywords):
            score += 7
        if is_star_board(code):
            score += 3

        min_sc = 64 if (ctx.get("theme_ctx") or keywords) else 68
        if score >= min_sc:
            results.append(make_pick(s, score, " + ".join(reason[:4]), int(min(90, score * 0.88))))

    results.sort(key=lambda x: x["strategy_score"], reverse=True)
    return results[:10]


metadata = {
    "name": "超跌企稳",
    "weight": 1.0,
    "enabled": True,
    "trade_rules": "aggressive",
    "market_filter": "loose",
    "max_positions": 5,
    "max_hold_days": 32,
    "take_profit": 0.72,
    "trailing_stop": 0.12,
    "min_strategy_score": 64,
    "description": "消息面+龙回头 | 涨停持股",
}
