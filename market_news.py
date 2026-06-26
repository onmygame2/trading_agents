"""
A股市场新闻获取模块

功能:
1. 从多个财经数据源获取实时新闻/公告/研报摘要
2. 本地缓存 JSON 格式
3. 提供按日期/关键词查询

数据源 (直连, 无需代理):
- 新浪财经滚动新闻
- 东方财富资讯接口
- 同花顺快讯

用法:
    from market_news import MarketNews
    news = MarketNews()
    headlines = news.get_today_news()  # 获取今日新闻
    news.save_today_news()             # 缓存到本地
"""

import os
import json
import time
import logging
import urllib.request
import urllib.error
from datetime import datetime, timedelta
from html import unescape

logger = logging.getLogger(__name__)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
NEWS_CACHE_DIR = os.path.join(BASE_DIR, 'data', 'news')
os.makedirs(NEWS_CACHE_DIR, exist_ok=True)

SINA_HEADERS = {
    'Referer': 'https://finance.sina.com.cn',
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
}


def _fetch_url(url, headers=None, timeout=10):
    """Fetch URL and return text content."""
    try:
        req = urllib.request.Request(url)
        if headers:
            for k, v in headers.items():
                req.add_header(k, v)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read().decode('utf-8', errors='ignore')
    except Exception as e:
        logger.debug(f"Fetch failed: {url} -> {e}")
        return None


class MarketNews:
    """A股市场新闻聚合器"""

    def __init__(self):
        self.cache_dir = NEWS_CACHE_DIR

    def _get_cache_path(self, date_str=None):
        if date_str is None:
            date_str = datetime.now().strftime('%Y-%m-%d')
        return os.path.join(self.cache_dir, f'news_{date_str}.json')

    def _load_cache(self, date_str=None):
        """Load cached news for a date."""
        path = self._get_cache_path(date_str)
        if os.path.exists(path):
            with open(path, 'r', encoding='utf-8') as f:
                return json.load(f)
        return None

    def _save_cache(self, news_items, date_str=None):
        """Save news to cache."""
        path = self._get_cache_path(date_str)
        cache = {
            'date': date_str or datetime.now().strftime('%Y-%m-%d'),
            'fetched_at': datetime.now().isoformat(),
            'count': len(news_items),
            'items': news_items
        }
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(cache, f, ensure_ascii=False, indent=2)
        return path

    def _clean_html(self, text):
        """Clean HTML tags and entities from text."""
        import re
        if not text:
            return ''
        text = unescape(text)
        text = re.sub(r'<[^>]+>', '', text)
        text = text.strip()
        # Collapse whitespace
        text = re.sub(r'\s+', ' ', text)
        return text

    # ---- Source 1: Sina Finance Rolling News ----

    def _fetch_sina_news(self, num=20):
        """
        新浪财经滚动新闻
        pageid=153 = 国内财经
        lid=2516 = 7x24快讯
        """
        items = []
        urls = [
            # 7x24 滚动快讯
            f"https://feed.mix.sina.com.cn/api/roll/get?pageid=153&lid=2516&num={num}&page=1",
            # 国内财经
            f"https://feed.mix.sina.com.cn/api/roll/get?pageid=153&lid=2510&num={num}&page=1",
        ]

        for url in urls:
            try:
                req = urllib.request.Request(url, headers=SINA_HEADERS)
                with urllib.request.urlopen(req, timeout=10) as resp:
                    data = json.loads(resp.read().decode('utf-8', errors='ignore'))

                result = data.get('result', {})
                news_list = result.get('data', [])

                for item in news_list:
                    title = self._clean_html(item.get('title', ''))
                    content = self._clean_html(item.get('intro', item.get('summary', '')))
                    url = item.get('url', '')
                    ctime = item.get('ctime', '')

                    if title:
                        items.append({
                            'title': title,
                            'summary': content or title,
                            'url': url,
                            'time': ctime,
                            'source': 'sina',
                            'source_name': '新浪财经'
                        })
            except Exception as e:
                logger.debug(f"Sina news fetch error: {e}")

        return items

    # ---- Source 2: East Money News ----

    def _fetch_eastmoney_news(self, num=20):
        """
        东方财富资讯接口
        """
        items = []
        # 东方财富 7x24 快讯 API
        api_url = f"https://np-listapi.eastmoney.com/comm/web/getNewsByColumns"
        params = {
            "column": "104",  # 7x24快讯
            "pageIndex": "1",
            "pageSize": str(num),
            "showClassification": "0",
            "fields": "title,summary,publishTime,url,sourceShortName"
        }
        query = "&".join(f"{k}={v}" for k, v in params.items())

        try:
            url = f"{api_url}?{query}"
            req = urllib.request.Request(url, headers={
                'User-Agent': SINA_HEADERS['User-Agent'],
                'Referer': 'https://www.eastmoney.com/'
            })
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode('utf-8', errors='ignore'))

            result = data.get('data', {})
            news_list = result.get('datas', [])

            for item in news_list:
                title = self._clean_html(item.get('title', ''))
                if title:
                    items.append({
                        'title': title,
                        'summary': self._clean_html(item.get('summary', '')) or title,
                        'url': item.get('url', ''),
                        'time': item.get('publishTime', ''),
                        'source': 'eastmoney',
                        'source_name': item.get('sourceShortName', '东方财富')
                    })
        except Exception as e:
            logger.debug(f"EastMoney news fetch error: {e}")

        return items

    # ---- Source 3: Sina Finance News Page (scrape fallback) ----

    def _fetch_sina_finance_scrape(self, num=10):
        """
        Fallback: scrape Sina finance news page directly
        """
        items = []
        try:
            text = _fetch_url(
                "https://finance.sina.com.cn/",
                headers=SINA_HEADERS,
                timeout=10
            )
            if text:
                import re
                # Extract headlines from the page
                # Pattern: <a href="..." title="..."> or similar
                pattern = r'<a[^>]*href="([^"]*)"[^>]*title="([^"]*)"[^>]*>'
                matches = re.findall(pattern, text)
                for url, title in matches[:num]:
                    title = self._clean_html(title)
                    if title and len(title) > 5 and '股票' in '股市行情资金要闻'.replace('', ''):
                        items.append({
                            'title': title,
                            'summary': title,
                            'url': 'https:' + url if url.startswith('//') else url,
                            'time': datetime.now().strftime('%Y-%m-%d %H:%M'),
                            'source': 'sina_scrape',
                            'source_name': '新浪财经'
                        })
        except Exception as e:
            logger.debug(f"Sina scrape error: {e}")

        return items

    # ---- Main methods ----

    def get_today_news(self, max_items=30, use_cache=True):
        """
        Get today's market news.

        Args:
            max_items: maximum number of items to return
            use_cache: if True and cache exists with >5 items, return cached

        Returns:
            list of news dicts with keys: title, summary, url, time, source, source_name
        """
        today = datetime.now().strftime('%Y-%m-%d')

        # Try cache first
        if use_cache:
            cached = self._load_cache(today)
            if cached and len(cached.get('items', [])) >= 5:
                return cached['items'][:max_items]

        # Fetch from multiple sources
        all_items = []
        seen_titles = set()

        sources = [
            ('sina', self._fetch_sina_news),
            ('eastmoney', self._fetch_eastmoney_news),
            ('sina_scrape', self._fetch_sina_finance_scrape),
        ]

        for source_name, fetch_fn in sources:
            try:
                items = fetch_fn(num=max_items)
                for item in items:
                    # Deduplicate by title
                    title_key = item.get('title', '')[:50]
                    if title_key and title_key not in seen_titles:
                        seen_titles.add(title_key)
                        all_items.append(item)

                if len(all_items) >= max_items:
                    break
            except Exception as e:
                logger.debug(f"Source {source_name} failed: {e}")

        # Save to cache
        if all_items:
            self._save_cache(all_items, today)

        return all_items[:max_items]

    def get_latest_headlines(self, max_items=10):
        """Get the most recent headlines (title + summary only)."""
        items = self.get_today_news(max_items=max_items)
        headlines = []
        for item in items:
            headlines.append({
                'title': item.get('title', '')[:80],
                'summary': item.get('summary', '')[:150],
                'time': item.get('time', ''),
                'source': item.get('source_name', ''),
                'url': item.get('url', '')
            })
        return headlines

    def get_stock_news(self, stock_code: str, stock_name: str = '', max_items: int = 10):
        """
        Get news related to a specific stock.

        Uses EastMoney search API to find stock-specific news/announcements.

        Args:
            stock_code: 6-digit stock code (e.g. '600519')
            stock_name: stock name for keyword search
            max_items: maximum number of items to return

        Returns:
            list of news dicts
        """
        items = []
        seen_titles = set()

        # Source 1: EastMoney search API (search by stock code)
        try:
            keyword = stock_name or stock_code
            em_url = (
                f"https://search-api-web.eastmoney.com/search/jsonp"
                f"?type=14&pageindex=1&pagesize={max_items}"
                f"&keyword={urllib.parse.quote(keyword)}"
                f"&sort=0&token=687e3552-306b-467b-9a6f-169273596097"
            )
            req = urllib.request.Request(em_url, headers={
                'User-Agent': SINA_HEADERS['User-Agent'],
                'Referer': 'https://www.eastmoney.com/'
            })
            with urllib.request.urlopen(req, timeout=10) as resp:
                raw = resp.read().decode('utf-8', errors='ignore')
            # JSONP wrapper: extract JSON
            import re
            json_match = re.search(r'\{.*\}', raw, re.DOTALL)
            if json_match:
                data = json.loads(json_match.group())
                em_results = data.get('result', [])
                for item in em_results[:max_items]:
                    title = self._clean_html(item.get('title', ''))
                    if title and title not in seen_titles:
                        seen_titles.add(title)
                        items.append({
                            'title': title,
                            'summary': self._clean_html(item.get('digest', '')) or title,
                            'url': item.get('url', ''),
                            'time': item.get('showTime', ''),
                            'source': 'eastmoney_stock',
                            'source_name': '东方财富',
                            'stock_code': stock_code,
                        })
        except Exception as e:
            logger.debug(f"EastMoney stock news error for {stock_code}: {e}")

        # Source 2: Sina stock news page - only grab "公司公告" / "公司新闻" section
        if len(items) < max_items:
            try:
                prefix = 'sh' if stock_code.startswith('6') else 'sz'
                sina_url = f"https://finance.sina.com.cn/realstock/company/{prefix}{stock_code}/nc.shtml"
                req = urllib.request.Request(sina_url, headers=SINA_HEADERS)
                with urllib.request.urlopen(req, timeout=10) as resp:
                    html = resp.read().decode('gbk', errors='ignore')
                import re
                # Only extract links that look like actual news (contain date patterns or news keywords)
                links = re.findall(r'<a[^>]*href="([^"]+\.shtml[^"]*|/news[^"]+)"[^>]*>([^<]+)</a>', html)
                generic_keywords = {'更多', '首页', '导航', '全部', '展开', '收起', '筛选',
                                    '一周强势股', '买入评级股', '基金重仓股', '趋势转升股',
                                    '短线出击股', '龙虎榜', '机构调研', '大宗交易',
                                    '股东研究', '行业对比', '板块排行'}
                for url, title in links:
                    title = self._clean_html(title)
                    # Filter: must be meaningful and not generic navigation
                    if (title and len(title) > 6
                            and not any(gk in title for gk in generic_keywords)
                            and title not in seen_titles):
                        seen_titles.add(title)
                        items.append({
                            'title': title,
                            'summary': title,
                            'url': url if url.startswith('http') else f'https:{url}',
                            'time': '',
                            'source': 'sina_stock',
                            'source_name': '新浪财经',
                            'stock_code': stock_code,
                        })
                        if len(items) >= max_items:
                            break
            except Exception as e:
                logger.debug(f"Sina stock news error for {stock_code}: {e}")

        # Source 3: EastMoney stock announcement API (reliable for announcements)
        if len(items) < max_items:
            try:
                em_secid = f"1.{stock_code}" if stock_code.startswith('6') else f"0.{stock_code}"
                em_ann_url = (
                    f"https://np-anotice-stock.eastmoney.com/api/security/ann"
                    f"?sr=-1&stock={em_secid}&pageSize={max_items}&pageNum=1"
                    f"&showClassify=0&fields=announceTime,code,title,webAnnNum"
                )
                req = urllib.request.Request(em_ann_url, headers={
                    'User-Agent': SINA_HEADERS['User-Agent'],
                    'Referer': 'https://data.eastmoney.com/'
                })
                with urllib.request.urlopen(req, timeout=10) as resp:
                    ann_data = json.loads(resp.read().decode('utf-8', errors='ignore'))
                for item in ann_data.get('data', ann_data.get('result', [])[:max_items]):
                    title = self._clean_html(item.get('title', ''))
                    if title and title not in seen_titles:
                        seen_titles.add(title)
                        web_num = item.get('webAnnNum', '')
                        ann_url = f"https://data.eastmoney.com/notices/{web_num}.html" if web_num else ''
                        items.append({
                            'title': title,
                            'summary': title,
                            'url': ann_url,
                            'time': item.get('announceTime', ''),
                            'source': 'eastmoney_ann',
                            'source_name': '东财公告',
                            'stock_code': stock_code,
                        })
                        if len(items) >= max_items:
                            break
            except Exception as e:
                logger.debug(f"EastMoney announcement error for {stock_code}: {e}")

        return items[:max_items]

    def get_news_by_keyword(self, keywords, max_items=10):
        """Filter today's news by keywords."""
        all_items = self.get_today_news(max_items=50)
        matched = []
        keyword_list = keywords if isinstance(keywords, list) else [keywords]
        for item in all_items:
            title = item.get('title', '').lower()
            summary = item.get('summary', '').lower()
            if any(k.lower() in title or k.lower() in summary for k in keyword_list):
                matched.append(item)
                if len(matched) >= max_items:
                    break
        return matched

    def get_all_cached_days(self):
        """List all dates that have cached news."""
        dates = []
        if os.path.exists(self.cache_dir):
            for f in sorted(os.listdir(self.cache_dir)):
                if f.startswith('news_') and f.endswith('.json'):
                    date_str = f[5:-5]
                    dates.append(date_str)
        return dates

    def save_today_news(self):
        """Force refresh and save today's news."""
        items = self.get_today_news(max_items=30, use_cache=False)
        return len(items)


if __name__ == '__main__':
    logging.basicConfig(level=logging.DEBUG)
    news = MarketNews()

    # Test fetch
    print("Fetching today's news...")
    items = news.get_today_news(max_items=15, use_cache=False)

    if items:
        print(f"\nGot {len(items)} news items:\n")
        for i, item in enumerate(items[:15], 1):
            print(f"{i}. [{item.get('source_name', '')}] {item.get('title', '')[:70]}")
            if item.get('time'):
                print(f"   Time: {item['time']}")
            print()
    else:
        print("No news fetched. All sources may be unavailable.")

    # Check cache
    dates = news.get_all_cached_days()
    print(f"Cached dates: {dates}")
