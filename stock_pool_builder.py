#!/usr/bin/env python3
"""
股票池候选集获取 — BaoStock 候选 + market_filter
"""
import logging
import os
import sys
from datetime import datetime
from typing import List, Dict

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

from market_filter import is_allowed, load_market_config

logger = logging.getLogger(__name__)


def fetch_from_baostock(date: str = None) -> List[Dict]:
    import baostock as bs
    date = date or datetime.now().strftime('%Y-%m-%d')
    bs.login()
    records = []
    try:
        rs = bs.query_stock_industry()
        rows = []
        while rs.error_code == '0':
            rows.append(rs.get_row_data())
            if not rs.next():
                break
        import pandas as pd
        df = pd.DataFrame(rows, columns=rs.fields)
        df = df[df['industryClassification'] == '证监会行业分类']
        df = df[df['industry'].notna() & (df['industry'] != '')]
        df['code_clean'] = df['code'].apply(lambda x: x.replace('sh.', '').replace('sz.', ''))
        df = df.drop_duplicates(subset='code_clean', keep='first')

        for _, row in df.iterrows():
            code = row['code_clean']
            name = row['code_name']
            ipo = ''
            try:
                full = 'sh.' + code if code.startswith('6') else 'sz.' + code
                rs_b = bs.query_stock_basic(code=full, fields='code,code_name,ipoDate')
                if rs_b.error_code == '0' and rs_b.next():
                    ipo = rs_b.get_row_data()[2]
            except Exception:
                pass
            if is_allowed(code, name, ipo, date):
                records.append({
                    'code': code,
                    'name': name,
                    'industry_name': row['industry'],
                    'industry': row['industry'],
                    'exchange': 'SH' if code.startswith('6') else 'SZ',
                    'ipo_date': ipo,
                    'source': 'baostock',
                })
    finally:
        bs.logout()
    logger.info(f'BaoStock 候选: {len(records)} 只')
    return records


def fetch_candidate_pool(source: str = None) -> List[Dict]:
    if source and source != 'baostock':
        logger.warning('不再支持股票池来源 %s，改用 BaoStock', source)
    return fetch_from_baostock()
