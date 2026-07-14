"""Daily review agent.

The reviewer converts raw trading artifacts into a product-facing daily brief:
portfolio metrics, risk flags, action items, and source references.
"""

import glob
import json
import os
from datetime import datetime
from typing import Any, Dict, List, Optional

try:
    from core.memory import TradingMemory
except Exception:
    TradingMemory = None


BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
KNOWLEDGE_DIR = os.path.join(BASE_DIR, 'knowledge_base')
ACCOUNT_DIR = os.path.join(BASE_DIR, 'account')
PAPER_DIR = os.path.join(ACCOUNT_DIR, 'paper')


def _read_json(path: str, default: Any = None) -> Any:
    if not path or not os.path.exists(path):
        return default
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return default


def _latest_file(pattern: str) -> Optional[str]:
    files = sorted(glob.glob(pattern))
    return files[-1] if files else None


def _pct(value: Any) -> Optional[float]:
    try:
        if value is None:
            return None
        return round(float(value), 2)
    except Exception:
        return None


def _strategy_paper_snapshot() -> List[Dict]:
    rows = []
    for path in sorted(glob.glob(os.path.join(PAPER_DIR, '*.json'))):
        name = os.path.basename(path).replace('.json', '')
        if name.endswith('_trades'):
            continue
        state = _read_json(path, {})
        initial = float(state.get('initial_cash') or 100000)
        total = float(state.get('total_assets') or state.get('total_equity') or initial)
        trades = _read_json(os.path.join(PAPER_DIR, f'{name}_trades.json'), [])
        rows.append({
            'strategy': name,
            'total_assets': round(total, 2),
            'return_pct': round((total / initial - 1) * 100, 2) if initial else 0,
            'positions': len(state.get('positions') or []),
            'trades': len(trades) if isinstance(trades, list) else 0,
        })
    return rows


class DailyReviewer:
    """Rule-based reviewer used as the first local Agent MVP."""

    def __init__(self, memory=None):
        self.memory = memory or (TradingMemory() if TradingMemory else None)

    def collect_context(self, date: str = None) -> Dict:
        account = _read_json(os.path.join(ACCOUNT_DIR, 'account_state_v2.json'), {})
        trades = _read_json(os.path.join(ACCOUNT_DIR, 'trade_log_v2.json'), [])
        pick_path = _latest_file(os.path.join(KNOWLEDGE_DIR, 'daily_pick_*.json'))
        picks = _read_json(pick_path, {}) if pick_path else {}

        lessons = []
        strategy_memory = []
        market_history = []
        if self.memory:
            try:
                lessons = self.memory.query_lessons(days=30, limit=8)
                lessons = [
                    l for l in lessons
                    if 'simulated_backfill' not in ' '.join(str(v) for v in l.values())
                ]
            except Exception:
                lessons = []
            try:
                strategy_memory = self.memory.get_strategy_comparison(days=90)
            except Exception:
                strategy_memory = []
            try:
                market_history = self.memory.get_market_history(days=30)
            except Exception:
                market_history = []
            try:
                signal_stats = self.memory.get_signal_stats(days=90)
            except Exception:
                signal_stats = {}
        else:
            signal_stats = {}

        return {
            'date': date or datetime.now().strftime('%Y-%m-%d'),
            'account': account,
            'trades': trades if isinstance(trades, list) else [],
            'picks': picks,
            'pick_path': pick_path,
            'paper': _strategy_paper_snapshot(),
            'lessons': lessons,
            'strategy_memory': strategy_memory,
            'market_history': market_history,
            'signal_stats': signal_stats,
        }

    def build_brief(self, context: Dict) -> Dict:
        account = context.get('account') or {}
        picks = context.get('picks') or {}
        paper = context.get('paper') or []
        lessons = context.get('lessons') or []
        strategy_memory = context.get('strategy_memory') or []
        market_history = context.get('market_history') or []
        signal_stats = context.get('signal_stats') or {}

        positions = account.get('positions') or {}
        position_rows = list(positions.values()) if isinstance(positions, dict) else positions
        position_cost_value = sum(
            float(p.get('shares') or 0) * float(p.get('avg_price') or p.get('avg_cost') or p.get('cost_price') or 0)
            for p in position_rows
            if isinstance(p, dict)
        )
        total_equity = (
            account.get('account_value')
            or account.get('total_assets')
            or account.get('total_equity')
            or picks.get('account_value')
            or (float(account.get('cash') or 0) + position_cost_value)
        )
        initial_cash = account.get('initial_cash') or 100000
        total_return_pct = _pct((float(total_equity) / float(initial_cash) - 1) * 100) if total_equity and initial_cash else 0
        pick_rows = picks.get('picks') or picks.get('top_picks') or []
        latest_market = market_history[0] if market_history else {}

        risk_flags = []
        if not account:
            risk_flags.append('账户状态缺失')
        if len(position_rows) > 5:
            risk_flags.append('持仓数超过 5 仓规则')
        if not pick_rows:
            risk_flags.append('最新选股报告无候选')
        losing_paper = [r for r in paper if float(r.get('return_pct') or 0) < -5]
        if losing_paper:
            risk_flags.append(f'{len(losing_paper)} 个纸面策略回撤超过 5%')

        action_items = []
        live_total = signal_stats.get('total_signals', 0)
        live_realized = signal_stats.get('realized', 0)
        if risk_flags:
            action_items.append('优先复核风险标记，确认是否需要暂停买入或降权策略')
        if pick_rows:
            action_items.append('盘前复核今日候选的流动性、涨停基因和隔夜风险')
        sample_ready = live_total >= 50 and live_realized >= 30
        if strategy_memory and sample_ready:
            weak = [s for s in strategy_memory if float(s.get('win_rate') or 0) < 35]
            if weak:
                action_items.append(f'复盘低胜率策略：{", ".join(str(s.get("strategy", "")) for s in weak[:3])}')
        if not action_items:
            action_items.append('保持观察，等待更多信号进入记忆库')
        if not sample_ready:
            action_items.append('live 记忆样本不足，暂不建议据此调参')

        best_paper = sorted(paper, key=lambda r: r.get('return_pct') or 0, reverse=True)[:1]
        lesson_text = lessons[0].get('description') or lessons[0].get('title') if lessons else ''
        market_text = latest_market.get('sentiment') or 'unknown'
        summary = (
            f"组合当前收益 {total_return_pct:+.2f}%，持仓 {len(position_rows)} 只，"
            f"最新候选 {len(pick_rows)} 只，市场状态 {market_text}。"
        )
        if best_paper:
            summary += f" 纸面领先策略为 {best_paper[0]['strategy']}({best_paper[0]['return_pct']:+.2f}%)。"
        if lesson_text:
            summary += f" 最新经验：{lesson_text[:80]}"

        return {
            'date': context.get('date'),
            'status': 'warning' if risk_flags else 'ok',
            'title': f"{context.get('date')} Agent 日报",
            'summary': summary,
            'action_items': action_items,
            'risk_flags': risk_flags,
            'metrics': {
                'total_equity': round(float(total_equity or 0), 2),
                'total_return_pct': total_return_pct,
                'positions': len(position_rows),
                'pick_count': len(pick_rows),
                'paper_strategy_count': len(paper),
                'lesson_count_30d': len(lessons),
                'market_sentiment': market_text,
                'live_signal_count_90d': signal_stats.get('total_signals', 0),
                'live_realized_count_90d': signal_stats.get('realized', 0),
            },
            'source_refs': [
                {'name': 'account_state_v2', 'path': 'account/account_state_v2.json'},
                {'name': 'latest_pick_report', 'path': os.path.relpath(context.get('pick_path'), BASE_DIR) if context.get('pick_path') else ''},
                {'name': 'trading_memory', 'path': 'knowledge_base/trading_memory.db'},
            ],
        }

    def run(self, date: str = None) -> Dict:
        return self.build_brief(self.collect_context(date=date))

