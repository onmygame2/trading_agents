"""Bridge live trading artifacts into TradingMemory.

The trading engine should not know SQLite details. This module translates
picker/trade outputs into structured memory rows with source tags.
"""

import logging
from collections import defaultdict
from typing import Dict, List

from core.memory import TradingMemory

logger = logging.getLogger(__name__)


def _safe_float(value, default=0.0) -> float:
    try:
        return float(value)
    except Exception:
        return default


def _signal_strategy(pick: Dict) -> str:
    return (
        pick.get("strategy_id")
        or pick.get("source_strategy_id")
        or pick.get("strategy_name")
        or "composite"
    )


def _signal_exists(mem: TradingMemory, date: str, code: str, strategy: str) -> bool:
    rows = mem.query_signals(
        code=code,
        strategy=strategy,
        days=7,
        source="live",
        include_simulated=True,
    )
    return any(r.get("date") == date and r.get("signal") == "buy" for r in rows)


def log_market_snapshot(date: str, market_overview: Dict, sector_data: Dict,
                        source: str = "live", mem: TradingMemory = None) -> None:
    mem = mem or TradingMemory()
    indices = market_overview.get("indices") or {}
    sentiment = market_overview.get("sentiment") or {}

    def idx(*names):
        for name in names:
            if name in indices:
                return indices[name] or {}
        return {}

    sh = idx("上证指数", "sh000001")
    hs300 = idx("沪深300", "sh000300")
    cyb = idx("创业板指", "sz399006")
    hot = sector_data.get("hot_sectors") or []

    mem.log_market_state({
        "date": date,
        "sh_index": sh.get("close") or sh.get("price"),
        "sh_change_pct": sh.get("change_pct"),
        "hs300": hs300.get("close") or hs300.get("price"),
        "hs300_change_pct": hs300.get("change_pct"),
        "cyb": cyb.get("close") or cyb.get("price"),
        "cyb_change_pct": cyb.get("change_pct"),
        "sentiment": sentiment.get("sentiment_label") or market_overview.get("regime") or "neutral",
        "hot_sectors": hot[:10],
        "market_breadth": sentiment.get("up_count"),
        "volume_ratio": market_overview.get("volume_ratio"),
        "source": source,
    })


def log_pick_signals(date: str, picks: List[Dict], source: str = "live",
                     mem: TradingMemory = None) -> int:
    mem = mem or TradingMemory()
    inserted = 0
    for pick in picks or []:
        code = str(pick.get("code") or "")
        if not code:
            continue
        strategy = _signal_strategy(pick)
        if _signal_exists(mem, date, code, strategy):
            continue
        mem.log_signal({
            "date": date,
            "code": code,
            "name": pick.get("name") or pick.get("stock_name"),
            "strategy": strategy,
            "signal": "buy",
            "price": pick.get("price") or pick.get("buy_price"),
            "confidence": pick.get("confidence") or pick.get("final_score") or pick.get("strategy_score"),
            "stop_loss": pick.get("stop_loss"),
            "take_profit": pick.get("take_profit"),
            "invalid_price": pick.get("invalid_price"),
            "risk_reward": pick.get("risk_reward"),
            "reason": pick.get("reason") or pick.get("strategy_name"),
            "tech_reasons": pick.get("reasons") or [],
            "source": source,
        })
        inserted += 1
    return inserted


def update_sell_outcomes(date: str, sell_actions: List[Dict], source: str = "live",
                         mem: TradingMemory = None) -> int:
    mem = mem or TradingMemory()
    updated = 0
    for action in sell_actions or []:
        if not action.get("ok", True):
            continue
        code = str(action.get("code") or "")
        if not code:
            continue
        pending = mem.query_signals(
            code=code,
            signal_type="buy",
            days=365,
            has_outcome=False,
            source=source,
            include_simulated=True,
        )
        if not pending:
            continue
        sid = action.get("strategy_id")
        signal = None
        if sid:
            signal = next((s for s in pending if s.get("strategy") == sid), None)
        signal = signal or pending[0]
        pnl = _safe_float(action.get("profit_pct"))
        outcome = "profit" if pnl > 0.1 else "loss" if pnl < -0.1 else "break_even"
        mem.update_signal_outcome(signal["id"], {
            "outcome": outcome,
            "exit_date": action.get("date") or date,
            "exit_price": action.get("price"),
            "pnl_pct": pnl,
            "hold_days": action.get("hold_days"),
        })
        if abs(pnl) >= 8:
            lesson_type = "big_win" if pnl > 0 else "big_loss"
            mem.log_lesson({
                "date": action.get("date") or date,
                "code": code,
                "strategy": signal.get("strategy"),
                "lesson_type": lesson_type,
                "title": f"{code} {'大幅盈利' if pnl > 0 else '大幅亏损'} {pnl:+.2f}%",
                "description": f"{code} 持仓 {action.get('hold_days', 0)} 天后以 {pnl:+.2f}% 结束，卖出原因：{action.get('reason', '')}",
                "pattern": action.get("reason", ""),
                "tags": ["live", lesson_type],
                "severity": 8 if pnl < 0 else 6,
                "source": source,
            })
        updated += 1
    return updated


def update_strategy_daily_perf(date: str, strategy_results: Dict[str, List[Dict]],
                               sell_actions: List[Dict], market_sentiment: str = None,
                               source: str = "live", mem: TradingMemory = None) -> int:
    mem = mem or TradingMemory()
    sells_by_strategy = defaultdict(list)
    for action in sell_actions or []:
        sid = action.get("strategy_id") or "composite"
        sells_by_strategy[sid].append(action)

    count = 0
    for strategy, picks in (strategy_results or {}).items():
        sells = sells_by_strategy.get(strategy, [])
        wins = [s for s in sells if _safe_float(s.get("profit_pct")) > 0]
        losses = [s for s in sells if _safe_float(s.get("profit_pct")) < 0]
        realized = len(wins) + len(losses)
        mem.update_strategy_perf(strategy, date, {
            "market_sentiment": market_sentiment,
            "total_signals": len(picks or []),
            "realized_signals": realized,
            "win_count": len(wins),
            "loss_count": len(losses),
            "avg_win_pct": sum(_safe_float(s.get("profit_pct")) for s in wins) / len(wins) if wins else None,
            "avg_loss_pct": sum(_safe_float(s.get("profit_pct")) for s in losses) / len(losses) if losses else None,
            "avg_hold_days": sum(_safe_float(s.get("hold_days")) for s in sells) / len(sells) if sells else None,
            "total_pnl_pct": sum(_safe_float(s.get("profit_pct")) for s in sells),
            "source": source,
        })
        count += 1
    return count


def record_picker_run(date: str, market_overview: Dict, sector_data: Dict,
                      buy_picks: List[Dict], strategy_results: Dict[str, List[Dict]],
                      stop_actions: List[Dict], source: str = "live") -> Dict:
    mem = TradingMemory()
    result = {"market": False, "signals": 0, "outcomes": 0, "strategy_perf": 0}
    try:
        log_market_snapshot(date, market_overview, sector_data, source=source, mem=mem)
        result["market"] = True
    except Exception as exc:
        logger.debug("市场记忆写入失败: %s", exc)
    try:
        result["signals"] = log_pick_signals(date, buy_picks, source=source, mem=mem)
    except Exception as exc:
        logger.debug("信号记忆写入失败: %s", exc)
    try:
        result["outcomes"] = update_sell_outcomes(date, stop_actions, source=source, mem=mem)
    except Exception as exc:
        logger.debug("信号结果写入失败: %s", exc)
    try:
        sentiment = (market_overview.get("sentiment") or {}).get("sentiment_label") or market_overview.get("regime")
        result["strategy_perf"] = update_strategy_daily_perf(
            date, strategy_results, stop_actions, sentiment, source=source, mem=mem,
        )
    except Exception as exc:
        logger.debug("策略表现写入失败: %s", exc)
    return result

