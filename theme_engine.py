"""
每日主线关键词自动生成 + 主线切换逻辑

从行业动量数据推导:
- 当季主线 (60日动量)
- 近期加速 (20日 vs 60日)
- 主线切换 (新进/退出 Top5)
- 当日关键词 (供选股/报告/因子加权)
"""
from __future__ import annotations

import json
import logging
import os
import re
from typing import Dict, List, Optional, Tuple

import numpy as np

logger = logging.getLogger(__name__)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATE_PATH = os.path.join(BASE_DIR, "knowledge_base", "theme_state.json")

# 行业片段 -> (主题名, 展示关键词)
THEME_MAP: List[Tuple[Tuple[str, ...], str, List[str]]] = [
    (("计算机", "通信", "电子", "半导体", "软件", "互联网", "光学", "智能", "信息"), "AI算力",
     ["AI", "算力", "光模块", "CPO", "半导体", "大模型"]),
    (("电气", "电力", "电池", "光伏", "风电", "储能", "新能源"), "新能源",
     ["新能源", "储能", "光伏", "锂电", "电力"]),
    (("专用设备", "通用设备", "仪器", "自动化", "机器人", "机械"), "高端制造",
     ["机器人", "工业母机", "自动化", "高端制造"]),
    (("化学", "材料", "橡胶", "塑料", "金属", "矿物"), "新材料",
     ["新材料", "化工", "稀土", "有色"]),
    (("医药", "生物", "医疗"), "医药创新",
     ["创新药", "医疗器械", "生物医药"]),
    (("汽车", "运输", "船舶"), "汽车链",
     ["汽车", "智能驾驶", "零部件"]),
    (("零售", "批发", "商务"), "消费复苏",
     ["消费", "零售", "电商"]),
    (("建筑", "装饰", "工程"), "基建",
     ["基建", "建筑", "工程"]),
]

_STOP_WORDS = ("业", "和", "及", "其他", "服务", "制造", "生产", "供应", "加工")


def is_star_board(code: str) -> bool:
    c = str(code).split(".")[-1]
    return c.startswith("688") or c.startswith("689")


def limit_up_threshold(code: str) -> float:
    return 19.5 if is_star_board(code) else 9.5


def _industry_fragments(industry: str) -> List[str]:
    if not industry:
        return []
    parts = re.split(r"[、，,\s]+", industry)
    out = []
    for p in parts:
        p = p.strip()
        if len(p) >= 2 and p not in _STOP_WORDS:
            out.append(p[-6:] if len(p) > 8 else p)
    return out[:4]


def classify_industry(industry: str) -> Tuple[str, List[str]]:
    """行业 -> (主题标签, 关键词列表)"""
    for kws, label, display in THEME_MAP:
        if any(k in industry for k in kws):
            frags = _industry_fragments(industry)
            keys = list(dict.fromkeys(display[:3] + frags[:2]))
            return label, keys
    frags = _industry_fragments(industry)
    short = frags[0] if frags else industry[:6]
    return short or "其他", [short] if short else []


def _aggregate_themes(industry_lines: List[Dict]) -> List[Dict]:
    """按主题标签聚合行业得分"""
    buckets: Dict[str, Dict] = {}
    for line in industry_lines:
        ind = line.get("name", "")
        label, kws = classify_industry(ind)
        if label not in buckets:
            buckets[label] = {
                "theme": label,
                "keywords": list(kws),
                "industries": [],
                "mom20": [],
                "mom60": [],
                "vol_trend": [],
                "mainline_score": [],
            }
        b = buckets[label]
        b["industries"].append(ind)
        b["mom20"].append(float(line.get("mom20", 0)))
        b["mom60"].append(float(line.get("mom60", 0)))
        b["vol_trend"].append(float(line.get("vol_trend", 1)))
        b["mainline_score"].append(float(line.get("mainline_score", 0)))
        for k in kws:
            if k not in b["keywords"]:
                b["keywords"].append(k)

    themes = []
    for label, b in buckets.items():
        mom20 = float(np.mean(b["mom20"])) if b["mom20"] else 0
        mom60 = float(np.mean(b["mom60"])) if b["mom60"] else 0
        vol_t = float(np.mean(b["vol_trend"])) if b["vol_trend"] else 1
        accel = mom20 - mom60 / 3.0
        score = float(np.mean(b["mainline_score"])) if b["mainline_score"] else mom60 * 0.5 + mom20 * 0.5
        themes.append({
            "theme": label,
            "keywords": b["keywords"][:8],
            "industries": b["industries"][:5],
            "mom20": round(mom20, 2),
            "mom60": round(mom60, 2),
            "vol_trend": round(vol_t, 2),
            "acceleration": round(accel, 2),
            "theme_score": round(score + accel * 0.35 + (vol_t - 1) * 12, 2),
        })
    themes.sort(key=lambda x: x["theme_score"], reverse=True)
    return themes


def _load_prev_state() -> Dict:
    if not os.path.exists(STATE_PATH):
        return {}
    try:
        with open(STATE_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_theme_state(state: Dict) -> None:
    os.makedirs(os.path.dirname(STATE_PATH), exist_ok=True)
    with open(STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def detect_daily_themes(
    industry_lines: List[Dict],
    date: str = "",
    prev_state: Optional[Dict] = None,
    persist: bool = False,
) -> Dict:
    """
    生成当日主线与关键词，并检测主线切换。

    切换规则:
    - 新进 Top5 且 acceleration > 0 → switched_in
    - 跌出 Top5 → switched_out
    - leader 变更且新 leader acceleration > 旧 leader → 主线切换
    """
    prev = prev_state if prev_state is not None else _load_prev_state()
    themes = _aggregate_themes(industry_lines)
    top5 = [t["theme"] for t in themes[:5]]
    prev_top5 = prev.get("top5", [])
    prev_leader = prev.get("leader_theme", "")

    switched_in, switched_out = [], []
    for t in top5:
        if t not in prev_top5:
            info = next((x for x in themes if x["theme"] == t), {})
            if info.get("acceleration", 0) > -1:
                switched_in.append(t)
    for t in prev_top5:
        if t not in top5:
            switched_out.append(t)

    leader = themes[0]["theme"] if themes else ""
    leader_changed = bool(leader and leader != prev_leader)
    rotation = bool(switched_in or switched_out or leader_changed)

    # 当日关键词: Top3 主题关键词 + 切换主题
    keywords: List[str] = []
    for t in themes[:3]:
        keywords.extend(t.get("keywords", [])[:4])
    for t in switched_in:
        info = next((x for x in themes if x["theme"] == t), {})
        keywords.extend(info.get("keywords", [])[:3])
        keywords.append(t)
    keywords = list(dict.fromkeys(k for k in keywords if k))[:12]

    strategy_bias = _strategy_bias(themes, rotation, switched_in)

    state = {
        "date": date,
        "leader_theme": leader,
        "top5": top5,
        "keywords": keywords,
        "active_themes": themes[:8],
        "switched_in": switched_in,
        "switched_out": switched_out,
        "rotation": rotation,
        "strategy_bias": strategy_bias,
    }
    if persist and date:
        save_theme_state(state)
    return state


def _strategy_bias(themes: List[Dict], rotation: bool, switched_in: List[str]) -> Dict:
    """根据主线状态推荐子策略侧重"""
    if not themes:
        return {"mode": "defensive", "prefer": ["oversold_reversal", "late_session_surge"]}
    leader = themes[0]
    accel = leader.get("acceleration", 0)
    mom20 = leader.get("mom20", 0)
    if rotation and switched_in:
        return {"mode": "rotation", "prefer": ["oversold_reversal", "late_session_surge"]}
    if accel > 2 and mom20 > 5:
        return {"mode": "momentum", "prefer": ["late_session_surge", "breakout_setup"]}
    if mom20 < 0:
        return {"mode": "defensive", "prefer": ["oversold_reversal"]}
    return {"mode": "balanced", "prefer": ["late_session_surge", "oversold_reversal"]}


def theme_boost_for_industry(industry: str, theme_ctx: Optional[Dict] = None) -> float:
    if not industry or not theme_ctx:
        label, _ = classify_industry(industry)
        return 1.12 if label in ("AI算力", "新能源", "高端制造") else 1.0

    label, _ = classify_industry(industry)
    boost = 1.0
    leader = theme_ctx.get("leader_theme", "")
    if label == leader:
        boost = 1.38
    elif label in theme_ctx.get("top5", []):
        boost = 1.22
    elif label in theme_ctx.get("switched_in", []):
        boost = 1.30
    keywords = theme_ctx.get("keywords", [])
    if any(k in industry for k in keywords):
        boost = max(boost, 1.15)
    return boost


def stock_theme_boost(code: str, industry: str, theme_ctx: Optional[Dict] = None) -> float:
    b = theme_boost_for_industry(industry, theme_ctx)
    if is_star_board(code) and theme_ctx:
        label, _ = classify_industry(industry)
        if label in ("AI算力", "高端制造", "医药创新") or label == theme_ctx.get("leader_theme"):
            b *= 1.12
    return b


def industry_matches_keywords(industry: str, keywords: List[str]) -> bool:
    if not industry or not keywords:
        return False
    label, kws = classify_industry(industry)
    pool = set(keywords) | set(kws) | {label}
    return any(k in industry or k in label for k in pool)
