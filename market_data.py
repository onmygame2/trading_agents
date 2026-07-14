"""
统一市场数据 Provider 工厂

日频系统只保留本地缓存 + 新浪 Provider。

用法:
    from market_data import get_market_data_provider, get_realtime_prices
    provider = get_market_data_provider()
    quotes = provider.get_realtime_quotes(['600519'])
"""

import logging
import os
from typing import Dict, List, Optional, Union

import yaml

logger = logging.getLogger(__name__)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SETTINGS_PATH = os.path.join(BASE_DIR, 'config', 'settings.yaml')

_provider_cache = None
_active_provider_name = 'sina'
_settings_cache = None


def load_env_file(path: str = None):
    """从 .env 文件加载环境变量 (不覆盖已有)"""
    env_path = path or os.path.join(BASE_DIR, '.env')
    if not os.path.exists(env_path):
        return
    try:
        with open(env_path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith('#') or '=' not in line:
                    continue
                key, _, val = line.partition('=')
                key = key.strip()
                val = val.strip().strip('"').strip("'")
                if key and key not in os.environ:
                    os.environ[key] = val
    except Exception as e:
        logger.debug(f'加载 .env 失败: {e}')


def load_settings() -> dict:
    global _settings_cache
    if _settings_cache is not None:
        return _settings_cache
    load_env_file()
    try:
        with open(SETTINGS_PATH, 'r', encoding='utf-8') as f:
            _settings_cache = yaml.safe_load(f) or {}
    except Exception as e:
        logger.warning(f'读取 settings.yaml 失败: {e}')
        _settings_cache = {}
    return _settings_cache


def get_data_config() -> dict:
    return load_settings().get('data', {})


def get_provider_name() -> str:
    """返回当前实际使用的 Provider 名称"""
    get_market_data_provider()
    return _active_provider_name


def get_market_data_provider(force: str = None):
    """
    获取市场数据 Provider

    Args:
        force: 仅保留兼容参数，实际始终使用新浪。
    """
    global _provider_cache, _active_provider_name
    if force:
        _provider_cache = None

    if _provider_cache is not None and force is None:
        return _provider_cache

    from sina_fetcher import SinaFetcher

    _provider_cache = SinaFetcher()
    _active_provider_name = 'sina'
    logger.debug('市场数据 Provider: 新浪')

    return _provider_cache


def get_realtime_prices(codes: List[str]) -> Dict[str, float]:
    """批量获取实时价格 {code: price}"""
    if not codes:
        return {}
    provider = get_market_data_provider()
    df = provider.get_realtime_quotes(codes)
    if df is None or df.empty:
        return {}
    prices = {}
    for _, row in df.iterrows():
        code = str(row.get('code', ''))
        price = row.get('close') or row.get('price')
        if code and price:
            prices[code] = float(price)
    return prices


def get_realtime_quote_dict(code: str) -> Optional[dict]:
    """获取单只股票实时行情 dict"""
    provider = get_market_data_provider()
    return provider.get_realtime_quote(code)


def refresh_realtime_on_picks(picks: list) -> list:
    """对选股结果刷新实时价格"""
    if not picks:
        return picks
    codes = [p['code'] for p in picks if p.get('code')]
    prices = get_realtime_prices(codes)
    for pick in picks:
        code = pick.get('code')
        if code in prices:
            pick['price'] = round(prices[code], 2)
            if 'price_volume' in pick and isinstance(pick['price_volume'], dict):
                pick['price_volume']['price'] = pick['price']
    return picks
