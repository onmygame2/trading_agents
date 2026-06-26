"""
strategies_v2 统一回测引擎

对齐 trade_engine_v2 规则:
- 初始资金 10 万, 万1免5, 印花税 0.1%
- 最大 5 仓, 单仓 20%
- 硬止损 -7%, 止盈 +15%, 移动止盈回撤 5%
- 隔夜模式: 尾盘(close)买入, 次日检查止损/止盈, hold_days>=2 强制平仓

用法:
    python backtest_v2.py --start 2024-01-01 --end 2025-12-31
    python backtest_v2.py --start 2025-01-01 --end 2025-06-01 --pool-top 300 --quick
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)

from factor_engine_v2 import FactorEngine
from market_filter import is_allowed
from strategies_v2.manager import StrategyManager
from trading_calendar import is_trading_day

from strategies_v2.trade_config import (
    MAX_POSITIONS,
    MAX_SINGLE_PCT,
    TOP_N_BUY,
    BUY_WEIGHTS,
    MIN_STRATEGY_SCORE,
    COOLDOWN_DAYS,
    MIN_TRAIL_PROFIT,
    MIN_TRAIL_PROFIT_SWING,
    OVERNIGHT_RULES,
    SWING_RULES,
    BOUNCE_RULES,
    AGGRESSIVE_RULES,
    MARKET_FILTERS,
    LIMIT_UP_HOLD,
    LIMIT_UP_THRESHOLD,
    BACKTEST_TRAIN_END,
    PAPER_TRADE_START,
)

logger = logging.getLogger(__name__)

DATA_DIR = os.path.join(BASE_DIR, "data")
KLINE_DIR = os.path.join(DATA_DIR, "kline")
FUND_DIR = os.path.join(DATA_DIR, "fundamentals")
REPORT_DIR = os.path.join(BASE_DIR, "reports", "backtest_v2")

INITIAL_CAPITAL = 100_000
COMMISSION_RATE = 0.0001
STAMP_TAX = 0.001
DEFAULT_MIN_SCORE = 40
DEFAULT_TOP_N = TOP_N_BUY
INDEX_CODE = "000001"


# ---------------------------------------------------------------------------
# 回测账户 (内存版 VirtualAccount)
# ---------------------------------------------------------------------------

class BacktestAccount:
    """单策略/组合独立虚拟账户"""

    def __init__(
        self,
        name: str,
        initial_capital: float = INITIAL_CAPITAL,
        max_positions: int = MAX_POSITIONS,
        stop_loss: float = SWING_RULES["stop_loss"],
        take_profit: float = SWING_RULES["take_profit"],
        trailing_stop: float = SWING_RULES["trailing_stop"],
        min_strategy_score: int = MIN_STRATEGY_SCORE,
        hold_mode: str = "swing",
        max_hold_days: int = SWING_RULES["max_hold_days"],
        force_exit_days: int = 0,
        market_filter: str = "normal",
    ):
        self.name = name
        self.initial_capital = initial_capital
        self.max_positions = max_positions
        self.stop_loss = stop_loss
        self.take_profit = take_profit
        self.trailing_stop = trailing_stop
        self.min_strategy_score = min_strategy_score
        self.hold_mode = hold_mode
        self.max_hold_days = max_hold_days
        self.force_exit_days = force_exit_days
        self.market_filter = market_filter
        self.cash = initial_capital
        self.positions: Dict[str, Dict] = {}
        self.trades: List[Dict] = []
        self.nav_history: List[Dict] = []
        self.total_profit = 0.0
        self.cooldown: Dict[str, str] = {}  # code -> last_sell_date

    def reset(self):
        self.cash = self.initial_capital
        self.positions = {}
        self.trades = []
        self.nav_history = []
        self.total_profit = 0.0
        self.cooldown = {}

    def get_total_value(self, prices: Dict[str, float]) -> float:
        pos_val = sum(
            prices.get(code, pos["avg_price"]) * pos["shares"]
            for code, pos in self.positions.items()
        )
        return self.cash + pos_val

    def can_buy(self) -> bool:
        return len(self.positions) < self.max_positions

    def in_cooldown(self, code: str, date: str) -> bool:
        if COOLDOWN_DAYS <= 0:
            return False
        last = self.cooldown.get(code)
        if not last:
            return False
        try:
            d0 = datetime.strptime(last, "%Y-%m-%d")
            d1 = datetime.strptime(date, "%Y-%m-%d")
            return (d1 - d0).days < COOLDOWN_DAYS
        except Exception:
            return False

    def get_buy_amount(self, rank_idx: int, prices: Dict[str, float]) -> float:
        total = self.get_total_value(prices)
        w = BUY_WEIGHTS[rank_idx] if rank_idx < len(BUY_WEIGHTS) else MAX_SINGLE_PCT
        return max(0, min(self.cash, total * w))

    def buy(
        self,
        code: str,
        price: float,
        amount: float,
        date: str,
        reason: str = "",
        stop_loss_pct: float = None,
        take_profit_pct: float = None,
    ) -> Dict:
        if code in self.positions or not self.can_buy() or price <= 0:
            return {"ok": False}

        shares = int(amount / (price * 100)) * 100
        if shares <= 0:
            return {"ok": False}

        cost = shares * price
        commission = cost * COMMISSION_RATE
        total_cost = cost + commission
        if total_cost > self.cash:
            shares = int((self.cash / (price * (1 + COMMISSION_RATE))) / 100) * 100
            if shares <= 0:
                return {"ok": False}
            cost = shares * price
            commission = cost * COMMISSION_RATE
            total_cost = cost + commission

        sl = stop_loss_pct if stop_loss_pct is not None else self.stop_loss
        tp = take_profit_pct if take_profit_pct is not None else self.take_profit

        self.cash -= total_cost
        self.positions[code] = {
            "shares": shares,
            "avg_price": price,
            "buy_date": date,
            "high_price": price,
            "reason": reason,
            "hold_days": 0,
            "last_hold_date": date,
            "stop_loss": sl,
            "take_profit": tp,
        }
        trade = {
            "action": "BUY",
            "code": code,
            "price": round(price, 2),
            "shares": shares,
            "amount": round(cost, 2),
            "commission": round(commission, 2),
            "date": date,
            "reason": reason,
        }
        self.trades.append(trade)
        return {"ok": True, **trade}

    def _can_sell_today(self, pos: Dict, date: str) -> bool:
        return pos.get("buy_date") != date

    def advance_hold_days(self, date: str):
        for pos in self.positions.values():
            if pos.get("last_hold_date") == date:
                continue
            pos["hold_days"] = pos.get("hold_days", 0) + 1
            pos["last_hold_date"] = date

    def sell(self, code: str, price: float, date: str, reason: str = "") -> Dict:
        if code not in self.positions or price <= 0:
            return {"ok": False}
        pos = self.positions[code]
        if not self._can_sell_today(pos, date):
            return {"ok": False}

        shares = pos["shares"]
        sell_amount = shares * price
        commission = sell_amount * COMMISSION_RATE
        stamp_tax = sell_amount * STAMP_TAX
        net = sell_amount - commission - stamp_tax
        cost_basis = shares * pos["avg_price"]
        profit = sell_amount - cost_basis - commission - stamp_tax
        profit_pct = profit / cost_basis * 100 if cost_basis else 0

        self.cash += net
        del self.positions[code]
        self.total_profit += profit
        self.cooldown[code] = date

        trade = {
            "action": "SELL",
            "code": code,
            "price": round(price, 2),
            "shares": shares,
            "amount": round(sell_amount, 2),
            "commission": round(commission, 2),
            "stamp_tax": round(stamp_tax, 2),
            "profit": round(profit, 2),
            "profit_pct": round(profit_pct, 2),
            "hold_days": pos.get("hold_days", 0),
            "date": date,
            "reason": reason,
            "buy_date": pos.get("buy_date", ""),
        }
        self.trades.append(trade)
        return {"ok": True, **trade}

    def record_nav(self, date: str, prices: Dict[str, float]):
        value = self.get_total_value(prices)
        ret = (value / self.initial_capital - 1) * 100
        self.nav_history.append({
            "date": date,
            "value": round(value, 2),
            "cash": round(self.cash, 2),
            "positions": len(self.positions),
            "return_pct": round(ret, 2),
        })


# ---------------------------------------------------------------------------
# 历史因子计算
# ---------------------------------------------------------------------------

def load_stock_pool() -> List[str]:
    pool_file = os.path.join(DATA_DIR, "stock_pool.json")
    codes = []
    if os.path.exists(pool_file):
        with open(pool_file, "r", encoding="utf-8") as f:
            pool = json.load(f)
        for item in pool:
            if isinstance(item, dict):
                code = str(item.get("code", "")).split(".")[-1]
                name = item.get("name", item.get("code_name", ""))
            else:
                code = str(item).split(".")[-1]
                name = ""
            if code and is_allowed(code, name):
                codes.append(code)
    return codes


def load_kline(code: str, start: str, end: str) -> Optional[pd.DataFrame]:
    path = os.path.join(KLINE_DIR, f"{code}.csv")
    if not os.path.exists(path):
        return None
    try:
        from kline_sanitize import sanitize_kline_df
        df = pd.read_csv(path)
        df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")
        for col in ("open", "high", "low", "close", "volume", "amount", "change_pct"):
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")
        df = sanitize_kline_df(df.sort_values("date"))
        df = df[(df["date"] >= start) & (df["date"] <= end)].copy()
        if len(df) < 30:
            return None
        return df.reset_index(drop=True)
    except Exception:
        return None


def build_trading_dates(start: str, end: str) -> List[str]:
    dates = []
    dt = datetime.strptime(start, "%Y-%m-%d")
    end_dt = datetime.strptime(end, "%Y-%m-%d")
    while dt <= end_dt:
        ds = dt.strftime("%Y-%m-%d")
        if is_trading_day(ds):
            dates.append(ds)
        dt += timedelta(days=1)
    return dates


def compute_pv_from_df(df: pd.DataFrame, idx: int) -> Dict:
    """截至 idx 日收盘的价量因子 (对齐 PriceVolumeFactors)"""
    if idx < 29:
        return {}

    close = df["close"].values[: idx + 1]
    high = df["high"].values[: idx + 1]
    low = df["low"].values[: idx + 1]
    volume = df["volume"].values[: idx + 1]
    row = df.iloc[idx]
    n = len(close)

    ma5 = float(np.nanmean(close[-5:]))
    ma10 = float(np.nanmean(close[-10:]))
    ma20 = float(np.nanmean(close[-20:]))
    ma60 = float(np.nanmean(close[-60:])) if n >= 60 else ma20

    dif_series = pd.Series(close).ewm(span=12).mean() - pd.Series(close).ewm(span=26).mean()
    dif = float(dif_series.iloc[-1])
    dea = float(dif_series.ewm(span=9).mean().iloc[-1])
    macd_hist = 2 * (dif - dea)
    prev_dif = float(dif_series.ewm(span=9).mean().iloc[-2]) if n >= 27 else dea

    delta = np.diff(close[-15:])
    gain = np.where(delta > 0, delta, 0)
    loss = np.where(delta < 0, -delta, 0)
    avg_gain = np.mean(gain)
    avg_loss = np.mean(loss)
    rsi = 100 - (100 / (1 + avg_gain / avg_loss)) if avg_loss > 0 else 100

    boll_mid = np.mean(close[-20:])
    boll_std = np.std(close[-20:])
    boll_up = boll_mid + 2 * boll_std
    boll_down = boll_mid - 2 * boll_std
    boll_width = (boll_up - boll_down) / boll_mid if boll_mid > 0 else 0

    vol_ma5 = np.mean(volume[-5:])
    vol_ma20 = np.mean(volume[-20:])
    vol_ratio = vol_ma5 / vol_ma20 if vol_ma20 > 0 else 1.0

    mom_5d = (close[-1] / close[-6] - 1) * 100 if n >= 6 else 0
    mom_10d = (close[-1] / close[-11] - 1) * 100 if n >= 11 else 0
    mom_20d = (close[-1] / close[-21] - 1) * 100 if n >= 21 else 0

    if n >= 21:
        rets = np.diff(close[-21:]) / close[-21:-1]
        volatility = float(np.std(rets) * np.sqrt(252) * 100)
    else:
        volatility = 0

    high_20 = np.max(high[-20:])
    low_20 = np.min(low[-20:])
    price_pos = (close[-1] - low_20) / (high_20 - low_20) * 100 if (high_20 - low_20) > 0 else 50

    break_60d = False
    if n >= 60:
        break_60d = close[-1] > np.max(high[-60:-1])

    ma_bull = bool(ma5 > ma10 > ma20)
    macd_golden_cross = bool(prev_dif and dif > dea and prev_dif <= dea)

    change_pct = float(row.get("change_pct", 0) or 0)
    if not change_pct and n >= 2:
        change_pct = (close[-1] / close[-2] - 1) * 100

    limit_up_count = 0
    has_limit_up = False
    scan = min(120, n - 1)
    for i in range(-1, -scan - 1, -1):
        prev = close[i - 1]
        if prev > 0 and (close[i] / prev - 1) >= 0.095:
            limit_up_count += 1
            has_limit_up = True

    today_high = float(row["high"])
    today_low = float(row["low"])
    current_price = float(row["close"])

    return {
        "price": round(current_price, 2),
        "today_high": round(today_high, 2),
        "today_low": round(today_low, 2),
        "ma5": round(ma5, 2),
        "ma10": round(ma10, 2),
        "ma20": round(ma20, 2),
        "ma60": round(ma60, 2),
        "macd_dif": round(dif, 4),
        "macd_dea": round(dea, 4),
        "macd_hist": round(macd_hist, 4),
        "rsi": round(rsi, 2),
        "boll_up": round(boll_up, 2),
        "boll_mid": round(boll_mid, 2),
        "boll_down": round(boll_down, 2),
        "boll_width": round(boll_width, 4),
        "vol_ratio": round(vol_ratio, 2),
        "mom_5d": round(mom_5d, 2),
        "mom_10d": round(mom_10d, 2),
        "mom_20d": round(mom_20d, 2),
        "volatility": round(volatility, 2),
        "price_pos": round(price_pos, 2),
        "break_60d": break_60d,
        "ma_bull": ma_bull,
        "macd_golden_cross": macd_golden_cross,
        "price_vs_ma20": round((current_price / ma20 - 1) * 100, 2) if ma20 else None,
        "change_pct": round(change_pct, 2),
        "has_limit_up_180d": has_limit_up,
        "limit_up_count_180d": limit_up_count,
    }


def load_fundamentals_cache(codes: List[str]) -> Dict[str, Dict]:
    cache = {}
    for code in codes:
        for year in ("2025", "2024"):
            path = os.path.join(FUND_DIR, f"{code}_fund_{year}.json")
            if not os.path.exists(path):
                continue
            try:
                with open(path, "r", encoding="utf-8") as f:
                    raw = json.load(f)
                profit = raw.get("profit", {})
                growth = raw.get("growth", {})
                balance = raw.get("balance", {})
                industry = raw.get("industry", {})
                fund = {
                    "roe": profit.get("roeAvg"),
                    "np_margin": profit.get("npMargin"),
                    "gp_margin": profit.get("gpMargin"),
                    "eps": profit.get("epsTTM"),
                    "yoy_ni": growth.get("YOYNI"),
                    "yoy_eps": growth.get("YOYEPSBasic"),
                    "liability_ratio": balance.get("liabilityToAsset"),
                    "current_ratio": balance.get("currentRatio"),
                    "industry": industry.get("industryName", industry.get("industry", "")),
                    "total_share": profit.get("totalShare"),
                }
                cache[code] = fund
                break
            except Exception:
                pass
    return cache


def load_industry_map() -> Dict[str, str]:
    path = os.path.join(DATA_DIR, "stock_industry.json")
    if not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as f:
        raw = json.load(f)
    result = {}
    for code, info in raw.items():
        code = str(code).split(".")[-1]
        if isinstance(info, dict):
            result[code] = info.get("industryName", info.get("industry", ""))
        else:
            result[code] = str(info)
    return result


def build_extra(fund: Dict, price: float) -> Dict:
    total_share = fund.get("total_share") or 0
    market_cap = total_share * price / 1e8 if total_share and price else 9999
    return {"market_cap": round(market_cap, 2)}


def compute_sector_data(
    kline_data: Dict[str, pd.DataFrame],
    date_idx: Dict[str, Dict[str, int]],
    date: str,
    industry_map: Dict[str, str],
) -> Dict:
    """用当日行业平均涨幅构造 hot_sectors"""
    industry_changes: Dict[str, List[float]] = defaultdict(list)
    for code, df in kline_data.items():
        idx = date_idx.get(code, {}).get(date)
        if idx is None:
            continue
        industry = industry_map.get(code, "")
        if not industry:
            continue
        chg = float(df.iloc[idx].get("change_pct", 0) or 0)
        industry_changes[industry].append(chg)

    hot = []
    for name, changes in industry_changes.items():
        if len(changes) >= 3:
            hot.append({"name": name, "change_pct": round(float(np.mean(changes)), 2)})
    hot.sort(key=lambda x: x["change_pct"], reverse=True)
    return {"hot_sectors": hot[:10], "hot_concepts": hot[:10], "cold_sectors": hot[-5:]}


def select_pool_by_liquidity(codes: List[str], kline_data: Dict[str, pd.DataFrame], top_n: int) -> List[str]:
    ranked = []
    for code in codes:
        df = kline_data.get(code)
        if df is None or df.empty:
            continue
        amt_col = "amount" if "amount" in df.columns else "volume"
        avg = float(df[amt_col].tail(60).mean())
        ranked.append((code, avg))
    ranked.sort(key=lambda x: x[1], reverse=True)
    return [c for c, _ in ranked[:top_n]]


def build_date_index(kline_data: Dict[str, pd.DataFrame]) -> Dict[str, Dict[str, int]]:
    idx_map: Dict[str, Dict[str, int]] = {}
    for code, df in kline_data.items():
        idx_map[code] = {d: i for i, d in enumerate(df["date"].tolist())}
    return idx_map


def score_stocks_for_date(
    codes: List[str],
    kline_data: Dict[str, pd.DataFrame],
    date_idx: Dict[str, Dict[str, int]],
    date: str,
    engine: FactorEngine,
    fund_cache: Dict[str, Dict],
    industry_map: Dict[str, str],
    sector_data: Dict,
    min_score: int,
) -> List[Dict]:
    capital_data = {"north_total_5d": 0}
    stocks_data = []

    for code in codes:
        idx = date_idx.get(code, {}).get(date)
        df = kline_data.get(code)
        if idx is None or df is None:
            continue
        pv = compute_pv_from_df(df, idx)
        if not pv:
            continue

        fund_raw = fund_cache.get(code, {})
        price = pv["price"]
        fund = dict(fund_raw)
        eps = fund.get("eps")
        if eps and eps > 0 and price > 0:
            fund["pe"] = round(price / eps, 2)
        if not fund.get("industry"):
            fund["industry"] = industry_map.get(code, "")

        try:
            scored = engine.score_stock(code, pv, fund, sector_data, capital_data)
            scored["price_volume"] = pv
            scored["fundamental"] = fund
            scored["extra"] = build_extra(fund, price)
            scored["price"] = price
            scored["industry"] = industry_map.get(code, fund.get("industry", ""))
            if scored["total_score"] >= min_score:
                stocks_data.append(scored)
        except Exception:
            pass

    stocks_data.sort(key=lambda x: x["total_score"], reverse=True)

    try:
        from message_screener import get_screener
        get_screener().score_batch(stocks_data, sector_data, date)
    except Exception:
        pass

    return stocks_data


def get_bar(df: pd.DataFrame, idx: int) -> Dict[str, float]:
    row = df.iloc[idx]
    vol_ratio = 1.0
    if "volume" in df.columns and idx >= 5:
        vol = df["volume"].values[: idx + 1]
        ma5 = float(np.mean(vol[-5:]))
        if ma5 > 0:
            vol_ratio = float(vol[-1] / ma5)
    chg = float(row.get("change_pct", 0) or 0)
    if not chg and idx >= 1:
        prev = float(df.iloc[idx - 1]["close"])
        if prev > 0:
            chg = (float(row["close"]) / prev - 1) * 100
    return {
        "open": float(row["open"]),
        "high": float(row["high"]),
        "low": float(row["low"]),
        "close": float(row["close"]),
        "change_pct": chg,
        "vol_ratio": vol_ratio,
    }


def adaptive_filter_level(
    index_mom_5d: float,
    index_mom_20d: float,
    index_bull: bool,
    base: str = "normal",
) -> str:
    """牛市放宽、弱势收紧"""
    if not index_bull or index_mom_20d < -3 or index_mom_5d < -5:
        return "strict" if base != "loose" else "normal"
    if index_bull and index_mom_20d > 2 and index_mom_5d > 0:
        return "loose" if base == "normal" else base
    return base


def market_allows_buy(
    index_change: float,
    index_mom_5d: float = 0.0,
    filter_level: str = "normal",
    index_mom_20d: float = 0.0,
    index_bull: bool = True,
) -> bool:
    filter_level = adaptive_filter_level(index_mom_5d, index_mom_20d, index_bull, filter_level)
    cfg = MARKET_FILTERS.get(filter_level, MARKET_FILTERS["normal"])
    if index_change < cfg["index_min"]:
        return False
    if index_mom_5d < cfg["mom5_min"]:
        return False
    mom20_min = cfg.get("mom20_min")
    if mom20_min is not None and index_mom_20d < mom20_min:
        return False
    if cfg.get("require_ma20") and not index_bull:
        return False
    return True


def index_momentum_5d(index_df: pd.DataFrame, idx: int) -> float:
    if index_df is None or idx is None or idx < 5:
        return 0.0
    close = index_df["close"].values[: idx + 1]
    return float((close[-1] / close[-6] - 1) * 100)


def index_momentum_20d(index_df: pd.DataFrame, idx: int) -> float:
    if index_df is None or idx is None or idx < 20:
        return 0.0
    close = index_df["close"].values[: idx + 1]
    return float((close[-1] / close[-21] - 1) * 100)


def index_above_ma20(index_df: pd.DataFrame, idx: int) -> bool:
    if index_df is None or idx is None or idx < 20:
        return True
    close = index_df["close"].values[: idx + 1]
    ma20 = float(np.mean(close[-20:]))
    return close[-1] >= ma20 * 0.995


def default_backtest_range() -> Tuple[str, str]:
    """默认回测: 2024-2025 训练验证"""
    return "2024-01-01", BACKTEST_TRAIN_END


_RULE_PRESETS = {
    "overnight": OVERNIGHT_RULES,
    "swing": SWING_RULES,
    "bounce": BOUNCE_RULES,
    "aggressive": AGGRESSIVE_RULES,
}


def _account_from_meta(name: str, meta: Dict) -> BacktestAccount:
    """从策略 metadata 创建回测账户 (隔夜 / 波段 / 反弹)"""
    preset_key = meta.get("trade_rules", "swing")
    preset = _RULE_PRESETS.get(preset_key, SWING_RULES)
    return BacktestAccount(
        name,
        max_positions=meta.get("max_positions", MAX_POSITIONS),
        stop_loss=meta.get("stop_loss", preset["stop_loss"]),
        take_profit=meta.get("take_profit", preset["take_profit"]),
        trailing_stop=meta.get("trailing_stop", preset.get("trailing_stop", SWING_RULES["trailing_stop"])),
        min_strategy_score=meta.get("min_strategy_score", MIN_STRATEGY_SCORE),
        hold_mode=preset["hold_mode"],
        max_hold_days=meta.get("max_hold_days", preset["max_hold_days"]),
        force_exit_days=meta.get("force_exit_days", preset.get("force_exit_days", 0)),
        market_filter=meta.get("market_filter", "normal"),
    )


def _pick_stop_take(pick: Dict, buy_price: float, acct: BacktestAccount) -> Tuple[float, float]:
    """统一使用账户级止损止盈，避免 pick 内过紧价格覆盖"""
    return acct.stop_loss, acct.take_profit


def process_sells(account: BacktestAccount, date: str, kline_data: Dict[str, pd.DataFrame], date_idx: Dict):
    """卖出: 涨停继续持股; 激进模式让利润奔跑"""
    account.advance_hold_days(date)
    is_overnight = account.hold_mode in ("overnight", "aggressive")
    gap_tp = OVERNIGHT_RULES.get("gap_take_profit", 0.08)
    gap_sl = OVERNIGHT_RULES.get("gap_stop_loss", -0.06)
    min_trail = MIN_TRAIL_PROFIT if account.hold_mode == "overnight" else MIN_TRAIL_PROFIT_SWING

    for code in list(account.positions.keys()):
        pos = account.positions.get(code)
        if not pos or not account._can_sell_today(pos, date):
            continue

        df = kline_data.get(code)
        idx = date_idx.get(code, {}).get(date)
        if df is None or idx is None:
            continue

        bar = get_bar(df, idx)
        buy_price = pos["avg_price"]
        open_p, high_p, low_p, close_p = bar["open"], bar["high"], bar["low"], bar["close"]
        sl = pos.get("stop_loss", account.stop_loss)
        tp = pos.get("take_profit", account.take_profit)
        trail = account.trailing_stop
        hold_days = pos.get("hold_days", 0)
        day_chg = bar.get("change_pct", 0)

        if high_p > pos.get("high_price", 0):
            pos["high_price"] = high_p

        # 涨停/封板: 继续持股; 连续涨停超过5天则尾盘减仓
        from theme_engine import limit_up_threshold
        lu_th = limit_up_threshold(code)
        if LIMIT_UP_HOLD and day_chg >= lu_th:
            pos["limit_up_streak"] = pos.get("limit_up_streak", 0) + 1
            if pos.get("limit_up_streak", 0) < 5:
                continue
        else:
            pos["limit_up_streak"] = 0

        reason = None
        sell_price = None
        open_chg = (open_p - buy_price) / buy_price if buy_price else 0
        close_chg = (close_p - buy_price) / buy_price if buy_price else 0
        vol_r = bar.get("vol_ratio", 1.0)
        peak_profit = (pos.get("high_price", buy_price) - buy_price) / buy_price

        if is_overnight and hold_days == 1:
            if open_chg >= gap_tp:
                reason, sell_price = f"跳空止盈({open_chg:.1%})", open_p
            elif open_chg <= gap_sl:
                reason, sell_price = f"跳空止损({open_chg:.1%})", open_p

        if not reason and hold_days >= account.max_hold_days:
            reason, sell_price = f"持仓到期({hold_days}天)", close_p

        skip_open_rules = account.hold_mode == "overnight" and hold_days <= 1
        if not reason and not skip_open_rules:
            if open_chg <= sl:
                reason, sell_price = f"硬止损({open_chg:.1%})", open_p
            elif open_chg >= tp:
                reason, sell_price = f"止盈({open_chg:.1%})", open_p
            else:
                low_chg = (low_p - buy_price) / buy_price
                high_chg = (high_p - buy_price) / buy_price
                if low_chg <= sl:
                    reason = f"硬止损({low_chg:.1%})"
                    sell_price = buy_price * (1 + sl)
                elif high_chg >= tp:
                    reason = f"止盈({high_chg:.1%})"
                    sell_price = buy_price * (1 + tp)
                elif pos.get("high_price", 0) > buy_price:
                    if peak_profit >= min_trail:
                        trail_price = pos["high_price"] * (1 - trail)
                        if low_p <= trail_price:
                            reason = f"移动止盈(峰值{peak_profit:.1%})"
                            sell_price = max(trail_price, low_p)

        # 量价观察 (非涨停日)
        if not reason and is_overnight and hold_days >= 1:
            if day_chg >= 3.0 and vol_r >= 1.2:
                pass
            elif day_chg <= -5.0 or (day_chg <= -3.0 and vol_r >= 1.5):
                reason = f"放量下跌({day_chg:.1f}%)"
                sell_price = close_p
            elif peak_profit >= 0.15 and close_chg < peak_profit - 0.08:
                reason = f"高位回撤({close_chg:.1%})"
                sell_price = close_p
            elif close_chg <= sl:
                reason = f"止损({close_chg:.1%})"
                sell_price = close_p

        if not reason and account.hold_mode == "aggressive" and hold_days >= max(5, account.max_hold_days - 5):
            if close_chg < -0.04 and peak_profit < 0.05:
                reason = f"弱势({close_chg:.1%})"
                sell_price = close_p

        if reason and sell_price:
            account.sell(code, sell_price, date, reason)


def process_buys(
    account: BacktestAccount,
    picks: List[Dict],
    date: str,
    kline_data: Dict[str, pd.DataFrame],
    date_idx: Dict[str, Dict[str, int]],
    top_n: int,
):
    """尾盘: close 价买入，按排名加权仓位"""
    prices = {}
    for code in account.positions:
        idx = date_idx.get(code, {}).get(date)
        df = kline_data.get(code)
        if idx is not None and df is not None:
            prices[code] = float(df.iloc[idx]["close"])

    bought = 0
    for pick in picks:
        if bought >= top_n or not account.can_buy():
            break
        score = pick.get("strategy_score", 0)
        if score < account.min_strategy_score:
            continue
        code = pick["code"]
        if code in account.positions or account.in_cooldown(code, date):
            continue
        idx = date_idx.get(code, {}).get(date)
        df = kline_data.get(code)
        if idx is None or df is None:
            continue
        price = float(df.iloc[idx]["close"])
        if price <= 0:
            continue
        chg = float(df.iloc[idx].get("change_pct", 0) or 0)
        if not chg and idx >= 1:
            prev = float(df.iloc[idx - 1]["close"])
            if prev > 0:
                chg = (price / prev - 1) * 100
        # 涨停日无法 realistically 买入，跳过新开仓
        from theme_engine import limit_up_threshold
        if chg >= limit_up_threshold(code) - 0.3:
            continue
        prices[code] = price
        sl, tp = _pick_stop_take(pick, price, account)
        amount = account.get_buy_amount(bought, prices)
        reason = pick.get("reason", "")
        result = account.buy(code, price, amount, date, reason, stop_loss_pct=sl, take_profit_pct=tp)
        if result.get("ok"):
            bought += 1


def analyze_account(account: BacktestAccount) -> Dict:
    sells = [t for t in account.trades if t["action"] == "SELL"]
    if not account.nav_history:
        return {"error": "no nav"}

    nav = account.nav_history
    final_value = nav[-1]["value"]
    total_return = (final_value / account.initial_capital - 1) * 100

    values = [n["value"] for n in nav]
    daily_rets = np.diff(values) / np.array(values[:-1]) if len(values) > 1 else np.array([0.0])
    sharpe = 0.0
    if len(daily_rets) > 1 and np.std(daily_rets) > 0:
        sharpe = float(np.mean(daily_rets) / np.std(daily_rets) * np.sqrt(252))

    peak = values[0]
    max_dd = 0.0
    for v in values:
        if v > peak:
            peak = v
        dd = (v - peak) / peak * 100
        if dd < max_dd:
            max_dd = dd

    wins = [t for t in sells if t.get("profit", 0) > 0]
    losses = [t for t in sells if t.get("profit", 0) <= 0]
    win_rate = len(wins) / len(sells) * 100 if sells else 0
    avg_win = float(np.mean([t["profit"] for t in wins])) if wins else 0.0
    avg_lose = float(np.mean([t["profit"] for t in losses])) if losses else 0.0
    gross_win = sum(t["profit"] for t in wins)
    gross_loss = abs(sum(t["profit"] for t in losses))
    profit_factor = round(gross_win / gross_loss, 2) if gross_loss > 0 else 0.0
    avg_hold = float(np.mean([t.get("hold_days", 0) for t in sells])) if sells else 0.0

    days_span = (
        datetime.strptime(nav[-1]["date"], "%Y-%m-%d")
        - datetime.strptime(nav[0]["date"], "%Y-%m-%d")
    ).days
    if days_span > 0 and final_value > 0:
        cagr = (final_value / account.initial_capital) ** (365 / days_span) - 1
        annual_return = cagr * 100
    else:
        annual_return = total_return

    # 月度收益 (月初→月末净值)
    month_open: Dict[str, float] = {}
    month_last: Dict[str, float] = {}
    for n in nav:
        m = n["date"][:7]
        if m not in month_open:
            month_open[m] = n["value"]
        month_last[m] = n["value"]
    monthly = {}
    for m in month_last:
        start_v = month_open.get(m, account.initial_capital)
        monthly[m] = (month_last[m] / start_v - 1) * 100 if start_v else 0

    return {
        "name": account.name,
        "initial_capital": account.initial_capital,
        "final_value": round(final_value, 2),
        "return_pct": round(total_return, 2),
        "annual_return_pct": round(annual_return, 2),
        "cagr_pct": round(annual_return, 2),
        "sharpe": round(sharpe, 3),
        "max_drawdown": round(max_dd, 2),
        "total_trades": len(sells),
        "win_rate": round(win_rate, 1),
        "win_count": len(wins),
        "lose_count": len(losses),
        "avg_win": round(avg_win, 2),
        "avg_lose": round(avg_lose, 2),
        "profit_factor": profit_factor,
        "avg_hold_days": round(avg_hold, 1),
        "total_profit": round(account.total_profit, 2),
        "trading_days": len(nav),
        "max_positions": account.max_positions,
        "monthly_returns": {k: round(v, 2) for k, v in sorted(monthly.items())},
    }


OVERNIGHT_STRATEGY_IDS = frozenset({"late_session_surge"})
SWING_STRATEGY_IDS = frozenset({"small_cap_volatil"})


def run_backtest(
    start: str,
    end: str,
    pool_top: Optional[int] = None,
    pool_mode: str = "mainline",
    sector_top: int = 10,
    per_sector: int = 10,
    min_score: int = None,
    top_n: int = DEFAULT_TOP_N,
) -> Dict:
    """运行 5 策略 + 组合账户回测"""
    if min_score is None:
        min_score = 32 if pool_mode == "mainline" else (35 if pool_mode == "sector" else DEFAULT_MIN_SCORE)
    warmup_start = (datetime.strptime(start, "%Y-%m-%d") - timedelta(days=120)).strftime("%Y-%m-%d")
    all_codes = load_stock_pool()
    logger.info("股票池: %d 只", len(all_codes))

    kline_data: Dict[str, pd.DataFrame] = {}
    for i, code in enumerate(all_codes):
        df = load_kline(code, warmup_start, end)
        if df is not None:
            kline_data[code] = df
        if (i + 1) % 500 == 0:
            logger.info("  加载K线: %d/%d", i + 1, len(all_codes))
    logger.info("有效K线: %d 只", len(kline_data))

    all_codes = list(kline_data.keys())
    if pool_mode == "liquidity" and pool_top and pool_top < len(all_codes):
        all_codes = select_pool_by_liquidity(all_codes, kline_data, pool_top)
        kline_data = {c: kline_data[c] for c in all_codes}
        logger.info("流动性子集: %d 只", len(all_codes))
    elif pool_mode == "sector":
        logger.info("扫描模式: 板块 Top%d × 每板块 Top%d (每日动态)", sector_top, per_sector)
    elif pool_mode == "mainline":
        from mainline_pool import TOP_MAINLINES, PER_MAINLINE
        logger.info("扫描模式: 主线主题 Top%d × 每主线 Top%d (放量强势股)", TOP_MAINLINES, PER_MAINLINE)
    else:
        logger.info("扫描模式: 全池 %d 只", len(all_codes))

    date_idx = build_date_index(kline_data)
    trading_dates = [d for d in build_trading_dates(start, end) if d in date_idx.get(INDEX_CODE, {})]
    if not trading_dates:
        raise ValueError("无有效交易日")

    fund_cache = load_fundamentals_cache(all_codes)
    industry_map = load_industry_map()
    engine = FactorEngine()
    mgr = StrategyManager()
    strategy_modules = mgr.strategies

    dl_selector = None
    try:
        from dl_factor_model import DLFactorSelector
        dl_selector = DLFactorSelector()
        if not dl_selector.load():
            dl_selector = None
            logger.info("DL模型未加载，回测不使用 DL 门控")
        else:
            logger.info("DL模型已加载，use_dl 策略将启用门控")
    except Exception as e:
        logger.warning("DL加载失败: %s", e)

    accounts: Dict[str, BacktestAccount] = {}
    for sname, mod in strategy_modules.items():
        accounts[sname] = _account_from_meta(sname, mod.metadata)
    accounts["composite"] = _account_from_meta("composite", {
        "trade_rules": "aggressive",
        "market_filter": "loose",
        "max_positions": 5,
        "max_hold_days": 32,
        "take_profit": 0.72,
        "trailing_stop": 0.12,
        "min_strategy_score": 55,
        "description": "多策略 weight 加权组合 | 实盘主账户",
    })

    logger.info("回测区间: %s ~ %s (%d 交易日)", start, end, len(trading_dates))
    theme_state: Dict = {}

    for di, date in enumerate(trading_dates):
        if di % 20 == 0:
            logger.info("  进度: %d/%d %s", di + 1, len(trading_dates), date)

        # 1) 早盘卖出
        for acct in accounts.values():
            process_sells(acct, date, kline_data, date_idx)

        # 2) 收盘选股
        if pool_mode == "mainline":
            from mainline_pool import mainline_sector_data
            sector_data = mainline_sector_data(
                kline_data, date_idx, date, industry_map, prev_theme_state=theme_state,
            )
            theme_state = sector_data.get("theme_ctx", theme_state)
        else:
            sector_data = compute_sector_data(kline_data, date_idx, date, industry_map)
        idx_row = date_idx.get(INDEX_CODE, {}).get(date)
        index_df = kline_data.get(INDEX_CODE)
        index_change = 0.0
        index_mom_5d = 0.0
        index_mom_20d = 0.0
        index_bull = True
        if index_df is not None and idx_row is not None:
            index_change = float(index_df.iloc[idx_row].get("change_pct", 0) or 0)
            index_mom_5d = index_momentum_5d(index_df, idx_row)
            index_mom_20d = index_momentum_20d(index_df, idx_row)
            index_bull = index_above_ma20(index_df, idx_row)
        allow_buy_global = market_allows_buy(
            index_change, index_mom_5d, "loose",
            index_mom_20d=index_mom_20d, index_bull=index_bull,
        )
        if pool_mode == "sector":
            from sector_pool import select_sector_pool_for_date
            daily_codes = select_sector_pool_for_date(
                all_codes, kline_data, date_idx, date, industry_map,
                hot_sectors=sector_data.get("hot_sectors"),
                top_sectors=sector_top,
                per_sector=per_sector,
            )
        elif pool_mode == "mainline":
            from mainline_pool import select_mainline_pool_for_date
            daily_codes = select_mainline_pool_for_date(
                all_codes, kline_data, date_idx, date, industry_map,
                fund_cache=fund_cache,
            )
        else:
            daily_codes = all_codes

        scored = score_stocks_for_date(
            daily_codes, kline_data, date_idx, date, engine, fund_cache,
            industry_map, sector_data, min_score,
        )

        dl_scores = {}
        if dl_selector:
            mctx = {"index_change": index_change, "sentiment": 50}
            dl_scores = dl_selector.predict_proba_map(scored, sector_data, mctx)
            for s in scored:
                c = s.get("code")
                if c in dl_scores:
                    s["dl_score"] = dl_scores[c]

        market_ctx = {
            "index_change": index_change,
            "index_mom_5d": index_mom_5d,
            "index_mom_20d": index_mom_20d,
            "index_bull": index_bull,
            "sector_pool": pool_mode in ("sector", "mainline"),
            "mainline_pool": pool_mode == "mainline",
            "theme_ctx": sector_data.get("theme_ctx", theme_state),
        }
        strategy_results = mgr.run_all(
            scored, sector_data, dl_scores=dl_scores or None, market_ctx=market_ctx,
        )
        merged = mgr.flatten_picks(strategy_results, top_n=top_n * 2)

        close_prices = {}
        price_codes = set(daily_codes)
        for acct in accounts.values():
            price_codes.update(acct.positions.keys())
        for code in price_codes:
            idx = date_idx.get(code, {}).get(date)
            df = kline_data.get(code)
            if idx is not None and df is not None:
                close_prices[code] = float(df.iloc[idx]["close"])

        # 3) 尾盘买入 (各策略独立大盘过滤)
        if allow_buy_global:
            enabled_results = {}
            for sname, mod in strategy_modules.items():
                meta = mod.metadata
                if meta.get("enabled", True) is False:
                    continue
                filt = meta.get("market_filter", accounts[sname].market_filter)
                if not market_allows_buy(
                    index_change, index_mom_5d, filt,
                    index_mom_20d=index_mom_20d, index_bull=index_bull,
                ):
                    continue
                picks = strategy_results.get(sname, [])
                picks = sorted(picks, key=lambda x: x.get("strategy_score", 0), reverse=True)
                strat_top = min(top_n, meta.get("max_positions", top_n))
                process_buys(accounts[sname], picks, date, kline_data, date_idx, strat_top)
                enabled_results[sname] = picks

            # 组合账户: 按各策略 weight 加权合并（仅 composite_pool 正收益策略）
            composite_picks = mgr.build_composite_picks(
                strategy_results, total=min(top_n, 5), min_score=55,
            )
            if market_allows_buy(
                index_change, index_mom_5d, "loose",
                index_mom_20d=index_mom_20d, index_bull=index_bull,
            ):
                process_buys(accounts["composite"], composite_picks, date, kline_data, date_idx, min(top_n, 5))

        # 4) 记录净值
        for acct in accounts.values():
            acct.record_nav(date, close_prices)

    results = {}
    for name, acct in accounts.items():
        mod = strategy_modules.get(name)
        display = mod.metadata["name"] if mod else "组合账户"
        stats = analyze_account(acct)
        stats["display_name"] = display
        mod = strategy_modules.get(name)
        stats["enabled"] = mod.metadata.get("enabled", True) if mod else (name == "composite")
        stats["description"] = mod.metadata.get("description", "") if mod else "多策略 weight 加权 | 实盘主账户"
        stats["hold_mode"] = acct.hold_mode
        stats["max_hold_days"] = acct.max_hold_days
        results[name] = stats

    if pool_mode == "sector":
        pool_desc = f"sector_{sector_top}x{per_sector}"
    elif pool_mode == "mainline":
        pool_desc = "mainline_theme_vol"
    else:
        pool_desc = f"liquidity_{pool_top}" if pool_top else "full"
    return {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "start": start,
        "end": end,
        "pool_mode": pool_mode,
        "pool_size": len(all_codes),
        "sector_top": sector_top if pool_mode == "sector" else None,
        "per_sector": per_sector if pool_mode == "sector" else None,
        "pool_desc": pool_desc,
        "min_score": min_score,
        "top_n": top_n,
        "strategies": results,
        "accounts": accounts,
    }


def generate_html_report(summary: Dict, accounts: Dict[str, "BacktestAccount"], tag: str) -> str:
    """生成可视化 HTML 回测报告"""
    strategies = summary.get("strategies", [])
    start = summary.get("start", "")
    end = summary.get("end", "")
    pool_size = summary.get("pool_size", 0)

    rows_html = ""
    for i, s in enumerate(strategies, 1):
        ret = s.get("return_pct", 0)
        cagr = s.get("cagr_pct", s.get("annual_return_pct", 0))
        color = "#0ecb81" if ret >= 0 else "#f6465d"
        bar_w = min(100, abs(ret))
        rows_html += f"""
        <tr onclick="showNav('{s.get('name','')}')" style="cursor:pointer">
          <td>{i}</td>
          <td><b>{s.get('display_name', s.get('name'))}</b></td>
          <td style="color:{color};font-weight:700">{ret:+.2f}%</td>
          <td style="color:{'#f0b90b' if cagr>=100 else color}">{cagr:+.2f}%</td>
          <td>{s.get('sharpe',0):.2f}</td>
          <td class="dd">{s.get('max_drawdown',0):.2f}%</td>
          <td>{s.get('profit_factor',0):.2f}</td>
          <td>{s.get('win_rate',0):.1f}%</td>
          <td>{s.get('total_trades',0)}</td>
          <td>{s.get('avg_hold_days',0):.1f}天</td>
          <td><div class="bar"><div class="fill" style="width:{bar_w}%;background:{color}"></div></div></td>
        </tr>"""

    nav_scripts = ""
    for name, acct in accounts.items():
        if name == "composite":
            continue
        dates = [n["date"] for n in acct.nav_history]
        vals = [n["value"] for n in acct.nav_history]
        if len(dates) < 2:
            continue
        nav_scripts += f"navData['{name}']={{dates:{json.dumps(dates)},values:{json.dumps(vals)}}};"

    html = f"""<!DOCTYPE html>
<html lang="zh"><head><meta charset="utf-8"><title>回测报告 {tag}</title>
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{background:#0b0e11;color:#eaecef;font-family:-apple-system,sans-serif;padding:24px}}
h1{{color:#f0b90b;margin-bottom:8px}} .meta{{color:#848e9c;font-size:13px;margin-bottom:24px}}
table{{width:100%;border-collapse:collapse;background:#141820;border-radius:8px;overflow:hidden}}
th,td{{padding:10px 12px;text-align:left;border-bottom:1px solid #242936;font-size:13px}}
th{{background:#1a1f2e;color:#848e9c;font-size:12px}}
tr:hover{{background:#1a1f2e}}
.dd{{color:#f6465d}} .bar{{background:#242936;height:6px;border-radius:3px;width:80px}}
.fill{{height:100%;border-radius:3px}}
#chart{{width:100%;height:360px;background:#141820;border-radius:8px;margin-top:24px}}
.stats{{display:flex;gap:16px;margin-bottom:20px;flex-wrap:wrap}}
.card{{background:#141820;padding:16px 20px;border-radius:8px;min-width:140px}}
.card .v{{font-size:22px;font-weight:700;margin-top:4px}}
.card .l{{font-size:12px;color:#848e9c}}
</style></head><body>
<h1>📊 strategies_v2 回测报告</h1>
<div class="meta">{start} ~ {end} | 股票池 {pool_size} | 3仓×33% | 止损-5% 止盈+18% | 生成 {summary.get('generated_at','')}</div>
<div class="stats">
  <div class="card"><div class="l">最佳策略</div><div class="v" style="color:#0ecb81">{strategies[0].get('display_name','-') if strategies else '-'}</div></div>
  <div class="card"><div class="l">最高收益</div><div class="v">{strategies[0].get('return_pct',0):+.1f}%</div></div>
  <div class="card"><div class="l">最高CAGR</div><div class="v" style="color:#f0b90b">{max((s.get('cagr_pct',0) for s in strategies), default=0):+.1f}%</div></div>
  <div class="card"><div class="l">策略数</div><div class="v">{len(strategies)}</div></div>
</div>
<table>
<thead><tr><th>#</th><th>策略</th><th>总收益</th><th>CAGR</th><th>Sharpe</th><th>最大回撤</th><th>盈亏比</th><th>胜率</th><th>交易</th><th>均持仓</th><th>收益条</th></tr></thead>
<tbody>{rows_html}</tbody>
</table>
<canvas id="chart"></canvas>
<script>
const navData={{}};
{nav_scripts}
let cur=null;
function showNav(name){{cur=name;draw()}}
function draw(){{
  const c=document.getElementById('chart');if(!c||!cur||!navData[cur])return;
  const d=navData[cur];const ctx=c.getContext('2d');
  const dpr=window.devicePixelRatio||1;const r=c.getBoundingClientRect();
  c.width=r.width*dpr;c.height=r.height*dpr;ctx.scale(dpr,dpr);
  const W=r.width,H=r.height,p={{l:60,r:20,t:20,b:30}};
  const vals=d.values;const mn=Math.min(...vals),mx=Math.max(...vals);
  ctx.fillStyle='#141820';ctx.fillRect(0,0,W,H);
  ctx.strokeStyle='#242936';ctx.beginPath();
  for(let i=0;i<=4;i++){{const y=p.t+(H-p.t-p.b)*i/4;ctx.moveTo(p.l,y);ctx.lineTo(W-p.r,y)}}
  ctx.stroke();
  ctx.beginPath();ctx.strokeStyle='#f0b90b';ctx.lineWidth=2;
  vals.forEach((v,i)=>{{
    const x=p.l+i/(vals.length-1)*(W-p.l-p.r);
    const y=p.t+(1-(v-mn)/(mx-mn||1))*(H-p.t-p.b);
    i?ctx.lineTo(x,y):ctx.moveTo(x,y);
  }});
  ctx.stroke();
  ctx.fillStyle='#848e9c';ctx.font='12px sans-serif';
  ctx.fillText(cur+' 净值曲线',p.l,p.t-4);
}}
window.onload=()=>{{const k=Object.keys(navData);if(k.length){{cur=k[0];draw()}}}};
window.onresize=draw;
</script></body></html>"""
    return html


def _max_trading_days(summary: Dict) -> int:
    strats = summary.get("strategies") or []
    if not strats:
        return 0
    return max(s.get("trading_days", 0) for s in strats)


def save_reports(result: Dict, tag: str) -> str:
    os.makedirs(REPORT_DIR, exist_ok=True)
    accounts: Dict[str, BacktestAccount] = result.pop("accounts")
    strategies = result.pop("strategies")

    summary = dict(result)
    summary["strategies"] = sorted(strategies.values(), key=lambda x: x.get("return_pct", 0), reverse=True)
    td = _max_trading_days(summary)
    if td >= 200:
        summary["report_type"] = "benchmark"
    elif td <= 90:
        summary["report_type"] = "quick"
    else:
        summary["report_type"] = "custom"
    summary["benchmark_tag"] = tag
    summary["rules"] = "训练回测 | 隔夜T+1 / 波段≤10日 | 各策略独立大盘过滤"
    summary_path = os.path.join(REPORT_DIR, f"summary_{tag}.json")
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    benchmark_path = os.path.join(REPORT_DIR, "summary_benchmark.json")
    if td >= 200:
        with open(benchmark_path, "w", encoding="utf-8") as f:
            json.dump(summary, f, ensure_ascii=False, indent=2)
        logger.info("已更新基准回测: %s (%s 交易日)", benchmark_path, td)
        try:
            from strategies_v2.composite_config import positive_strategy_ids, save_composite_pool, load_benchmark_returns
            pool = positive_strategy_ids()
            save_composite_pool(pool, load_benchmark_returns())
            logger.info("组合策略池(正收益): %s", pool)
        except Exception as e:
            logger.warning("组合池更新失败: %s", e)

    html_path = os.path.join(REPORT_DIR, f"report_{tag}.html")
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(generate_html_report(summary, accounts, tag))

    for name, acct in accounts.items():
        nav_path = os.path.join(REPORT_DIR, f"nav_{name}_{tag}.json")
        with open(nav_path, "w", encoding="utf-8") as f:
            json.dump({"strategy": name, "nav": acct.nav_history}, f, ensure_ascii=False, indent=2)

        trades_path = os.path.join(REPORT_DIR, f"trades_{name}_{tag}.json")
        with open(trades_path, "w", encoding="utf-8") as f:
            json.dump({"strategy": name, "trades": acct.trades}, f, ensure_ascii=False, indent=2)

    logger.info("报告已保存: %s + %s", summary_path, html_path)
    return summary_path


def print_ranking(strategies: Dict[str, Dict]):
    rows = sorted(strategies.values(), key=lambda x: x.get("return_pct", 0), reverse=True)
    print("\n" + "=" * 88)
    print("  strategies_v2 回测排名 (激进模式: 5仓/无冷却/涨停持股)")
    print("=" * 88)
    print(f"{'排名':<4} {'策略':<18} {'收益%':>8} {'CAGR%':>8} {'Sharpe':>7} {'回撤%':>8} {'盈亏比':>7} {'胜率%':>7} {'交易':>5}")
    print("-" * 88)
    for i, r in enumerate(rows, 1):
        print(
            f"{i:<4} {r.get('display_name', r['name']):<18} "
            f"{r.get('return_pct', 0):>+8.2f} {r.get('cagr_pct', r.get('annual_return_pct', 0)):>+8.2f} "
            f"{r.get('sharpe', 0):>7.3f} {r.get('max_drawdown', 0):>8.2f} "
            f"{r.get('profit_factor', 0):>7.2f} {r.get('win_rate', 0):>7.1f} "
            f"{r.get('total_trades', 0):>5}"
        )
    print("=" * 88)


def main():
    parser = argparse.ArgumentParser(description="strategies_v2 统一回测")
    parser.add_argument("--start", default="2024-01-01", help="默认2024-01-01")
    parser.add_argument("--end", default=BACKTEST_TRAIN_END, help=f"默认{BACKTEST_TRAIN_END}")
    parser.add_argument("--pool-mode", choices=["mainline", "sector", "liquidity", "full"], default="mainline",
                        help="扫描池: mainline=主线放量强势股, sector=热门板块Top10×10")
    parser.add_argument("--pool-top", type=int, default=500, help="liquidity 模式子集大小 (0=全池)")
    parser.add_argument("--sector-top", type=int, default=10, help="sector 模式热门板块数")
    parser.add_argument("--per-sector", type=int, default=10, help="sector 模式每板块个股数")
    parser.add_argument("--min-score", type=int, default=DEFAULT_MIN_SCORE)
    parser.add_argument("--top-n", type=int, default=DEFAULT_TOP_N, help="每策略/组合最大买入数")
    parser.add_argument("--quick", action="store_true", help="近3个月 + liquidity pool-top 200")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    logging.getLogger("strategies_v2.manager").setLevel(logging.WARNING)

    end = args.end or datetime.now().strftime("%Y-%m-%d")
    pool_top = args.pool_top if args.pool_top > 0 else None

    pool_mode = args.pool_mode
    if args.quick:
        start = (datetime.now() - timedelta(days=90)).strftime("%Y-%m-%d")
        pool_mode = "liquidity"
        pool_top = min(pool_top or 200, 200)
    elif args.start:
        start = args.start
    else:
        start, end = default_backtest_range()

    if pool_mode == "full":
        pool_top = None

    if pool_mode == "mainline":
        pool_label = "主线主题 × 放量强势股 (~80只/日)"
    elif pool_mode == "sector":
        pool_label = f"板块 Top{args.sector_top} × 每板块 Top{args.per_sector} (每日~{args.sector_top * args.per_sector})"
    elif pool_top:
        pool_label = f"流动性 Top {pool_top}"
    else:
        pool_label = "全池"

    print(f"\n{'='*60}")
    print("  backtest_v2 - strategies_v2 统一回测")
    print(f"{'='*60}")
    print(f"  区间: {start} ~ {end}")
    print(f"  扫描池: {pool_label}")
    print(f"  最低分: {args.min_score} | 每策略买入: Top {args.top_n}")
    print(f"{'='*60}\n")

    result = run_backtest(
        start=start,
        end=end,
        pool_top=pool_top,
        pool_mode=pool_mode,
        sector_top=args.sector_top,
        per_sector=args.per_sector,
        min_score=args.min_score,
        top_n=args.top_n,
    )

    tag = datetime.now().strftime("%Y%m%d_%H%M%S")
    strategies = dict(result["strategies"])
    save_reports(result, tag)
    print_ranking(strategies)


if __name__ == "__main__":
    main()
