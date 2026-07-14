#!/usr/bin/env python3
"""
批量更新K线缓存 - 支持 新浪 / BaoStock 双后端

用法:
    python update_kline.py              # 按 settings.yaml data.kline_backend 选择后端
    python update_kline.py --backend sina # 强制新浪
    python update_kline.py --top 100      # 只更新前100只（测试用）
"""
import os
import sys
import time
import logging
import pandas as pd
from datetime import datetime, timedelta
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
    return 'sina'


def _baostock_query_to_df(bs, code: str, days: int = 120):
    end = datetime.now().strftime('%Y-%m-%d')
    start = (datetime.now() - timedelta(days=int(days * 1.6))).strftime('%Y-%m-%d')
    full = f"sh.{code}" if code.startswith('6') else f"sz.{code}"
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


def _fetch_kline_baostock(code: str, days: int = 120):
    import baostock as bs
    bs.login()
    try:
        return _baostock_query_to_df(bs, code, days)
    finally:
        bs.logout()


def _fetch_kline_akshare(code: str, days: int = 120):
    """Fetch the Eastmoney history used by AKShare, with an explicit timeout."""
    import requests

    start = (datetime.now() - timedelta(days=int(days * 1.8))).strftime('%Y%m%d')
    end = datetime.now().strftime('%Y%m%d')
    market = "1" if code.startswith("6") else "0"
    response = requests.get(
        "https://push2his.eastmoney.com/api/qt/stock/kline/get",
        params={
            "secid": f"{market}.{code}",
            "fields1": "f1,f2,f3,f4,f5,f6",
            "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
            "klt": "101",
            "fqt": "0",
            "beg": start,
            "end": end,
            "lmt": str(max(days, 120)),
        },
        headers={"User-Agent": "Mozilla/5.0", "Referer": "https://quote.eastmoney.com/"},
        timeout=(5, 15),
    )
    response.raise_for_status()
    klines = ((response.json().get("data") or {}).get("klines") or [])
    if not klines:
        return None
    rows = [line.split(",") for line in klines]
    df = pd.DataFrame(rows, columns=[
        "date", "open", "close", "high", "low", "volume", "amount",
        "amplitude", "change_pct", "change", "turnover",
    ])
    df = df[['date', 'open', 'high', 'low', 'close', 'volume', 'amount', 'change_pct']].copy()
    df['date'] = pd.to_datetime(df['date'])
    for c in ['open', 'high', 'low', 'close', 'volume', 'amount', 'change_pct']:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors='coerce')
    df['stock_code'] = code
    return df.sort_values('date').tail(days)


def _fetch_kline(backend: str, code: str, days: int, max_retries: int = 3):
    original = backend
    for attempt in range(max_retries):
        try:
            if backend == 'baostock':
                df = _fetch_kline_baostock(code, days)
                return df if df is not None and not df.empty else None
            if backend == 'akshare':
                df = _fetch_kline_akshare(code, days)
                return df if df is not None and not df.empty else None
            if backend == 'sina' or original == 'sina':
                from sina_fetcher import SinaFetcher
                if _SINA_DELAY > 0:
                    time.sleep(_SINA_DELAY)
                df = SinaFetcher()._fetch_sina_historical(code, days)
                if df is not None and not df.empty:
                    return df
        except Exception as e:
            if attempt < max_retries - 1:
                time.sleep(1.0 * (attempt + 1))
            else:
                return None, str(e)
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


def init_single_stock(code, days=120, backend='sina'):
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


def init_missing_baostock_batch(codes, days=120):
    """单次登录 BaoStock 批量初始化缺失 K 线。"""
    import baostock as bs

    updated = 0
    failed = 0
    total_rows = 0
    start_ts = time.time()
    os.makedirs(KLINEDIR, exist_ok=True)
    bs.login()
    try:
        for i, code in enumerate(codes, 1):
            csv_path = os.path.join(KLINEDIR, f'{code}.csv')
            if os.path.exists(csv_path):
                continue
            try:
                df = _baostock_query_to_df(bs, code, days)
                if df is None or df.empty or 'date' not in df.columns:
                    failed += 1
                    continue
                df = df.drop_duplicates('date', keep='last').sort_values('date')
                df.to_csv(csv_path, index=False)
                updated += 1
                total_rows += len(df)
            except Exception as e:
                failed += 1
                if failed <= 10:
                    logger.warning(f"{code}: {e}")

            if i % 50 == 0:
                elapsed = time.time() - start_ts
                rate = i / elapsed if elapsed > 0 else 0
                eta = (len(codes) - i) / rate if rate > 0 else 0
                logger.info(
                    f"Progress: {i}/{len(codes)} updated={updated} failed={failed} "
                    f"({rate:.1f}/s, ETA {eta:.0f}s)"
                )
    finally:
        bs.logout()
    return updated, failed, total_rows


def update_baostock_batch(codes, days=30):
    """Single-login BaoStock refresh to avoid concurrent login failures."""
    import baostock as bs

    updated = 0
    failed = 0
    total_rows = 0
    start_ts = time.time()
    bs.login()
    try:
        for i, code in enumerate(codes, 1):
            path = os.path.join(KLINEDIR, f"{code}.csv")
            try:
                local = pd.read_csv(path)
                local["date"] = pd.to_datetime(local["date"])
                remote = _baostock_query_to_df(bs, code, days)
                if remote is None or remote.empty:
                    failed += 1
                    continue
                combined = pd.concat([local, remote], ignore_index=True)
                combined = combined.drop_duplicates("date", keep="last").sort_values("date")
                new_rows = len(combined) - len(local)
                if new_rows > 0:
                    combined.to_csv(path, index=False)
                    updated += 1
                    total_rows += new_rows
            except Exception as exc:
                failed += 1
                if failed <= 10:
                    logger.warning("%s: %s", code, exc)
            if i % 100 == 0:
                elapsed = time.time() - start_ts
                rate = i / elapsed if elapsed else 0
                eta = (len(codes) - i) / rate if rate else 0
                logger.info(
                    "Progress: %d/%d updated=%d failed=%d (%.1f/s, ETA %.0fs)",
                    i, len(codes), updated, failed, rate, eta,
                )
    finally:
        bs.logout()
    return updated, failed, total_rows


def update_from_realtime_snapshot(codes):
    """Append the latest completed market snapshot to existing daily CSVs."""
    from sina_fetcher import SinaFetcher

    quotes = SinaFetcher().get_realtime_quotes(codes)
    if quotes is None or quotes.empty:
        raise RuntimeError("全市场行情快照为空")
    quote_map = {
        str(row["code"]): row
        for _, row in quotes.iterrows()
        if row.get("date") and float(row.get("close") or 0) > 0
    }
    updated = 0
    failed = 0
    for code in codes:
        row = quote_map.get(code)
        path = os.path.join(KLINEDIR, f"{code}.csv")
        if row is None:
            failed += 1
            continue
        try:
            local = pd.read_csv(path)
            local["date"] = pd.to_datetime(local["date"])
            quote_date = pd.to_datetime(str(row["date"])[:10])
            latest = local["date"].max() if not local.empty else None
            if latest is not None and quote_date <= latest:
                continue
            daily = pd.DataFrame([{
                "date": quote_date,
                "open": row.get("open"),
                "high": row.get("high"),
                "low": row.get("low"),
                "close": row.get("close"),
                "volume": row.get("volume"),
                "amount": row.get("amount"),
                "change_pct": row.get("change_pct"),
                "stock_code": code,
            }])
            combined = pd.concat([local, daily], ignore_index=True)
            combined = combined.drop_duplicates("date", keep="last").sort_values("date")
            combined.to_csv(path, index=False)
            updated += 1
        except Exception as exc:
            failed += 1
            if failed <= 10:
                logger.warning("%s: %s", code, exc)
    return updated, failed, updated


def _get_pool_codes():
    from factor_data import get_stock_pool
    return get_stock_pool()


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--top', type=int, default=0)
    parser.add_argument('--offset', type=int, default=0, help='跳过前 N 只股票，便于分批初始化')
    parser.add_argument('--days', type=int, default=30)
    parser.add_argument('--init-days', type=int, default=120, help='--init-missing 初始拉取天数')
    parser.add_argument('--workers', type=int, default=5)
    parser.add_argument('--backend', choices=['sina', 'baostock', 'akshare'], default=None)
    parser.add_argument('--init-missing', action='store_true', help='为 stock_pool 中无 CSV 的股票初始化K线')
    parser.add_argument('--sina-delay', type=float, default=0, help='新浪请求间隔秒数 (限流时用)')
    parser.add_argument('--snapshot', action='store_true', help='用全市场实时快照批量追加最新日K')
    args = parser.parse_args()

    global _SINA_DELAY
    _SINA_DELAY = args.sina_delay

    backend = _get_backend(args.backend)
    logger.info(f"K线更新后端: {backend}")

    if args.init_missing:
        pool_codes = _get_pool_codes()
        existing = {f.replace('.csv', '') for f in os.listdir(KLINEDIR) if f.endswith('.csv')} if os.path.exists(KLINEDIR) else set()
        codes = [c for c in pool_codes if c not in existing]
        if args.offset > 0:
            codes = codes[args.offset:]
        if args.top > 0:
            codes = codes[:args.top]
        logger.info(f"init-missing: {len(codes)} 只股票待初始化 (days={args.init_days})")
        if backend == 'baostock':
            updated, failed, total_new_rows = init_missing_baostock_batch(codes, args.init_days)
            logger.info('=' * 60)
            logger.info(
                f"Complete! backend={backend} Updated={updated}, Failed={failed}, New rows={total_new_rows}"
            )
            return
        worker_fn = init_single_stock
        worker_days = args.init_days
    else:
        csv_files = sorted([f for f in os.listdir(KLINEDIR) if f.endswith('.csv')])
        codes = [f.replace('.csv', '') for f in csv_files]
        if args.offset > 0:
            codes = codes[args.offset:]
        if args.top > 0:
            codes = codes[:args.top]
        worker_fn = update_single_stock
        worker_days = args.days
        logger.info(f"Found {len(codes)} stocks to update (days={args.days}, workers={args.workers})")
        if args.snapshot:
            updated, failed, total_new_rows = update_from_realtime_snapshot(codes)
            logger.info('=' * 60)
            logger.info(
                "Complete! backend=snapshot Updated=%d, Failed=%d, New rows=%d",
                updated, failed, total_new_rows,
            )
            return
        if backend == 'baostock':
            updated, failed, total_new_rows = update_baostock_batch(codes, args.days)
            logger.info('=' * 60)
            logger.info(
                "Complete! backend=%s Updated=%d, Failed=%d, New rows=%d",
                backend, updated, failed, total_new_rows,
            )
            return

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
