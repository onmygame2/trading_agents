"""
策略排名与收益分析 - 多策略横向对比
"""

import json
import os
import pandas as pd
import numpy as np
from typing import List, Dict
from datetime import datetime


class StrategyRanker:
    """策略排名器"""

    def __init__(self):
        self.results: Dict[str, dict] = {}

    def add_result(self, strategy_name: str, account_summary: dict, daily_nav: List[dict] = None):
        self.results[strategy_name] = {
            'summary': account_summary,
            'daily_nav': daily_nav or []
        }

    def compute_advanced_metrics(self, strategy_name: str) -> dict:
        if strategy_name not in self.results:
            return {}
        nav_list = self.results[strategy_name].get('daily_nav', [])
        if len(nav_list) < 2:
            return {}

        nav_df = pd.DataFrame(nav_list)
        nav_df['daily_return'] = nav_df['total_value'].pct_change().fillna(0)

        init = self.results[strategy_name]['summary']['initial_cash']

        # 夏普
        daily_rf = 0.03 / 252
        excess = nav_df['daily_return'] - daily_rf
        sharpe = (excess.mean() / excess.std() * np.sqrt(252)) if excess.std() > 0 else 0

        # 最大回撤
        peak = nav_df['total_value'].cummax()
        dd = (nav_df['total_value'] - peak) / peak * 100
        max_dd = dd.min()

        # 卡玛
        annual_ret = (nav_df.iloc[-1]['total_value'] / init - 1) / max(len(nav_df) / 252, 0.001)
        calmar = annual_ret / abs(max_dd) if max_dd != 0 else 0

        # 索提诺
        downside = excess[excess < 0]
        sortino = (excess.mean() / downside.std() * np.sqrt(252)) if len(downside) > 0 and downside.std() > 0 else 0

        # 年化收益
        years = max(len(nav_df) / 252, 0.001)
        ann_ret = ((nav_df.iloc[-1]['total_value'] / init) ** (1 / years) - 1) * 100

        return {
            'sharpe_ratio': round(sharpe, 4),
            'max_drawdown': round(max_dd, 2),
            'calmar_ratio': round(calmar, 4),
            'sortino_ratio': round(sortino, 4),
            'annual_return_pct': round(ann_ret, 2)
        }

    def rankings(self) -> List[dict]:
        ranked = []
        for name, data in self.results.items():
            s = data['summary'].copy()
            adv = self.compute_advanced_metrics(name)
            s.update(adv)
            ranked.append(s)
        ranked.sort(key=lambda x: x.get('total_value', 0), reverse=True)
        for i, r in enumerate(ranked):
            r['rank'] = i + 1
        return ranked

    def report(self) -> str:
        ranked = self.rankings()
        lines = []
        lines.append("=" * 80)
        lines.append("                   策略排名报告")
        lines.append(f"  生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        lines.append("=" * 80)

        lines.append("")
        lines.append(f"{'排名':<5} {'策略':<25} {'收益率%':>10} {'总价值':>14} {'夏普':>8} {'最大回撤%':>10} {'胜率%':>8} {'交易次数':>8}")
        lines.append("-" * 80)

        for r in ranked:
            name = r.get('strategy', 'N/A')[:24]
            lines.append(
                f"{r.get('rank', '?'):<5} {name:<25} {r.get('return_pct', 0):>9.2f}% "
                f"{r.get('total_value', 0):>13,.2f} {r.get('sharpe_ratio', 0):>7.3f} "
                f"{r.get('max_drawdown', 0):>9.2f}% {r.get('win_rate', 0):>7.1f}% {r.get('total_trades', 0):>7}"
            )

        lines.append("")
        lines.append("=" * 80)

        # 最佳策略详情
        if ranked:
            best = ranked[0]
            lines.append("")
            lines.append(f"【最佳策略: {best.get('strategy', 'N/A')}】")
            lines.append(f"  总收益: {best.get('return_pct', 0):.2f}%")
            lines.append(f"  年化收益: {best.get('annual_return_pct', 0):.2f}%")
            lines.append(f"  夏普: {best.get('sharpe_ratio', 0):.4f}  卡玛: {best.get('calmar_ratio', 0):.4f}")
            lines.append(f"  最大回撤: {best.get('max_drawdown', 0):.2f}%")

        lines.append("")
        return "\n".join(lines)

    def save(self, path: str):
        ranked = self.rankings()
        os.makedirs(os.path.dirname(path) if os.path.dirname(path) else '.', exist_ok=True)
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(ranked, f, ensure_ascii=False, indent=2)
