"""策略共用: 横截面排名、消息面加权、信号模板"""
from typing import Dict, List, Optional, Tuple


def rank_field(stocks: List[Dict], field: str, key: str = "price_volume") -> None:
    vals = []
    for s in stocks:
        pv = s.get(key, {}) or {}
        v = pv.get(field)
        if v is not None:
            vals.append((s, float(v)))
    if len(vals) < 5:
        for s, _ in vals:
            s.setdefault("_rank", {})[field] = 50.0
        return
    vals.sort(key=lambda x: x[1])
    n = len(vals)
    for i, (s, _) in enumerate(vals):
        s.setdefault("_rank", {})[field] = round((i + 1) / n * 100, 1)


def get_rank(stock: Dict, field: str) -> float:
    return (stock.get("_rank") or {}).get(field, 50.0)


def prepare_ranks(stocks: List[Dict]) -> List[Dict]:
    for f in ("mom_5d", "mom_10d", "mom_20d", "vol_ratio", "price_pos"):
        rank_field(stocks, f)
    return stocks


def is_sector_pool(ctx: Dict = None) -> bool:
    """候选池是否来自主题预筛（板块/主线小池 ~80–100只）"""
    ctx = ctx or {}
    return bool(ctx.get("sector_pool") or ctx.get("mainline_pool"))


def pool_min_score(base: int, relaxed: int, ctx: Dict = None) -> int:
    return relaxed if is_sector_pool(ctx) else base


def pool_rank_cut(base: float, ctx: Dict = None, relax: float = 10.0) -> float:
    """板块小池子内降低横截面排名门槛"""
    return max(50.0, base - relax) if is_sector_pool(ctx) else base


def make_pick(stock: Dict, score: float, reason: str, confidence: int = 85) -> Dict:
    pv = stock.get("price_volume", {}) or {}
    return {
        "code": stock["code"],
        "price": pv.get("price", 0),
        "strategy_score": int(min(99, score)),
        "reason": reason,
        "confidence": min(95, confidence),
    }


def tradable_today(pv: Dict, code: str = "") -> bool:
    from theme_engine import limit_up_threshold
    lim = limit_up_threshold(code or pv.get("code", ""))
    chg = pv.get("change_pct", 0) or 0
    return -lim < chg < lim and (pv.get("price", 0) or 0) > 0


def pos_in_day(pv: Dict) -> float:
    close = pv.get("price", 0) or 0
    high = pv.get("today_high", 0) or 0
    low = pv.get("today_low", 0) or 0
    if high > low > 0:
        return (close - low) / (high - low)
    return 0.5


def message_boost(stock: Dict, base: float, weight: float = 0.24) -> Tuple[float, List[str]]:
    msg = stock.get("message_score", 50) or 50
    score = base + msg * weight
    reason = list((stock.get("message_tags") or [])[:2])
    if msg >= 58:
        score += 3
    return score, reason


def trend_pullback_signal(
    pv: Dict,
    mom20_min: float = 3,
    mom5_lo: float = -14,
    mom5_hi: float = -1.5,
    chg_lo: float = 0.8,
    chg_hi: float = 6.5,
    rsi_max: float = 64,
    code: str = "",
) -> Tuple[bool, float, List[str]]:
    mom5 = pv.get("mom_5d", 0) or 0
    mom10 = pv.get("mom_10d", 0) or 0
    mom20 = pv.get("mom_20d", 0) or 0
    chg = pv.get("change_pct", 0) or 0
    rsi = pv.get("rsi", 50) or 50
    price = pv.get("price", 0) or 0
    ma20 = pv.get("ma20", 0) or 0
    vol_r = pv.get("vol_ratio", 1) or 1

    if not tradable_today(pv, code or pv.get("code", "")):
        return False, 0, []
    if mom20 < mom20_min or mom10 < -3:
        return False, 0, []
    if not (mom5_lo <= mom5 <= mom5_hi):
        return False, 0, []
    if not (chg_lo <= chg <= chg_hi):
        return False, 0, []
    if rsi > rsi_max:
        return False, 0, []
    if ma20 and price < ma20 * 0.88:
        return False, 0, []

    score = 74 + min(10, -mom5)
    reason = [f"回调{mom5:.0f}%", f"反弹{chg:.1f}%"]
    if pv.get("ma_bull"):
        score += 5
        reason.append("多头")
    if 1.0 <= vol_r <= 2.5:
        score += 5
        reason.append(f"量{vol_r:.1f}x")
    if mom20 > 12:
        score += 4
        reason.append(f"20日{mom20:.0f}%")
    return True, score, reason


def momentum_continuation_signal(
    pv: Dict,
    min_r20: float = 70,
    stock: Dict = None,
    chg_hi: float = 5.5,
) -> Tuple[bool, float, List[str]]:
    mom20 = pv.get("mom_20d", 0) or 0
    chg = pv.get("change_pct", 0) or 0
    vol_r = pv.get("vol_ratio", 1) or 1
    if not tradable_today(pv):
        return False, 0, []
    if chg < 0.5 or chg > chg_hi:
        return False, 0, []
    if mom20 < 6:
        return False, 0, []
    if not (0.85 <= vol_r <= 2.8):
        return False, 0, []
    r20 = get_rank(stock, "mom_20d") if stock else 50
    if r20 < min_r20:
        return False, 0, []

    score = 80 + (r20 - min_r20) * 0.22
    reason = [f"动量Top{r20:.0f}%", f"涨{chg:.1f}%"]
    if pv.get("break_60d"):
        score += 6
        reason.append("新高")
    if pv.get("ma_bull"):
        score += 4
        reason.append("多头")
    return True, score, reason


def elite_breakout_signal(
    pv: Dict,
    stock: Dict,
    min_r20: float = 78,
) -> Tuple[bool, float, List[str]]:
    """强势突破: 60日新高 + 动量前列 + 放量"""
    if not tradable_today(pv):
        return False, 0, []
    mom20 = pv.get("mom_20d", 0) or 0
    chg = pv.get("change_pct", 0) or 0
    vol_r = pv.get("vol_ratio", 1) or 1
    if mom20 < 8 or chg < 0.8 or chg > 6.5:
        return False, 0, []
    if not pv.get("break_60d"):
        return False, 0, []
    r20 = get_rank(stock, "mom_20d") if stock else 0
    if r20 < min_r20:
        return False, 0, []
    if vol_r < 1.15:
        return False, 0, []

    score = 84 + (r20 - min_r20) * 0.25
    reason = [f"60日新高", f"动量Top{r20:.0f}%", f"量{vol_r:.1f}x", f"涨{chg:.1f}%"]
    if pv.get("ma_bull"):
        score += 5
        reason.append("多头")
    if vol_r >= 1.8:
        score += 4
        reason.append("放量")
    return True, score, reason


def strong_close_signal(
    pv: Dict,
    min_pos: float = 0.78,
    chg_lo: float = 0.3,
    chg_hi: float = 5.0,
) -> Tuple[bool, float, List[str]]:
    if not tradable_today(pv):
        return False, 0, []
    chg = pv.get("change_pct", 0) or 0
    if not (chg_lo <= chg <= chg_hi):
        return False, 0, []
    pos = pos_in_day(pv)
    if pos < min_pos:
        return False, 0, []
    mom20 = pv.get("mom_20d", 0) or 0
    score = 72 + (pos - min_pos) * 35
    reason = [f"强收{pos:.0%}", f"涨{chg:.1f}%"]
    if mom20 > 5:
        score += 4
        reason.append(f"20日{mom20:.0f}%")
    if pv.get("ma_bull"):
        score += 4
        reason.append("多头")
    return True, score, reason
