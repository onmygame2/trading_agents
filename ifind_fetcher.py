"""
iFinD HTTP API 数据获取模块

认证: refresh_token (环境变量 IFIND_REFRESH_TOKEN) -> access_token (本地缓存)
API: https://quantapi.51ifind.com/api/v1/

用法:
    from ifind_fetcher import IFindFetcher
    fetcher = IFindFetcher()
    quotes = fetcher.get_realtime_quotes(['600519', '000001'])
"""

import json
import logging
import os
import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Union

import pandas as pd
import requests

logger = logging.getLogger(__name__)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, 'data')
KLINEDIR = os.path.join(DATA_DIR, 'kline')
os.makedirs(DATA_DIR, exist_ok=True)

DEFAULT_BASE_URL = 'https://quantapi.51ifind.com/api/v1'
DEFAULT_REALTIME_INDICATORS = (
    'open,high,low,latest,preClose,changeRatio,volume,amount,turnoverRatio'
)
BATCH_SIZE = 50
TOKEN_CACHE_DAYS = 6
QUOTA_FLAG_PATH = os.path.join(DATA_DIR, 'ifind_quota_exceeded.json')


def is_ifind_quota_exceeded() -> bool:
    return os.path.exists(QUOTA_FLAG_PATH)


def mark_ifind_quota_exceeded(reason: str = ''):
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(QUOTA_FLAG_PATH, 'w') as f:
        json.dump({'time': datetime.now().isoformat(), 'reason': reason}, f)
    logger.warning('iFind 配额已用尽，历史K线将降级新浪')


def _to_ifind_code(code: str) -> str:
    """600000 -> 600000.SH, 000001 -> 000001.SZ"""
    code = str(code).replace('.SH', '').replace('.SZ', '').replace('sh', '').replace('sz', '')
    if code.startswith('6'):
        return f'{code}.SH'
    return f'{code}.SZ'


def _from_ifind_code(thscode: str) -> str:
    """600000.SH -> 600000"""
    return thscode.split('.')[0] if thscode else ''


class IFindFetcher:
    """iFinD HTTP API 数据获取器"""

    def __init__(self, refresh_token: str = None, config: dict = None):
        config = config or {}
        self.refresh_token = refresh_token or os.environ.get('IFIND_REFRESH_TOKEN', '')
        self.base_url = config.get('base_url', DEFAULT_BASE_URL).rstrip('/')
        self.token_cache_path = config.get(
            'token_cache',
            os.path.join(DATA_DIR, 'ifind_token.json'),
        )
        if not os.path.isabs(self.token_cache_path):
            self.token_cache_path = os.path.join(BASE_DIR, self.token_cache_path)
        self.usage_path = os.path.join(DATA_DIR, 'ifind_usage.json')
        self.realtime_indicators = config.get(
            'realtime_indicators', DEFAULT_REALTIME_INDICATORS,
        )
        self.history_indicators = config.get(
            'history_indicators', 'open,high,low,close,volume,amount,changeRatio',
        )
        self.edb_north_indicators = config.get('edb_north_indicators', '')
        self.stock_universe_search = config.get('stock_universe_search', '全部A股')
        self._access_token = None
        self._token_expires_at = 0

    @property
    def available(self) -> bool:
        return bool(self.refresh_token)

    # ==================== Token ====================

    def get_access_token(self, force_refresh: bool = False) -> str:
        if not self.refresh_token:
            raise ValueError('IFIND_REFRESH_TOKEN 未配置')

        if not force_refresh:
            cached = self._load_token_cache()
            if cached:
                return cached

        url = f'{self.base_url}/get_access_token'
        headers = {
            'Content-Type': 'application/json',
            'refresh_token': self.refresh_token,
        }
        resp = requests.post(url, headers=headers, timeout=30)
        resp.raise_for_status()
        data = resp.json()

        if data.get('errorcode', -1) != 0:
            raise RuntimeError(f"iFind token 获取失败: {data.get('errmsg', data)}")

        token = data['data']['access_token']
        self._access_token = token
        self._token_expires_at = time.time() + TOKEN_CACHE_DAYS * 86400
        self._save_token_cache(token)
        logger.info('iFind access_token 已刷新')
        return token

    def _load_token_cache(self) -> Optional[str]:
        try:
            if os.path.exists(self.token_cache_path):
                with open(self.token_cache_path, 'r') as f:
                    info = json.load(f)
                expires = info.get('expires_at', 0)
                if time.time() < expires - 86400:
                    self._access_token = info['access_token']
                    self._token_expires_at = expires
                    return self._access_token
        except Exception as e:
            logger.debug(f'读取 token 缓存失败: {e}')
        return None

    def _save_token_cache(self, token: str):
        os.makedirs(os.path.dirname(self.token_cache_path), exist_ok=True)
        with open(self.token_cache_path, 'w') as f:
            json.dump({
                'access_token': token,
                'expires_at': self._token_expires_at,
                'updated_at': datetime.now().isoformat(),
            }, f)

    def _headers(self) -> dict:
        token = self.get_access_token()
        return {
            'Content-Type': 'application/json',
            'access_token': token,
        }

    def _record_usage(self, data_vol: int):
        if not data_vol:
            return
        today = datetime.now().strftime('%Y-%m-%d')
        usage = {}
        try:
            if os.path.exists(self.usage_path):
                with open(self.usage_path, 'r') as f:
                    usage = json.load(f)
        except Exception:
            pass
        usage[today] = usage.get(today, 0) + int(data_vol)
        with open(self.usage_path, 'w') as f:
            json.dump(usage, f, indent=2)

    def _post(self, endpoint: str, payload: dict) -> dict:
        url = f'{self.base_url}/{endpoint}'
        resp = requests.post(url, headers=self._headers(), json=payload, timeout=60)
        resp.raise_for_status()
        data = resp.json()
        self._record_usage(data.get('dataVol', 0))
        if data.get('errorcode', -1) != 0:
            errmsg = data.get('errmsg', str(data))
            if 'exceeded' in str(errmsg).lower():
                mark_ifind_quota_exceeded(str(errmsg))
            raise RuntimeError(f"iFind API {endpoint} 错误: {errmsg}")
        return data

    def _parse_tables(self, data: dict) -> List[dict]:
        """解析 tables 结构为扁平记录列表"""
        records = []
        for table in data.get('tables', []):
            thscode = table.get('thscode', '')
            code = _from_ifind_code(thscode)
            tbl = table.get('table', {})
            times = table.get('time', [])

            if times:
                for i, t in enumerate(times):
                    row = {'code': code, 'thscode': thscode, 'time': t}
                    for k, vals in tbl.items():
                        if isinstance(vals, list) and i < len(vals):
                            row[k] = vals[i]
                    records.append(row)
            else:
                row = {'code': code, 'thscode': thscode}
                for k, vals in tbl.items():
                    if isinstance(vals, list) and vals:
                        row[k] = vals[-1] if len(vals) == 1 else vals
                    else:
                        row[k] = vals
                records.append(row)
        return records

    # ==================== 实时行情 ====================

    def get_realtime_quotes(self, stock_codes=None) -> pd.DataFrame:
        if stock_codes is None:
            from sina_fetcher import SinaFetcher
            pool = SinaFetcher().get_stock_pool()
            if pool is None or pool.empty:
                return pd.DataFrame()
            stock_codes = pool['code'].tolist()

        if not stock_codes:
            return pd.DataFrame()

        all_rows = []
        codes = list(stock_codes)
        for i in range(0, len(codes), BATCH_SIZE):
            batch = codes[i:i + BATCH_SIZE]
            ifind_codes = ','.join(_to_ifind_code(c) for c in batch)
            try:
                data = self._post('real_time_quotation', {
                    'codes': ifind_codes,
                    'indicators': self.realtime_indicators,
                })
                for rec in self._parse_tables(data):
                    all_rows.append(self._normalize_realtime_row(rec))
            except Exception as e:
                logger.warning(f'iFind 实时行情 batch {i // BATCH_SIZE} 失败: {e}')

        if not all_rows:
            return pd.DataFrame()
        df = pd.DataFrame(all_rows)
        logger.info(f'iFind 实时行情: {len(df)} 只')
        return df

    def _normalize_realtime_row(self, rec: dict) -> dict:
        latest = float(rec.get('latest') or rec.get('close') or 0)
        pre_close = float(rec.get('preClose') or 0)
        change_pct = rec.get('changeRatio')
        if change_pct is None and pre_close > 0:
            change_pct = round((latest - pre_close) / pre_close * 100, 2)
        return {
            'code': rec.get('code', ''),
            'name': rec.get('name', ''),
            'open': float(rec.get('open') or 0),
            'pre_close': pre_close,
            'close': latest,
            'high': float(rec.get('high') or 0),
            'low': float(rec.get('low') or 0),
            'volume': float(rec.get('volume') or 0),
            'amount': float(rec.get('amount') or 0),
            'change_pct': round(float(change_pct or 0), 2),
            'date': datetime.now().strftime('%Y-%m-%d'),
            'time': datetime.now().strftime('%H:%M:%S'),
        }

    def get_realtime_quote(self, stock_code: str) -> Optional[dict]:
        df = self.get_realtime_quotes([stock_code])
        if df.empty:
            return None
        row = df[df['code'] == str(stock_code).replace('.SH', '').replace('.SZ', '')]
        if row.empty:
            return None
        return row.iloc[0].to_dict()

    def get_market_summary(self) -> dict:
        from sina_fetcher import SinaFetcher
        quotes = self.get_realtime_quotes()
        if quotes.empty:
            return SinaFetcher().get_market_summary()
        up = len(quotes[quotes['change_pct'] > 0])
        down = len(quotes[quotes['change_pct'] < 0])
        flat = len(quotes[quotes['change_pct'] == 0])
        return {
            'up': up,
            'down': down,
            'flat': flat,
            'up_pct': round(up / len(quotes) * 100, 1) if len(quotes) else 0,
            'limit_up': len(quotes[quotes['change_pct'] >= 9.8]),
            'limit_down': len(quotes[quotes['change_pct'] <= -9.8]),
            'total_amount': round(quotes['amount'].sum() / 1e8, 2),
            'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        }

    # ==================== 历史K线 ====================

    def get_daily_kline(self, stock_code: str, days: int = 120) -> pd.DataFrame:
        end = datetime.now().strftime('%Y-%m-%d')
        start = (datetime.now() - timedelta(days=int(days * 1.6))).strftime('%Y-%m-%d')
        ifind_code = _to_ifind_code(stock_code)

        try:
            data = self._post('cmd_history_quotation', {
                'codes': ifind_code,
                'indicators': self.history_indicators,
                'startdate': start,
                'enddate': end,
                'functionpara': {'Fill': 'Blank', 'CPS': '3'},
            })
        except Exception as e:
            logger.warning(f'iFind 历史K线失败 {stock_code}: {e}')
            return pd.DataFrame()

        rows = []
        for rec in self._parse_tables(data):
            t = rec.get('time', '')
            close_val = rec.get('close') or rec.get('latest')
            if not t or close_val is None:
                continue
            rows.append({
                'date': pd.to_datetime(str(t)[:10]),
                'stock_code': stock_code,
                'open': float(rec.get('open') or 0),
                'high': float(rec.get('high') or 0),
                'low': float(rec.get('low') or 0),
                'close': float(close_val),
                'volume': float(rec.get('volume') or 0),
                'amount': float(rec.get('amount') or 0),
                'change_pct': float(rec.get('changeRatio') or 0),
            })

        if not rows:
            return pd.DataFrame()
        df = pd.DataFrame(rows).sort_values('date').drop_duplicates('date', keep='last')
        return df.tail(days)

    # ==================== 指数 ====================

    def get_index_quotes(self) -> pd.DataFrame:
        indices = {
            '000001.SH': '上证指数',
            '399001.SZ': '深证成指',
            '399006.SZ': '创业板指',
            '000300.SH': '沪深300',
        }
        try:
            data = self._post('real_time_quotation', {
                'codes': ','.join(indices.keys()),
                'indicators': 'latest,preClose,changeRatio',
            })
            rows = []
            for rec in self._parse_tables(data):
                thscode = rec.get('thscode', '')
                latest = float(rec.get('latest') or 0)
                pre = float(rec.get('preClose') or 0)
                cp = rec.get('changeRatio')
                if cp is None and pre > 0:
                    cp = round((latest - pre) / pre * 100, 2)
                rows.append({
                    'code': _from_ifind_code(thscode),
                    'name': indices.get(thscode, thscode),
                    'close': latest,
                    'change_pct': round(float(cp or 0), 2),
                })
            return pd.DataFrame(rows)
        except Exception as e:
            logger.warning(f'iFind 指数行情失败: {e}')
            from sina_fetcher import SinaFetcher
            return SinaFetcher().get_index_quotes()

    # ==================== EDB 北向 ====================

    def get_north_flow_edb(self, days: int = 5) -> List[Dict]:
        if not self.edb_north_indicators:
            return []
        end = datetime.now().strftime('%Y-%m-%d')
        start = (datetime.now() - timedelta(days=days * 3)).strftime('%Y-%m-%d')
        try:
            data = self._post('edb_service', {
                'indicators': self.edb_north_indicators,
                'startdate': start,
                'enddate': end,
            })
            results = []
            for table in data.get('tables', []):
                times = table.get('time', [])
                tbl = table.get('table', {})
                for indicator, vals in tbl.items():
                    if not isinstance(vals, list):
                        continue
                    for i, val in enumerate(vals):
                        if i < len(times):
                            results.append({
                                'date': str(times[i])[:10],
                                'net_flow': float(val or 0),
                                'indicator': indicator,
                            })
            results.sort(key=lambda x: x['date'], reverse=True)
            seen = set()
            unique = []
            for r in results:
                if r['date'] not in seen:
                    seen.add(r['date'])
                    unique.append(r)
            return unique[:days]
        except Exception as e:
            logger.warning(f'iFind 北向 EDB 失败: {e}')
            return []

    # ==================== 日内增强 (P2) ====================

    def get_intraday_snapshot(self, stock_code: str, date: str = None) -> pd.DataFrame:
        """日内快照 - 精确 high/low/分时"""
        date = date or datetime.now().strftime('%Y-%m-%d')
        ifind_code = _to_ifind_code(stock_code)
        try:
            data = self._post('snap_shot', {
                'codes': ifind_code,
                'indicators': 'open,high,low,latest,volume,amount',
                'starttime': f'{date} 09:30:00',
                'endtime': f'{date} 15:00:00',
            })
            rows = self._parse_tables(data)
            return pd.DataFrame(rows) if rows else pd.DataFrame()
        except Exception as e:
            logger.debug(f'iFind snap_shot 失败 {stock_code}: {e}')
            return pd.DataFrame()

    def get_afternoon_volume_ratio(self, stock_code: str) -> Optional[float]:
        """14:00-14:30 分钟放量比 (相对全天)"""
        today = datetime.now().strftime('%Y-%m-%d')
        ifind_code = _to_ifind_code(stock_code)
        try:
            data = self._post('high_frequency', {
                'codes': ifind_code,
                'indicators': 'volume',
                'starttime': f'{today} 09:30:00',
                'endtime': f'{today} 15:00:00',
                'functionpara': {'Interval': '1'},
            })
            rows = self._parse_tables(data)
            if not rows:
                return None
            total_vol = sum(float(r.get('volume') or 0) for r in rows)
            afternoon_vol = sum(
                float(r.get('volume') or 0) for r in rows
                if str(r.get('time', ''))[11:16] >= '14:00'
            )
            if total_vol <= 0:
                return None
            return round(afternoon_vol / total_vol, 3)
        except Exception as e:
            logger.debug(f'iFind high_frequency 失败 {stock_code}: {e}')
            return None

    def get_intraday_metrics(self, stock_code: str) -> dict:
        """尾盘策略增强指标"""
        metrics = {}
        snap = self.get_intraday_snapshot(stock_code)
        if not snap.empty:
            if 'high' in snap.columns:
                metrics['today_high'] = float(snap['high'].max())
            if 'low' in snap.columns:
                metrics['today_low'] = float(snap['low'].min())
        ratio = self.get_afternoon_volume_ratio(stock_code)
        if ratio is not None:
            metrics['afternoon_vol_ratio'] = ratio
        return metrics

    # ==================== 股票池 ====================

    def get_all_a_share_codes(self) -> List[Dict]:
        """
        获取全部 A 股列表 (智能选股)
        返回 [{code, name, thscode}, ...]
        """
        try:
            data = self._post('smart_stock_picking', {
                'searchstring': self.stock_universe_search,
                'searchtype': 'stock',
            })
            records = []
            for table in data.get('tables', []):
                tbl = table.get('table', {})
                codes = tbl.get('thscode') or tbl.get('THSCODE') or []
                names = tbl.get('stockName') or tbl.get('stockname') or tbl.get('name') or []
                if isinstance(codes, str):
                    codes = [codes]
                if isinstance(names, str):
                    names = [names]
                for i, thscode in enumerate(codes):
                    code = _from_ifind_code(str(thscode))
                    name = names[i] if i < len(names) else ''
                    if code:
                        records.append({'code': code, 'name': name, 'thscode': thscode})
            if records:
                logger.info(f'iFind 智能选股: {len(records)} 只')
                return records
        except Exception as e:
            logger.warning(f'iFind 智能选股失败: {e}')
        return []

    def get_minute_kline(self, stock_code: str, date: str = None, interval: str = '1') -> pd.DataFrame:
        """指定日期的分钟 K 线 (high_frequency)"""
        date = date or datetime.now().strftime('%Y-%m-%d')
        ifind_code = _to_ifind_code(stock_code)
        try:
            data = self._post('high_frequency', {
                'codes': ifind_code,
                'indicators': 'open,high,low,close,volume,amount',
                'starttime': f'{date} 09:30:00',
                'endtime': f'{date} 15:00:00',
                'functionpara': {'Interval': str(interval)},
            })
            rows = []
            for rec in self._parse_tables(data):
                t = rec.get('time', '')
                if not t:
                    continue
                rows.append({
                    'datetime': str(t),
                    'open': float(rec.get('open') or 0),
                    'high': float(rec.get('high') or 0),
                    'low': float(rec.get('low') or 0),
                    'close': float(rec.get('close') or rec.get('latest') or 0),
                    'volume': float(rec.get('volume') or 0),
                    'amount': float(rec.get('amount') or 0),
                })
            if not rows:
                return pd.DataFrame()
            df = pd.DataFrame(rows)
            df['datetime'] = pd.to_datetime(df['datetime'])
            return df.sort_values('datetime')
        except Exception as e:
            logger.warning(f'iFind 分钟K线失败 {stock_code} {date}: {e}')
            return pd.DataFrame()
