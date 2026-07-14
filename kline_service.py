"""
统一 K 线访问层 — 日/周/月读本地 CSV，分钟按需拉取+缓存
"""
import json
import logging
import os
from datetime import datetime, timedelta
from typing import Dict, List, Optional

import pandas as pd

logger = logging.getLogger(__name__)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
KLINEDIR = os.path.join(BASE_DIR, 'data', 'kline')


def _load_settings():
    from market_data import get_data_config
    return get_data_config()


def _minute_cache_path(code: str, date: str) -> str:
    cfg = _load_settings()
    cache_dir = cfg.get('minute_cache_dir', 'data/minute_kline')
    if not os.path.isabs(cache_dir):
        cache_dir = os.path.join(BASE_DIR, cache_dir)
    stock_dir = os.path.join(cache_dir, code)
    os.makedirs(stock_dir, exist_ok=True)
    return os.path.join(stock_dir, f'{date}_1min.json')


def _read_daily_csv(code: str) -> pd.DataFrame:
    path = os.path.join(KLINEDIR, f'{code}.csv')
    if not os.path.exists(path):
        return pd.DataFrame()
    try:
        df = pd.read_csv(path)
        if df.empty:
            return pd.DataFrame()
        df['date'] = pd.to_datetime(df['date'])
        for col in ['open', 'high', 'low', 'close', 'volume']:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors='coerce')
        return df.sort_values('date').drop_duplicates('date', keep='last')
    except Exception as e:
        logger.warning(f'读取K线失败 {code}: {e}')
        return pd.DataFrame()


def _ensure_daily(code: str, min_bars: int = 60) -> pd.DataFrame:
    df = _read_daily_csv(code)
    if len(df) >= min_bars:
        return df
    try:
        from update_kline import _fetch_kline_baostock
        remote = _fetch_kline_baostock(code, 120)
        if remote is not None and not remote.empty:
            if 'date' not in remote.columns and 'day' in remote.columns:
                remote['date'] = pd.to_datetime(remote['day'])
            combined = pd.concat([df, remote], ignore_index=True)
            combined['date'] = pd.to_datetime(combined['date'])
            combined = combined.drop_duplicates('date', keep='last').sort_values('date')
            os.makedirs(KLINEDIR, exist_ok=True)
            combined.to_csv(os.path.join(KLINEDIR, f'{code}.csv'), index=False)
            return combined
    except Exception as e:
        logger.debug(f'补K线失败 {code}: {e}')
    return df


def _to_chart_bars(df: pd.DataFrame, time_col: str = 'date') -> List[Dict]:
    bars = []
    for _, row in df.iterrows():
        ts = row[time_col]
        if hasattr(ts, 'strftime'):
            if time_col == 'datetime':
                t = ts.strftime('%Y-%m-%d %H:%M')
            else:
                t = ts.strftime('%Y-%m-%d')
        else:
            t = str(ts)[:16]
        bars.append({
            't': t,
            'o': float(row.get('open', 0) or 0),
            'h': float(row.get('high', 0) or 0),
            'l': float(row.get('low', 0) or 0),
            'c': float(row.get('close', 0) or 0),
            'v': int(float(row.get('volume', 0) or 0)),
        })
    return bars


def get_daily(code: str, count: int = 120) -> List[Dict]:
    df = _ensure_daily(code)
    if df.empty:
        return []
    return _to_chart_bars(df.tail(count))


def get_weekly(code: str, count: int = 80) -> List[Dict]:
    df = _ensure_daily(code, min_bars=20)
    if df.empty:
        return []
    w = df.set_index('date').resample('W').agg({
        'open': 'first', 'high': 'max', 'low': 'min', 'close': 'last', 'volume': 'sum',
    }).dropna(subset=['close'])
    w = w.reset_index()
    return _to_chart_bars(w.tail(count))


def get_monthly(code: str, count: int = 60) -> List[Dict]:
    df = _ensure_daily(code, min_bars=20)
    if df.empty:
        return []
    m = df.set_index('date').resample('M').agg({
        'open': 'first', 'high': 'max', 'low': 'min', 'close': 'last', 'volume': 'sum',
    }).dropna(subset=['close'])
    m = m.reset_index()
    return _to_chart_bars(m.tail(count))


def _cache_valid(path: str, date: str) -> bool:
    if not os.path.exists(path):
        return False
    if date != datetime.now().strftime('%Y-%m-%d'):
        return True
    ttl = int(_load_settings().get('minute_cache_ttl_intraday', 300))
    return (datetime.now().timestamp() - os.path.getmtime(path)) < ttl


def _fetch_intraday_remote(code: str, date: str) -> pd.DataFrame:
    # sina via minute_kline module
    try:
        from minute_kline import get_minute_kline, code_to_sina_format
        prefix = 'sh' if code.startswith('6') else 'sz'
        sina_code = f'{prefix}.{code}'
        df = get_minute_kline(sina_code, period='1', use_cache=False)
        if df is not None and not df.empty:
            df = df.rename(columns={'day': 'datetime'})
            if date:
                df['datetime'] = pd.to_datetime(df['datetime'])
                df = df[df['datetime'].dt.strftime('%Y-%m-%d') == date]
            return df
    except Exception as e:
        logger.debug(f'新浪分钟 fallback 失败: {e}')
    return pd.DataFrame()


def get_intraday(code: str, date: str = None) -> List[Dict]:
    """按需获取分钟 K 线，带本地缓存"""
    if date in (None, '', 'today'):
        date = datetime.now().strftime('%Y-%m-%d')

    cache_path = _minute_cache_path(code, date)
    if _cache_valid(cache_path, date):
        try:
            with open(cache_path, 'r') as f:
                return json.load(f).get('data', [])
        except Exception:
            pass

    df = _fetch_intraday_remote(code, date)
    if df.empty:
        return []

    if 'datetime' not in df.columns:
        df['datetime'] = pd.to_datetime(df.index)
    bars = _to_chart_bars(df, 'datetime')

    try:
        with open(cache_path, 'w') as f:
            json.dump({'code': code, 'date': date, 'data': bars, 'updated': datetime.now().isoformat()}, f)
    except Exception:
        pass
    return bars


def get_kline(code: str, frequency: str = '1d', count: int = 120) -> List[Dict]:
    freq = frequency.lower()
    if freq in ('1d', 'd', 'day', 'daily'):
        return get_daily(code, count)
    if freq in ('1w', 'w', 'week', 'weekly'):
        return get_weekly(code, count)
    if freq in ('1m', 'month', 'monthly'):
        return get_monthly(code, count)
    if freq in ('intraday', 'today', '分时'):
        return get_intraday(code)
    return get_daily(code, count)
