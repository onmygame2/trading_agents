"""
A股实时数据获取模块 - 新浪/腾讯 API 版本

功能:
1. 全市场实时行情快照（新浪 API，直连可用）
2. 个股日线K线（新浪历史 + 本地缓存）
3. 股票池更新（从新浪实时行情中提取）
4. 技术指标计算（兼容现有系统）

数据源:
- 实时行情: https://hq.sinajs.cn (直连，盘中实时)
- 历史K线: https://money.finance.sina.com.cn + 本地 CSV 缓存
- 大盘指数: 新浪指数接口

用法:
    from sina_fetcher import SinaFetcher
    fetcher = SinaFetcher()
    quotes = fetcher.get_realtime_quotes()           # 全市场实时行情
    kline = fetcher.get_daily_kline('600000', days=120)  # 个股日线
    pool = fetcher.get_stock_pool()                   # 股票池
"""

import os
import re
import json
import time
import logging
import urllib.request
import urllib.error
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed

logger = logging.getLogger(__name__)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, 'data')
KLINEDIR = os.path.join(DATA_DIR, 'kline')
os.makedirs(KLINEDIR, exist_ok=True)

SINA_HEADERS = {
    'Referer': 'https://finance.sina.com.cn',
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
}

# 允许的股票前缀 — 统一由 market_filter 管理
from market_filter import get_include_prefixes, is_allowed, filter_stock_records

def _allowed_prefixes():
    return get_include_prefixes()

ALLOWED_PREFIXES = _allowed_prefixes()


class SinaFetcher:
    """新浪/腾讯 A股数据获取器"""

    def __init__(self):
        self._stock_pool = None
        self._realtime_cache = None
        self._cache_time = 0

    # ==================== 实时行情 ====================

    def get_realtime_quotes(self, stock_codes=None):
        """
        获取全市场实时行情快照（新浪 API）

        参数:
            stock_codes: 指定股票代码列表。None=获取全市场（从 stock_pool）

        返回: DataFrame with columns:
            code, name, open, pre_close, close, high, low,
            volume, amount, change_pct, date, time
        """
        if stock_codes is None:
            pool = self.get_stock_pool()
            if pool is None or pool.empty:
                return pd.DataFrame()
            stock_codes = pool['code'].tolist()

        # Build sina code list with sh/sz prefix
        sina_codes = []
        for c in stock_codes:
            if c.startswith('6'):
                sina_codes.append('sh' + c)
            elif c.startswith(('0', '2', '3')):
                sina_codes.append('sz' + c)
            else:
                sina_codes.append('sh' + c)  # default to SH

        all_data = []
        batch_size = 500

        for i in range(0, len(sina_codes), batch_size):
            batch = sina_codes[i:i + batch_size]
            url = 'https://hq.sinajs.cn/list=' + ','.join(batch)
            try:
                req = urllib.request.Request(url, headers=SINA_HEADERS)
                resp = urllib.request.urlopen(req, timeout=15)
                text = resp.read().decode('gbk', errors='replace')

                for line in text.strip().split('\n'):
                    m = re.match(r'var hq_str_(\w+)="(.*)"', line)
                    if not m:
                        continue
                    code_key = m.group(1)
                    parts = m.group(2).split(',')

                    if len(parts) < 32 or not parts[0]:
                        continue

                    exchange = code_key[:2]
                    code = code_key[2:]
                    pre_close = float(parts[2]) if parts[2] else 0
                    close = float(parts[3]) if parts[3] else 0

                    change_pct = 0
                    if pre_close > 0:
                        change_pct = round((close - pre_close) / pre_close * 100, 2)

                    all_data.append({
                        'code': code,
                        'name': parts[0],
                        'open': float(parts[1]),
                        'pre_close': pre_close,
                        'close': close,
                        'high': float(parts[4]),
                        'low': float(parts[5]),
                        'volume': float(parts[8]),
                        'amount': float(parts[9]),
                        'date': parts[30],
                        'time': parts[31],
                        'change_pct': change_pct,
                    })

            except Exception as e:
                logger.warning(f"新浪行情批量拉取失败 batch {i // batch_size}: {e}")

        if not all_data:
            return pd.DataFrame()

        df = pd.DataFrame(all_data)
        self._realtime_cache = df
        self._cache_time = time.time()
        logger.info(f"新浪实时行情: {len(df)} 只股票")
        return df

    def get_realtime_quote(self, stock_code):
        """
        获取单只股票实时行情

        返回: dict with code, name, open, pre_close, close, high, low, volume, amount, change_pct
        """
        quotes = self.get_realtime_quotes([stock_code])
        if quotes.empty:
            return None
        row = quotes[quotes['code'] == stock_code]
        if row.empty:
            return None
        return row.iloc[0].to_dict()

    def get_market_summary(self):
        """
        获取市场概览：涨跌家数、涨停/跌停、成交额排名

        返回: dict
        """
        quotes = self.get_realtime_quotes()
        if quotes.empty:
            return {}

        up = len(quotes[quotes['change_pct'] > 0])
        down = len(quotes[quotes['change_pct'] < 0])
        flat = len(quotes[quotes['change_pct'] == 0])
        limit_up = len(quotes[quotes['change_pct'] >= 9.8])
        limit_down = len(quotes[quotes['change_pct'] <= -9.8])

        top_amount = quotes.nlargest(10, 'amount')[['code', 'name', 'close', 'change_pct', 'amount']]

        return {
            'up': up,
            'down': down,
            'flat': flat,
            'up_pct': round(up / len(quotes) * 100, 1),
            'limit_up': limit_up,
            'limit_down': limit_down,
            'total_amount': round(quotes['amount'].sum() / 1e8, 2),  # 亿
            'top_amount': top_amount.to_dict('records'),
            'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        }

    # ==================== 历史K线 ====================

    def get_daily_kline(self, stock_code, days=120):
        """
        获取个股日线K线（前复权）

        优先从本地 CSV 缓存读取，然后用新浪历史 K 线补充最近数据。

        参数:
            stock_code: 纯数字代码，如 '600000'
            days: 获取最近 N 天

        返回: DataFrame with columns:
            date, stock_code, open, high, low, close, volume, amount, change_pct, turnover
        """
        # Step 1: Load from local CSV cache
        local_df = self._load_local_kline(stock_code)

        # Step 2: Fetch from Sina historical API to get latest data
        sina_df = self._fetch_sina_historical(stock_code, days)

        if sina_df is not None and not sina_df.empty:
            # Merge: sina data (latest) + local data (historical)
            if local_df is not None and not local_df.empty:
                # Combine and deduplicate by date
                combined = pd.concat([local_df, sina_df], ignore_index=True)
                combined = combined.drop_duplicates(subset='date', keep='last')
                combined = combined.sort_values('date')
            else:
                combined = sina_df
        else:
            combined = local_df if local_df is not None else pd.DataFrame()

        if combined.empty:
            return pd.DataFrame()

        combined = combined.tail(days).reset_index(drop=True)

        # Ensure standard columns
        if 'stock_code' not in combined.columns:
            combined['stock_code'] = stock_code
        if 'change_pct' not in combined.columns:
            combined['change_pct'] = combined['close'].pct_change() * 100

        return combined

    def _load_local_kline(self, stock_code):
        """Load from local CSV cache"""
        csv_path = os.path.join(KLINEDIR, f'{stock_code}.csv')
        if not os.path.exists(csv_path):
            return None
        try:
            df = pd.read_csv(csv_path)
            df['date'] = pd.to_datetime(df['date'])
            return df
        except Exception as e:
            logger.warning(f"读取本地K线失败 {stock_code}: {e}")
            return None

    def _fetch_sina_historical(self, stock_code, days=120):
        """
        Fetch historical K-line from Sina API.

        Sina API supports scale=240 (daily), max 120 records per call.
        Returns pre-adjusted (前复权) data.
        """
        exchange = 'sh' if stock_code.startswith('6') else 'sz'
        symbol = exchange + stock_code

        # Sina daily: scale=240, datalen up to 120 per call
        # For more data, make multiple calls
        total_len = min(days * 2, 300)  # max 300 records

        all_records = []
        for start in range(0, total_len, 120):
            datalen = min(120, total_len - start)
            url = (
                f'https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/'
                f'CN_MarketData.getKLineData?symbol={symbol}&scale=240&ma=no&datalen={datalen}'
            )
            try:
                req = urllib.request.Request(url, headers=SINA_HEADERS)
                resp = urllib.request.urlopen(req, timeout=15)
                data = json.loads(resp.read().decode())
                if not data:
                    break
                all_records.extend(data)
                if len(data) < datalen:
                    break  # No more data
            except Exception as e:
                logger.warning(f"新浪历史K线失败 {stock_code} offset={start}: {e}")
                break

        if not all_records:
            return None

        df = pd.DataFrame(all_records)
        df['date'] = pd.to_datetime(df['day'])
        df['stock_code'] = stock_code
        df['open'] = pd.to_numeric(df['open'], errors='coerce')
        df['high'] = pd.to_numeric(df['high'], errors='coerce')
        df['low'] = pd.to_numeric(df['low'], errors='coerce')
        df['close'] = pd.to_numeric(df['close'], errors='coerce')
        df['volume'] = pd.to_numeric(df['volume'], errors='coerce')

        # Sina historical doesn't have amount/turnover directly
        # Compute change_pct
        df['change_pct'] = df['close'].pct_change() * 100

        # Drop original columns
        df = df.drop(columns=['day', 'ma5', 'ma10', 'ma20'], errors='ignore')
        df = df[['date', 'stock_code', 'open', 'high', 'low', 'close', 'volume', 'change_pct']]

        return df

    # ==================== 股票池 ====================

    def get_stock_pool(self, date=None, refresh=False):
        """
        获取A股股票池

        优先从本地 stock_pool.json 加载，refresh=True 则从新浪实时行情更新。

        返回: DataFrame with columns: code, name, industry_name, exchange
        """
        if not refresh and self._stock_pool is not None:
            return self._stock_pool

        pool_path = os.path.join(DATA_DIR, 'stock_pool.json')

        try:
            if os.path.exists(pool_path):
                with open(pool_path, 'r', encoding='utf-8') as f:
                    records = json.load(f)
                df = pd.DataFrame(records)

                # Normalize column names
                if 'code_name' in df.columns and 'name' not in df.columns:
                    df['name'] = df['code_name']
                if 'code_name' in df.columns:
                    df = df.drop(columns=['code_name'])

                from market_filter import is_allowed
                if 'name' in df.columns:
                    mask = df.apply(lambda row: is_allowed(row['code'], row.get('name', '')), axis=1)
                else:
                    mask = df['code'].apply(lambda x: is_allowed(x))
                df = df[mask].copy()

                self._stock_pool = df
                logger.info(f"股票池: {len(df)} 只 (from cache)")
                return df
        except Exception as e:
            logger.warning(f"加载股票池缓存失败: {e}")

        # Fallback: build from realtime quotes
        return pd.DataFrame()

    def update_stock_pool(self):
        """
        Update stock pool from Sina realtime quotes.
        Saves to data/stock_pool.json.
        """
        quotes = self.get_realtime_quotes()
        if quotes.empty:
            logger.error("更新股票池失败: 无实时数据")
            return

        # Filter allowed stocks
        mask = quotes['code'].apply(lambda x: any(
            x.startswith(p) for p in ALLOWED_PREFIXES
        ))
        quotes = quotes[mask].copy()

        # Exclude ST
        quotes = quotes[~quotes['name'].str.contains('ST', case=False, na=False)]

        # Determine exchange
        quotes['exchange'] = quotes['code'].apply(
            lambda x: 'SH' if x.startswith('6') else 'SZ'
        )

        # Load industry info from existing pool
        old_pool_path = os.path.join(DATA_DIR, 'stock_pool.json')
        industry_map = {}
        if os.path.exists(old_pool_path):
            with open(old_pool_path, 'r', encoding='utf-8') as f:
                old_records = json.load(f)
            for r in old_records:
                industry_map[r['code']] = r.get('industry_name', '')

        # Build new pool records
        records = []
        for _, row in quotes.iterrows():
            record = {
                'code': row['code'],
                'code_name': row['name'],
                'industry_code': industry_map.get(row['code'], ''),
                'industry_name': industry_map.get(row['code'], ''),
                'exchange': row['exchange'],
            }
            records.append(record)

        # Save
        manifest_path = os.path.join(DATA_DIR, 'stock_pool.json')
        with open(manifest_path, 'w', encoding='utf-8') as f:
            json.dump(records, f, ensure_ascii=False, indent=2)

        df = pd.DataFrame(records)
        df['name'] = df['code_name']
        self._stock_pool = df
        logger.info(f"股票池已更新: {len(records)} 只 -> {manifest_path}")

    # ==================== 大盘指数 ====================

    def get_index_quotes(self):
        """
        获取主要指数实时行情

        返回: DataFrame with code, name, close, change_pct
        """
        indices = {
            'sh000001': '上证指数',
            'sh000300': '沪深300',
            'sh000016': '上证50',
            'sh000905': '中证500',
            'sz399001': '深证成指',
            'sz399006': '创业板指',
        }

        data = []
        for code, name in indices.items():
            try:
                url = f'https://hq.sinajs.cn/list={code}'
                req = urllib.request.Request(url, headers=SINA_HEADERS)
                resp = urllib.request.urlopen(req, timeout=10)
                text = resp.read().decode('gbk', errors='replace')

                m = re.match(r'var hq_str_\w+="(.*)"', text)
                if not m:
                    continue
                parts = m.group(1).split(',')
                if len(parts) < 8:
                    continue

                # Index format: name, open, pre_close, close, high, low, volume, amount
                pre_close = float(parts[2]) if parts[2] else 0
                close = float(parts[3]) if parts[3] else 0
                change_pct = 0
                if pre_close > 0:
                    change_pct = round((close - pre_close) / pre_close * 100, 2)

                data.append({
                    'code': code[2:],
                    'name': name,
                    'close': close,
                    'change_pct': change_pct,
                })
            except Exception as e:
                logger.warning(f"指数 {code} 获取失败: {e}")

        return pd.DataFrame(data)

    # ==================== 补充数据（腾讯 API） ====================

    def get_turnover_rate(self, stock_code):
        """
        获取换手率等补充数据（腾讯 API）

        返回: dict with turnover, amplitude, etc.
        """
        exchange = 'sh' if stock_code.startswith('6') else 'sz'
        code = exchange + stock_code

        try:
            url = f'https://qt.gtimg.cn/q={code}'
            req = urllib.request.Request(url, headers=SINA_HEADERS)
            resp = urllib.request.urlopen(req, timeout=10)
            text = resp.read().decode('gbk', errors='replace')

            m = re.match(r'v_\w+="(.*)"', text)
            if not m:
                return {}

            parts = m.group(1).split('~')
            if len(parts) < 40:
                return {}

            # 腾讯字段映射 (索引):
            # 1:name, 3:close, 4:open, 5:pre_close, 6:volume, 7:buy_vol, 8:sell_vol
            # 31:time, 32:change, 33:change_pct, 34:high, 35:low
            # 36:price/vol/amount, 37:vol, 38:amount
            # 39:turnover%, 40:pe
            return {
                'name': parts[1],
                'close': float(parts[3]),
                'turnover': float(parts[38]) if parts[38] else 0,  # 换手率
                'pe': float(parts[40]) if parts[40] else 0,
                'change_pct': float(parts[33]) if parts[33] else 0,
            }
        except Exception as e:
            logger.warning(f"腾讯行情失败 {stock_code}: {e}")
            return {}

    # ==================== 批量 K 线更新 ====================

    def update_kline_cache(self, stock_codes=None, days=120):
        """
        批量更新本地 K 线缓存

        参数:
            stock_codes: 股票代码列表，None=全部
            days: 获取最近 N 天

        返回: 成功更新的股票数量
        """
        if stock_codes is None:
            pool = self.get_stock_pool()
            if pool.empty:
                return 0
            stock_codes = pool['code'].tolist()

        updated = 0
        for i, code in enumerate(stock_codes):
            try:
                df = self.get_daily_kline(code, days)
                if df.empty:
                    continue

                # Save to local CSV
                csv_path = os.path.join(KLINEDIR, f'{code}.csv')
                df.to_csv(csv_path, index=False)
                updated += 1

                if (i + 1) % 100 == 0:
                    logger.info(f"K线更新进度: {i + 1}/{len(stock_codes)}")

                # Rate limit: 100ms between requests
                time.sleep(0.1)

            except Exception as e:
                logger.warning(f"K线更新失败 {code}: {e}")

        logger.info(f"K线缓存更新完成: {updated}/{len(stock_codes)}")
        return updated


# ==================== 兼容层 ====================

class BaoStockFetcher(SinaFetcher):
    """
    BaoStockFetcher 兼容层 - 完全继承 SinaFetcher

    现有代码无需修改，直接 import 即可。
    如果 BaoStock 可用则优先用 BaoStock，否则自动 fallback 到新浪。
    """

    def __init__(self):
        super().__init__()
        self._bs_available = False
        self._logged_in = False

        # Try to import baostock
        try:
            import baostock as bs
            lg = bs.login()
            if lg.error_code == '0':
                self._bs_available = True
                self._logged_in = True
                bs.logout()
                self._logged_in = False
            else:
                logger.warning(f"BaoStock 登录失败: {lg.error_msg}")
        except ImportError:
            pass
        except Exception as e:
            logger.warning(f"BaoStock 不可用: {e}")

    def login(self):
        """Login to BaoStock (if available)"""
        if not self._bs_available:
            return
        try:
            import baostock as bs
            lg = bs.login()
            if lg.error_code == '0':
                self._logged_in = True
        except Exception:
            pass

    def logout(self):
        """Logout from BaoStock"""
        if self._logged_in and self._bs_available:
            try:
                import baostock as bs
                bs.logout()
            except Exception:
                pass
            self._logged_in = False

    def get_stock_pool(self, date=None, refresh=False):
        """优先用 BaoStock，fallback 到新浪"""
        if self._bs_available and refresh:
            return self._get_bs_stock_pool(date)
        return super().get_stock_pool(date, refresh)

    def get_daily_kline(self, stock_code, days=120):
        """优先用新浪+本地缓存，BaoStock 作为补充"""
        return super().get_daily_kline(stock_code, days)

    def _get_bs_stock_pool(self, date=None):
        """Get stock pool from BaoStock"""
        if date is None:
            date = datetime.now().strftime('%Y-%m-%d')
        try:
            import baostock as bs
            self.login()
            rs = bs.query_all_stock(day=date)
            if rs.error_code != '0':
                return pd.DataFrame()
            all_stocks = []
            while rs.error_code == '0' and rs.next():
                all_stocks.append(rs.get_row_data())
            if not all_stocks:
                return pd.DataFrame()
            df = pd.DataFrame(all_stocks, columns=rs.fields)
            mask = df['code'].apply(lambda x: any(
                x.startswith(p) for p in ALLOWED_PREFIXES
            ))
            df = df[mask].copy()
            if 'code_name' in df.columns:
                df = df[~df['code_name'].str.contains('ST', case=False, na=False)]
            df['code'] = df['code'].str.replace('sh.', '').str.replace('sz.', '')
            df['name'] = df['code_name']
            self.logout()
            return df
        except Exception:
            return pd.DataFrame()

    def get_stock_name(self, stock_code):
        """Get stock name"""
        pool = self.get_stock_pool()
        if pool is None or pool.empty:
            return ''
        row = pool[pool['code'] == stock_code]
        if row.empty:
            return ''
        return row.iloc[0]['name']

    def get_current_price(self, stock_code):
        """Get latest close price"""
        df = self.get_daily_kline(stock_code, days=5)
        if df.empty:
            return None
        return float(df.iloc[-1]['close'])

    def get_market_benchmark(self, index_code='sh.000001', days=30):
        """Get market benchmark index"""
        return self.get_index_quotes()

    def save_stock_pool_manifest(self, stock_pool=None):
        """Save stock pool manifest"""
        if stock_pool is None:
            stock_pool = self.get_stock_pool()
        if stock_pool is None or stock_pool.empty:
            return
        manifest_path = os.path.join(DATA_DIR, 'stock_pool.json')
        records = stock_pool[['code', 'name']].to_dict('records')
        with open(manifest_path, 'w', encoding='utf-8') as f:
            json.dump(records, f, ensure_ascii=False, indent=2)
        logger.info(f"股票池清单: {len(records)} 只 -> {manifest_path}")

    def get_top_stocks_by_amount(self, top_n=100, date=None):
        """Get top stocks by trading amount"""
        quotes = self.get_realtime_quotes()
        if quotes.empty:
            return pd.DataFrame()
        return quotes.nlargest(top_n, 'amount')[['code', 'name', 'amount', 'close', 'change_pct']].reset_index(drop=True)
