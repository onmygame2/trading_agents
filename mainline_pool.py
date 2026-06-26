"""
主线主题选股池 — 抓月/季度市场主线，在主线内选放量强势股

逻辑:
1. 行业 20/60 日动量 + 成交额趋势 → 识别当季主线板块
2. 主线内个股: 量比放大(近5日 vs 60日)、有趋势、有操作空间
3. 排除大盘蓝筹/银行保险地产 (如中国银行类)
"""
import logging
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from factor_data import (
    SectorFactors,
    load_kline,
    _liquidity_series,
    get_stock_pool,
    TencentBatchFetcher,
)
from theme_engine import (
    detect_daily_themes,
    is_star_board,
    limit_up_threshold,
    stock_theme_boost,
    theme_boost_for_industry,
)

logger = logging.getLogger(__name__)

# 排除防守/大盘行业
EXCLUDE_INDUSTRY_KW = (
    "货币金融", "保险业", "资本市场", "房地产", "铁路运输",
    "水上运输", "航空运输", "邮政", "公共设施", "自来水",
)

# 主题簇关键词 (行业名模糊匹配) — 用于主线得分加权
THEME_CLUSTERS = {
    "AI算力": ("计算机", "通信", "电子", "半导体", "软件", "互联网", "光学", "智能", "信息", "算力", "光通信"),
    "新能源": ("电气", "电力", "光伏", "电池", "风电", "储能", "新能源"),
    "高端制造": ("专用设备", "通用设备", "仪器", "自动化", "机器人", "机械"),
}

MAX_MARKET_CAP = 420.0   # 亿，排除中国银行等超大盘
MIN_MARKET_CAP = 12.0    # 科创板小盘纳入

# 硬性排除：国有大行/超大盘蓝筹
EXCLUDE_CODES = frozenset({
    "601988", "601398", "601288", "601939", "601328", "601166", "601818",
    "600036", "000001", "002142", "601009", "600000", "601998", "601658",
    "600519", "601857", "600028", "601088", "600900",
})
MIN_VOL_SURGE = 1.10     # 近5日量 / 60日均量
TOP_MAINLINES = 10
PER_MAINLINE = 12
TARGET_POOL = 100


def _industry_excluded(industry: str) -> bool:
    if not industry:
        return True
    return any(kw in industry for kw in EXCLUDE_INDUSTRY_KW)


def _theme_boost(industry: str, theme_ctx: Optional[Dict] = None) -> float:
    return theme_boost_for_industry(industry, theme_ctx)


def _volume_series(df: pd.DataFrame, end: int, window: int) -> float:
    if end < 0 or df.empty:
        return 0.0
    start = max(0, end - window + 1)
    sub = df.iloc[start: end + 1]
    if "volume" in sub.columns:
        v = pd.to_numeric(sub["volume"], errors="coerce").fillna(0)
        if float(v.sum()) > 0:
            return float(v.mean())
    if "amount" in sub.columns:
        a = pd.to_numeric(sub["amount"], errors="coerce").fillna(0)
        if float(a.sum()) > 0:
            return float(a.mean())
    if "volume" in sub.columns and "close" in sub.columns:
        est = pd.to_numeric(sub["volume"], errors="coerce").fillna(0) * pd.to_numeric(
            sub["close"], errors="coerce"
        ).fillna(0)
        if float(est.sum()) > 0:
            return float(est.mean())
    return 0.0


def _mom_pct(close: np.ndarray, days: int) -> float:
    if len(close) <= days:
        return 0.0
    base = float(close[-days - 1])
    if base <= 0:
        return 0.0
    return (float(close[-1]) / base - 1) * 100


def _stock_metrics_at(df: pd.DataFrame, idx: int) -> Dict:
    if idx < 60 or df.empty:
        return {}
    close = df["close"].values[: idx + 1]
    vol5 = _volume_series(df, idx, 5)
    vol60 = _volume_series(df, idx, 60)
    vol_surge = vol5 / vol60 if vol60 > 0 else 0.0
    mom20 = _mom_pct(close, 20)
    mom60 = _mom_pct(close, 60)
    row = df.iloc[idx]
    chg = float(row.get("change_pct", 0) or 0)
    if not chg and idx >= 1:
        prev = float(df.iloc[idx - 1]["close"])
        if prev > 0:
            chg = (float(row["close"]) / prev - 1) * 100
    liq = _volume_series(df, idx, 20)
    return {
        "mom20": mom20,
        "mom60": mom60,
        "vol_surge": vol_surge,
        "change_pct": chg,
        "liquidity": liq,
        "price": float(row["close"]),
    }


def _code_excluded(code: str) -> bool:
    return str(code).split(".")[-1] in EXCLUDE_CODES


def _cap_ok(market_cap: float) -> bool:
    if market_cap <= 0:
        return True  # 缺数据时不硬拦
    return MIN_MARKET_CAP <= market_cap <= MAX_MARKET_CAP


def score_mainline_stock(
    metrics: Dict,
    market_cap: float = 0,
    industry: str = "",
    relaxed: bool = False,
    code: str = "",
    theme_ctx: Optional[Dict] = None,
) -> float:
    """主线内强势股得分: 放量 + 趋势 + 有操作空间"""
    if not metrics:
        return 0.0
    if _industry_excluded(industry):
        return 0.0
    if market_cap > 0 and not _cap_ok(market_cap):
        return 0.0

    vol_surge = metrics.get("vol_surge", 0)
    mom20 = metrics.get("mom20", 0)
    mom60 = metrics.get("mom60", 0)
    chg = metrics.get("change_pct", 0)
    liq = metrics.get("liquidity", 0)

    vol_min = 1.02 if relaxed else MIN_VOL_SURGE
    if vol_surge < vol_min:
        return 0.0
    if relaxed:
        if mom20 < -8 or mom60 < -15:
            return 0.0
    else:
        mom_floor = -2 if vol_surge >= 1.45 else 0.5
        if mom20 < mom_floor or mom60 < -5:
            return 0.0
    lim = limit_up_threshold(code) if code else 9.5
    if chg >= lim or chg <= -lim:
        return 0.0
    if liq <= 0:
        return 0.0

    cap_score = 1.0
    if market_cap > 0:
        if is_star_board(code) and 15 <= market_cap <= 180:
            cap_score = 1.35
        elif 25 <= market_cap <= 200:
            cap_score = 1.25
        elif market_cap > 320:
            cap_score = 0.65

    score = liq * (
        1.0
        + min(3.0, vol_surge - 1) * 0.55
        + max(0, mom20) / 40.0
        + max(0, mom60) / 70.0
    ) * cap_score * _theme_boost(industry, theme_ctx)
    if code:
        score *= stock_theme_boost(code, industry, theme_ctx)

    chg_hi = min(lim * 0.75, 12.0 if not is_star_board(code) else 16.0)
    if 0.3 <= chg <= chg_hi:
        score *= 1.12
    elif chg > chg_hi:
        score *= 0.88
    return score


def compute_industry_mainlines(
    codes: List[str],
    industry_map: Dict[str, str],
    kline_loader=None,
    idx: Optional[int] = None,
    kline_data: Optional[Dict[str, pd.DataFrame]] = None,
    date_idx: Optional[Dict[str, Dict[str, int]]] = None,
    date: Optional[str] = None,
    top_n: int = TOP_MAINLINES,
    theme_ctx: Optional[Dict] = None,
) -> List[Dict]:
    """
    按行业聚合 20/60 日动量与量能趋势，识别当季主线。
    回测传 kline_data + date_idx + date；实盘传 kline_loader=load_kline。
    """
    groups: Dict[str, List[str]] = {}
    for code in codes:
        ind = industry_map.get(code, "")
        if not ind or _industry_excluded(ind):
            continue
        groups.setdefault(ind, []).append(code)

    industry_scores: List[Dict] = []
    for ind, members in groups.items():
        if len(members) < 3:
            continue
        moms20, moms60, surges, amounts = [], [], [], []
        for code in members:
            if _code_excluded(code):
                continue
            if kline_data is not None and date_idx is not None and date:
                df = kline_data.get(code)
                if df is None:
                    continue
                i = date_idx.get(code, {}).get(date)
                if i is None:
                    continue
            else:
                df = (kline_loader or load_kline)(code, days=90)
                i = len(df) - 1 if df is not None and not df.empty else None
                if i is None:
                    continue

            m = _stock_metrics_at(df, i)
            if not m or m["liquidity"] <= 0:
                continue
            moms20.append(m["mom20"])
            moms60.append(m["mom60"])
            surges.append(m["vol_surge"])
            amounts.append(m["liquidity"])

        if len(moms20) < 3:
            continue

        mom20 = float(np.mean(moms20))
        mom60 = float(np.mean(moms60))
        vol_trend = float(np.mean(surges))
        amt = float(np.mean(amounts))
        # 季度主线 + 近期加速 + 板块放量
        # 季度主线(60日)权重更高，兼顾近期加速(20日)与板块放量
        raw = mom60 * 0.48 + mom20 * 0.32 + (vol_trend - 1) * 28 + np.log1p(amt / 1e7) * 2
        raw *= _theme_boost(ind, theme_ctx)
        industry_scores.append({
            "name": ind,
            "mom20": round(mom20, 2),
            "mom60": round(mom60, 2),
            "vol_trend": round(vol_trend, 2),
            "mainline_score": round(raw, 2),
            "stock_count": len(members),
        })

    industry_scores.sort(key=lambda x: x["mainline_score"], reverse=True)
    return industry_scores[:top_n]


def _cap_from_fund(fund: Dict, price: float) -> float:
    ts = fund.get("total_share") or 0
    return float(ts) * float(price) / 1e8 if ts and price > 0 else 0.0


def pick_stocks_in_mainline(
    members: List[str],
    industry: str,
    quote_map: Optional[Dict[str, Dict]] = None,
    cap_map: Optional[Dict[str, Dict]] = None,
    fund_cache: Optional[Dict[str, Dict]] = None,
    per_line: int = PER_MAINLINE,
    kline_loader=None,
    kline_data: Optional[Dict[str, pd.DataFrame]] = None,
    date_idx: Optional[Dict[str, Dict[str, int]]] = None,
    date: Optional[str] = None,
    theme_ctx: Optional[Dict] = None,
) -> List[Dict]:
    quote_map = quote_map or {}
    cap_map = cap_map or {}
    ranked = []
    for code in members:
        if _code_excluded(code):
            continue
        if kline_data is not None and date_idx is not None and date:
            df = kline_data.get(code)
            if df is None:
                continue
            idx = date_idx.get(code, {}).get(date)
            if idx is None:
                continue
        else:
            df = (kline_loader or load_kline)(code, days=90)
            idx = len(df) - 1 if df is not None and not df.empty else None
            if idx is None:
                continue

        metrics = _stock_metrics_at(df, idx)
        cap = float((cap_map.get(code) or {}).get("market_cap", 0) or 0)
        if cap <= 0:
            q = quote_map.get(code, {})
            cap = float(q.get("market_cap", 0) or 0)
        if cap <= 0 and fund_cache:
            cap = _cap_from_fund(fund_cache.get(code, {}), metrics.get("price", 0))
        sc = score_mainline_stock(metrics, cap, industry, relaxed=False, code=code, theme_ctx=theme_ctx)
        if sc <= 0:
            sc = score_mainline_stock(metrics, cap, industry, relaxed=True, code=code, theme_ctx=theme_ctx) * 0.82
        if sc > 0:
            ranked.append({
                "code": code,
                "score": sc,
                "vol_surge": round(metrics.get("vol_surge", 0), 2),
                "mom20": round(metrics.get("mom20", 0), 2),
                "market_cap": cap,
                "change_pct": metrics.get("change_pct"),
            })
    ranked.sort(key=lambda x: x["score"], reverse=True)
    return ranked[:per_line]


def select_mainline_pool(
    full_pool: Optional[List[str]] = None,
    top_mainlines: int = TOP_MAINLINES,
    per_mainline: int = PER_MAINLINE,
) -> Tuple[List[str], Dict]:
    """实盘: 主线主题池"""
    full_pool = full_pool or get_stock_pool()
    industry_map = SectorFactors._load_industry_map()

    groups: Dict[str, List[str]] = {}
    for code in full_pool:
        if _code_excluded(code):
            continue
        ind = industry_map.get(code, "")
        if ind and not _industry_excluded(ind):
            groups.setdefault(ind, []).append(code)

    mainlines = compute_industry_mainlines(
        full_pool, industry_map, kline_loader=load_kline, top_n=top_mainlines,
    )
    from datetime import datetime
    theme_ctx = detect_daily_themes(mainlines, date=datetime.now().strftime("%Y-%m-%d"), persist=True)
    mainlines = compute_industry_mainlines(
        full_pool, industry_map, kline_loader=load_kline, top_n=top_mainlines, theme_ctx=theme_ctx,
    )

    quote_map: Dict[str, Dict] = {}
    try:
        from market_data import get_market_data_provider
        qdf = get_market_data_provider().get_realtime_quotes()
        if qdf is not None and not qdf.empty:
            for _, row in qdf.iterrows():
                quote_map[str(row.get("code", ""))] = row.to_dict()
    except Exception as e:
        logger.warning("主线选股: 实时行情不可用 %s", e)

    cap_map = TencentBatchFetcher.fetch_batch(full_pool)

    line_picks: Dict[str, List[Dict]] = {}
    seen = set()
    ordered: List[str] = []

    for line in mainlines:
        name = line["name"]
        members = groups.get(name, [])
        picks = pick_stocks_in_mainline(
            members, name,
            quote_map=quote_map, cap_map=cap_map,
            per_line=per_mainline, kline_loader=load_kline,
            theme_ctx=theme_ctx,
        )
        if not picks:
            continue
        line_picks[name] = picks
        for p in picks:
            code = p["code"]
            if code not in seen:
                seen.add(code)
                ordered.append(code)

    if len(ordered) < TARGET_POOL:
        extras = []
        for code in full_pool:
            if code in seen or _code_excluded(code):
                continue
            ind = industry_map.get(code, "")
            if _industry_excluded(ind):
                continue
            df = load_kline(code, days=90)
            if df.empty:
                continue
            m = _stock_metrics_at(df, len(df) - 1)
            cap = float((cap_map.get(code) or {}).get("market_cap", 0) or 0)
            sc = score_mainline_stock(m, cap, ind, relaxed=False, code=code, theme_ctx=theme_ctx)
            if sc <= 0:
                sc = score_mainline_stock(m, cap, ind, relaxed=True, code=code, theme_ctx=theme_ctx)
            if sc > 0:
                extras.append((code, sc))
        extras.sort(key=lambda x: x[1], reverse=True)
        for code, _ in extras[: TARGET_POOL - len(ordered)]:
            if code not in seen:
                seen.add(code)
                ordered.append(code)
        if extras:
            line_picks["_动量补齐"] = [{"code": c} for c, _ in extras[: TARGET_POOL - len(ordered)]]

    meta = {
        "pool_mode": "mainline",
        "mainlines": mainlines,
        "line_picks": line_picks,
        "line_counts": {k: len(v) for k, v in line_picks.items()},
        "candidate_total": len(ordered),
        "theme_ctx": theme_ctx,
        "keywords": theme_ctx.get("keywords", []),
        "leader_theme": theme_ctx.get("leader_theme", ""),
        "switched_in": theme_ctx.get("switched_in", []),
        "filters": {
            "max_cap": MAX_MARKET_CAP,
            "min_vol_surge": MIN_VOL_SURGE,
            "star_board": True,
            "exclude": list(EXCLUDE_INDUSTRY_KW[:4]),
        },
    }
    logger.info("主线选股: %d 条主线 -> %d 只候选", len(mainlines), len(ordered))
    return ordered, meta


def select_mainline_pool_for_date(
    all_codes: List[str],
    kline_data: Dict[str, pd.DataFrame],
    date_idx: Dict[str, Dict[str, int]],
    date: str,
    industry_map: Dict[str, str],
    fund_cache: Optional[Dict[str, Dict]] = None,
    top_mainlines: int = TOP_MAINLINES,
    per_mainline: int = PER_MAINLINE,
) -> List[str]:
    """回测: 当日主线主题池"""
    mainlines = compute_industry_mainlines(
        all_codes, industry_map,
        kline_data=kline_data, date_idx=date_idx, date=date,
        top_n=top_mainlines,
    )
    theme_ctx = detect_daily_themes(mainlines, date=date)
    mainlines = compute_industry_mainlines(
        all_codes, industry_map,
        kline_data=kline_data, date_idx=date_idx, date=date,
        top_n=top_mainlines, theme_ctx=theme_ctx,
    )

    groups: Dict[str, List[str]] = {}
    for code in all_codes:
        if _code_excluded(code):
            continue
        ind = industry_map.get(code, "")
        if ind and not _industry_excluded(ind):
            groups.setdefault(ind, []).append(code)

    seen: List[str] = []
    seen_set = set()
    fund_cache = fund_cache or {}

    for line in mainlines:
        name = line["name"]
        members = groups.get(name, [])
        picks = pick_stocks_in_mainline(
            members, name,
            fund_cache=fund_cache,
            per_line=per_mainline,
            kline_data=kline_data, date_idx=date_idx, date=date,
            theme_ctx=theme_ctx,
        )
        for p in picks:
            code = p["code"]
            if code not in seen_set:
                seen_set.add(code)
                seen.append(code)

    if len(seen) < TARGET_POOL:
        extras = []
        for code in all_codes:
            if code in seen_set or _code_excluded(code):
                continue
            ind = industry_map.get(code, "")
            if _industry_excluded(ind):
                continue
            idx = date_idx.get(code, {}).get(date)
            df = kline_data.get(code)
            if idx is None or df is None:
                continue
            m = _stock_metrics_at(df, idx)
            cap = _cap_from_fund(fund_cache.get(code, {}), m.get("price", 0))
            sc = score_mainline_stock(m, cap, ind, relaxed=False, code=code, theme_ctx=theme_ctx)
            if sc <= 0:
                sc = score_mainline_stock(m, cap, ind, relaxed=True, code=code, theme_ctx=theme_ctx)
            if sc > 0:
                extras.append((code, sc))
        extras.sort(key=lambda x: x[1], reverse=True)
        for code, _ in extras[: TARGET_POOL - len(seen)]:
            if code not in seen_set:
                seen_set.add(code)
                seen.append(code)
    return seen


def mainline_sector_data(
    kline_data: Dict[str, pd.DataFrame],
    date_idx: Dict[str, Dict[str, int]],
    date: str,
    industry_map: Dict[str, str],
    prev_theme_state: Optional[Dict] = None,
) -> Dict:
    """供因子引擎使用的板块上下文 (主线 + 每日关键词)"""
    mainlines = compute_industry_mainlines(
        list(kline_data.keys()), industry_map,
        kline_data=kline_data, date_idx=date_idx, date=date,
        top_n=12,
    )
    theme_ctx = detect_daily_themes(mainlines, date=date, prev_state=prev_theme_state)
    hot = [
        {
            "name": x["name"],
            "change_pct": x["mom20"],
            "mainline_score": x["mainline_score"],
            "mom60": x.get("mom60", 0),
        }
        for x in mainlines
    ]
    cold = hot[-3:] if len(hot) >= 3 else []
    return {
        "hot_sectors": hot,
        "hot_concepts": hot,
        "cold_sectors": cold,
        "mainlines": mainlines,
        "theme_ctx": theme_ctx,
        "keywords": theme_ctx.get("keywords", []),
        "leader_theme": theme_ctx.get("leader_theme", ""),
        "active_themes": theme_ctx.get("active_themes", []),
        "switched_in": theme_ctx.get("switched_in", []),
        "strategy_bias": theme_ctx.get("strategy_bias", {}),
    }
