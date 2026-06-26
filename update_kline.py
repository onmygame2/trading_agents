#!/usr/bin/env python3
"""
批量更新K线缓存 - 支持 iFind / 新浪双后端

用法:
    python update_kline.py              # 按 settings.yaml data.provider 选择后端
    python update_kline.py --backend sina # 强制新浪
    python update_kline.py --top 100      # 只更新前100只（测试用）
"""
import os
import sys
import time
import logging
import pandas as pd
from concurrent.futures import ThreadPoolExecutor, as_completed

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger(__name__)

from sina_fetcher import KLINEDIR

_SINA_DELAY = 0.0


def _get_backend(force: str = None) -> str:
    if force:
        return force
    from market_data import get_data_config
    cfg = get_data_config()
    if cfg.get('kline_backend'):
        return cfg['kline_backend']
    try:
        from ifind_fetcher import is_ifind_quota_exceeded
        if is_ifind_quota_exceeded():
            return 'sina'
    except Exception:
        pass
    from market_data import get_provider_name
    name = get_provider_name()
    return 'ifind' if name == 'ifind' else 'sina'


def _fetch_kline_baostock(code: str, days: int = 120):
    import baostock as bs
    from datetime import datetime, timedelta
    end = datetime.now().strftime('%Y-%m-%d')
    start = (datetime.now() - timedelta(days=int(days * 1.6))).strftime('%Y-%m-%d')
    full = f"sh.{code}" if code.startswith('6') else f"sz.{code}"
    bs.login()
    try:
        rs = bs.query_history_k_data_plus(
            full, 'date,open,high,low,close,volume,amount,pctChg',
            start_date=start, end_date=end, frequency='d', adjustflag='3',
        )
        rows = []
        while rs.error_code == '0' and rs.next():
            rows.append(rs.get_row_data())
        if not rows:
            return None
        df = pd.DataFrame(rows, columns=rs.fields)
        df['date'] = pd.to_datetime(df['date'])
        for c in ['open', 'high', 'low', 'close', 'volume', 'amount']:
            if c in df.columns:
                df[c] = pd.to_numeric(df[c], errors='coerce')
        if 'pctChg' in df.columns:
            df['change_pct'] = pd.to_numeric(df['pctChg'], errors='coerce')
        df['stock_code'] = code
        return df.sort_values('date').tail(days)
    finally:
        bs.logout()


def _fetch_kline(backend: str, code: str, days: int, max_retries: int = 3):
    original = backend
    if backend not in ('baostock',):
        try:
            from ifind_fetcher import is_ifind_quota_exceeded
            if is_ifind_quota_exceeded():
                backend = 'sina'
        except Exception:
            pass
    for attempt in range(max_retries):
        try:
            if backend == 'baostock':
                df = _fetch_kline_baostock(code, days)
                return df if df is not None and not df.empty else None
            if backend == 'ifind':
                from ifind_fetcher import IFindFetcher
                from market_data import get_data_config
                fetcher = IFindFetcher(config=get_data_config().get('ifind', {}))
                if not fetcher.available:
                    backend = 'sina'
                else:
                    df = fetcher.get_daily_kline(code, days)
                    if df is not None and not df.empty:
                        return df
            if backend == 'sina' or original in ('ifind', 'sina'):
                from sina_fetcher import SinaFetcher
                if _SINA_DELAY > 0:
                    time.sleep(_SINA_DELAY)
                df = SinaFetcher()._fetch_sina_historical(code, days)
                if df is not None and not df.empty:
                    return df
        except Exception as e:
            err = str(e)
            if 'exceeded' in err.lower():
                try:
                    from ifind_fetcher import mark_ifind_quota_exceeded
                    mark_ifind_quota_exceeded(err)
                except Exception:
                    pass
                backend = 'sina'
            if attempt < max_retries - 1:
                time.sleep(1.0 * (attempt + 1))
            else:
                return None, err
    return None


def update_single_stock(code, days=30, backend='sina'):
    try:
        csv_path = os.path.join(KLINEDIR, f'{code}.csv')
        if not os.path.exists(csv_path):
            return (code, False, 0)

        local_df = pd.read_csv(csv_path)
        local_df['date'] = pd.to_datetime(local_df['date'])
        old_count = len(local_df)

        result = _fetch_kline(backend, code, days)
        if isinstance(result, tuple):
            return (code, False, 0, result[1] if len(result) > 1 else 'retry failed')
        remote_df = result
        if remote_df is None or remote_df.empty:
            return (code, False, 0)

        combined = pd.concat([local_df, remote_df], ignore_index=True)
        combined = combined.drop_duplicates(subset='date', keep='last')
        combined = combined.sort_values('date')
        try:
            from kline_sanitize import sanitize_kline_df
            combined = sanitize_kline_df(combined)
        except Exception:
            pass

        new_count = len(combined)
        new_rows = new_count - old_count

        if new_rows > 0:
            combined.to_csv(csv_path, index=False)
            new_max = combined['date'].max().strftime('%Y-%m-%d')
            return (code, True, new_rows, new_max)
        return (code, False, 0)
    except Exception as e:
        return (code, False, 0, str(e))


def init_single_stock(code, days=120, backend='ifind'):
    """为无 CSV 的股票初始化历史 K 线"""
    try:
        csv_path = os.path.join(KLINEDIR, f'{code}.csv')
        if os.path.exists(csv_path):
            return (code, False, 0, 'exists')

        result = _fetch_kline(backend, code, days)
        if isinstance(result, tuple):
            return (code, False, 0, result[1] if len(result) > 1 else 'failed')
        if result is None or result.empty:
            return (code, False, 0, 'empty')

        df = result.copy()
        if 'date' not in df.columns:
            return (code, False, 0, 'no date col')
        df['date'] = pd.to_datetime(df['date'])
        df = df.drop_duplicates('date', keep='last').sort_values('date')
        os.makedirs(KLINEDIR, exist_ok=True)
        df.to_csv(csv_path, index=False)
        return (code, True, len(df), df['date'].max().strftime('%Y-%m-%d'))
    except Exception as e:
        return (code, False, 0, str(e))


def _get_pool_codes():
    from factor_data import get_stock_pool
    return get_stock_pool()


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--top', type=int, default=0)
    parser.add_argument('--days', type=int, default=30)
    parser.add_argument('--init-days', type=int, default=120, help='--init-missing 初始拉取天数')
    parser.add_argument('--workers', type=int, default=5)
    parser.add_argument('--backend', choices=['ifind', 'sina', 'baostock'], default=None)
    parser.add_argument('--init-missing', action='store_true', help='为 stock_pool 中无 CSV 的股票初始化K线')
    parser.add_argument('--sina-delay', type=float, default=0, help='新浪请求间隔秒数 (限流时用)')
    args = parser.parse_args()

    global _SINA_DELAY
    _SINA_DELAY = args.sina_delay

    backend = _get_backend(args.backend)
    logger.info(f"K线更新后端: {backend}")

    if args.init_missing:
        pool_codes = _get_pool_codes()
        existing = {f.replace('.csv', '') for f in os.listdir(KLINEDIR) if f.endswith('.csv')} if os.path.exists(KLINEDIR) else set()
        codes = [c for c in pool_codes if c not in existing]
        if args.top > 0:
            codes = codes[:args.top]
        logger.info(f"init-missing: {len(codes)} 只股票待初始化 (days={args.init_days})")
        worker_fn = init_single_stock
        worker_days = args.init_days
    else:
        csv_files = sorted([f for f in os.listdir(KLINEDIR) if f.endswith('.csv')])
        codes = [f.replace('.csv', '') for f in csv_files]
        if args.top > 0:
            codes = codes[:args.top]
        worker_fn = update_single_stock
        worker_days = args.days
        logger.info(f"Found {len(codes)} stocks to update (days={args.days}, workers={args.workers})")

    if not codes:
        logger.info('无待处理股票')
        return

    updated = 0
    failed = 0
    total_new_rows = 0
    start = time.time()

    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = {
            executor.submit(worker_fn, code, worker_days, backend): code
            for code in codes
        }

        for i, future in enumerate(as_completed(futures)):
            code = futures[future]
            try:
                result = future.result(timeout=60)
                if len(result) == 4:
                    c, success, rows, msg = result
                    if success and rows > 0:
                        updated += 1
                        total_new_rows += rows
                        logger.info(f"[{i+1}/{len(codes)}] {c}: +{rows} rows -> {msg}")
                    elif not success and isinstance(msg, str) and msg:
                        failed += 1
                else:
                    c, success, rows = result
                    if success and rows > 0:
                        updated += 1
                        total_new_rows += rows
                    else:
                        failed += 1
            except Exception as e:
                failed += 1
                logger.warning(f"Worker error {code}: {e}")

            if (i + 1) % 50 == 0:
                elapsed = time.time() - start
                rate = (i + 1) / elapsed if elapsed > 0 else 0
                eta = (len(codes) - i - 1) / rate if rate > 0 else 0
                logger.info(
                    f"Progress: {i+1}/{len(codes)} updated={updated} failed={failed} "
                    f"({rate:.1f}/s, ETA {eta:.0f}s)"
                )

    elapsed = time.time() - start
    logger.info('=' * 60)
    logger.info(
        f"Complete! backend={backend} Time={elapsed:.0f}s, "
        f"Updated={updated}, Failed={failed}, New rows={total_new_rows}"
    )


if __name__ == '__main__':
    main()
