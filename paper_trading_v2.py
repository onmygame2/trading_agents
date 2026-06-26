"""
分策略纸面交易 v2 — 各策略独立 10 万虚拟盘

盘中: 各策略按自身 filter 信号买入；卖出按各策略 trade_rules
(波段/激进: 止损止盈/持仓超时; 仅 overnight 策略有次日强平)。

持久化:
  account/paper/{strategy}.json
  account/paper/{strategy}_trades.json
  state/paper_nav/{date}.json
"""

from __future__ import annotations

import glob
import json
import logging
import os
from datetime import datetime
from typing import Dict, List, Optional

from strategies_v2.trade_config import TOP_N_BUY, OVERNIGHT_RULES
from trade_engine_v2 import resolve_trade_rules

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PAPER_DIR = os.path.join(BASE_DIR, "account", "paper")
NAV_DIR = os.path.join(BASE_DIR, "state", "paper_nav")

PAPER_TOP_N = TOP_N_BUY

logger = logging.getLogger(__name__)


def _ensure_dirs():
    os.makedirs(PAPER_DIR, exist_ok=True)
    os.makedirs(NAV_DIR, exist_ok=True)


def get_strategy_list() -> Dict[str, str]:
    """已启用策略 id -> display_name"""
    from strategies_v2.manager import load_all_strategies
    mods = load_all_strategies()
    return {
        name: mod.metadata.get("name", name)
        for name, mod in mods.items()
        if mod.metadata.get("enabled", True)
    }


def get_paper_account(strategy_id: str, display_name: str = None) -> "VirtualAccount":
    from trade_engine_v2 import VirtualAccount

    _ensure_dirs()
    names = get_strategy_list()
    display = display_name or names.get(strategy_id, strategy_id)
    account_file = os.path.join(PAPER_DIR, f"{strategy_id}.json")
    trade_log = os.path.join(PAPER_DIR, f"{strategy_id}_trades.json")
    return VirtualAccount(
        account_file=account_file,
        trade_log_file=trade_log,
        strategy_id=strategy_id,
        display_name=display,
    )


def get_all_paper_accounts() -> Dict[str, "VirtualAccount"]:
    accounts = {}
    for sid, name in get_strategy_list().items():
        accounts[sid] = get_paper_account(sid, name)
    return accounts


def fetch_prices(codes: List[str], fallback: Dict[str, float] = None) -> Dict[str, float]:
    """实时价 + CSV 降级"""
    prices = dict(fallback or {})
    if not codes:
        return prices
    try:
        from market_data import get_realtime_prices
        rt = get_realtime_prices(codes)
        prices.update({k: v for k, v in rt.items() if v and v > 0})
    except Exception as e:
        logger.warning("实时价格失败: %s", e)

    missing = [c for c in codes if c not in prices or prices[c] <= 0]
    if missing:
        from factor_data import PriceVolumeFactors
        for code in missing:
            try:
                pv = PriceVolumeFactors.compute(code)
                if pv and pv.get("price"):
                    prices[code] = pv["price"]
            except Exception:
                pass
    return prices


def run_paper_buy(
    date: str,
    strategy_results: Dict[str, list],
    allow_buy: bool,
    current_prices: Dict[str, float],
    top_n: int = PAPER_TOP_N,
) -> Dict[str, List[Dict]]:
    """
    各策略独立买入（仅本策略信号）
    """
    _ensure_dirs()
    all_buys: Dict[str, List[Dict]] = {}

    for strategy_id, picks in strategy_results.items():
        from strategies_v2.manager import load_all_strategies
        mod = load_all_strategies().get(strategy_id)
        if mod and mod.metadata.get("enabled", True) is False:
            continue
        meta = mod.metadata if mod else {}
        min_score = meta.get("min_strategy_score", 0)
        acct = get_paper_account(strategy_id)
        buys: List[Dict] = []

        # 尾盘前先检查已有持仓止损
        codes = list(acct.positions.keys())
        if codes:
            px = fetch_prices(codes, current_prices)
            acct.check_stop_loss_take_profit(px, date)

        if allow_buy and picks:
            sorted_picks = sorted(picks, key=lambda x: x.get("strategy_score", 0), reverse=True)
            for pick in sorted_picks[:top_n]:
                if pick.get("strategy_score", 0) < min_score:
                    continue
                if not acct.can_buy():
                    break
                code = pick["code"]
                if code in acct.positions:
                    continue
                price = pick.get("price") or current_prices.get(code, 0)
                if not price or price <= 0:
                    continue
                amount = acct.get_buy_amount(price)
                reason = pick.get("reason", "")
                result = acct.buy(code, price, amount, date, reason)
                if result.get("ok"):
                    buys.append(result)

        acct.save()
        all_buys[strategy_id] = buys
        if buys:
            logger.info("纸面 %s: 买入 %d 笔", acct.display_name, len(buys))

    snapshot_nav(date, current_prices)
    return all_buys


def run_paper_sell(date: str) -> Dict[str, Dict]:
    """各策略盘中卖出检查（规则按 trade_rules 区分）"""
    _ensure_dirs()
    from strategies_v2.manager import load_all_strategies
    strategy_modules = load_all_strategies()
    results = {}

    for strategy_id, acct in get_all_paper_accounts().items():
        if not acct.positions:
            results[strategy_id] = {
                "display_name": acct.display_name,
                "sell_actions": [],
                "account_value": acct.cash,
                "positions": [],
            }
            continue

        codes = list(acct.positions.keys())
        prices = fetch_prices(codes)

        acct.advance_hold_days(date)
        stop_actions = acct.check_stop_loss_take_profit(prices, date)
        sold = {s["code"] for s in stop_actions if s.get("ok")}

        meta = strategy_modules[strategy_id].metadata if strategy_id in strategy_modules else {}
        rules = resolve_trade_rules(strategy_id, meta)
        overnight = []
        if rules.get("trade_rules") == "overnight":
            force_days = rules.get("force_exit_days") or OVERNIGHT_RULES.get("force_exit_days") or 1
            if force_days <= 0:
                force_days = 1
            for code, pos in list(acct.positions.items()):
                hold = pos.get("hold_days", 0)
                if hold >= force_days and code not in sold:
                    price = prices.get(code, pos["avg_price"])
                    r = acct.sell(code, price, date, f"隔夜平仓({hold}天)")
                    if r.get("ok"):
                        overnight.append(r)

        acct.save()
        sell_all = stop_actions + overnight
        results[strategy_id] = {
            "display_name": acct.display_name,
            "sell_actions": sell_all,
            "account_value": round(acct.get_total_value(prices), 2),
            "positions": acct.get_positions_summary(prices),
        }
        if sell_all:
            logger.info("纸面 %s: 卖出 %d 笔", acct.display_name, len(sell_all))

    snapshot_nav(date, fetch_prices([]))
    return results


def snapshot_nav(date: str, price_hint: Dict[str, float] = None):
    """每日净值快照"""
    _ensure_dirs()
    snapshot = {"date": date, "strategies": {}, "composite_ref": None}

    try:
        from trade_engine_v2 import get_account, INITIAL_CAPITAL
        composite = get_account()
        all_codes = []
        for acct in get_all_paper_accounts().values():
            all_codes.extend(acct.positions.keys())
        all_codes.extend(composite.positions.keys())
        prices = fetch_prices(list(set(all_codes)), price_hint or {})

        for sid, acct in get_all_paper_accounts().items():
            val = acct.get_total_value(prices)
            snapshot["strategies"][sid] = {
                "display_name": acct.display_name,
                "value": round(val, 2),
                "cash": round(acct.cash, 2),
                "return_pct": round((val / INITIAL_CAPITAL - 1) * 100, 2),
                "positions": len(acct.positions),
                "total_profit": round(acct.total_profit, 2),
            }

        cval = composite.get_total_value(prices)
        snapshot["composite_ref"] = {
            "value": round(cval, 2),
            "return_pct": round((cval / INITIAL_CAPITAL - 1) * 100, 2),
        }
    except Exception as e:
        logger.warning("净值快照失败: %s", e)

    path = os.path.join(NAV_DIR, f"{date}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(snapshot, f, ensure_ascii=False, indent=2)
    return snapshot


def load_nav_history(limit: int = 90) -> List[Dict]:
    files = sorted(glob.glob(os.path.join(NAV_DIR, "*.json")))[-limit:]
    history = []
    for path in files:
        try:
            with open(path, "r", encoding="utf-8") as f:
                history.append(json.load(f))
        except Exception:
            pass
    return history


def compute_paper_stats(strategy_id: str) -> Dict:
    """单策略纸面绩效"""
    from trade_engine_v2 import INITIAL_CAPITAL

    acct = get_paper_account(strategy_id)
    codes = list(acct.positions.keys())
    prices = fetch_prices(codes)
    equity = acct.get_total_value(prices)
    return_pct = (equity / INITIAL_CAPITAL - 1) * 100

    trades = []
    if os.path.exists(acct.trade_log_file):
        with open(acct.trade_log_file, "r", encoding="utf-8") as f:
            trades = json.load(f)
    sells = [t for t in trades if t.get("action") == "SELL"]
    wins = [t for t in sells if (t.get("profit") or 0) > 0]
    win_rate = len(wins) / len(sells) * 100 if sells else 0

    return {
        "name": strategy_id,
        "display_name": acct.display_name,
        "equity": round(equity, 2),
        "cash": round(acct.cash, 2),
        "return_pct": round(return_pct, 2),
        "total_profit": round(acct.total_profit, 2),
        "total_trades": len(sells),
        "win_rate": round(win_rate, 1),
        "positions": acct.get_positions_summary(prices),
        "position_count": len(acct.positions),
        "created_at": acct.created_at,
        "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }


def build_paper_ranking() -> List[Dict]:
    stats = [compute_paper_stats(sid) for sid in get_strategy_list()]
    stats.sort(key=lambda x: x["return_pct"], reverse=True)
    return stats


def init_paper_accounts():
    """初始化 5 策略纸面账户（若不存在）"""
    _ensure_dirs()
    for sid, name in get_strategy_list().items():
        path = os.path.join(PAPER_DIR, f"{sid}.json")
        if not os.path.exists(path):
            acct = get_paper_account(sid, name)
            acct.save()
            log_path = os.path.join(PAPER_DIR, f"{sid}_trades.json")
            with open(log_path, "w", encoding="utf-8") as f:
                json.dump([], f)
            logger.info("初始化纸面账户: %s", name)
