#!/usr/bin/env python3
"""从 K 线历史构建 DL 因子训练集

用法:
  python scripts/build_dl_dataset.py --start 2023-01-01 --end 2025-12-31 --pool-top 500
"""
from __future__ import annotations

import argparse
import json
import os
import sys

import numpy as np

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

from dl_factor_model import DLFactorSelector, FEATURE_NAMES


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", default="2024-01-01")
    parser.add_argument("--end", default="2025-12-31")
    parser.add_argument("--pool-top", type=int, default=500)
    parser.add_argument("--label-days", type=int, default=5)
    parser.add_argument("--sample-step", type=int, default=3, help="每N个交易日采样一次")
    parser.add_argument("--out", default=None)
    args = parser.parse_args()

    from backtest_v2 import (
        load_stock_pool,
        load_kline,
        build_date_index,
        build_trading_dates,
        compute_pv_from_df,
        load_fundamentals_cache,
        load_industry_map,
        compute_sector_data,
        select_pool_by_liquidity,
    )
    from factor_engine_v2 import FactorEngine
    from datetime import timedelta, datetime

    out_path = args.out or os.path.join(BASE, "data", "ml_models", "dl_train_dataset.npz")

    warmup = (datetime.strptime(args.start, "%Y-%m-%d") - timedelta(days=120)).strftime("%Y-%m-%d")
    codes = load_stock_pool()
    kline = {}
    for c in codes:
        df = load_kline(c, warmup, args.end)
        if df is not None:
            kline[c] = df
    if args.pool_top:
        codes = select_pool_by_liquidity(list(kline.keys()), kline, args.pool_top)
        kline = {c: kline[c] for c in codes}

    date_idx = build_date_index(kline)
    dates = build_trading_dates(args.start, args.end)
    dates = [d for d in dates if d in date_idx.get("000001", {})]
    fund_cache = load_fundamentals_cache(codes)
    industry_map = load_industry_map()
    engine = FactorEngine()
    sel = DLFactorSelector()

    X_list, y_list, meta_rows = [], [], []

    for di, date in enumerate(dates):
        if di % args.sample_step != 0:
            continue
        sector_data = compute_sector_data(kline, date_idx, date, industry_map)
        for code in codes:
            idx = date_idx.get(code, {}).get(date)
            df = kline.get(code)
            if idx is None or df is None or idx + args.label_days >= len(df):
                continue
            pv = compute_pv_from_df(df, idx)
            if not pv:
                continue
            fund = fund_cache.get(code, {})
            extra = {"market_cap": 100}
            if fund.get("total_share") and pv.get("price"):
                extra["market_cap"] = fund["total_share"] * pv["price"] / 1e8
            r = engine.score_stock(code, pv, fund, sector_data, {})
            r["price_volume"] = pv
            r["extra"] = extra
            r["industry"] = industry_map.get(code, "")

            feat = sel.build_matrix([r], sector_data)[1]
            if feat.size == 0:
                continue
            cur = float(df.iloc[idx]["close"])
            fut = float(df.iloc[idx + args.label_days]["close"])
            if cur <= 0:
                continue
            ret = (fut - cur) / cur
            label = 1.0 if ret > 0.01 else 0.0

            X_list.append(feat[0])
            y_list.append(label)
            meta_rows.append({"date": date, "code": code, "ret": round(ret, 4)})

        if di % 60 == 0:
            print(f"  {date}: 累计 {len(X_list)} 样本")

    X = np.array(X_list, dtype=np.float64)
    y = np.array(y_list, dtype=np.float64)
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    np.savez(out_path, X=X, y=y)
    with open(out_path.replace(".npz", "_meta.json"), "w") as f:
        json.dump({"n": len(y), "pos_rate": float(y.mean()), "samples": meta_rows[-20:]}, f, indent=2)
    print(f"数据集: {out_path} | 样本 {len(y)} | 正类率 {y.mean():.1%}")


if __name__ == "__main__":
    main()
