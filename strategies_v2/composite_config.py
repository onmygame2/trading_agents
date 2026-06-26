"""组合账户策略池 — 仅纳入回测正收益策略，其余独立跟踪"""
import json
import os
import logging

logger = logging.getLogger(__name__)

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BENCHMARK_PATH = os.path.join(BASE_DIR, "reports", "backtest_v2", "summary_benchmark.json")
POOL_PATH = os.path.join(BASE_DIR, "reports", "backtest_v2", "composite_pool.json")

MIN_RETURN_PCT = 0.0
COMPOSITE_FALLBACK = ["oversold_reversal"]


def load_benchmark_returns() -> dict:
    """strategy_id -> return_pct"""
    if not os.path.isfile(BENCHMARK_PATH):
        return {}
    try:
        with open(BENCHMARK_PATH, encoding="utf-8") as f:
            data = json.load(f)
        out = {}
        for s in data.get("strategies", []):
            name = s.get("name")
            if name and name != "composite":
                out[name] = float(s.get("return_pct", 0) or 0)
        return out
    except Exception as e:
        logger.warning("读取回测基准失败: %s", e)
        return {}


def positive_strategy_ids(min_return: float = MIN_RETURN_PCT) -> list:
    """回测收益 > min_return 的策略 id 列表"""
    returns = load_benchmark_returns()
    positive = [k for k, v in returns.items() if v > min_return]
    positive.sort(key=lambda k: returns[k], reverse=True)
    return positive or list(COMPOSITE_FALLBACK)


def save_composite_pool(strategy_ids: list, returns: dict = None) -> None:
    """回测结束后写入组合池"""
    os.makedirs(os.path.dirname(POOL_PATH), exist_ok=True)
    returns = returns or load_benchmark_returns()
    payload = {
        "updated_at": __import__("datetime").datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "min_return_pct": MIN_RETURN_PCT,
        "strategies": strategy_ids,
        "returns": {k: returns.get(k, 0) for k in strategy_ids},
    }
    with open(POOL_PATH, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    logger.info("组合池已更新: %s", strategy_ids)


def load_composite_pool() -> list:
    """优先读 composite_pool.json，否则从 benchmark 推导"""
    if os.path.isfile(POOL_PATH):
        try:
            with open(POOL_PATH, encoding="utf-8") as f:
                data = json.load(f)
            strategies = data.get("strategies") or []
            if strategies:
                return strategies
        except Exception:
            pass
    return positive_strategy_ids()


def is_composite_member(strategy_id: str, mod_metadata: dict = None) -> bool:
    """是否可进入组合买入"""
    if mod_metadata and mod_metadata.get("composite_eligible", True) is False:
        return False
    return strategy_id in load_composite_pool()
