"""
v2 策略统一交易参数 — 激进模式
"""
MAX_POSITIONS = 5
MAX_SINGLE_PCT = 0.24
TOP_N_BUY = 5
BUY_WEIGHTS = [0.24, 0.22, 0.20, 0.18, 0.16]

MIN_STRATEGY_SCORE = 62
COOLDOWN_DAYS = 0

MIN_TRAIL_PROFIT = 0.03
MIN_TRAIL_PROFIT_SWING = 0.04

LIMIT_UP_HOLD = True
LIMIT_UP_THRESHOLD = 9.5

# 激进持仓: 涨停继续持股，让利润奔跑 (与回测 oversold_reversal/composite 对齐)
AGGRESSIVE_RULES = {
    "hold_mode": "aggressive",
    "max_hold_days": 32,
    "force_exit_days": 0,
    "stop_loss": -0.08,
    "take_profit": 0.72,
    "trailing_stop": 0.12,
    "hold_limit_up": True,
}

OVERNIGHT_RULES = {
    "hold_mode": "aggressive",
    "max_hold_days": 25,
    "force_exit_days": 0,
    "stop_loss": -0.08,
    "take_profit": 0.58,
    "trailing_stop": 0.10,
    "gap_take_profit": 0.08,
    "gap_stop_loss": -0.06,
    "hold_limit_up": True,
}

SWING_RULES = {
    "hold_mode": "aggressive",
    "max_hold_days": 45,
    "force_exit_days": 0,
    "stop_loss": -0.08,
    "take_profit": 0.72,
    "trailing_stop": 0.12,
    "hold_limit_up": True,
}

BOUNCE_RULES = {
    "hold_mode": "aggressive",
    "max_hold_days": 28,
    "force_exit_days": 0,
    "stop_loss": -0.06,
    "take_profit": 0.80,
    "trailing_stop": 0.10,
    "hold_limit_up": True,
}

STOP_LOSS = AGGRESSIVE_RULES["stop_loss"]
TAKE_PROFIT = AGGRESSIVE_RULES["take_profit"]
TRAILING_STOP = AGGRESSIVE_RULES["trailing_stop"]
MAX_HOLD_DAYS = AGGRESSIVE_RULES["max_hold_days"]
OVERNIGHT_MAX_HOLD_DAYS = OVERNIGHT_RULES["max_hold_days"]

# 回测 2024-2025 / 实测 2026
BACKTEST_TRAIN_END = "2025-12-31"
PAPER_TRADE_START = "2026-01-01"

MARKET_FILTERS = {
    "strict": {"index_min": -0.6, "mom5_min": -2.5, "mom20_min": -2.0, "require_ma20": True},
    "normal": {"index_min": -1.2, "mom5_min": -4.0, "mom20_min": -6.0, "require_ma20": False},
    "loose": {"index_min": -2.0, "mom5_min": -6.0, "mom20_min": -10.0, "require_ma20": False},
}
