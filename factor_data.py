"""
因子数据采集层 - 多因子量化选股系统 v2

数据采集维度:
A. 价量因子 (K线计算)
B. 基本面因子 (BaoStock / AKShare)
C. 板块因子 (AKShare 行业+概念)
D. 资金面因子 (AKShare 北向+龙虎榜)
E. 市场情绪因子 (AKShare 全市场行情)

缓存目录: data/factor_cache/
"""

import os
import json
import time
import hashlib
import logging
import pandas as pd
import numpy as np
import requests
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, 'data')
FACTOR_CACHE_DIR = os.path.join(DATA_DIR, 'factor_cache')
KLINEDIR = os.path.join(DATA_DIR, 'kline')
FUND_DIR = os.path.join(DATA_DIR, 'fundamentals')
os.makedirs(FACTOR_CACHE_DIR, exist_ok=True)

logger = logging.getLogger(__name__)

# AKShare请求超时配置 (秒)
AKSHARE_TIMEOUT = 10
AKSHARE_RETRIES = 2


# 本地代理配置
PROXY_URL = os.environ.get('HTTP_PROXY', 'http://127.0.0.1:1935')
PROXIES = {'http': PROXY_URL, 'https': PROXY_URL}


def _akshare_with_retry(fn, *args, **kwargs):
    """AKShare调用包装器：重试+超时+代理"""
    import requests as req_lib

    for attempt in range(AKSHARE_RETRIES + 1):
        try:
            session = req_lib.Session()
            session.trust_env = False
            session.proxies = PROXIES
            session.headers.update({"User-Agent": "Mozilla/5.0"})
            # Monkey-patch the session for this call
            orig_session = req_lib.session
            # AKShare uses requests.get/post directly, so patch at session level
            old_get = req_lib.get
            old_post = req_lib.post
            def proxied_get(url, **kw):
                kw.setdefault('timeout', AKSHARE_TIMEOUT)
                kw.setdefault('proxies', PROXIES)
                return session.get(url, **kw)
            def proxied_post(url, **kw):
                kw.setdefault('timeout', AKSHARE_TIMEOUT)
                kw.setdefault('proxies', PROXIES)
                return session.post(url, **kw)
            req_lib.get = proxied_get
            req_lib.post = proxied_post

            result = fn(*args, **kwargs)

            req_lib.get = old_get
            req_lib.post = old_post
            session.close()
            return result
        except Exception as e:
            req_lib.get = old_get if 'old_get' in dir() else req_lib.get
            req_lib.post = old_post if 'old_post' in dir() else req_lib.post
            logger.warning(f"AKShare调用失败 (尝试{attempt+1}/{AKSHARE_RETRIES+1}): {e}")
            if attempt < AKSHARE_RETRIES:
                time.sleep(2 * (attempt + 1))
            else:
                logger.error(f"AKShare调用最终失败: {fn.__name__ if hasattr(fn, '__name__') else str(fn)}")
                raise


# ==================== 工具函数 ====================

def cache_get(key: str, max_age: int = 3600) -> Optional[Any]:
    """从缓存读取 (TTL过期自动失效)"""
    path = os.path.join(FACTOR_CACHE_DIR, f"{key}.json")
    if os.path.exists(path):
        if time.time() - os.path.getmtime(path) < max_age:
            try:
                with open(path, 'r') as f:
                    return json.load(f)
            except:
                pass
    return None


def cache_set(key: str, data: Any) -> None:
    """写入缓存"""
    path = os.path.join(FACTOR_CACHE_DIR, f"{key}.json")
    try:
        with open(path, 'w') as f:
            json.dump(data, f, ensure_ascii=False, default=str)
    except Exception as e:
        logger.warning(f"缓存写入失败 {key}: {e}")


def safe_float(val, default=0.0):
    """安全转float"""
    try:
        v = float(val)
        return v if not np.isnan(v) else default
    except:
        return default


def get_stock_pool() -> List[str]:
    """获取股票池（含科创板，排除北交所/ST）"""
    pool_file = os.path.join(DATA_DIR, 'stock_pool.json')
    if os.path.exists(pool_file):
        with open(pool_file, 'r') as f:
            pool = json.load(f)
        if isinstance(pool, list):
            return [s['code'] if isinstance(s, dict) else s for s in pool]
        if isinstance(pool, dict):
            return list(pool.keys())
    
    # fallback: 从kline目录读取
    from market_filter import is_allowed
    codes = []
    if os.path.exists(KLINEDIR):
        for f in os.listdir(KLINEDIR):
            if f.endswith('.csv'):
                code = f.replace('.csv', '')
                if is_allowed(code):
                    codes.append(code)
    return codes


def _liquidity_series(df: pd.DataFrame, tail: int = 20) -> float:
    """近 N 日流动性指标：优先成交额，amount 无效时用 volume*close"""
    if df.empty:
        return 0.0
    n = min(tail, len(df))
    if 'amount' in df.columns:
        s = pd.to_numeric(df['amount'].tail(n), errors='coerce')
        if s.notna().any() and float(s.fillna(0).sum()) > 0:
            return float(s.mean())
    if 'volume' in df.columns and 'close' in df.columns:
        vol = pd.to_numeric(df['volume'].tail(n), errors='coerce').fillna(0)
        close = pd.to_numeric(df['close'].tail(n), errors='coerce').fillna(0)
        est = vol * close
        if float(est.sum()) > 0:
            return float(est.mean())
    if 'volume' in df.columns:
        s = pd.to_numeric(df['volume'].tail(n), errors='coerce')
        if s.notna().any() and float(s.fillna(0).sum()) > 0:
            return float(s.mean())
    return 0.0


def select_pool_top_liquidity(codes: List[str], top_n: int) -> List[str]:
    """按近20日成交额/成交量预筛流动性 Top N（仅读本地K线，秒级~分钟级）"""
    if not top_n or top_n >= len(codes):
        return codes
    ranked = []
    for code in codes:
        df = load_kline(code, days=30)
        if df.empty:
            continue
        avg = _liquidity_series(df, 20)
        if avg > 0:
            ranked.append((code, avg))
    ranked.sort(key=lambda x: x[1], reverse=True)
    return [c for c, _ in ranked[:top_n]]


def load_kline(code: str, days: int = 120) -> pd.DataFrame:
    """加载个股K线数据"""
    kline_file = os.path.join(KLINEDIR, f"{code}.csv")
    if not os.path.exists(kline_file):
        return pd.DataFrame()
    try:
        df = pd.read_csv(kline_file)
        if df.empty:
            return pd.DataFrame()
        try:
            from kline_sanitize import sanitize_kline_df
            df = sanitize_kline_df(df)
        except Exception:
            pass
        # 统一列名
        col_map = {}
        for c in df.columns:
            cl = c.lower().strip()
            if cl in ('date', 'datetime'):
                col_map[c] = 'date'
            elif cl in ('open',):
                col_map[c] = 'open'
            elif cl in ('close', '收盘'):
                col_map[c] = 'close'
            elif cl in ('high', '最高'):
                col_map[c] = 'high'
            elif cl in ('low', '最低'):
                col_map[c] = 'low'
            elif cl in ('volume', '成交量'):
                col_map[c] = 'volume'
            elif cl in ('amount', '成交额'):
                col_map[c] = 'amount'
            elif cl in ('turnover', '换手率'):
                col_map[c] = 'turnover'
        df = df.rename(columns=col_map)
        return df.tail(days).reset_index(drop=True)
    except:
        return pd.DataFrame()


# ==================== A. 价量因子 ====================

class PriceVolumeFactors:
    """价量因子计算"""

    @staticmethod
    def compute(code: str) -> Dict:
        """计算单只股票的价量因子"""
        cache_key = f"pv_{code}_{datetime.now().strftime('%Y%m%d')}"
        cached = cache_get(cache_key, max_age=86400)
        if cached:
            return PriceVolumeFactors._overlay_realtime(code, cached)

        df = load_kline(code, days=120)
        if df.empty or len(df) < 30:
            return {}

        close = df['close'].values
        high = df['high'].values
        low = df['low'].values
        volume = df['volume'].values
        amount = df['amount'].values if 'amount' in df.columns else None

        # 均线
        ma5 = np.nanmean(close[-5:]) if len(close) >= 5 else None
        ma10 = np.nanmean(close[-10:]) if len(close) >= 10 else None
        ma20 = np.nanmean(close[-20:]) if len(close) >= 20 else None
        ma60 = np.nanmean(close[-60:]) if len(close) >= 60 else None

        # MACD
        if len(close) >= 26:
            ema12 = pd.Series(close).ewm(span=12).mean().values
            ema26 = pd.Series(close).ewm(span=26).mean().values
            dif = ema12[-1] - ema26[-1]
            dea = pd.Series(dif - np.zeros_like(dif)).ewm(span=9).mean().values[-1] if len(close) >= 26 else 0
            # 简化: DEA就是DIF的9日EMA
            dif_series = ema12 - ema26
            dea = pd.Series(dif_series).ewm(span=9).mean().iloc[-1]
            macd_hist = 2 * (dif - dea)
            prev_dif = pd.Series(dif_series).ewm(span=9).mean().iloc[-2] if len(close) >= 27 else dea
        else:
            dif = dea = macd_hist = prev_dif = 0

        # RSI
        if len(close) >= 15:
            delta = np.diff(close[-15:])
            gain = np.where(delta > 0, delta, 0)
            loss = np.where(delta < 0, -delta, 0)
            avg_gain = np.mean(gain)
            avg_loss = np.mean(loss)
            rsi = 100 - (100 / (1 + avg_gain / avg_loss)) if avg_loss > 0 else 100
        else:
            rsi = 50

        # 布林带
        if len(close) >= 20:
            boll_mid = np.mean(close[-20:])
            boll_std = np.std(close[-20:])
            boll_up = boll_mid + 2 * boll_std
            boll_down = boll_mid - 2 * boll_std
            boll_width = (boll_up - boll_down) / boll_mid if boll_mid > 0 else 0
        else:
            boll_mid = boll_up = boll_down = boll_width = 0

        # 成交量指标
        vol_ma5 = np.mean(volume[-5:]) if len(volume) >= 5 else 0
        vol_ma20 = np.mean(volume[-20:]) if len(volume) >= 20 else 0
        vol_ratio = vol_ma5 / vol_ma20 if vol_ma20 > 0 else 1.0

        # 换手率
        turnover_ma5 = 0
        if 'turnover' in df.columns:
            t = df['turnover'].values
            turnover_ma5 = np.mean(t[-5:]) if len(t) >= 5 else 0

        # 动量
        mom_5d = (close[-1] / close[-6] - 1) * 100 if len(close) >= 6 else 0
        mom_10d = (close[-1] / close[-11] - 1) * 100 if len(close) >= 11 else 0
        mom_20d = (close[-1] / close[-21] - 1) * 100 if len(close) >= 21 else 0

        # 波动率 (20日年化)
        if len(close) >= 21:
            returns = np.diff(close[-21:]) / close[-21:-1]
            volatility = np.std(returns) * np.sqrt(252) * 100
        else:
            volatility = 0

        # 价格位置 (20日区间)
        if len(close) >= 20:
            high_20 = np.max(high[-20:])
            low_20 = np.min(low[-20:])
            price_pos = (close[-1] - low_20) / (high_20 - low_20) * 100 if (high_20 - low_20) > 0 else 50
        else:
            price_pos = 50

        # ATR (14日)
        if len(close) >= 15:
            tr1 = high[-14:] - low[-14:]
            tr2 = np.abs(high[-14:] - np.roll(close[-15:-1], 1))
            tr3 = np.abs(low[-14:] - np.roll(close[-15:-1], 1))
            # 简化计算
            prev_close = close[-15:-1]
            tr_list = []
            for i in range(14):
                t = max(high[-14+i] - low[-14+i],
                        abs(high[-14+i] - prev_close[i]),
                        abs(low[-14+i] - prev_close[i]))
                tr_list.append(t)
            atr = np.mean(tr_list)
        else:
            atr = 0

        # 是否突破60日新高
        break_60d = False
        if len(high) >= 60:
            high_60 = np.max(high[-60:-1])  # 排除今日
            break_60d = close[-1] > high_60

        # 是否均线多头 (MA5 > MA10 > MA20)
        ma_bull = bool(ma5 and ma10 and ma20 and ma5 > ma10 > ma20)

        # MACD金叉
        macd_golden_cross = bool(prev_dif and dif > dea and prev_dif <= dea)

        current_price = float(close[-1])

        # 涨跌幅
        change_pct = (close[-1] / close[-2] - 1) * 100 if len(close) >= 2 else 0

        # 半年内涨停统计
        limit_up_count_180d = 0
        has_limit_up_180d = False
        if len(close) >= 120:  # ~180 trading days
            for i in range(-1, -120, -1):
                if i < -len(close):
                    break
                prev = close[i-1] if i-1 >= -len(close) else close[i]
                curr = close[i]
                if prev > 0 and (curr / prev - 1) >= 0.095:  # ~10% limit up
                    limit_up_count_180d += 1
                    has_limit_up_180d = True

        result = {
            'price': round(current_price, 2),
            'ma5': round(ma5, 2) if ma5 else None,
            'ma10': round(ma10, 2) if ma10 else None,
            'ma20': round(ma20, 2) if ma20 else None,
            'ma60': round(ma60, 2) if ma60 else None,
            'macd_dif': round(dif, 4),
            'macd_dea': round(dea, 4),
            'macd_hist': round(macd_hist, 4),
            'rsi': round(rsi, 2),
            'boll_up': round(boll_up, 2),
            'boll_mid': round(boll_mid, 2),
            'boll_down': round(boll_down, 2),
            'boll_width': round(boll_width, 4),
            'vol_ratio': round(vol_ratio, 2),
            'turnover_ma5': round(turnover_ma5, 2),
            'mom_5d': round(mom_5d, 2),
            'mom_10d': round(mom_10d, 2),
            'mom_20d': round(mom_20d, 2),
            'volatility': round(volatility, 2),
            'price_pos': round(price_pos, 2),
            'atr': round(atr, 2),
            'break_60d': break_60d,
            'ma_bull': ma_bull,
            'macd_golden_cross': macd_golden_cross,
            # 派生指标
            'price_vs_ma20': round((current_price / ma20 - 1) * 100, 2) if ma20 else None,
            'price_vs_ma60': round((current_price / ma60 - 1) * 100, 2) if ma60 else None,
            # 新增加字段 - 策略 v2 需要
            'change_pct': round(change_pct, 2),
            'has_limit_up_180d': has_limit_up_180d,
            'limit_up_count_180d': limit_up_count_180d,
        }

        # 盘中 overlay 实时字段 (iFind/新浪 Provider)
        result = PriceVolumeFactors._overlay_realtime(code, result)

        cache_set(cache_key, result)
        return result

    @staticmethod
    def _overlay_realtime(code: str, result: Dict) -> Dict:
        """用实时行情覆盖 price/change_pct/today_high/today_low"""
        try:
            from market_data import get_market_data_provider, get_provider_name
            provider = get_market_data_provider()
            rt = provider.get_realtime_quote(code)
            if not rt:
                return result

            latest = float(rt.get('close') or rt.get('price') or 0)
            pre_close = float(rt.get('pre_close') or 0)
            if latest > 0:
                result['price'] = round(latest, 2)
            if rt.get('change_pct') is not None:
                result['change_pct'] = round(float(rt['change_pct']), 2)
            elif pre_close > 0 and latest > 0:
                result['change_pct'] = round((latest - pre_close) / pre_close * 100, 2)

            result['today_high'] = round(float(rt.get('high') or 0), 2)
            result['today_low'] = round(float(rt.get('low') or 0), 2)
            result['today_open'] = round(float(rt.get('open') or 0), 2)
            result['today_volume'] = float(rt.get('volume') or 0)
            result['price_source'] = get_provider_name()

            # iFind 日内增强 (尾盘策略，仅 iFind 可用时)
            if get_provider_name() == 'ifind':
                try:
                    from ifind_fetcher import IFindFetcher
                    from market_data import get_data_config
                    ifind = IFindFetcher(config=get_data_config().get('ifind', {}))
                    if ifind.available:
                        intraday = ifind.get_intraday_metrics(code)
                        if intraday.get('today_high'):
                            result['today_high'] = round(intraday['today_high'], 2)
                        if intraday.get('today_low'):
                            result['today_low'] = round(intraday['today_low'], 2)
                        if intraday.get('afternoon_vol_ratio') is not None:
                            result['afternoon_vol_ratio'] = intraday['afternoon_vol_ratio']
                except Exception:
                    pass
        except Exception as e:
            logger.debug(f'实时 overlay 失败 {code}: {e}')
        return result


# ==================== B. 基本面因子 ====================

class FundamentalFactors:
    """基本面因子"""

    @staticmethod
    def compute(code: str, price: float = 0) -> Dict:
        """获取基本面因子"""
        cache_key = f"fund_{code}"
        cached = cache_get(cache_key, max_age=86400 * 7)  # 基本面缓存7天
        if cached:
            return cached

        # 从已有缓存读取
        years = ['2025', '2024']
        data = {}
        for year in years:
            fund_file = os.path.join(FUND_DIR, f"{code}_fund_{year}.json")
            if os.path.exists(fund_file):
                try:
                    with open(fund_file, 'r') as f:
                        data = json.load(f)
                    data['_year'] = year
                    break
                except:
                    pass

        if not data:
            cache_set(cache_key, {})
            return {}

        result = {}

        # 盈利能力
        profit = data.get('profit', {})
        result['roe'] = safe_float(profit.get('roeAvg'))
        result['np_margin'] = safe_float(profit.get('npMargin'))
        result['gp_margin'] = safe_float(profit.get('gpMargin'))
        result['eps'] = safe_float(profit.get('epsTTM'))

        # 成长能力
        growth = data.get('growth', {})
        result['yoy_ni'] = safe_float(growth.get('YOYNI'))
        result['yoy_eps'] = safe_float(growth.get('YOYEPSBasic'))
        result['yoy_asset'] = safe_float(growth.get('YOYAsset'))

        # 财务健康
        balance = data.get('balance', {})
        result['liability_ratio'] = safe_float(balance.get('liabilityToAsset'))
        result['current_ratio'] = safe_float(balance.get('currentRatio'))

        # 行业
        industry = data.get('industry', {})
        result['industry'] = industry.get('industryName', '')

        # PE计算
        eps = result.get('eps', 0)
        if eps and eps > 0 and price and price > 0:
            result['pe'] = round(price / eps, 2)
        else:
            result['pe'] = None

        # PB (简化)
        bvps = safe_float(profit.get('bvps'))
        if bvps and bvps > 0 and price and price > 0:
            result['pb'] = round(price / bvps, 2)
        else:
            result['pb'] = None

        cache_set(cache_key, result)
        return result


# ==================== C. 板块因子 ====================

# ==================== 新浪/腾讯直连市场数据 ====================
# AKShare走代理有SSL问题，全部改用直连API

import urllib.request as _urllib_req
import urllib.error as _urllib_err
import re as _re

_SINA_HEADERS = {
    'Referer': 'https://finance.sina.com.cn',
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
}

def _sina_get(url, timeout=10):
    """新浪API直连请求"""
    req = _urllib_req.Request(url, headers=_SINA_HEADERS)
    resp = _urllib_req.urlopen(req, timeout=timeout)
    return resp.read().decode('gbk', errors='replace')


class SectorFactors:
    """板块因子 - 基于本地行业映射+新浪实时行情计算板块表现"""

    @staticmethod
    def _load_industry_map() -> Dict[str, str]:
        """加载本地行业映射 (code -> industry_name)"""
        ind_file = os.path.join(DATA_DIR, 'stock_industry.json')
        if os.path.exists(ind_file):
            with open(ind_file, 'r') as f:
                data = json.load(f)
            if isinstance(data, dict):
                return {code: info.get('industryName', '其他') for code, info in data.items()}
        return {}

    @staticmethod
    def _get_sector_performance(industry_map: Dict[str, str]) -> List[Dict]:
        """通过实时行情计算各板块表现 (统一 Provider)"""
        from market_data import get_market_data_provider
        provider = get_market_data_provider()
        quotes_df = provider.get_realtime_quotes()

        # quotes_df: DataFrame with code, close, change_pct, amount, name
        # Convert to dict keyed by code
        if quotes_df.empty:
            return []
        quote_map = {row['code']: row.to_dict() for _, row in quotes_df.iterrows()}

        sector_data: Dict[str, Dict] = {}
        for code, industry in industry_map.items():
            if industry not in sector_data:
                sector_data[industry] = {'changes': [], 'stocks': [], 'total_amount': 0}
            q = quote_map.get(code)
            if q:
                cp = safe_float(q.get('change_pct', 0), 0)
                sector_data[industry]['changes'].append(cp)
                sector_data[industry]['stocks'].append(code)
                sector_data[industry]['total_amount'] += safe_float(q.get('amount', 0), 0)

        results = []
        for sector, data in sector_data.items():
            if not data['changes']:
                continue
            avg_change = sum(data['changes']) / len(data['changes'])
            # Find lead stock (highest change)
            lead = None
            lead_change = -999
            for code in data['stocks']:
                q = quote_map.get(code)
                if q:
                    cp = safe_float(q.get('change_pct', 0), 0)
                    if cp > lead_change:
                        lead_change = cp
                        lead = code
            results.append({
                'name': sector,
                'change_pct': round(avg_change, 2),
                'stock_count': len(data['changes']),
                'total_amount': round(data['total_amount'] / 1e8, 2),  # 亿
                'lead_stock': lead or '',
            })

        results.sort(key=lambda x: x['change_pct'], reverse=True)
        return results

    @staticmethod
    def get_industry_board() -> pd.DataFrame:
        """获取行业板块表现 (本地数据+新浪行情)"""
        cache_key = f"sector_industry_{datetime.now().strftime('%Y%m%d')}"
        cached = cache_get(cache_key)
        if cached:
            return pd.DataFrame(cached)

        industry_map = SectorFactors._load_industry_map()
        sectors = SectorFactors._get_sector_performance(industry_map)

        cache_set(cache_key, sectors)
        return pd.DataFrame(sectors)

    @staticmethod
    def get_concept_board() -> pd.DataFrame:
        """概念板块 (暂用行业板块代替)"""
        return SectorFactors.get_industry_board()

    @staticmethod
    def get_hot_sectors(top_n: int = 10) -> List[Dict]:
        """获取热门板块"""
        df = SectorFactors.get_industry_board()
        if df.empty:
            return []
        return df.head(top_n).to_dict(orient="records")

    @staticmethod
    def get_cold_sectors(top_n: int = 10) -> List[Dict]:
        """获取冷门板块"""
        df = SectorFactors.get_industry_board()
        if df.empty:
            return []
        return df.tail(top_n).to_dict(orient="records")

    @staticmethod
    def get_hot_concepts(top_n: int = 15) -> List[Dict]:
        """获取热门概念"""
        return SectorFactors.get_hot_sectors(top_n)

    @staticmethod
    def get_sector_summary() -> Dict:
        """板块综合摘要"""
        hot = SectorFactors.get_hot_sectors(10)
        cold = SectorFactors.get_cold_sectors(5)
        concepts = SectorFactors.get_hot_concepts(10)
        return {
            "hot_sectors": hot,
            "cold_sectors": cold,
            "hot_concepts": concepts,
        }


class CapitalFactors:
    """资金因子 - 使用新浪/腾讯直连API"""

    @staticmethod
    def get_north_flow(days: int = 5) -> List[Dict]:
        """
        获取北向资金流向
        优先 iFind EDB，失败降级新浪
        """
        cache_key = f"north_flow_{datetime.now().strftime('%Y%m%d')}"
        cached = cache_get(cache_key)
        if cached:
            return cached

        # iFind EDB
        try:
            from market_data import get_provider_name, get_data_config
            if get_provider_name() == 'ifind':
                from ifind_fetcher import IFindFetcher
                ifind = IFindFetcher(config=get_data_config().get('ifind', {}))
                if ifind.available and ifind.edb_north_indicators:
                    results = ifind.get_north_flow_edb(days)
                    if results:
                        cache_set(cache_key, results)
                        return results[:days]
        except Exception as e:
            logger.debug(f'iFind 北向失败: {e}')

        try:
            # 新浪北向资金接口
            url = "https://vip.stock.finance.sina.com.cn/q/view.php?view=mtks&date=&page=1&num=5&type=hsgt"
            text = _sina_get(url, timeout=15)

            # Try to parse the response
            results = []
            # Pattern: date | net_flow
            lines = text.split('\n')
            for line in lines:
                parts = [p.strip() for p in line.split('|') if p.strip()]
                if len(parts) >= 3:
                    try:
                        results.append({
                            "date": parts[0][:10] if len(parts[0]) > 4 else "",
                            "net_flow": safe_float(parts[1], 0),
                        })
                    except:
                        pass

            if results:
                cache_set(cache_key, results)
                return results[:days]
        except Exception as e:
            logger.warning(f"获取北向资金失败: {e}")

        # Fallback: return empty
        return []

    @staticmethod
    def get_lhb_recent(days: int = 3) -> Dict[str, float]:
        """获取龙虎榜最近活跃股 (腾讯API)"""
        cache_key = f"lhb_{datetime.now().strftime('%Y%m%d')}"
        cached = cache_get(cache_key)
        if cached:
            return cached

        result = {}
        # 简化版: 不做龙虎榜了，返回空
        cache_set(cache_key, result)
        return result

    @staticmethod
    def get_capital_summary() -> Dict:
        """资金综合摘要"""
        north = CapitalFactors.get_north_flow(5)
        north_total = sum(n.get("net_flow", 0) for n in north)
        return {
            "north_flow_5d": north,
            "north_total_5d": north_total,
            "north_trend": "净流入" if north_total > 0 else "净流出",
            "lhb": CapitalFactors.get_lhb_recent(),
        }


class SentimentFactors:
    """情绪因子 - 使用新浪/腾讯直连API"""

    @staticmethod
    def get_market_sentiment() -> Dict:
        """获取市场情绪 (统一 Provider 实时行情)"""
        from market_data import get_market_data_provider
        provider = get_market_data_provider()
        summary = provider.get_market_summary()
        return {
            "up_count": summary.get("up", 0),
            "down_count": summary.get("down", 0),
            "flat_count": summary.get("flat", 0),
            "up_pct": summary.get("up_pct", 0),
            "limit_up": summary.get("limit_up", 0),
            "limit_down": summary.get("limit_down", 0),
            "total_amount": summary.get("total_amount", 0),
            "sentiment_score": summary.get("up_pct", 50),
            "sentiment_label": (
                "强势" if summary.get("up_pct", 0) > 70
                else "偏多" if summary.get("up_pct", 0) > 55
                else "中性" if summary.get("up_pct", 0) > 40
                else "偏空" if summary.get("up_pct", 0) > 25
                else "弱势"
            ),
            "timestamp": summary.get("timestamp", ""),
        }

    @staticmethod
    def get_index_summary() -> Dict:
        """获取主要指数概览 (新浪API)"""
        from sina_fetcher import SinaFetcher
        fetcher = SinaFetcher()
        df = fetcher.get_index_quotes()

        indices = {}
        if not df.empty:
            for _, row in df.iterrows():
                code = row.get("code", "")
                name = row.get("name", "")
                close = safe_float(row.get("close", 0), 0)
                change_pct = safe_float(row.get("change_pct", 0), 0)

                # 简单趋势判断
                if change_pct > 0:
                    trend = "上涨"
                elif change_pct < -0.5:
                    trend = "下跌"
                else:
                    trend = "震荡"

                indices[name] = {
                    "code": code,
                    "close": round(close, 2),
                    "change_pct": round(change_pct, 2),
                    "trend": trend,
                }

        return indices

    @staticmethod
    def get_market_overview() -> Dict:
        """获取市场综合概览"""
        sentiment = SentimentFactors.get_market_sentiment()
        indices = SentimentFactors.get_index_summary()

        # 市场状态判断
        up_pct = sentiment.get("up_pct", 50)
        sh_change = indices.get("上证指数", {}).get("change_pct", 0)

        if up_pct > 70 and sh_change > 1:
            regime = "强势上涨"
            suggestion = "可积极操作，顺势而为"
        elif up_pct > 55 and sh_change > 0:
            regime = "温和上涨"
            suggestion = "适度参与，精选个股"
        elif up_pct > 40:
            regime = "震荡整理"
            suggestion = "控制仓位，低吸为主"
        elif up_pct > 25:
            regime = "偏弱下跌"
            suggestion = "谨慎操作，减少开仓"
        else:
            regime = "弱势下跌"
            suggestion = "空仓观望，等待企稳"

        return {
            "sentiment": sentiment,
            "indices": indices,
            "regime": regime,
            "suggestion": suggestion,
        }


class TencentBatchFetcher:
    """腾讯行情批量获取器 - 市值/量比/换手率"""

    _TEQ_HEADERS = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        'Referer': 'https://finance.qq.com',
    }

    @staticmethod
    def fetch_batch(stock_codes: List[str], batch_size: int = 80) -> Dict[str, Dict]:
        """
        批量获取腾讯行情数据
        返回: {code: {market_cap, vol_ratio, turnover, pe, total_share, float_share}}
        """
        result = {}
        for i in range(0, len(stock_codes), batch_size):
            batch = stock_codes[i:i + batch_size]
            symbols = []
            for c in batch:
                if c.startswith('6'):
                    symbols.append('sh' + c)
                else:
                    symbols.append('sz' + c)

            try:
                url = f'https://qt.gtimg.cn/q={",".join(symbols)}'
                req = _urllib_req.Request(url, headers=TencentBatchFetcher._TEQ_HEADERS)
                resp = _urllib_req.urlopen(req, timeout=15)
                text = resp.read().decode('gbk', errors='replace')

                for line in text.strip().split('\n'):
                    m = _re.match(r'v_\w+="(.*)"', line)
                    if not m:
                        continue
                    parts = m.group(1).split('~')
                    if len(parts) < 49:
                        continue

                    code = parts[2]
                    result[code] = {
                        'market_cap': safe_float(parts[46], 0),     # 总市值(亿)
                        'float_cap': safe_float(parts[47], 0),      # 流通市值(亿)
                        'vol_ratio': safe_float(parts[48], 0),      # 量比
                        'turnover': safe_float(parts[38], 0),       # 换手率(%)
                        'pe': safe_float(parts[39], 0),             # 市盈率
                        'total_share': safe_float(parts[44], 0),    # 总股本(亿)
                        'float_share': safe_float(parts[45], 0),    # 流通股本(亿)
                        'pb': safe_float(parts[40], 0),             # 市净率
                        'amplitude': safe_float(parts[43], 0),      # 振幅(%)
                    }
            except Exception as e:
                logger.warning(f"腾讯行情批量获取失败 batch {i}: {e}")

        return result


class FactorCollector:
    """因子收集器 - 统一采集所有因子数据"""

    @staticmethod
    def collect_for_stock(code: str, price: float = 0) -> Dict:
        """收集单只股票的所有因子"""
        pv = PriceVolumeFactors.compute(code)
        fund = FundamentalFactors.compute(code, price)

        # 补充腾讯实时数据
        tencent = TencentBatchFetcher.fetch_batch([code])
        extra = tencent.get(code, {})

        return {
            'code': code,
            'price_volume': pv,
            'fundamental': fund,
            'extra': extra,
            'price': pv.get('price', price),
        }

    @staticmethod
    def collect_batch(stock_codes: List[str]) -> List[Dict]:
        """批量收集股票因子 (含腾讯实时数据)"""
        # 批量获取腾讯数据
        tencent_data = TencentBatchFetcher.fetch_batch(stock_codes)

        results = []
        for code in stock_codes:
            pv = PriceVolumeFactors.compute(code)
            extra = tencent_data.get(code, {})
            results.append({
                'code': code,
                'price_volume': pv,
                'extra': extra,
                'price': pv.get('price', 0),
            })
        return results

    @staticmethod
    def collect_market() -> Dict:
        """收集市场级别因子"""
        return {
            'market': SentimentFactors.get_market_overview(),
            'sectors': SectorFactors.get_sector_summary(),
            'capital': CapitalFactors.get_capital_summary(),
        }


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)

    # 测试价量因子
    print("=== 价量因子测试 ===")
    pv = PriceVolumeFactors.compute('600519')
    for k, v in pv.items():
        print(f"  {k}: {v}")

    # 测试基本面
    print("\n=== 基本面因子测试 ===")
    fund = FundamentalFactors.compute('600519', price=1600)
    for k, v in fund.items():
        print(f"  {k}: {v}")

    # 测试板块
    print("\n=== 板块因子测试 ===")
    hot = SectorFactors.get_hot_sectors()
    for s in hot[:5]:
        print(f"  {s['name']}: {s['change_pct']:+.2f}%")

    # 测试情绪
    print("\n=== 市场情绪 ===")
    overview = SentimentFactors.get_market_overview()
    print(f"  市场状态: {overview.get('regime')}")
    for name, data in overview.get('indices', {}).items():
        arrow = '+' if data['change_pct'] > 0 else ''
        print(f"  {name}: {data['close']} ({arrow}{data['change_pct']:.2f}%)")
