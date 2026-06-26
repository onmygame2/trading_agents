"""
统一 A 股市场范围过滤器

读取 config/settings.yaml 的 market 段，供股票池/K线/回测/Dashboard 复用。
"""

import os
import re
from datetime import datetime
from typing import Dict, List, Optional, Union

import yaml

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SETTINGS_PATH = os.path.join(BASE_DIR, 'config', 'settings.yaml')

_DEFAULT = {
    'include_prefixes': ['600', '601', '603', '605', '000', '001', '002', '003', '300', '301', '302', '688', '689'],
    'exclude_prefixes': ['8', '4', '920'],
    'exclude_st': True,
    'min_listing_days': 60,
}

_config_cache = None


def reload_market_config() -> dict:
    global _config_cache
    _config_cache = None
    return load_market_config()


def load_market_config() -> dict:
    global _config_cache
    if _config_cache is not None:
        return _config_cache
    cfg = dict(_DEFAULT)
    try:
        with open(SETTINGS_PATH, 'r') as f:
            settings = yaml.safe_load(f) or {}
        market = settings.get('market', {})
        for k in _DEFAULT:
            if k in market and market[k] is not None:
                cfg[k] = market[k]
    except Exception:
        pass
    _config_cache = cfg
    return cfg


def get_include_prefixes() -> tuple:
    return tuple(load_market_config().get('include_prefixes', _DEFAULT['include_prefixes']))


def is_st_name(name: str) -> bool:
    if not name:
        return False
    return bool(re.search(r'ST|\*ST|退', str(name), re.IGNORECASE))


def is_excluded_code(code: str) -> bool:
    code = str(code).split('.')[-1].replace('sh', '').replace('sz', '')
    cfg = load_market_config()
    for prefix in cfg.get('exclude_prefixes', []):
        if code.startswith(str(prefix)):
            return True
    return False


def has_allowed_prefix(code: str) -> bool:
    code = str(code).split('.')[-1].replace('sh', '').replace('sz', '')
    return any(code.startswith(p) for p in get_include_prefixes())


def listing_days_ok(ipo_date: Union[str, datetime, None], ref_date: Union[str, datetime, None] = None) -> bool:
    if not ipo_date:
        return True
    min_days = int(load_market_config().get('min_listing_days', 60))
    try:
        if isinstance(ipo_date, str):
            ipo = datetime.strptime(ipo_date[:10], '%Y-%m-%d')
        else:
            ipo = ipo_date
        if ref_date is None:
            ref = datetime.now()
        elif isinstance(ref_date, str):
            ref = datetime.strptime(ref_date[:10], '%Y-%m-%d')
        else:
            ref = ref_date
        return (ref - ipo).days >= min_days
    except Exception:
        return True


def is_allowed(
    code: str,
    name: str = '',
    ipo_date: Union[str, datetime, None] = None,
    ref_date: Union[str, datetime, None] = None,
) -> bool:
    code = str(code).split('.')[-1].replace('sh', '').replace('sz', '')
    if not code or len(code) != 6 or not code.isdigit():
        return False
    if is_excluded_code(code):
        return False
    if not has_allowed_prefix(code):
        return False
    if load_market_config().get('exclude_st', True) and is_st_name(name):
        return False
    if ipo_date is not None and not listing_days_ok(ipo_date, ref_date):
        return False
    return True


def filter_codes(codes: List[str], names: Dict[str, str] = None) -> List[str]:
    names = names or {}
    return [c for c in codes if is_allowed(c, names.get(c, ''))]


def filter_stock_records(records: List[dict], ref_date: str = None) -> List[dict]:
    """过滤 stock_pool 记录列表 [{code, name, industry_name, ipo_date, ...}]"""
    out = []
    for rec in records:
        code = rec.get('code', '')
        name = rec.get('name', rec.get('code_name', ''))
        ipo = rec.get('ipo_date', rec.get('ipoDate'))
        if is_allowed(code, name, ipo, ref_date):
            out.append(rec)
    return out
