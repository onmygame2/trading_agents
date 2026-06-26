"""主线龙头 — 主题加速期的放量突破/动量延续"""
from typing import Dict, List
from strategies_v2.common import (
    prepare_ranks, get_rank, make_pick, tradable_today,
    elite_breakout_signal, momentum_continuation_signal,
)
from theme_engine import classify_industry, is_star_board


def _theme_match(stock: Dict, sector_data: Dict, market_ctx: Dict = None) -> bool:
    ctx = market_ctx or {}
    tc = (sector_data or {}).get("theme_ctx") or ctx.get("theme_ctx") or {}
    keywords = tc.get("keywords") or (sector_data or {}).get("keywords") or []
    if not keywords:
        return True
    ind = stock.get("industry", "") or (stock.get("fundamental") or {}).get("industry", "")
    label, kws = classify_industry(ind)
    pool = set(keywords) | set(kws) | {label}
    top5 = set(tc.get("top5") or [])
    if label in top5:
        return True
    return any(k in ind or k in label for k in pool)


def _momentum_regime(sector_data: Dict, market_ctx: Dict = None) -> bool:
    ctx = market_ctx or {}
    tc = (sector_data or {}).get("theme_ctx") or ctx.get("theme_ctx") or {}
    bias = tc.get("strategy_bias") or (sector_data or {}).get("strategy_bias") or {}
    if bias.get("mode") in ("momentum", "rotation"):
        return True
    leader = next((t for t in tc.get("active_themes", []) if t.get("theme") == tc.get("leader_theme")), {})
    return leader.get("acceleration", 0) > 1.5 or leader.get("mom20", 0) > 6


def filter(stocks: List[Dict], sector_data: Dict = None, market_ctx: Dict = None) -> List[Dict]:
    ctx = market_ctx or {}
    if ctx.get("index_mom_20d", 0) < -4 and not ctx.get("index_bull", True):
        return []
    if not _momentum_regime(sector_data, ctx):
        return []

    pool = prepare_ranks(stocks)
    results = []
    for s in pool:
        code = s.get("code", "")
        pv = s.get("price_volume", {}) or {}
        if not tradable_today(pv, code):
            continue
        if not _theme_match(s, sector_data, ctx):
            continue

        ok, score, reason = elite_breakout_signal(pv, s, min_r20=72)
        if not ok:
            ok, score, reason = momentum_continuation_signal(pv, min_r20=68, stock=s, chg_hi=6.0)
        if not ok:
            continue

        vol_r = pv.get("vol_ratio", 1) or 1
        if vol_r < 1.1:
            continue
        mom20 = pv.get("mom_20d", 0) or 0
        if mom20 < 10:
            continue

        msg = s.get("message_score", 50) or 50
        score += msg * 0.12
        dl = s.get("dl_score")
        if dl is not None:
            if dl < 0.50:
                continue
            score += float(dl) * 14
        if is_star_board(code):
            score += 5
        tc = (sector_data or {}).get("theme_ctx") or ctx.get("theme_ctx") or {}
        if classify_industry(s.get("industry", ""))[0] == tc.get("leader_theme"):
            score += 8
            reason.append("领涨主线")

        if score >= 78:
            results.append(make_pick(s, score, " + ".join(reason[:5]), int(min(95, score * 0.9))))

    results.sort(key=lambda x: x["strategy_score"], reverse=True)
    return results[:6]


metadata = {
    "name": "主线龙头",
    "weight": 1.1,
    "enabled": True,
    "trade_rules": "aggressive",
    "market_filter": "normal",
    "max_positions": 2,
    "min_strategy_score": 76,
    "description": "已暂停 — 回测拖累组合收益",
}
