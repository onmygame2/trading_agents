#!/usr/bin/env python3
"""
批量更新K线缓存 - 使用新浪API（BaoStock已停服）

用法:
    python update_kline_sina.py              # 更新全部
    python update_kline_sina.py --top 100    # 只更新前100只（测试用）
"""
import os, sys, time, logging
import pandas as pd
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger(__name__)

from sina_fetcher import SinaFetcher, KLINEDIR

def fetch_with_retry(fetcher, code, days, max_retries=3):
    """Fetch with exponential backoff retry"""
    for attempt in range(max_retries):
        try:
            df = fetcher._fetch_sina_historical(code, days)
            if df is not None and not df.empty:
                return df
        except Exception as e:
            if attempt < max_retries - 1:
                time.sleep(0.5 * (attempt + 1))  # 0.5s, 1.0s, 1.5s
            else:
                return None, str(e)
    return None

def update_single_stock(code, days=30):
    """Update kline for a single stock, return (code, success, new_rows)"""
    try:
        csv_path = os.path.join(KLINEDIR, f'{code}.csv')
        if not os.path.exists(csv_path):
            return (code, False, 0)

        # Read existing
        local_df = pd.read_csv(csv_path)
        local_df['date'] = pd.to_datetime(local_df['date'])
        old_count = len(local_df)

        # Create per-stock fetcher to avoid shared state issues
        from sina_fetcher import SinaFetcher
        fetcher = SinaFetcher()

        # Fetch from Sina with retry
        result = fetch_with_retry(fetcher, code, days)
        if isinstance(result, tuple):
            return (code, False, 0, result[1] if len(result) > 1 else 'retry failed')
        sina_df = result
        if sina_df is None or sina_df.empty:
            return (code, False, 0)

        # Merge: sina is latest, keep both (dedup by date, keep sina's version)
        combined = pd.concat([local_df, sina_df], ignore_index=True)
        combined = combined.drop_duplicates(subset='date', keep='last')
        combined = combined.sort_values('date')

        new_count = len(combined)
        new_rows = new_count - old_count

        if new_rows > 0:
            combined.to_csv(csv_path, index=False)
            new_max = combined['date'].max().strftime('%Y-%m-%d')
            return (code, True, new_rows, new_max)
        else:
            return (code, False, 0)
    except Exception as e:
        return (code, False, 0, str(e))

def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--top', type=int, default=0, help='Only update top N stocks (for testing)')
    parser.add_argument('--days', type=int, default=30, help='Days of recent data to fetch')
    parser.add_argument('--workers', type=int, default=5, help='Concurrent workers')
    args = parser.parse_args()

    fetcher = SinaFetcher()

    # Get stock codes from existing CSV files
    csv_files = sorted([f for f in os.listdir(KLINEDIR) if f.endswith('.csv')])
    codes = [f.replace('.csv', '') for f in csv_files]

    if args.top > 0:
        codes = codes[:args.top]

    logger.info(f"Found {len(codes)} stocks to update (days={args.days}, workers={args.workers})")

    updated = 0
    failed = 0
    total_new_rows = 0
    start = time.time()

    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = {executor.submit(update_single_stock, code, args.days): code
                   for code in codes}

        for i, future in enumerate(as_completed(futures)):
            code = futures[future]
            try:
                result = future.result(timeout=30)
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
                logger.info(f"Progress: {i+1}/{len(codes)} updated={updated} failed={failed} ({rate:.1f}/s, ETA {eta:.0f}s)")

    elapsed = time.time() - start
    logger.info(f"=" * 60)
    logger.info(f"Complete! Time={elapsed:.0f}s, Updated={updated}, Failed={failed}, New rows={total_new_rows}")
    logger.info(f"Rate: {len(codes)/elapsed:.1f} stocks/sec")

if __name__ == '__main__':
    main()
