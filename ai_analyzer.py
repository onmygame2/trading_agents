"""
AI 市场分析模块

功能:
1. 收集市场概况数据（大盘指数、板块热度、资金流向）
2. 分析新闻情绪（正面/中性/负面）
3. 汇总策略信号，生成综合评分
4. 输出 AI 分析日报

用法:
    from ai_analyzer import AIAnalyzer
    analyzer = AIAnalyzer()
    report = analyzer.analyze()
    print(report)
"""

import os
import sys
import json
import re
import logging
from datetime import datetime, timedelta
from collections import defaultdict

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)

logger = logging.getLogger(__name__)

# Stock name lookup
STOCK_NAMES_CACHE = {}
def get_stock_name(code):
    if code in STOCK_NAMES_CACHE:
        return STOCK_NAMES_CACHE[code]
    try:
        pool_path = os.path.join(BASE_DIR, 'data', 'stock_pool.json')
        with open(pool_path, 'r') as f:
            pool = json.load(f)
        STOCK_NAMES_CACHE.clear()
        for p in pool:
            STOCK_NAMES_CACHE[p['code']] = p.get('code_name', '')
        return STOCK_NAMES_CACHE.get(code, '')
    except:
        return ''


class AIAnalyzer:
    """AI 市场分析师"""

    def __init__(self):
        self.sina = None
        self.news_fetcher = None
        self._init_fetchers()

    def _init_fetchers(self):
        try:
            from sina_fetcher import SinaFetcher
            self.sina = SinaFetcher()
        except Exception as e:
            logger.warning(f"SinaFetcher init failed: {e}")

        try:
            from market_news import MarketNews
            self.news_fetcher = MarketNews()
        except Exception as e:
            logger.warning(f"MarketNews init failed: {e}")

    # ---- 1. 市场概况 ----

    def get_market_overview(self) -> dict:
        """获取大盘概况"""
        overview = {
            'date': datetime.now().strftime('%Y-%m-%d'),
            'indices': {},
            'sector_hot': [],
            'market_sentiment': 'neutral'
        }

        # 大盘指数
        if self.sina:
            try:
                idx = self.sina.get_index_quotes()
                overview['indices'] = idx
            except Exception as e:
                logger.warning(f"Failed to get index quotes: {e}")

        # 板块热度
        try:
            overview['sector_hot'] = self._get_sector_heat()
        except Exception as e:
            logger.warning(f"Failed to get sector heat: {e}")

        # 综合情绪判断
        overview['market_sentiment'] = self._judge_sentiment(overview)

        return overview

    def _get_sector_heat(self) -> list:
        """获取板块热度排行"""
        if not self.sina:
            return []

        try:
            quotes = self.sina.get_realtime_quotes()
            if quotes.empty:
                return []

            # 按行业分类汇总涨跌幅
            industry_pct = defaultdict(lambda: {'total_pct': 0, 'count': 0, 'stocks': []})

            code_to_industry = {}
            pool_path = os.path.join(BASE_DIR, 'data', 'stock_pool.json')
            if os.path.exists(pool_path):
                with open(pool_path, 'r') as f:
                    pool = json.load(f)
                for p in pool:
                    code_to_industry[p['code']] = p.get('industry_name', '')

            for _, row in quotes.iterrows():
                code = str(row.get('code', ''))
                industry = code_to_industry.get(code, '')
                if not industry:
                    continue
                try:
                    pct = float(row.get('change_pct', 0))
                except:
                    continue
                industry_pct[industry]['total_pct'] += pct
                industry_pct[industry]['count'] += 1
                industry_pct[industry]['stocks'].append(code)

            # 计算平均涨跌幅
            sector_list = []
            for ind, data in industry_pct.items():
                if data['count'] < 3:
                    continue
                avg_pct = data['total_pct'] / data['count']
                sector_list.append({
                    'industry': ind,
                    'avg_change_pct': round(avg_pct, 2),
                    'stock_count': data['count']
                })

            # 排序
            sector_list.sort(key=lambda x: x['avg_change_pct'], reverse=True)
            return sector_list[:10]

        except Exception as e:
            logger.warning(f"Sector heat failed: {e}")
            return []

    def _judge_sentiment(self, overview) -> str:
        """综合判断市场情绪"""
        indices = overview.get('indices', {})

        total_pct = 0
        count = 0

        # Handle both DataFrame and dict
        if hasattr(indices, 'iterrows'):
            if indices.empty:
                return 'neutral'
            for _, row in indices.iterrows():
                try:
                    pct = float(row.get('change_pct', 0))
                    total_pct += pct
                    count += 1
                except:
                    pass
        elif isinstance(indices, dict) and len(indices) > 0:
            for name, data in indices.items():
                try:
                    pct = float(data.get('change_pct', data.get('change', 0)))
                    total_pct += pct
                    count += 1
                except:
                    pass
        else:
            return 'neutral'

        if count == 0:
            return 'neutral'

        avg = total_pct / count
        if avg > 0.5:
            return 'bullish'
        elif avg < -0.5:
            return 'bearish'
        else:
            return 'neutral'

    # ---- 2. 新闻分析 ----

    def get_news_summary(self) -> dict:
        """获取并分析新闻"""
        news_summary = {
            'headlines': [],
            'sentiment': 'neutral',
            'key_topics': []
        }

        if not self.news_fetcher:
            return news_summary

        try:
            news_items = self.news_fetcher.get_today_news(max_items=20)
            news_summary['headlines'] = []
            sentiments = []

            for item in news_items[:15]:
                title = item.get('title', '')
                if not title:
                    continue
                news_summary['headlines'].append(title)
                sentiments.append(self._classify_news_sentiment(title))

            # 计算整体情绪
            if sentiments:
                pos = sentiments.count('positive')
                neg = sentiments.count('negative')
                if pos > neg + 2:
                    news_summary['sentiment'] = 'positive'
                elif neg > pos + 2:
                    news_summary['sentiment'] = 'negative'
                else:
                    news_summary['sentiment'] = 'neutral'

            # 提取关键话题
            news_summary['key_topics'] = self._extract_topics(news_items)

        except Exception as e:
            logger.warning(f"News analysis failed: {e}")

        return news_summary

    def _classify_news_sentiment(self, title: str) -> str:
        """简单的情绪分类"""
        pos_words = ['利好', '大涨', '突破', '上涨', '强劲', '新高', '放量', '反弹', '强势', '增长', '利好', '涨停']
        neg_words = ['利空', '大跌', '破位', '下跌', '疲软', '新低', '缩量', '回调', '弱势', '亏损', '跌停', '风险', '暴跌']

        pos_count = sum(1 for w in pos_words if w in title)
        neg_count = sum(1 for w in neg_words if w in title)

        if pos_count > neg_count:
            return 'positive'
        elif neg_count > pos_count:
            return 'negative'
        return 'neutral'

    def _extract_topics(self, news_items) -> list:
        """提取新闻中的关键话题"""
        topics = defaultdict(int)
        sector_keywords = [
            '科技', '半导体', '芯片', 'AI', '人工智能', '新能源', '光伏',
            '锂电', '医药', '医疗', '消费', '白酒', '金融', '银行',
            '地产', '基建', '军工', '汽车', '航空', '航运', '农业',
            '资源', '钢铁', '有色', '化工', '纺织', '电力', '煤炭'
        ]

        for item in news_items:
            title = item.get('title', '')
            for kw in sector_keywords:
                if kw in title:
                    topics[kw] += 1

        return sorted(topics.items(), key=lambda x: x[1], reverse=True)[:5]

    # ---- 3. 策略信号汇总 ----

    def get_strategy_summary(self, date_str: str = None) -> dict:
        """汇总当日策略信号"""
        if date_str is None:
            date_str = datetime.now().strftime('%Y-%m-%d')

        # 读取 knowledge_base 中的每日报告
        kb_dir = os.path.join(BASE_DIR, 'knowledge_base')
        report_file = os.path.join(kb_dir, f'daily_{date_str.replace("-", "")}.json')

        summary = {
            'date': date_str,
            'buy_signals': [],
            'sell_signals': [],
            'total_value': 100000,
            'positions': []
        }

        if os.path.exists(report_file):
            try:
                with open(report_file, 'r') as f:
                    data = json.load(f)
                summary['buy_signals'] = data.get('buy_signals', [])
                summary['sell_signals'] = data.get('sell_signals', [])
                account = data.get('account', {})
                summary['total_value'] = account.get('cash', 100000)
                summary['positions'] = list(account.get('positions', {}).keys())
            except:
                pass

        return summary

    # ---- 4. 生成综合报告 ----

    def analyze(self) -> str:
        """
        运行完整分析，生成日报

        返回: 格式化的分析报告字符串
        """
        print("[AI Analyzer] 开始市场分析...")

        # 1. 市场概况
        print("  [1/4] 获取市场概况...")
        overview = self.get_market_overview()

        # 2. 新闻分析
        print("  [2/4] 分析新闻情绪...")
        news = self.get_news_summary()

        # 3. 策略信号
        print("  [3/4] 汇总策略信号...")
        strategy = self.get_strategy_summary()

        # 4. 生成报告
        print("  [4/4] 生成综合报告...")
        report = self._generate_report(overview, news, strategy)

        return report

    def _generate_report(self, overview, news, strategy) -> str:
        """生成格式化的综合分析报告"""
        lines = []

        # 标题
        date = overview.get('date', datetime.now().strftime('%Y-%m-%d'))
        lines.append(f"===== AI 市场分析报告 {date} =====")
        lines.append("")

        # 情绪判断
        sentiment_map = {
            'bullish': '看多  ',
            'bearish': '看空  ',
            'neutral': '中性  '
        }
        market_sentiment = sentiment_map.get(overview.get('market_sentiment', 'neutral'), '中性  ')
        news_sentiment = sentiment_map.get(news.get('sentiment', 'neutral'), '中性  ')

        lines.append(f"[市场情绪] 大盘: {market_sentiment}  新闻: {news_sentiment}")
        lines.append("")

        # 大盘指数
        lines.append("[大盘指数]")
        indices = overview.get('indices', {})
        if isinstance(indices, dict) and len(indices) > 0:
            for name, data in indices.items():
                try:
                    price = float(data.get('price', data.get('close', 0)))
                    pct = float(data.get('change_pct', data.get('change', 0)))
                    sign = '+' if pct >= 0 else ''
                    lines.append(f"  {name}: {price:.2f} ({sign}{pct:.2f}%)")
                except:
                    lines.append(f"  {name}: 数据暂缺")
        elif hasattr(indices, 'iterrows') and not indices.empty:
            for _, row in indices.iterrows():
                try:
                    name = str(row.get('name', row.get('code', '?')))
                    price = float(row.get('price', row.get('close', 0)))
                    pct = float(row.get('change_pct', 0))
                    sign = '+' if pct >= 0 else ''
                    lines.append(f"  {name}: {price:.2f} ({sign}{pct:.2f}%)")
                except:
                    pass
        else:
            lines.append("  数据暂缺")
        lines.append("")

        # 板块热度
        sectors = overview.get('sector_hot', [])
        if sectors:
            lines.append("[板块热度 TOP5]")
            for i, s in enumerate(sectors[:5], 1):
                pct = s.get('avg_change_pct', 0)
                sign = '+' if pct >= 0 else ''
                lines.append(f"  {i}. {s['industry']}: {sign}{pct:.2f}% ({s['stock_count']}只)")
        lines.append("")

        # 关键话题
        topics = news.get('key_topics', [])
        if topics:
            lines.append("[热点话题]")
            for topic, count in topics[:5]:
                lines.append(f"  {topic} (提及{count}次)")
        lines.append("")

        # 新闻头条
        headlines = news.get('headlines', [])
        if headlines:
            lines.append("[新闻头条]")
            for h in headlines[:5]:
                lines.append(f"  - {h}")
        lines.append("")

        # 策略信号
        buy_signals = strategy.get('buy_signals', [])
        sell_signals = strategy.get('sell_signals', [])

        if sell_signals:
            lines.append(f"[卖出信号] ({len(sell_signals)}只)")
            for sig in sell_signals:
                name = sig.get('stock_name', get_stock_name(sig.get('stock_code', '')))
                lines.append(f"  SELL {sig.get('stock_code', '')} {name} @ {sig.get('price', 0):.2f}")
                lines.append(f"       {sig.get('reason', '')}")
            lines.append("")

        if buy_signals:
            lines.append(f"[买入信号] ({len(buy_signals)}只)")
            for i, sig in enumerate(buy_signals[:5], 1):
                code = sig.get('stock_code', '')
                name = sig.get('stock_name', get_stock_name(code))
                lines.append(f"  {i}. {code} {name}")
                lines.append(f"     买入: {sig.get('buy_price', sig.get('price', 0)):.2f}  "
                           f"止损: {sig.get('stop_loss', 'N/A')}  "
                           f"止盈: {sig.get('take_profit', 'N/A')}")
                lines.append(f"     策略: {', '.join(sig.get('original_strategies', []))}  "
                           f"置信: {sig.get('confidence', 0):.0%}")
                lines.append(f"     {sig.get('reason', '')}")
            lines.append("")
        else:
            lines.append("[买入信号] 暂无")
            lines.append("")

        # 账户状态
        total = strategy.get('total_value', 100000)
        pos_count = len(strategy.get('positions', []))
        pnl = total - 100000
        pnl_pct = pnl / 100000 * 100
        lines.append(f"[账户] 总资产: {total:,.0f} ({pnl:+,.0f}/{pnl_pct:+.1f}%) | 持仓: {pos_count}只")
        lines.append("")
        lines.append("===== 以上为 AI 辅助分析，仅供参考，不构成投资建议 =====")

        return '\n'.join(lines)

    def analyze_for_hermes(self) -> str:
        """
        生成适合 Hermes 聊天推送的精简版报告

        返回: 紧凑格式的报告
        """
        print("[AI Analyzer] 生成 Hermes 精简报告...")

        overview = self.get_market_overview()
        news = self.get_news_summary()
        strategy = self.get_strategy_summary()

        buy_signals = strategy.get('buy_signals', [])

        # 精简版
        parts = []
        date = overview.get('date', datetime.now().strftime('%Y-%m-%d'))
        parts.append(f"📊 AI选股 {date}")

        # 大盘
        indices = overview.get('indices', {})
        idx_parts = []
        if isinstance(indices, dict):
            for name in ['上证指数', '深证成指', '创业板指']:
                if name in indices:
                    d = indices[name]
                    try:
                        pct = float(d.get('change_pct', d.get('change', 0)))
                        sign = '+' if pct >= 0 else ''
                        idx_parts.append(f"{name}{sign}{pct:.2f}%")
                    except:
                        pass
        elif hasattr(indices, 'iterrows') and not indices.empty:
            for _, row in indices.iterrows():
                try:
                    name = str(row.get('name', ''))
                    pct = float(row.get('change_pct', 0))
                    sign = '+' if pct >= 0 else ''
                    idx_parts.append(f"{name}{sign}{pct:.2f}%")
                except:
                    pass
        if idx_parts:
            parts.append(' | '.join(idx_parts[:3]))

        # 情绪
        sent = overview.get('market_sentiment', 'neutral')
        sent_icon = {'bullish': '🟢', 'bearish': '🔴', 'neutral': '🟡'}.get(sent, '🟡')
        parts.append(f"情绪: {sent_icon}")

        # 买入信号
        if buy_signals:
            parts.append(f"\n📈 推荐 ({len(buy_signals)}只):")
            for sig in buy_signals[:5]:
                code = sig.get('stock_code', '')
                name = sig.get('stock_name', get_stock_name(code))
                buy = sig.get('buy_price', sig.get('price', 0))
                sl = sig.get('stop_loss', 0)
                tp = sig.get('take_profit', 0)
                conf = sig.get('confidence', 0)
                parts.append(f"  {code} {name} 买@{buy:.2f} 止损{sl:.2f} 止盈{tp:.2f} ({conf:.0%})")

        # 账户
        total = strategy.get('total_value', 100000)
        pnl = total - 100000
        parts.append(f"\n💰 账户: {total:,.0f} ({pnl:+,.0f})")

        return '\n'.join(parts)


def main():
    logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')

    analyzer = AIAnalyzer()

    # 详细版
    full_report = analyzer.analyze()
    print("\n" + full_report)

    # 保存到 knowledge_base
    kb_dir = os.path.join(BASE_DIR, 'knowledge_base')
    os.makedirs(kb_dir, exist_ok=True)

    date_str = datetime.now().strftime('%Y%m%d')
    with open(os.path.join(kb_dir, f'ai_analysis_{date_str}.txt'), 'w', encoding='utf-8') as f:
        f.write(full_report)

    # 精简版
    brief = analyzer.analyze_for_hermes()
    with open(os.path.join(kb_dir, f'ai_brief_{date_str}.txt'), 'w', encoding='utf-8') as f:
        f.write(brief)

    print(f"\n报告已保存到 knowledge_base/")


if __name__ == '__main__':
    main()
