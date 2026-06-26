"""
策略表现追踪器 - 记录历史表现并生成分析

自动生成:
- knowledge_base/performance_tracker.json: 策略级别性能追踪
- reports/strategy_performance.md: 可读性报告
"""
import os
import json
from datetime import datetime, timedelta
from collections import defaultdict


class StrategyPerformanceTracker:
    """追踪每个策略的历史选股表现"""

    def __init__(self, kb_dir='knowledge_base', reports_dir='reports'):
        self.kb_dir = kb_dir
        self.reports_dir = reports_dir
        self.tracker_path = os.path.join(kb_dir, 'performance_tracker.json')
        self._ensure_dirs()

    def _ensure_dirs(self):
        os.makedirs(self.kb_dir, exist_ok=True)
        os.makedirs(self.reports_dir, exist_ok=True)

    def _load_tracker(self) -> dict:
        if os.path.exists(self.tracker_path):
            with open(self.tracker_path, 'r') as f:
                return json.load(f)
        return {
            'strategies': {},
            'daily_records': [],
            'updated_at': ''
        }

    def record_daily(self, date: str, selection: dict, review: dict = None):
        """记录当日选股和复盘结果"""
        tracker = self._load_tracker()

        # 记录选股结果
        signals = selection.get('signals', [])
        for sig in signals:
            code = sig.get('code', '')
            strategies = sig.get('strategies', [])
            for strat in strategies:
                sname = strat.get('strategy', '')
                if sname not in tracker['strategies']:
                    tracker['strategies'][sname] = {
                        'total_signals': 0,
                        'total_profit': 0,
                        'total_loss': 0,
                        'wins': 0,
                        'losses': 0,
                        'avg_score': 0,
                        'scores': []
                    }
                strat_data = tracker['strategies'][sname]
                strat_data['total_signals'] += 1
                score = strat.get('score', 0)
                strat_data['scores'].append(score)
                if len(strat_data['scores']) > 100:
                    strat_data['scores'] = strat_data['scores'][-100:]
                strat_data['avg_score'] = sum(strat_data['scores']) / len(strat_data['scores'])

        # 更新策略胜率（从复盘数据）
        if review:
            summary = review.get('summary', {})
            daily_record = {
                'date': date,
                'total_value': summary.get('total_value', 0),
                'daily_return_pct': summary.get('daily_return_pct', 0),
                'total_return_pct': summary.get('total_return_pct', 0),
                'positions': summary.get('current_positions', 0),
                'trades': summary.get('new_trades', 0),
                'top_picks': selection.get('position_plan', [])
            }
            tracker['daily_records'].append(daily_record)

            # 保留最近60天的记录
            if len(tracker['daily_records']) > 60:
                tracker['daily_records'] = tracker['daily_records'][-60:]

        tracker['updated_at'] = datetime.now().isoformat()
        with open(self.tracker_path, 'w') as f:
            json.dump(tracker, f, ensure_ascii=False, indent=2)

        return tracker

    def get_strategy_rankings(self) -> list:
        """获取策略排名"""
        tracker = self._load_tracker()
        rankings = []
        for sname, data in tracker['strategies'].items():
            rankings.append({
                'strategy': sname,
                'total_signals': data['total_signals'],
                'avg_score': round(data['avg_score'], 2),
                'wins': data['wins'],
                'losses': data['losses'],
                'win_rate': round(data['wins'] / max(data['wins'] + data['losses'], 1) * 100, 1)
            })
        rankings.sort(key=lambda x: x['avg_score'], reverse=True)
        return rankings

    def generate_report(self) -> str:
        """生成可读性报告"""
        tracker = self._load_tracker()
        rankings = self.get_strategy_rankings()
        daily = tracker.get('daily_records', [])

        lines = [
            '# 策略表现追踪报告',
            f'## 更新: {tracker.get("updated_at", "N/A")}',
            '',
            '### 策略排名',
            '| 排名 | 策略 | 信号数 | 平均分 | 胜率 |',
            '|------|------|--------|--------|------|',
        ]

        for i, r in enumerate(rankings, 1):
            lines.append(f'| {i} | {r["strategy"]} | {r["total_signals"]} | {r["avg_score"]:.1f} | {r["win_rate"]:.0f}% |')

        if daily:
            lines.append('')
            lines.append('### 最近交易记录')
            lines.append('| 日期 | 总资产 | 日收益率 | 总收益率 | 持仓 | 交易 |')
            lines.append('|------|--------|---------|---------|------|------|')
            for d in daily[-10:]:
                lines.append(
                    f'| {d["date"]} | {d["total_value"]:,.0f} '
                    f'| {d["daily_return_pct"]:+.2f}% '
                    f'| {d["total_return_pct"]:+.2f}% '
                    f'| {d["positions"]} | {d["trades"]} |'
                )

        report = '\n'.join(lines)
        report_path = os.path.join(self.reports_dir, 'strategy_performance.md')
        with open(report_path, 'w', encoding='utf-8') as f:
            f.write(report)

        return report_path


if __name__ == '__main__':
    t = StrategyPerformanceTracker()
    print(t.generate_report())
