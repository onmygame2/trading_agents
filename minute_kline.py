"""
分钟级K线数据模块 - 获取A股分钟级K线数据
数据源: 
  主: 新浪API (akshare stock_zh_a_minute) - 直连可用，无需代理
  备: 东方财富 trends2 API - 新浪失败时自动降级
支持: 1分钟/5分钟/15分钟/30分钟/60分钟
"""
import os
import json
import time
import urllib.request
import urllib.parse
from datetime import datetime, timedelta
from typing import Dict, Optional, List

# 使用 venv_akshare 的 akshare
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'venv_akshare', 'lib', 'python3.11', 'site-packages'))

import akshare as ak
import pandas as pd


DATA_DIR = os.path.join(os.path.dirname(__file__), 'data', 'minute_kline')
os.makedirs(DATA_DIR, exist_ok=True)


def code_to_sina_format(code: str) -> str:
    """Convert sh.600519 / sz.000001 to sina format: sh600519 / sz000001"""
    if '.' in code:
        return code.replace('.', '')
    # If already sina format
    return code


def code_to_eastmoney_code(code: str) -> tuple:
    """
    Convert stock code to East Money format.
    Returns (secid, prefix) e.g. ('1.600519', 'sh')
    """
    raw = code.replace('sh.', '').replace('sz.', '').replace('sh', '').replace('sz', '')
    # Strip any remaining dots
    raw = raw.replace('.', '')
    if raw[0] in ('6', '9'):
        return ('1.' + raw, 'sh')
    return ('0.' + raw, 'sz')


def code_to_eastmoney_url(code: str) -> str:
    """Convert stock code to East Money K-line URL"""
    code = code.replace('sh.', '').replace('sz.', '')
    prefix = 'sh' if code[0] in ('6', '9') else 'sz'
    return f'https://quote.eastmoney.com/{prefix}{code}.html'


def fetch_eastmoney_minute(secid: str, period: str = '5') -> Optional[pd.DataFrame]:
    """
    从东方财富trends2 API获取分钟K线（备用数据源）
    
    Args:
        secid: East Money secid like '1.600519'
        period: '1', '5', '15', '30', '60' (分钟)
    
    Returns:
        DataFrame or None
    """
    # period mapping for eastmoney: 1=min1, 5=min5, etc.
    fm_map = {'1': '1', '5': '5', '15': '15', '30': '30', '60': '60'}
    fm = fm_map.get(period, '5')
    
    # trends2 API - get latest minute bars
    # fmt=X,Y,2,3,4,5,6 = time, open, close, volume, high, low, amount
    url = f"https://push2his.eastmoney.com/api/qt/stock/kline/get?secid={secid}&fields1=f1,f2,f3,f4,f5,f6&fields2=f51,f52,f53,f54,f55,f56,f57&klt={fm * 60}&fqt=1&end=20500101&lmt=120"
    
    try:
        req = urllib.request.Request(url, headers={
            'User-Agent': 'Mozilla/5.0',
            'Referer': 'https://quote.eastmoney.com/'
        })
        resp = urllib.request.urlopen(req, timeout=10)
        data = json.loads(resp.read().decode('utf-8'))
        
        klines = data.get('data', {}).get('klines', [])
        if not klines:
            return None
        
        rows = []
        for kl in klines:
            parts = kl.split(',')
            rows.append({
                'day': parts[0][:10] + ' ' + parts[0][11:] if len(parts[0]) > 10 else parts[0],
                'open': float(parts[1]),
                'close': float(parts[2]),
                'volume': float(parts[3]),
                'high': float(parts[4]),
                'low': float(parts[5]),
                'amount': float(parts[6]) if len(parts) > 6 else 0,
            })
        
        df = pd.DataFrame(rows)
        df['day'] = pd.to_datetime(df['day'])
        return df
    except Exception as e:
        print(f"[MinuteKline] EastMoney fallback failed: {e}")
        return None


def get_minute_kline(code: str, period: str = '1', use_cache: bool = True) -> Optional[pd.DataFrame]:
    """
    获取分钟级K线数据（新浪主 + 东方财富备）

    Args:
        code: 股票代码 (sh.600519 / sz.000001)
        period: 周期 '1', '5', '15', '30', '60' (分钟)
        use_cache: 是否使用本地缓存

    Returns:
        DataFrame with columns: ['day', 'open', 'high', 'low', 'close', 'volume', 'amount']
        注意: 新浪API只返回最近约1970条数据（约3-4个月交易日），不返回历史完整数据
    """
    sina_code = code_to_sina_format(code)

    # Check cache first
    if use_cache:
        cache_file = os.path.join(DATA_DIR, f'{sina_code}_{period}min.json')
        if os.path.exists(cache_file):
            mtime = os.path.getmtime(cache_file)
            now = time.time()
            # Cache valid for 30 minutes during trading hours
            if now - mtime < 1800:
                try:
                    with open(cache_file, 'r') as f:
                        data = json.load(f)
                    df = pd.DataFrame(data)
                    df['day'] = pd.to_datetime(df['day'])
                    return df
                except Exception:
                    pass

    # Try Sina API via akshare first
    try:
        df = ak.stock_zh_a_minute(symbol=sina_code, period=period)
        if df is not None and len(df) > 0:
            df['day'] = pd.to_datetime(df['day'])

            # Save to cache
            if use_cache:
                cache_file = os.path.join(DATA_DIR, f'{sina_code}_{period}min.json')
                try:
                    df_cache = df.copy()
                    df_cache['day'] = df_cache['day'].astype(str)
                    with open(cache_file, 'w') as f:
                        df_cache.to_json(f, orient='records', force_ascii=False)
                except Exception:
                    pass
            return df
    except Exception as e:
        print(f"[MinuteKline] Sina API failed for {code} {period}min: {e}")

    # Fallback: East Money trends2 API
    try:
        secid, _ = code_to_eastmoney_code(code)
        df = fetch_eastmoney_minute(secid, period)
        if df is not None and len(df) > 0:
            # Save to cache under sina code name for consistency
            if use_cache:
                cache_file = os.path.join(DATA_DIR, f'{sina_code}_{period}min.json')
                try:
                    df_cache = df.copy()
                    df_cache['day'] = df_cache['day'].astype(str)
                    with open(cache_file, 'w') as f:
                        df_cache.to_json(f, orient='records', force_ascii=False)
                except Exception:
                    pass
            return df
    except Exception as e:
        print(f"[MinuteKline] EastMoney fallback also failed: {e}")

    return None


def get_realtime_minute_kline(code: str, period: str = '1', last_n: int = 240) -> Optional[pd.DataFrame]:
    """
    获取实时分钟K线（最近N条）

    Args:
        code: 股票代码
        period: 周期 '1', '5', '15', '30', '60'
        last_n: 取最近N条

    Returns:
        DataFrame with latest minute K-line data
    """
    df = get_minute_kline(code, period)
    if df is not None and len(df) > 0:
        return df.tail(last_n).reset_index(drop=True)
    return None


def get_today_minute_kline(code: str, period: str = '1') -> Optional[pd.DataFrame]:
    """
    获取当日分钟K线

    Args:
        code: 股票代码
        period: 周期

    Returns:
        Only today's minute K-line data
    """
    df = get_minute_kline(code, period)
    if df is not None and len(df) > 0:
        today = datetime.now().strftime('%Y-%m-%d')
        mask = df['day'].dt.strftime('%Y-%m-%d') == today
        return df[mask].reset_index(drop=True)
    return None


def calculate_minute_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """
    计算分钟K线技术指标

    Args:
        df: minute K-line DataFrame

    Returns:
        df with added indicator columns
    """
    if df is None or len(df) < 5:
        return df

    df = df.copy()

    # Ensure numeric columns
    for col in ['open', 'high', 'low', 'close', 'volume', 'amount']:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors='coerce')

    # MA lines
    df['ma5'] = df['close'].rolling(5).mean()
    df['ma10'] = df['close'].rolling(10).mean()
    df['ma20'] = df['close'].rolling(20).mean()
    df['ma60'] = df['close'].rolling(60).mean()

    # VWAP (Volume Weighted Average Price) - cumulative
    df['vwap'] = df['amount'].cumsum() / df['volume'].cumsum().replace(0, 1)

    # RSI (6-period)
    delta = df['close'].diff()
    gain = delta.where(delta > 0, 0).rolling(6).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(6).mean()
    rs = gain / loss.replace(0, float('nan'))
    df['rsi6'] = 100 - (100 / (1 + rs))

    # Volume ratio (current vol / 20-period avg vol)
    df['vol_ratio'] = df['volume'] / df['volume'].rolling(20).mean()

    # Intraday high/low position (0-100 scale)
    day_high = df['high'].rolling(240).max()  # ~1 trading day in 1-min bars
    day_low = df['low'].rolling(240).min()
    df['day_position'] = (df['close'] - day_low) / (day_high - day_low).replace(0, 1) * 100

    return df


def detect_minute_signal(df: pd.DataFrame, signal_type: str = 'breakout') -> Optional[Dict]:
    """
    检测分钟级交易信号

    Signal types:
    - breakout: 放量突破日内高点
    - dip: 缩量回调到均线支撑
    - reversal: RSI超卖反转
    - volume_surge: 突发放量

    Args:
        df: minute K-line DataFrame with indicators
        signal_type: signal detection type

    Returns:
        Dict with signal details or None
    """
    if df is None or len(df) < 20:
        return None

    df = df.copy()
    last = df.iloc[-1]
    prev = df.iloc[-2]

    if signal_type == 'breakout':
        # Price breaks above recent high with volume surge
        recent_high = df['high'].iloc[-20:-1].max()
        if last['close'] > recent_high and last.get('vol_ratio', 0) > 1.5:
            return {
                'type': 'breakout',
                'price': last['close'],
                'volume': last['volume'],
                'vol_ratio': last.get('vol_ratio', 0),
                'message': f"放量突破 {recent_high:.3f}, 量比{last.get('vol_ratio', 0):.1f}"
            }

    elif signal_type == 'dip':
        # Price dips to MA20 support with shrinking volume
        ma20 = last.get('ma20', 0)
        if ma20 > 0 and abs(last['close'] - ma20) / ma20 < 0.01 and last.get('vol_ratio', 0) < 0.8:
            return {
                'type': 'dip',
                'price': last['close'],
                'support': ma20,
                'vol_ratio': last.get('vol_ratio', 0),
                'message': f"缩量回调到MA20({ma20:.3f})支撑"
            }

    elif signal_type == 'reversal':
        # RSI oversold reversal
        rsi = last.get('rsi6', 50)
        prev_rsi = prev.get('rsi6', 50)
        if rsi < 20 and prev_rsi < rsi:
            return {
                'type': 'reversal',
                'price': last['close'],
                'rsi': rsi,
                'message': f"RSI超卖反转 ({rsi:.1f})"
            }

    elif signal_type == 'volume_surge':
        # Sudden volume spike
        if last.get('vol_ratio', 0) > 3.0:
            return {
                'type': 'volume_surge',
                'price': last['close'],
                'volume': last['volume'],
                'vol_ratio': last.get('vol_ratio', 0),
                'message': f"突发放量 ({last.get('vol_ratio', 0):.1f}倍)"
            }

    return None


def batch_check_stock_picks(picks: List[Dict], period: str = '5') -> List[Dict]:
    """
    批量检查选股列表的实时分钟K线信号

    Args:
        picks: List of dicts with 'code' key
        period: minute period

    Returns:
        List of dicts with code, realtime data, and signals
    """
    results = []

    for pick in picks:
        code = pick['code']
        result = {
            'code': code,
            'name': pick.get('name', ''),
            'url': code_to_eastmoney_url(code),
            'minute_data': None,
            'indicators': None,
            'signals': []
        }

        # Get minute K-line
        df = get_realtime_minute_kline(code, period, last_n=120)

        if df is not None:
            # Calculate indicators
            df = calculate_minute_indicators(df)
            result['minute_data'] = True

            # Get latest values
            if len(df) > 0:
                last = df.iloc[-1]
                result['indicators'] = {
                    'price': round(float(last['close']), 2),
                    'ma5': round(float(last['ma5']), 2) if not pd.isna(last.get('ma5', 0)) else None,
                    'ma20': round(float(last['ma20']), 2) if not pd.isna(last.get('ma20', 0)) else None,
                    'rsi6': round(float(last['rsi6']), 1) if not pd.isna(last.get('rsi6', 0)) else None,
                    'vol_ratio': round(float(last['vol_ratio']), 2) if not pd.isna(last.get('vol_ratio', 0)) else None,
                    'day_position': round(float(last['day_position']), 1) if not pd.isna(last.get('day_position', 0)) else None,
                    'vwap': round(float(last['vwap']), 2) if not pd.isna(last.get('vwap', 0)) else None,
                    'volume': int(last['volume']),
                    'last_time': str(last['day'])
                }

                # Detect signals
                for sig_type in ['breakout', 'dip', 'reversal', 'volume_surge']:
                    sig = detect_minute_signal(df, sig_type)
                    if sig:
                        result['signals'].append(sig)

        time.sleep(0.3)  # Rate limit

        results.append(result)

    return results


if __name__ == '__main__':
    # Test: fetch minute K-line for a stock
    code = 'sh.600519'  # 贵州茅台
    print(f"=== Testing minute K-line for {code} ===")
    print(f"East Money URL: {code_to_eastmoney_url(code)}")

    for period in ['1', '5', '15']:
        df = get_minute_kline(code, period)
        if df is not None:
            print(f"\n--- {period}min K-line: {len(df)} rows ---")
            print(df.columns.tolist())
            print(df.tail(3))

            # Calculate indicators
            df_ind = calculate_minute_indicators(df)
            print("\n--- Latest indicators ---")
            last = df_ind.iloc[-1]
            for col in ['close', 'ma5', 'ma20', 'rsi6', 'vol_ratio', 'day_position', 'vwap']:
                val = last.get(col)
                if val is not None and not pd.isna(val):
                    print(f"  {col}: {val:.2f}")

            # Detect signals
            for sig_type in ['breakout', 'dip', 'reversal', 'volume_surge']:
                sig = detect_minute_signal(df_ind, sig_type)
                if sig:
                    print(f"\n  [SIGNAL] {sig_type}: {sig['message']}")
        else:
            print(f"\n--- {period}min: No data ---")
