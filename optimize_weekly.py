"""
持续优化脚本 - 每周自动回测 + 策略分析

用法:
  python optimize_weekly.py          # 完整回测
  python optimize_weekly.py --quick  # 近3个月快速检查
"""

import json
import logging
import os
import sys
from datetime import datetime, timedelta

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)

RESULTS_DIR = os.path.join(BASE_DIR, "optimization")
BASELINE_FILE = os.path.join(RESULTS_DIR, "baseline.json")
os.makedirs(RESULTS_DIR, exist_ok=True)


def run_optimization(quick=False):
    from backtest_v2 import (
        BACKTEST_TRAIN_END,
        default_backtest_range,
        print_ranking,
        run_backtest,
        save_reports,
    )

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    logging.getLogger("strategies_v2.manager").setLevel(logging.WARNING)

    print("=" * 60)
    print("v2 策略周优化回测")
    print("=" * 60)

    if quick:
        start = (datetime.now() - timedelta(days=90)).strftime("%Y-%m-%d")
        end = datetime.now().strftime("%Y-%m-%d")
        pool_mode = "liquidity"
        pool_top = 200
    else:
        start, end = default_backtest_range()
        pool_mode = "mainline"
        pool_top = None

    result = run_backtest(
        start=start,
        end=end or BACKTEST_TRAIN_END,
        pool_mode=pool_mode,
        pool_top=pool_top,
    )
    strategies = result.get("strategies", {})
    print_ranking(strategies)

    tag = f"weekly_{datetime.now().strftime('%Y%m%d')}"
    if quick:
        tag += "_quick"
    save_reports(result, tag)

    sorted_results = sorted(strategies.values(), key=lambda x: x.get("return_pct", 0), reverse=True)
    losing = [r for r in sorted_results if r.get("return_pct", 0) < 0]

    print("\n" + "=" * 60)
    print("优化分析")
    print("=" * 60)
    if not losing:
        print("\n所有策略表现健康，无需紧急优化。")
    else:
        print("\n亏损策略:")
        for r in losing:
            name = r.get("display_name", r.get("strategy", ""))
            print(
                f"  - {name}: 收益 {r.get('return_pct', 0):.2f}%, "
                f"胜率 {r.get('win_rate', 0):.1f}%, 回撤 {r.get('max_drawdown', 0):.2f}%"
            )

    baseline = {
        "date": datetime.now().strftime("%Y-%m-%d"),
        "start": start,
        "end": end or BACKTEST_TRAIN_END,
        "quick": quick,
        "results": {
            r.get("strategy", r.get("display_name", "unknown")): {
                "return_pct": r.get("return_pct", 0),
                "sharpe_ratio": r.get("sharpe", r.get("sharpe_ratio", 0)),
                "max_drawdown": r.get("max_drawdown", 0),
                "win_rate": r.get("win_rate", 0),
                "total_trades": r.get("total_trades", 0),
            }
            for r in sorted_results
        },
    }

    with open(BASELINE_FILE, "w", encoding="utf-8") as f:
        json.dump(baseline, f, ensure_ascii=False, indent=2)

    report_path = os.path.join(RESULTS_DIR, f"weekly_{datetime.now().strftime('%Y%m%d')}.json")
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump({"baseline": baseline, "rankings": sorted_results}, f, ensure_ascii=False, indent=2)

    log_path = os.path.join(RESULTS_DIR, "optimization_log.md")
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(f"\n## {baseline['date']} 周优化 ({'quick' if quick else 'full'})\n")
        f.write(f"- 区间: {start} ~ {end or BACKTEST_TRAIN_END}\n")
        if sorted_results:
            best = sorted_results[0]
            f.write(
                f"- 最佳: {best.get('display_name', best.get('strategy'))} "
                f"收益 {best.get('return_pct', 0):+.2f}%\n"
            )

    print(f"\n基线已保存: {BASELINE_FILE}")
    print(f"详细报告: {report_path}")
    return sorted_results


if __name__ == "__main__":
    run_optimization(quick="--quick" in sys.argv)
