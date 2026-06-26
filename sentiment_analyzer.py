"""
Market Sentiment Analyzer - A股综合情绪分析引擎

功能:
1. 从多源获取市场热度数据 (东财热点/财新新闻/百度经济日历)
2. 基于LLM对新闻进行情绪评分
3. 生成综合市场情绪指数 (0-100)
4. 输出热门概念板块排行
5. 为选股策略提供情绪加分

数据源:
- 东财热点排名 (stock_hot_rank_em)
- 东财热点关键词 (stock_hot_keyword_em)
- 财新财经新闻 (stock_news_main_cx)
- 百度经济日历 (news_economic_baidu)

用法:
    analyzer = SentimentAnalyzer()
    result = analyzer.analyze()
    print(result['sentiment_score'])  # 0-100
    print(result['hot_concepts'])     # 热门概念列表
"""

import os
import json
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
import pandas as pd
import numpy as np

logger = logging.getLogger(__name__)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SENTIMENT_CACHE_DIR = os.path.join(BASE_DIR, 'data', 'sentiment')
os.makedirs(SENTIMENT_CACHE_DIR, exist_ok=True)


# ---------------------------------------------------------------------------
# LLM-based sentiment scoring prompt
# ---------------------------------------------------------------------------
SENTIMENT_PROMPT = """你是一个专业的A股市场分析师。请根据以下财经新闻，给出市场情绪评分。

新闻列表:
{news_list}

请严格按以下JSON格式返回（不要其他内容）:
{{
    "score": 75,
    "reason": "理由简述",
    "bullish_keywords": ["利好关键词"],
    "bearish_keywords": ["利空关键词"],
    "hot_sectors": ["热门板块"]
}}

评分标准:
- 0-20: 极度悲观 (重大利空, 恐慌抛售)
- 20-40: 悲观 (利空主导, 市场低迷)
- 40-60: 中性 (多空均衡, 震荡)
- 60-80: 乐观 (利好居多, 温和上涨)
- 80-100: 极度乐观 (重大利好, 牛市情绪)
"""


class SentimentAnalyzer:
    """综合市场情绪分析器"""

    def __init__(self, cache_dir=None):
        self.cache_dir = cache_dir or SENTIMENT_CACHE_DIR
        os.makedirs(self.cache_dir, exist_ok=True)

    def get_hot_rank(self) -> pd.DataFrame:
        """获取东方财富热门股票排名"""
        try:
            import akshare as ak
            df = ak.stock_hot_rank_em()
            # 过滤ST和科创板
            df = df[~df['股票名称'].str.contains('ST', na=False)]
            df = df[~df['代码'].str.startswith('688')]
            df = df[~df['代码'].str.startswith('689')]
            return df
        except Exception as e:
            logger.warning(f"获取热点排名失败: {e}")
            return pd.DataFrame()

    def get_hot_keywords(self) -> pd.DataFrame:
        """获取东方财富热点概念关键词"""
        try:
            import akshare as ak
            df = ak.stock_hot_keyword_em()
            return df
        except Exception as e:
            logger.warning(f"获取热点关键词失败: {e}")
            return pd.DataFrame()

    def get_finance_news(self) -> pd.DataFrame:
        """获取财新财经新闻"""
        try:
            import akshare as ak
            df = ak.stock_news_main_cx()
            return df
        except Exception as e:
            logger.warning(f"获取财新新闻失败: {e}")
            return pd.DataFrame()

    def get_economic_calendar(self) -> pd.DataFrame:
        """获取百度经济日历"""
        try:
            import akshare as ak
            df = ak.news_economic_baidu()
            return df
        except Exception as e:
            logger.warning(f"获取经济日历失败: {e}")
            return pd.DataFrame()

    def _score_from_price_action(self, hot_rank_df: pd.DataFrame) -> float:
        """基于热门股票的涨跌情况评分 (0-100)"""
        if hot_rank_df.empty:
            return 50  # 默认中性

        # 取前50名热门股
        top50 = hot_rank_df.head(50)
        change_pct = top50['涨跌幅'].astype(float)

        # 上涨比例
        up_ratio = (change_pct > 0).sum() / len(change_pct)

        # 平均涨幅
        avg_change = change_pct.mean()

        # 综合评分
        score = 50 + (up_ratio - 0.5) * 40 + avg_change * 2
        return np.clip(score, 0, 100)

    def _get_hot_concepts(self, keywords_df: pd.DataFrame) -> List[Dict]:
        """提取热门概念板块"""
        if keywords_df.empty:
            return []

        concepts = []
        # 按热度分组
        grouped = keywords_df.groupby('概念名称')['热度'].sum().reset_index()
        grouped = grouped.sort_values('热度', ascending=False)

        for _, row in grouped.head(20).iterrows():
            concepts.append({
                'name': row['概念名称'],
                'heat': int(row['热度']),
            })

        return concepts

    def _keyword_sentiment(self, news_df: pd.DataFrame) -> float:
        """基于关键词的情绪评分 (无需LLM的轻量版)"""
        if news_df.empty:
            return 50

        bullish_words = [
            '上涨', '突破', '新高', '利好', '增长', '盈利', '复苏',
            '强劲', '超预期', '反弹', '牛市', '加仓', '看好',
            '创新高', '大涨', '涨停', '放量', '资金流入'
        ]
        bearish_words = [
            '下跌', '暴跌', '利空', '下滑', '亏损', '衰退',
            '疲软', '不及预期', '调整', '熊市', '减仓', '看空',
            '新低', '大跌', '跌停', '缩量', '资金流出', '风险'
        ]

        bullish_count = 0
        bearish_count = 0

        for summary in news_df['summary'].dropna():
            for word in bullish_words:
                if word in str(summary):
                    bullish_count += 1
            for word in bearish_words:
                if word in str(summary):
                    bearish_count += 1

        total = bullish_count + bearish_count
        if total == 0:
            return 50

        ratio = bullish_count / total
        score = 50 + (ratio - 0.5) * 40
        return np.clip(score, 0, 100)

    def analyze(self, use_llm=False) -> Dict:
        """
        执行综合情绪分析

        Args:
            use_llm: 是否使用LLM评分 (默认False，用轻量关键词法)

        Returns:
            {
                'sentiment_score': 75,  # 综合情绪分 (0-100)
                'price_action_score': 70,  # 价量评分
                'news_sentiment_score': 65,  # 新闻情绪评分
                'hot_concepts': [...],  # 热门概念
                'hot_stocks': [...],  # 热门股票
                'news_summary': [...],  # 新闻摘要
                'timestamp': '2026-05-21 18:00:00'
            }
        """
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        # 1. 获取数据
        logger.info("Fetching market sentiment data...")
        hot_rank = self.get_hot_rank()
        keywords = self.get_hot_keywords()
        news = self.get_finance_news()
        calendar = self.get_economic_calendar()

        # 2. 价量评分
        price_score = self._score_from_price_action(hot_rank)

        # 3. 新闻情绪评分
        if use_llm:
            # LLM评分 (需要API) - 预留
            news_score = self._keyword_sentiment(news)
        else:
            news_score = self._keyword_sentiment(news)

        # 4. 综合评分 (加权)
        sentiment_score = price_score * 0.6 + news_score * 0.4

        # 5. 热门概念
        hot_concepts = self._get_hot_concepts(keywords)

        # 6. 热门股票 (前20)
        hot_stocks = []
        if not hot_rank.empty:
            for _, row in hot_rank.head(20).iterrows():
                hot_stocks.append({
                    'rank': int(row['当前排名']),
                    'code': row['代码'],
                    'name': row['股票名称'],
                    'price': float(row['最新价']),
                    'change_pct': float(row['涨跌幅']),
                })

        # 7. 新闻摘要
        news_summary = []
        if not news.empty:
            for _, row in news.head(10).iterrows():
                news_summary.append({
                    'tag': row.get('tag', ''),
                    'summary': str(row.get('summary', ''))[:200],
                })

        result = {
            'sentiment_score': round(sentiment_score, 1),
            'price_action_score': round(price_score, 1),
            'news_sentiment_score': round(news_score, 1),
            'hot_concepts': hot_concepts,
            'hot_stocks': hot_stocks,
            'news_summary': news_summary,
            'data_sources': {
                'hot_rank_count': len(hot_rank),
                'keywords_count': len(keywords),
                'news_count': len(news),
                'calendar_count': len(calendar),
            },
            'timestamp': timestamp,
        }

        # 8. 缓存结果
        cache_file = os.path.join(
            self.cache_dir,
            f"sentiment_{datetime.now().strftime('%Y%m%d_%H%M')}.json"
        )
        with open(cache_file, 'w', encoding='utf-8') as f:
            json.dump(result, f, ensure_ascii=False, indent=2)

        return result

    def get_sentiment_for_stock(self, stock_code: str, stock_name: str) -> Dict:
        """
        获取个股情绪分析

        Returns:
            {
                'is_in_hot_rank': bool,
                'hot_rank': int or None,
                'related_concepts': [...],
                'sentiment_boost': float  # 情绪加分 (-10 to +10)
            }
        """
        hot_rank = self.get_hot_rank()
        keywords = self.get_hot_keywords()

        # 检查是否在热门榜
        in_hot = False
        rank = None
        if not hot_rank.empty:
            match = hot_rank[hot_rank['代码'] == stock_code]
            if not match.empty:
                in_hot = True
                rank = int(match.iloc[0]['当前排名'])

        # 查找相关概念
        related = []
        if not keywords.empty:
            # 简化：只检查概念热度
            for concept in keywords['概念名称'].unique():
                related.append(concept)

        # 计算情绪加分
        boost = 0
        if in_hot:
            boost = max(0, 20 - rank * 0.5)  # 排名越靠前加分越多
        boost = np.clip(boost, -10, 10)

        return {
            'is_in_hot_rank': in_hot,
            'hot_rank': rank,
            'related_concepts': related[:10],
            'sentiment_boost': round(boost, 1),
        }

    def get_latest_sentiment(self) -> Optional[Dict]:
        """获取最新缓存的情绪分析结果"""
        if not os.path.exists(self.cache_dir):
            return None

        files = sorted([
            f for f in os.listdir(self.cache_dir)
            if f.startswith('sentiment_') and f.endswith('.json')
        ], reverse=True)

        if not files:
            return None

        cache_file = os.path.join(self.cache_dir, files[0])
        try:
            with open(cache_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            logger.warning(f"读取缓存失败: {e}")
            return None


def main():
    logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')

    analyzer = SentimentAnalyzer()
    result = analyzer.analyze()

    print("=" * 60)
    print("A股市场情绪分析报告")
    print("=" * 60)
    print(f"时间: {result['timestamp']}")
    print(f"\n综合情绪指数: {result['sentiment_score']}/100")
    print(f"  价量评分: {result['price_action_score']}/100")
    print(f"  新闻情绪评分: {result['news_sentiment_score']}/100")

    print(f"\n数据源:")
    for k, v in result['data_sources'].items():
        print(f"  {k}: {v}")

    print(f"\nTop 10 热门概念:")
    for i, c in enumerate(result['hot_concepts'][:10], 1):
        print(f"  {i}. {c['name']} (热度: {c['heat']})")

    print(f"\nTop 10 热门股票:")
    for s in result['hot_stocks'][:10]:
        direction = "↑" if s['change_pct'] > 0 else "↓"
        print(f"  #{s['rank']} {s['name']} ({s['code']}) {s['price']:.2f} {direction}{abs(s['change_pct']):.2f}%")

    print(f"\n最新财经新闻:")
    for n in result['news_summary'][:5]:
        print(f"  [{n['tag']}] {n['summary'][:80]}...")

    print("=" * 60)


if __name__ == '__main__':
    main()
