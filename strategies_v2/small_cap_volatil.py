"""小盘强势 — 复用突破逻辑 + 市值过滤"""
from typing import Dict, List
from strategies_v2 import breakout_setup


def filter(stocks: List[Dict], sector_data: Dict = None) -> List[Dict]:
    small = []
    for s in stocks:
        cap = (s.get("extra") or {}).get("market_cap", 9999) or 9999
        if 22 <= cap <= 60:
            small.append(s)
    picks = breakout_setup.filter(small, sector_data) or []
    out = []
    for p in picks:
        code = p["code"]
        stock = next((x for x in small if x.get("code") == code), None)
        cap = (stock.get("extra") or {}).get("market_cap", 0) if stock else 0
        out.append({
            **p,
            "reason": f"小盘{cap:.0f}亿 | " + p.get("reason", ""),
            "strategy_score": min(99, p.get("strategy_score", 0) + 2),
        })
    return out[:4]


metadata = {
    "name": "小盘强势",
    "weight": 0.95,
    "enabled": True,
    "trade_rules": "swing",
    "market_filter": "loose",
    "max_positions": 2,
    "min_strategy_score": 72,
    "description": "突破蓄势逻辑限定小市值",
}
