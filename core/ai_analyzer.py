"""
AI 分析引擎

利用 LLM 能力做盘前分析和盘后复盘。

功能:
1. 盘前分析 (08:30) - 基于隔夜消息 + 市场状态预测当日行情
2. 盘后复盘 (15:30) - 总结当日交易结果，提取经验教训
3. 选股分析 - 对信号做二次评估，提高选股质量

注意: 本模块通过调用外部 LLM API 或使用本地模型实现。
如果 LLM 不可用，降级为规则分析。
"""

import json
import os
import sys
from datetime import datetime, timedelta
from typing import Dict, List, Optional

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

from core.memory import TradingMemory


class AIAnalyzer:
    """AI 分析引擎"""

    def __init__(self, memory: TradingMemory = None):
        self.memory = memory or TradingMemory(
            db_path=os.path.join(BASE_DIR, 'knowledge_base', 'trading_memory.db')
        )

    def pre_market_analysis(self, date: str = None) -> Dict:
        """
        盘前分析
        
        分析内容:
        1. 前日市场回顾
        2. 近期趋势判断
        3. 今日操作建议
        4. 推荐策略权重
        """
        if date is None:
            date = datetime.now().strftime('%Y-%m-%d')

        result = {
            'date': date,
            'analysis': self._generate_pre_market_report(date),
            'strategy_weights': self._get_recommended_weights(date),
            'risk_level': self._assess_risk_level(date)
        }

        return result

    def post_market_review(self, date: str = None) -> Dict:
        """
        盘后复盘
        
        分析内容:
        1. 当日信号回顾与结果
        2. 策略表现对比
        3. 经验教训提取
        4. 明日展望
        """
        if date is None:
            date = datetime.now().strftime('%Y-%m-%d')

        result = {
            'date': date,
            'review': self._generate_post_market_report(date),
            'lessons': self._extract_lessons(date),
            'strategy_ranking': self._get_strategy_ranking(date)
        }

        return result

    def analyze_picks(self, buy_signals: List[Dict], date: str = None) -> List[Dict]:
        """
        对选股信号做二次分析
        
        检查:
        1. 个股历史记录 - 之前是否在此价位买入过，结果如何
        2. 当前市场状态是否适合该策略
        3. 信号质量评分调整
        """
        if date is None:
            date = datetime.now().strftime('%Y-%m-%d')

        analyzed = []
        for sig in buy_signals:
            code = sig.get('code', sig.get('stock_code', ''))
            strategy = sig.get('strategy', 'unknown')

            # 1. 查询该策略在此类股票上的历史表现
            stock_history = self.memory.get_stock_history(code, days=60)
            signal_history = self.memory.query_signals(code=code, strategy=strategy, days=60)

            # 2. 查询当前市场状态
            market_state = self.memory.get_market_state(date)
            if not market_state:
                # 用最近的市场状态
                history = self.memory.get_market_history(days=5)
                market_state = history[0] if history else {}

            # 3. 计算调整系数
            adj_factor = 1.0
            reasons = list(sig.get('tech_reasons', []))

            # 如果该策略有历史数据，调整置信度
            realized = [s for s in signal_history if s.get('outcome')]
            if realized:
                win_rate = sum(1 for s in realized if s.get('outcome') == 'profit') / len(realized)
                if win_rate < 0.3:
                    adj_factor = 0.7
                    reasons.append(f'历史预警: 该策略对此股胜率仅{win_rate:.0%}')
                elif win_rate > 0.7:
                    adj_factor = 1.15
                    reasons.append(f'历史加分: 该策略对此股胜率{win_rate:.0%}')

            # 市场情绪不匹配时降低权重
            best_strat = self.memory.get_best_strategy_for_market(
                market_state.get('sentiment', 'neutral')
            )
            if best_strat and best_strat['strategy'] != strategy:
                if market_state.get('sentiment') == 'bearish':
                    adj_factor *= 0.85
                    reasons.append('市场偏空，保守操作')

            # 4. 应用调整
            new_confidence = min(1.0, sig.get('confidence', 0.5) * adj_factor)
            analyzed.append({
                **sig,
                'ai_adjusted_confidence': round(new_confidence, 3),
                'ai_adjustment_factor': round(adj_factor, 2),
                'ai_reasons': reasons,
                'historical_signals': len(signal_history),
                'realized_outcomes': len(realized)
            })

        # 按调整后的置信度排序
        analyzed.sort(key=lambda x: x.get('ai_adjusted_confidence', 0), reverse=True)
        return analyzed

    def _generate_pre_market_report(self, date: str) -> str:
        """生成盘前分析报告"""
        lines = []
        lines.append(f"=== 盘前分析 {date} ===")
        lines.append("")

        # 最近市场状态
        market_history = self.memory.get_market_history(days=5)
        if market_history:
            latest = market_history[0]
            lines.append(f"[市场回顾]")
            lines.append(f"  上证指数: {latest.get('sh_index', 'N/A')} ({latest.get('sh_change_pct', 'N/A')}%)")
            lines.append(f"  创业板指: {latest.get('cyb', 'N/A')} ({latest.get('cyb_change_pct', 'N/A')}%)")
            lines.append(f"  市场情绪: {latest.get('sentiment', 'N/A')}")
            lines.append("")

        # 情绪分布
        sentiment_dist = self.memory.get_sentiment_distribution(days=20)
        if sentiment_dist:
            lines.append(f"[近期情绪分布 (20日)]")
            for s, pct in sorted(sentiment_dist.items()):
                bar = '#' * int(pct / 5)
                lines.append(f"  {s}: {pct}% {bar}")
            lines.append("")

        # 最佳策略
        if market_history:
            sentiment = market_history[0].get('sentiment', 'neutral')
            best = self.memory.get_best_strategy_for_market(sentiment)
            if best:
                lines.append(f"[推荐策略]")
                lines.append(f"  {best['strategy']} (胜率{best['win_rate']:.0f}%, 平均收益{best['avg_pnl_pct']:+.1f}%)")
            lines.append("")

        # 信号统计
        stats = self.memory.get_signal_stats(days=30)
        if stats['total_signals'] > 0:
            lines.append(f"[近期信号统计 (30日)]")
            lines.append(f"  总信号: {stats['total_signals']} | 已实现: {stats['realized']} | 待观察: {stats['pending']}")
            lines.append(f"  胜率: {stats['win_rate']:.1f}% | 平均收益: {stats['avg_pnl_pct']:+.1f}%")
            lines.append(f"  平均持仓: {stats['avg_hold_days']:.0f}天")
            lines.append("")

        return '\n'.join(lines)

    def _generate_post_market_report(self, date: str) -> str:
        """生成盘后复盘报告"""
        lines = []
        lines.append(f"=== 盘后复盘 {date} ===")
        lines.append("")

        # 当日信号
        signals = self.memory.query_signals(days=1)
        buy_signals = [s for s in signals if s.get('signal') == 'buy']
        sell_signals = [s for s in signals if s.get('signal') == 'sell']

        lines.append(f"[今日信号]")
        lines.append(f"  买入: {len(buy_signals)} 只 | 卖出: {len(sell_signals)} 只")
        lines.append("")

        if buy_signals:
            lines.append(f"[买入信号详情]")
            for s in buy_signals[:5]:
                lines.append(f"  {s.get('code', '')} {s.get('name', '')} @ {s.get('price', 'N/A')}")
                lines.append(f"    策略: {s.get('strategy', '')} | 置信度: {s.get('confidence', 0):.0%}")
                lines.append(f"    原因: {s.get('reason', '')[:80]}")
            lines.append("")

        # 策略表现
        ranking = self.memory.get_strategy_comparison(days=30)
        if ranking:
            lines.append(f"[策略排名 (30日)]")
            for i, r in enumerate(ranking[:5], 1):
                lines.append(f"  {i}. {r['strategy']} | 胜率{r['win_rate']:.0f}% | 平均{r['avg_pnl_pct']:+.1f}%")
            lines.append("")

        return '\n'.join(lines)

    def _get_recommended_weights(self, date: str) -> Dict[str, float]:
        """根据当前市场状态推荐策略权重"""
        market_history = self.memory.get_market_history(days=1)
        if not market_history:
            return {}

        sentiment = market_history[0].get('sentiment', 'neutral')

        # 基础权重
        base_weights = {
            'trend_following': 1.0,
            'mean_reversion': 0.8,
            'momentum_breakout': 0.9,
            'multi_factor': 1.0,
            'oversold_bounce': 0.8
        }

        # 根据市场情绪调整
        if sentiment == 'bullish':
            base_weights['momentum_breakout'] = 1.2
            base_weights['trend_following'] = 1.1
            base_weights['mean_reversion'] = 0.6
            base_weights['oversold_bounce'] = 0.5
        elif sentiment == 'bearish':
            base_weights['mean_reversion'] = 1.0
            base_weights['oversold_bounce'] = 1.1
            base_weights['momentum_breakout'] = 0.5
            base_weights['trend_following'] = 0.6
        # neutral = base

        return base_weights

    def _assess_risk_level(self, date: str) -> str:
        """评估风险等级"""
        market_history = self.memory.get_market_history(days=10)
        if not market_history:
            return 'medium'

        # 计算近期波动
        changes = []
        for m in market_history:
            chg = abs(m.get('sh_change_pct', 0) or 0)
            changes.append(chg)

        avg_vol = sum(changes) / len(changes) if changes else 0

        if avg_vol > 1.5:
            return 'high'
        elif avg_vol < 0.3:
            return 'low'
        return 'medium'

    def _extract_lessons(self, date: str) -> List[Dict]:
        """提取经验教训"""
        signals = self.memory.query_signals(days=7, has_outcome=True)
        lessons = []

        for s in signals:
            pnl = s.get('pnl_pct', 0)
            if pnl and abs(pnl) > 10:
                lesson_type = 'big_win' if pnl > 0 else 'big_loss'
                lessons.append({
                    'date': date,
                    'code': s.get('code'),
                    'strategy': s.get('strategy'),
                    'lesson_type': lesson_type,
                    'title': f"{s.get('code', '')} {s.get('strategy', '')} {pnl:+.1f}%",
                    'description': f"收益{pnl:+.1f}%, 持仓{s.get('hold_days', 0)}天",
                    'severity': min(10, abs(pnl))
                })

        # 记录到记忆系统
        for lesson in lessons:
            self.memory.log_lesson(lesson)

        return lessons

    def _get_strategy_ranking(self, date: str) -> List[Dict]:
        """获取策略排名"""
        return self.memory.get_strategy_comparison(days=30)


def generate_pre_market_report(date: str = None) -> str:
    """便捷函数: 生成盘前报告文本"""
    analyzer = AIAnalyzer()
    result = analyzer.pre_market_analysis(date)
    return result.get('analysis', '')


def generate_post_market_report(date: str = None) -> str:
    """便捷函数: 生成盘后报告文本"""
    analyzer = AIAnalyzer()
    result = analyzer.post_market_review(date)
    return result.get('review', '')


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='AI分析引擎')
    parser.add_argument('--mode', choices=['pre', 'post', 'picks'], default='pre')
    parser.add_argument('--date', type=str, default=None)
    args = parser.parse_args()

    analyzer = AIAnalyzer()
    if args.mode == 'pre':
        result = analyzer.pre_market_analysis(args.date)
        print(result['analysis'])
        print(f"\n风险等级: {result['risk_level']}")
        print(f"\n推荐策略权重:")
        for s, w in result.get('strategy_weights', {}).items():
            print(f"  {s}: {w:.2f}")
    elif args.mode == 'post':
        result = analyzer.post_market_review(args.date)
        print(result['review'])
    elif args.mode == 'picks':
        print("Usage: analyzer.analyze_picks(signals, date)")
