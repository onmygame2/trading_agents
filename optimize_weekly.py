"""
持续优化脚本 - 每周自动回测 + 策略分析

用法:
  python optimize_weekly.py          # 完整回测
  python optimize_weekly.py --quick  # 近3个月快速检查
"""

import json
import os
import sys
from datetime import datetime, timedelta

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)

RESULTS_DIR = os.path.join(BASE_DIR, "optimization")
BASELINE_FILE = os.path.join(RESULTS_DIR, "baseline.json")
os.makedirs(RESULTS_DIR, exist_ok=True)


def run_optimization(quick=False):
    from strategies_runner import MultiStrategyRunner
    from historical_loader import HistoricalDataLoader

    print("=" * 60)
    print("策略优化回测")
    print("=" * 60)

    data_dir = os.path.join(BASE_DIR, "data", "kline")
    loader = HistoricalDataLoader(data_dir)
    loader.login()

    try:
        end = datetime.now().strftime("%Y-%m-%d")
        start = "2024-01-02"
        if quick:
            start = (datetime.now() - timedelta(days=90)).strftime("%Y-%m-%d")

        runner = MultiStrategyRunner()
        runner.add_all_strategies()
        runner.load_data(data_dir=data_dir, top_n=100)

        result = runner.run(start_date=start, end_date=end)
        rankings = result.get("rankings", [])
        sorted_results = sorted(rankings, key=lambda x: x.get("return_pct", 0), reverse=True)

        print(f"\n回测区间: {start} ~ {end}")
        print(f"策略数: {len(sorted_results)}")
        print("\n" + "=" * 60)
        print("回测结果")
        print("=" * 60)
        print(f"{'排名':<5} {'策略':<20} {'收益率%':<10} {'夏普':<8} {'最大回撤%':<10} {'胜率%':<8} {'交易次数'}")
        print("-" * 60)

        for i, r in enumerate(sorted_results, 1):
            name = r.get("strategy", r.get("name", "unknown"))
            flag = " [需优化]" if r.get("return_pct", 0) < 0 else ""
            print(
                f"{i:<5} {name:<20} {r.get('return_pct', 0):<10.2f} "
                f"{r.get('sharpe_ratio', 0):<8.3f} {r.get('max_drawdown', 0):<10.2f} "
                f"{r.get('win_rate', 0):<8.1f} {r.get('total_trades', 0)}{flag}"
            )

        losing = [r for r in sorted_results if r.get("return_pct", 0) < 0]
        print("\n" + "=" * 60)
        print("优化分析")
        print("=" * 60)
        if not losing:
            print("\n所有策略表现健康，无需紧急优化。")
        else:
            print("\n亏损策略:")
            for r in losing:
                name = r.get("strategy", r.get("name", ""))
                print(
                    f"  - {name}: 收益 {r.get('return_pct', 0):.2f}%, "
                    f"胜率 {r.get('win_rate', 0):.1f}%, 回撤 {r.get('max_drawdown', 0):.2f}%"
                )

        baseline = {
            "date": datetime.now().strftime("%Y-%m-%d"),
            "start": start,
            "end": end,
            "quick": quick,
            "results": {
                r.get("strategy", r.get("name", "unknown")): {
                    "return_pct": r.get("return_pct", 0),
                    "sharpe_ratio": r.get("sharpe_ratio", 0),
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
            f.write(f"- 区间: {start} ~ {end}\n")
            if sorted_results:
                best = sorted_results[0]
                f.write(
                    f"- 最佳: {best.get('strategy', best.get('name'))} "
                    f"收益 {best.get('return_pct', 0):+.2f}%\n"
                )

        print(f"\n基线已保存: {BASELINE_FILE}")
        print(f"详细报告: {report_path}")
        return sorted_results
    finally:
        loader.logout()


if __name__ == "__main__":
    run_optimization(quick="--quick" in sys.argv)
