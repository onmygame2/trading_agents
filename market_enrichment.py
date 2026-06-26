"""
市场增强数据模块 - AKShare

整合北向资金、板块热度、市场情绪到选股报告中。

数据源: AKShare (东方财富)
缓存: data/market_enriched/ 目录
"""

import akshare as ak
import pandas as pd
import numpy as np
import os
import json
import time
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, 'data', 'market_enriched')
os.makedirs(DATA_DIR, exist_ok=True)


class MarketEnrichment:
    """市场增强数据收集器"""

    def __init__(self):
        self.cache = {}

    def get_north_flow_daily(self) -> List[Dict]:
        """
        获取北向资金（沪深港通）每日净流入
        
        返回: 最近5-10个交易日数据
        """
        cache_key = 'north_flow_daily'
        if cache_key in self.cache:
            return self.cache[cache_key]

        try:
            # 沪深港通持股 - 北向资金汇总
            df = ak.stock_hsgt_fund_flow_summary_em()
            if df.empty:
                return []

            # 筛选北向数据
            north = df[df['资金方向'] == '北向']
            if north.empty:
                return []

            north = north.tail(10).copy()
            if '日期' in north.columns:
                north['日期'] = pd.to_datetime(north['日期']).dt.strftime('%Y-%m-%d')

            result = []
            for _, row in north.iterrows():
                result.append({
                    'date': str(row.get('日期', row.get('交易日', ''))),
                    'north_net_buy': float(row.get('沪股通', row.get('成交净买额', 0))),
                    'related_index': str(row.get('相关指数', '')),
                    'index_change': float(row.get('指数涨跌幅', 0))
                })

            self.cache[cache_key] = result
            return result

        except Exception as e:
            logger.warning(f"获取北向资金流向失败: {e}")
            return []

    def get_north_flow_history(self, days=30) -> pd.DataFrame:
        """
        获取历史北向资金数据
        
        返回: DataFrame with date, net_flow columns
        """
        cache_key = 'north_flow_history'
        if cache_key in self.cache:
            return self.cache[cache_key]

        try:
            df = ak.stock_hsgt_north_hist_em(symbol="北向")
            if df.empty:
                return pd.DataFrame()

            df = df.tail(days * 2).copy()
            if '日期' in df.columns:
                df['日期'] = pd.to_datetime(df['日期']).dt.strftime('%Y-%m-%d')

            df = df.rename(columns={
                '日期': 'date',
                '成交净买额': 'net_flow',
                '资金净流入': 'net_inflow'
            })

            self.cache[cache_key] = df
            return df

        except Exception as e:
            logger.warning(f"获取历史北向资金失败: {e}")
            return pd.DataFrame()

    def get_sector_ranking(self) -> Dict:
        """
        获取行业板块排名
        
        返回: {top_gainers: [...], top_losers: [...], hot_sectors: [...]}
        """
        cache_key = 'sector_ranking'
        if cache_key in self.cache:
            return self.cache[cache_key]

        result = {
            'top_gainers': [],
            'top_losers': [],
            'hot_sectors': []
        }

        try:
            df = ak.stock_board_industry_name_em()
            if df.empty:
                return result

            # 按涨跌幅排序
            df_sorted = df.sort_values('涨跌幅', ascending=False)

            # 涨幅前10
            for _, row in df_sorted.head(10).iterrows():
                result['top_gainers'].append({
                    'name': str(row.get('板块名称', '')),
                    'change_pct': float(row.get('涨跌幅', 0)),
                    'lead_stock': str(row.get('领涨股票', '')),
                    'market_cap': float(row.get('总市值', 0))
                })

            # 跌幅前10
            for _, row in df_sorted.tail(10).iterrows():
                result['top_losers'].append({
                    'name': str(row.get('板块名称', '')),
                    'change_pct': float(row.get('涨跌幅', 0)),
                    'lead_stock': str(row.get('领涨股票', ''))
                })

            # 计算板块热度评分 (成交额排名)
            if '成交额' in df_sorted.columns:
                hot = df_sorted.nlargest(10, '成交额')
                for _, row in hot.iterrows():
                    result['hot_sectors'].append({
                        'name': str(row.get('板块名称', '')),
                        'change_pct': float(row.get('涨跌幅', 0)),
                        'amount': float(row.get('成交额', 0))
                    })

            self.cache[cache_key] = result
            return result

        except Exception as e:
            logger.warning(f"获取板块排名失败: {e}")
            return result

    def get_concept_ranking(self) -> List[Dict]:
        """
        获取概念板块热度
        
        返回: 热门概念板块列表
        """
        cache_key = 'concept_ranking'
        if cache_key in self.cache:
            return self.cache[cache_key]

        try:
            df = ak.stock_board_concept_name_em()
            if df.empty:
                return []

            df_sorted = df.sort_values('涨跌幅', ascending=False)
            result = []
            for _, row in df_sorted.head(15).iterrows():
                result.append({
                    'name': str(row.get('板块名称', '')),
                    'change_pct': float(row.get('涨跌幅', 0)),
                    'lead_stock': str(row.get('领涨股票', ''))
                })

            self.cache[cache_key] = result
            return result

        except Exception as e:
            logger.warning(f"获取概念板块失败: {e}")
            return []

    def get_market_sentiment(self) -> Dict:
        """
        综合市场情绪指标
        
        返回: {
            'up_count': 上涨家数,
            'down_count': 下跌家数,
            'limit_up': 涨停家数,
            'limit_down': 跌停家数,
            'avg_change': 平均涨幅,
            'sentiment_score': 情绪评分(0-100),
            'sentiment_label': 情绪标签
        }
        """
        try:
            df = ak.stock_zh_a_spot_em()
            if df.empty:
                return {}

            change_col = '涨跌幅'
            df[change_col] = pd.to_numeric(df[change_col], errors='coerce')

            up_count = len(df[df[change_col] > 0])
            down_count = len(df[df[change_col] < 0])
            flat_count = len(df[df[change_col] == 0])

            # 涨停 (>9.8%) / 跌停 (<-9.8%)
            limit_up = len(df[df[change_col] > 9.8])
            limit_down = len(df[df[change_col] < -9.8])

            avg_change = df[change_col].mean()

            # 情绪评分 (0-100)
            total = len(df)
            up_ratio = up_count / total if total > 0 else 0.5
            sentiment_score = int(up_ratio * 100)

            if sentiment_score > 75:
                label = "极强"
            elif sentiment_score > 60:
                label = "偏强"
            elif sentiment_score > 40:
                label = "中性"
            elif sentiment_score > 25:
                label = "偏弱"
            else:
                label = "极弱"

            result = {
                'up_count': int(up_count),
                'down_count': int(down_count),
                'flat_count': int(flat_count),
                'limit_up': int(limit_up),
                'limit_down': int(limit_down),
                'avg_change': round(float(avg_change), 2),
                'sentiment_score': sentiment_score,
                'sentiment_label': label
            }

            return result

        except Exception as e:
            logger.warning(f"获取市场情绪失败: {e}")
            return {}

    def get_index_data(self) -> Dict:
        """
        获取主要指数数据
        
        返回: {index_name: {close, change_pct, trend}}
        """
        indices = {
            'sh000001': '上证指数',
            'sz399001': '深证成指',
            'sz399006': '创业板指',
            'sh000300': '沪深300',
            'sh000016': '上证50',
            'sh000905': '中证500'
        }

        result = {}
        for code, name in indices.items():
            try:
                df = ak.stock_zh_index_daily_em(symbol=code)
                if df.empty or len(df) < 5:
                    continue

                latest = df.iloc[-1]
                prev = df.iloc[-2]

                close_col = 'close' if 'close' in df.columns else '收盘'
                close = float(latest.get(close_col, 0))
                prev_close = float(prev.get(close_col, 0))
                change_pct = (close / prev_close - 1) * 100 if prev_close > 0 else 0

                # 简单趋势判断: 20日均线
                if len(df) >= 20:
                    ma20 = df[close_col].tail(20).mean()
                    trend = 'up' if close > ma20 else 'down'
                else:
                    trend = 'neutral'

                result[name] = {
                    'close': round(close, 2),
                    'change_pct': round(change_pct, 2),
                    'trend': trend
                }

            except Exception as e:
                logger.warning(f"获取指数 {name} 失败: {e}")

        return result

    def get_market_overview(self) -> Dict:
        """
        获取完整市场概览
        
        组合所有数据源，返回综合市场报告
        """
        logger.info("正在获取市场增强数据...")

        overview = {
            'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'indices': self.get_index_data(),
            'sentiment': self.get_market_sentiment(),
            'north_flow': self.get_north_flow_daily(),
            'sectors': self.get_sector_ranking(),
            'concepts': self.get_concept_ranking()
        }

        # 判断整体市场环境
        overview['market_regime'] = self._judge_market_regime(overview)

        # 保存缓存
        cache_file = os.path.join(DATA_DIR, f"market_{datetime.now().strftime('%Y%m%d')}.json")
        try:
            with open(cache_file, 'w', encoding='utf-8') as f:
                json.dump(overview, f, indent=2, ensure_ascii=False, default=str)
        except:
            pass

        return overview

    def _judge_market_regime(self, overview: Dict) -> Dict:
        """
        判断当前市场状态
        
        返回: {
            'regime': 'bull'/'bear'/'neutral',
            'confidence': float,
            'reason': str,
            'suggestion': str
        }
        """
        reasons = []
        score = 50  # 基准中性

        # 1. 指数趋势
        indices = overview.get('indices', {})
        up_trend_count = sum(1 for v in indices.values() if v.get('trend') == 'up')
        total_indices = len(indices)
        if total_indices > 0:
            up_ratio = up_trend_count / total_indices
            if up_ratio > 0.7:
                score += 15
                reasons.append(f"多数指数上升趋势({up_trend_count}/{total_indices})")
            elif up_ratio < 0.3:
                score -= 15
                reasons.append(f"多数指数下降趋势({up_trend_count}/{total_indices})")

        # 2. 市场情绪
        sentiment = overview.get('sentiment', {})
        sentiment_score = sentiment.get('sentiment_score', 50)
        if sentiment_score > 60:
            score += 10
            reasons.append(f"市场情绪偏强({sentiment_score})")
        elif sentiment_score < 40:
            score -= 10
            reasons.append(f"市场情绪偏弱({sentiment_score})")

        # 3. 北向资金
        north_flow = overview.get('north_flow', [])
        if len(north_flow) >= 3:
            recent_flows = north_flow[:3]
            positive_days = sum(1 for f in recent_flows if f.get('north_net_buy', 0) > 0)
            if positive_days >= 3:
                score += 10
                reasons.append("北向连续净流入")
            elif positive_days <= 0:
                score -= 10
                reasons.append("北向连续净流出")

        # 4. 板块表现
        sectors = overview.get('sectors', {})
        top_gainers = sectors.get('top_gainers', [])
        if top_gainers:
            avg_gain = sum(s.get('change_pct', 0) for s in top_gainers) / len(top_gainers)
            if avg_gain > 3:
                score += 5
                reasons.append(f"板块涨幅强劲(平均{avg_gain:.1f}%)")
            elif avg_gain < -2:
                score -= 5
                reasons.append(f"板块普跌(平均{avg_gain:.1f}%)")

        # 综合判断
        if score >= 70:
            regime = 'bull'
            suggestion = '市场偏强，可适当提高仓位，关注顺势策略'
        elif score <= 30:
            regime = 'bear'
            suggestion = '市场偏弱，建议降低仓位，防守为主，关注超跌反弹'
        else:
            regime = 'neutral'
            suggestion = '市场中性，均衡配置，注意个股选择'

        return {
            'regime': regime,
            'score': score,
            'confidence': min(abs(score - 50) / 50, 1.0),
            'reasons': reasons,
            'suggestion': suggestion
        }

    def format_market_report(self, overview: Dict) -> str:
        """
        格式化为可读的市场报告文本
        """
        lines = []
        lines.append("")
        lines.append("=" * 50)
        lines.append("  市场环境分析")
        lines.append("=" * 50)

        # 指数行情
        indices = overview.get('indices', {})
        if indices:
            lines.append("")
            lines.append("[主要指数]")
            for name, data in indices.items():
                arrow = "↑" if data['change_pct'] > 0 else "↓"
                trend_str = "↑趋势" if data['trend'] == 'up' else "↓趋势" if data['trend'] == 'down' else "→震荡"
                lines.append(f"  {name}: {data['close']:.0f} ({data['change_pct']:+.2f}%) {trend_str}")

        # 市场情绪
        sentiment = overview.get('sentiment', {})
        if sentiment:
            lines.append("")
            lines.append(f"[市场情绪] {sentiment.get('sentiment_label', 'N/A')} ({sentiment.get('sentiment_score', 0)}/100)")
            lines.append(f"  上涨 {sentiment.get('up_count', 0)} | 下跌 {sentiment.get('down_count', 0)} | 涨停 {sentiment.get('limit_up', 0)} | 跌停 {sentiment.get('limit_down', 0)}")
            lines.append(f"  平均涨幅: {sentiment.get('avg_change', 0):+.2f}%")

        # 市场状态判断
        regime = overview.get('market_regime', {})
        if regime:
            lines.append("")
            regime_map = {'bull': '🐂 牛市', 'bear': '🐻 熊市', 'neutral': '⚖️ 中性'}
            lines.append(f"[市场判断] {regime_map.get(regime.get('regime', ''), regime.get('regime', ''))} (评分: {regime.get('score', 50)}/100)")
            lines.append(f"  建议: {regime.get('suggestion', '')}")
            for r in regime.get('reasons', []):
                lines.append(f"  - {r}")

        # 热门板块
        sectors = overview.get('sectors', {})
        if sectors.get('top_gainers'):
            lines.append("")
            lines.append("[热门板块 Top5]")
            for s in sectors['top_gainers'][:5]:
                lines.append(f"  {s['name']}: {s['change_pct']:+.2f}% (领涨: {s.get('lead_stock', '')})")

        # 概念热点
        concepts = overview.get('concepts', [])
        if concepts:
            lines.append("")
            lines.append("[概念热点 Top5]")
            for c in concepts[:5]:
                lines.append(f"  {c['name']}: {c['change_pct']:+.2f}%")

        return '\n'.join(lines)


# 全局实例
_enrichment = None

def get_enrichment() -> MarketEnrichment:
    global _enrichment
    if _enrichment is None:
        _enrichment = MarketEnrichment()
    return _enrichment


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)

    enrich = MarketEnrichment()
    overview = enrich.get_market_overview()

    print(enrich.format_market_report(overview))
    
    # 也输出JSON用于程序使用
    print("\n\n--- JSON ---")
    print(json.dumps(overview, indent=2, ensure_ascii=False, default=str)[:2000])
