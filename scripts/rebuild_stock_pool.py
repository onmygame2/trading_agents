#!/usr/bin/env python3
"""
重建股票池 — BaoStock 候选 + market_filter

用法:
    python scripts/rebuild_stock_pool.py
    python scripts/rebuild_stock_pool.py --dry-run
    python scripts/rebuild_stock_pool.py --source baostock
"""
import argparse
import json
import os
import sys
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

from stock_pool_builder import fetch_candidate_pool
from market_filter import reload_market_config

POOL_PATH = os.path.join(BASE_DIR, 'data', 'stock_pool.json')
INDUSTRY_PATH = os.path.join(BASE_DIR, 'data', 'stock_industry.json')
BACKUP_DIR = os.path.join(BASE_DIR, 'data', 'backups')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--source', default='baostock', choices=['baostock'])
    args = parser.parse_args()

    reload_market_config()
    records = fetch_candidate_pool(args.source)
    records.sort(key=lambda x: x['code'])

    print(f'候选池: {len(records)} 只')

    if args.dry_run:
        print('dry-run 模式，未写入文件')
        return 0

    os.makedirs(BACKUP_DIR, exist_ok=True)
    if os.path.exists(POOL_PATH):
        bak = os.path.join(BACKUP_DIR, f'stock_pool_{datetime.now().strftime("%Y%m%d_%H%M%S")}.json')
        with open(POOL_PATH, 'r') as f:
            old = f.read()
        with open(bak, 'w') as f:
            f.write(old)
        print(f'已备份: {bak}')

    pool_out = []
    industry_out = {}
    for r in records:
        pool_out.append({
            'code': r['code'],
            'name': r.get('name', ''),
            'code_name': r.get('name', ''),
            'industry_name': r.get('industry_name', r.get('industry', '')),
            'industry': r.get('industry_name', r.get('industry', '')),
            'exchange': r.get('exchange', 'SH' if r['code'].startswith('6') else 'SZ'),
            'ipo_date': r.get('ipo_date', ''),
        })
        if r.get('industry_name') or r.get('industry'):
            industry_out[r['code']] = {
                'industryName': r.get('industry_name', r.get('industry', '')),
                'industry': r.get('industry_name', r.get('industry', '')),
            }

    with open(POOL_PATH, 'w', encoding='utf-8') as f:
        json.dump(pool_out, f, ensure_ascii=False, indent=2)

    if industry_out:
        with open(INDUSTRY_PATH, 'w', encoding='utf-8') as f:
            json.dump(industry_out, f, ensure_ascii=False, indent=2)

    print(f'已写入: {POOL_PATH} ({len(pool_out)} 只)')
    print(f'行业映射: {INDUSTRY_PATH} ({len(industry_out)} 条)')
    return 0


if __name__ == '__main__':
    sys.exit(main())
