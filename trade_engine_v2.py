"""
虚拟账户交易引擎 v2

规则:
- 初始资金: 100,000元
- 手续费: 0.01% (免5, min_commission=0)
- 印花税: 0.1% (仅卖出)
- 最大持仓: 5只
- 单只最大仓位: 20%
- 硬止损: -7%
- 止盈: +15%
- 移动止盈: 回撤5%
- 最大持仓天数: 20个交易日
"""
import os
import json
import logging
from datetime import datetime
from typing import Dict, List, Optional, Any

from trading_calendar import is_trading_day, get_trading_date
from trading_session import trade_datetime

from strategies_v2.trade_config import (
    MAX_POSITIONS, MAX_SINGLE_PCT, TOP_N_BUY,
    OVERNIGHT_RULES, SWING_RULES, BOUNCE_RULES, AGGRESSIVE_RULES,
    MIN_TRAIL_PROFIT, MIN_TRAIL_PROFIT_SWING, COOLDOWN_DAYS, LIMIT_UP_HOLD, LIMIT_UP_THRESHOLD,
)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ACCOUNT_FILE = os.path.join(BASE_DIR, "account", "account_state_v2.json")
TRADE_LOG_FILE = os.path.join(BASE_DIR, "account", "trade_log_v2.json")

logger = logging.getLogger(__name__)

INITIAL_CAPITAL = 100000
COMMISSION_RATE = 0.0001
STAMP_TAX = 0.001

_RULE_PRESETS = {
    "overnight": OVERNIGHT_RULES,
    "swing": SWING_RULES,
    "bounce": BOUNCE_RULES,
    "aggressive": AGGRESSIVE_RULES,
}


def resolve_trade_rules(strategy_id: str = None, meta: Dict = None) -> Dict:
    """按策略 metadata 解析止损/止盈/持仓规则"""
    meta = dict(meta or {})
    if strategy_id and strategy_id != "composite" and not meta:
        try:
            from strategies_v2.manager import load_all_strategies
            mod = load_all_strategies().get(strategy_id)
            if mod:
                meta = mod.metadata
        except Exception:
            pass
    preset_key = meta.get("trade_rules", "aggressive" if strategy_id == "composite" else "swing")
    preset = _RULE_PRESETS.get(preset_key, AGGRESSIVE_RULES)
    return {
        "trade_rules": preset_key,
        "stop_loss": meta.get("stop_loss", preset["stop_loss"]),
        "take_profit": meta.get("take_profit", preset["take_profit"]),
        "trailing_stop": meta.get("trailing_stop", preset.get("trailing_stop", AGGRESSIVE_RULES["trailing_stop"])),
        "max_hold_days": meta.get("max_hold_days", preset["max_hold_days"]),
        "force_exit_days": meta.get("force_exit_days", preset.get("force_exit_days", 0)),
        "min_trail_profit": MIN_TRAIL_PROFIT if preset_key == "overnight" else MIN_TRAIL_PROFIT_SWING,
    }


# 组合账户默认规则（向后兼容模块级常量）
_DEFAULT_RULES = resolve_trade_rules("composite")
STOP_LOSS = _DEFAULT_RULES["stop_loss"]
TAKE_PROFIT = _DEFAULT_RULES["take_profit"]
TRAILING_STOP = _DEFAULT_RULES["trailing_stop"]
MAX_HOLD_DAYS = _DEFAULT_RULES["max_hold_days"]
OVERNIGHT_MAX_HOLD_DAYS = OVERNIGHT_RULES["max_hold_days"]
MIN_TRAIL_PROFIT_LIVE = MIN_TRAIL_PROFIT


class VirtualAccount:
    """虚拟账户"""

    def __init__(
        self,
        account_file: str = None,
        trade_log_file: str = None,
        strategy_id: str = None,
        display_name: str = None,
    ):
        self.account_file = account_file or ACCOUNT_FILE
        self.trade_log_file = trade_log_file or TRADE_LOG_FILE
        self.strategy_id = strategy_id or "composite"
        self.display_name = display_name or "组合账户"
        self.rules = resolve_trade_rules(self.strategy_id)
        self.cash = INITIAL_CAPITAL
        self.positions: Dict[str, Dict] = {}
        self.total_trades = 0
        self.total_profit = 0
        self.created_at = datetime.now().strftime("%Y-%m-%d")
        self._load()

    def _load(self):
        """加载账户状态"""
        if os.path.exists(self.account_file):
            try:
                with open(self.account_file, "r") as f:
                    data = json.load(f)
                self.cash = data.get("cash", INITIAL_CAPITAL)
                self.positions = data.get("positions", {})
                self.total_trades = data.get("total_trades", 0)
                self.total_profit = data.get("total_profit", 0)
                self.created_at = data.get("created_at", datetime.now().strftime("%Y-%m-%d"))
                self.strategy_id = data.get("strategy_id", self.strategy_id)
                self.display_name = data.get("display_name", self.display_name)
                self.rules = resolve_trade_rules(self.strategy_id)
            except Exception as e:
                logger.warning(f"加载账户失败: {e}")

    def save(self):
        """保存账户状态"""
        os.makedirs(os.path.dirname(self.account_file), exist_ok=True)
        data = {
            "cash": round(self.cash, 2),
            "positions": self.positions,
            "total_trades": self.total_trades,
            "total_profit": round(self.total_profit, 2),
            "created_at": self.created_at,
            "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "strategy_id": self.strategy_id,
            "display_name": self.display_name,
        }
        with open(self.account_file, "w") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def get_total_value(self, current_prices: Dict[str, float] = None) -> float:
        """计算总资产"""
        position_value = 0
        for code, pos in self.positions.items():
            price = current_prices.get(code, pos["avg_price"]) if current_prices else pos["avg_price"]
            position_value += price * pos["shares"]
        return self.cash + position_value

    def can_buy(self) -> bool:
        """是否可以买入（持仓未满）"""
        return len(self.positions) < MAX_POSITIONS

    def get_buy_amount(self, price: float) -> float:
        """计算可买入金额 — 按当前持仓数取递减权重，与 backtest_v2 的 BUY_WEIGHTS 对齐"""
        from strategies_v2.trade_config import BUY_WEIGHTS
        rank_idx = len(self.positions)
        w = BUY_WEIGHTS[rank_idx] if rank_idx < len(BUY_WEIGHTS) else MAX_SINGLE_PCT
        target = self.get_total_value() * w
        return max(0, min(self.cash, target))

    def buy(self, code: str, price: float, amount: float, date: str, reason: str = "") -> Dict:
        """买入"""
        if code in self.positions:
            return {"ok": False, "error": f"已持有 {code}"}
        if not self.can_buy():
            return {"ok": False, "error": "持仓已满"}

        commission = amount * COMMISSION_RATE
        total_cost = amount + commission

        if total_cost > self.cash:
            # 调整到可承受范围
            available = self.cash - self.cash * 0.0001
            amount = min(amount, available)
            commission = amount * COMMISSION_RATE
            total_cost = amount + commission

        shares = int(amount / (price * 100) * 100)  # 取整到100股
        if shares == 0:
            return {"ok": False, "error": "资金不足"}

        actual_cost = shares * price
        actual_commission = actual_cost * COMMISSION_RATE
        actual_total = actual_cost + actual_commission

        self.cash -= actual_total
        self.positions[code] = {
            "shares": shares,
            "avg_price": price,
            "buy_date": date,
            "high_price": price,
            "reason": reason,
            "hold_days": 0,
            "last_hold_date": date,
        }
        self.total_trades += 1

        trade = {
            "action": "BUY",
            "code": code,
            "price": price,
            "shares": shares,
            "amount": round(actual_cost, 2),
            "commission": round(actual_commission, 2),
            "date": date,
            "datetime": trade_datetime(),
            "reason": reason,
            "strategy_id": self.strategy_id,
        }
        self._log_trade(trade)

        logger.info(f"买入 {code} @ {price} x {shares} = {actual_cost:.2f}")
        return {
            "ok": True,
            "code": code,
            "price": price,
            "shares": shares,
            "amount": round(actual_cost, 2),
        }

    def _can_sell_today(self, pos: Dict, date: str) -> bool:
        """A股 T+1: 买入当日不可卖出"""
        return pos.get("buy_date") != date

    def advance_hold_days(self, date: str):
        """按买入日重算 hold_days，避免漏跑 cron 导致天数不准"""
        if not is_trading_day(date):
            return
        from trading_calendar import count_trading_days_since
        changed = False
        for pos in self.positions.values():
            buy_date = pos.get("buy_date", "")
            hold = count_trading_days_since(buy_date, date) if buy_date else pos.get("hold_days", 0)
            if pos.get("hold_days") != hold or pos.get("last_hold_date") != date:
                pos["hold_days"] = hold
                pos["last_hold_date"] = date
                changed = True
        if changed:
            self.save()

    def sell(self, code: str, price: float, date: str, reason: str = "") -> Dict:
        """卖出"""
        if code not in self.positions:
            return {"ok": False, "error": f"未持有 {code}"}

        pos = self.positions[code]
        if not self._can_sell_today(pos, date):
            return {"ok": False, "error": f"T+1限制: {code} 买入当日不可卖出"}
        shares = pos["shares"]
        sell_amount = shares * price
        commission = sell_amount * COMMISSION_RATE
        stamp_tax = sell_amount * STAMP_TAX
        net_amount = sell_amount - commission - stamp_tax

        profit = sell_amount - shares * pos["avg_price"] - commission - stamp_tax

        self.cash += net_amount
        del self.positions[code]
        self.total_trades += 1
        self.total_profit += profit

        trade = {
            "action": "SELL",
            "code": code,
            "price": price,
            "shares": shares,
            "amount": round(sell_amount, 2),
            "commission": round(commission, 2),
            "stamp_tax": round(stamp_tax, 2),
            "profit": round(profit, 2),
            "profit_pct": round(profit / (shares * pos["avg_price"]) * 100, 2),
            "hold_days": pos.get("hold_days", 0),
            "date": date,
            "datetime": trade_datetime(),
            "reason": reason,
            "strategy_id": self.strategy_id,
        }
        self._log_trade(trade)

        logger.info(f"卖出 {code} @ {price} x {shares} = {sell_amount:.2f} (盈亏: {profit:.2f})")
        return {
            "ok": True,
            "code": code,
            "price": price,
            "shares": shares,
            "profit": round(profit, 2),
            "profit_pct": round(profit / (shares * pos["avg_price"]) * 100, 2),
        }

    def check_stop_loss_take_profit(self, current_prices: Dict[str, float], date: str) -> List[Dict]:
        """检查止损/止盈"""
        rules = self.rules or resolve_trade_rules(self.strategy_id)
        stop_loss = rules["stop_loss"]
        take_profit = rules["take_profit"]
        trailing_stop = rules["trailing_stop"]
        max_hold_days = rules["max_hold_days"]
        min_trail_profit = rules["min_trail_profit"]
        actions = []
        codes_to_remove = []

        for code, pos in list(self.positions.items()):
            if not self._can_sell_today(pos, date):
                continue

            current_price = current_prices.get(code, pos["avg_price"])
            if not current_price:
                continue

            change_pct = (current_price - pos["avg_price"]) / pos["avg_price"]

            # 更新最高价
            if current_price > pos.get("high_price", 0):
                pos["high_price"] = current_price

            # 涨停继续持股
            if LIMIT_UP_HOLD:
                day_gain = (current_price - pos["avg_price"]) / pos["avg_price"]
                if day_gain >= LIMIT_UP_THRESHOLD / 100 * 0.85:
                    prev_close = pos.get("prev_close") or pos["avg_price"]
                    if prev_close > 0 and (current_price / prev_close - 1) >= LIMIT_UP_THRESHOLD / 100 * 0.9:
                        continue

            reason = ""

            # 硬止损
            if change_pct <= stop_loss:
                reason = f"硬止损 ({change_pct:.1%})"

            # 止盈
            elif change_pct >= take_profit:
                reason = f"止盈 ({change_pct:.1%})"

            # 移动止盈: 峰值盈利达标后才启用
            elif pos.get("high_price") and pos["high_price"] > pos["avg_price"]:
                peak = (pos["high_price"] - pos["avg_price"]) / pos["avg_price"]
                if peak >= min_trail_profit:
                    drawdown = (current_price - pos["high_price"]) / pos["high_price"]
                    if drawdown <= -trailing_stop:
                        reason = f"移动止盈 (回撤{drawdown:.1%})"

            # 最大持仓天数
            if not reason and pos.get("hold_days", 0) >= max_hold_days:
                reason = f"持仓超时 ({pos['hold_days']}天)"

            if reason:
                result = self.sell(code, current_price, date, reason)
                actions.append(result)

        self.save()
        return actions

    def update_positions(self, current_prices: Dict[str, float], date: str):
        """更新持仓最高价"""
        for code, pos in self.positions.items():
            price = current_prices.get(code, pos["avg_price"])
            if price and price > pos.get("high_price", 0):
                pos["high_price"] = price
        self.save()

    def get_positions_summary(self, current_prices: Dict[str, float] = None) -> List[Dict]:
        """获取持仓摘要"""
        summary = []
        for code, pos in self.positions.items():
            price = current_prices.get(code, pos["avg_price"]) if current_prices else pos["avg_price"]
            market_value = price * pos["shares"]
            cost = pos["avg_price"] * pos["shares"]
            profit = market_value - cost
            profit_pct = profit / cost * 100 if cost > 0 else 0

            summary.append({
                "code": code,
                "shares": pos["shares"],
                "avg_price": pos["avg_price"],
                "current_price": round(price, 2),
                "market_value": round(market_value, 2),
                "profit": round(profit, 2),
                "profit_pct": round(profit_pct, 2),
                "hold_days": pos.get("hold_days", 0),
                "buy_date": pos.get("buy_date", ""),
                "reason": pos.get("reason", ""),
            })
        return summary

    def _log_trade(self, trade: Dict):
        """记录交易日志 (去重)"""
        try:
            log = []
            if os.path.exists(self.trade_log_file):
                with open(self.trade_log_file, "r") as f:
                    log = json.load(f)
            dedup_key = (
                trade.get("action"),
                trade.get("code"),
                trade.get("date"),
                trade.get("price"),
                trade.get("shares"),
            )
            for existing in log[-20:]:
                existing_key = (
                    existing.get("action"),
                    existing.get("code"),
                    existing.get("date"),
                    existing.get("price"),
                    existing.get("shares"),
                )
                if existing_key == dedup_key:
                    return
            log.append(trade)
            os.makedirs(os.path.dirname(self.trade_log_file), exist_ok=True)
            with open(self.trade_log_file, "w") as f:
                json.dump(log, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.warning(f"交易日志记录失败: {e}")

    def reset(self):
        """重置账户"""
        self.cash = INITIAL_CAPITAL
        self.positions = {}
        self.total_trades = 0
        self.total_profit = 0
        self.created_at = datetime.now().strftime("%Y-%m-%d")
        self.save()
        if os.path.exists(self.trade_log_file):
            with open(self.trade_log_file, "w") as f:
                json.dump([], f)


def get_account() -> VirtualAccount:
    """获取全局账户实例"""
    return VirtualAccount()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    acct = VirtualAccount()
    print(f"现金: {acct.cash:.2f}")
    print(f"持仓: {len(acct.positions)}")
    print(f"总资产: {acct.get_total_value():.2f}")
    print(f"总交易: {acct.total_trades}")
    print(f"总盈亏: {acct.total_profit:.2f}")
    for p in acct.get_positions_summary():
        print(f"  {p['code']} {p['shares']}股 @ {p['avg_price']} (当前: {p['current_price']}, 盈亏: {p['profit_pct']:+.1f}%)")
