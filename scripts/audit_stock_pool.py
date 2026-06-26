#!/usr/bin/env python3
"""
股票池审计 — 对比当前池 vs 目标候选集

用法:
    python scripts/audit_stock_pool.py
    python scripts/audit_stock_pool.py --source baostock
"""
import argparse
import json
import os
import sys
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

from market_filter import is_allowed, is_st_name
from stock_pool_builder import fetch_candidate_pool

POOL_PATH = os.path.join(BASE_DIR, 'data', 'stock_pool.json')
REPORT_DIR = os.path.join(BASE_DIR, 'reports')


def load_current_pool():
    if not os.path.exists(POOL_PATH):
        return []
    with open(POOL_PATH, 'r') as f:
        data = json.load(f)
    records = []
    for item in data:
        if isinstance(item, dict):
            records.append(item)
        else:
            records.append({'code': str(item), 'name': ''})
    return records


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--source', default=None, choices=['ifind', 'baostock'])
    args = parser.parse_args()

    current = load_current_pool()
    current_codes = {r['code'] for r in current}
    target = fetch_candidate_pool(args.source)
    target_codes = {r['code'] for r in target}

    missing = sorted(target_codes - current_codes)
    extra = sorted(current_codes - target_codes)
    st_leaks = [r for r in current if is_st_name(r.get('name', r.get('code_name', '')))]
    bj_leaks = [r['code'] for r in current if not is_allowed(r['code'], r.get('name', ''))]

    report = {
        'timestamp': datetime.now().isoformat(),
        'current_count': len(current_codes),
        'target_count': len(target_codes),
        'missing_count': len(missing),
        'extra_count': len(extra),
        'st_leaks': [r['code'] for r in st_leaks],
        'invalid_leaks': bj_leaks,
        'missing_sample': missing[:50],
        'extra_sample': extra[:50],
    }

    os.makedirs(REPORT_DIR, exist_ok=True)
    out_path = os.path.join(REPORT_DIR, f'stock_pool_audit_{datetime.now().strftime("%Y%m%d")}.json')
    with open(out_path, 'w') as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    print('=' * 50)
    print(f'当前池: {report["current_count"]} 只')
    print(f'目标池: {report["target_count"]} 只')
    print(f'缺失:   {report["missing_count"]} 只')
    print(f'多余:   {report["extra_count"]} 只')
    print(f'ST漏网: {len(st_leaks)} 只')
    print(f'非法码: {len(bj_leaks)} 只')
    print(f'报告:   {out_path}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
