"""
历史数据加载器 - BaoStock 版本

功能:
1. 从 BaoStock 批量下载个股历史K线
2. 缓存为本地 CSV 文件（按股票代码命名）
3. 支持增量更新（只下载缺失的日期）
4. 列名统一为英文标准格式
5. 过滤科创板/北交所
6. 支持从本地缓存加载股票池（当 BaoStock 不可用时）

用法:
    loader = HistoricalDataLoader()
    loader.download_stock_pool(top_n=100, start_date='2024-01-01')
    data = loader.load_all()  # {stock_code: DataFrame}
"""

import os
import json
import time
import logging
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

from baostock_fetcher import BaoStockFetcher

logger = logging.getLogger(__name__)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, 'data', 'kline')
os.makedirs(DATA_DIR, exist_ok=True)


class HistoricalDataLoader:
    """历史K线数据加载器"""

    def __init__(self, data_dir=None):
        self.data_dir = data_dir or DATA_DIR
        os.makedirs(self.data_dir, exist_ok=True)
        self.fetcher = BaoStockFetcher()

    def login(self):
        """登录 BaoStock"""
        self.fetcher.login()

    def logout(self):
        """退出 BaoStock"""
        self.fetcher.logout()

    def get_stock_pool(self, date=None):
        """获取股票池"""
        return self.fetcher.get_stock_pool(date=date)

    def _load_cached_stock_pool(self) -> pd.DataFrame:
        """从本地缓存加载股票池 (当 BaoStock 不可用时的回退方案)"""
        manifest_path = os.path.join(os.path.dirname(self.data_dir), 'stock_pool.json')
        if not os.path.exists(manifest_path):
            logger.warning(f"本地缓存不存在: {manifest_path}")
            return pd.DataFrame()

        try:
            with open(manifest_path, 'r', encoding='utf-8') as f:
                records = json.load(f)

            if not records:
                return pd.DataFrame()

            df = pd.DataFrame(records)

            # 统一字段名: code_name -> name
            if 'code_name' in df.columns and 'name' not in df.columns:
                df['name'] = df['code_name']

            # 确保有 code 和 name 字段
            if 'code' in df.columns and 'name' in df.columns:
                df = df[['code', 'name']].copy()
                return df
            else:
                logger.warning(f"stock_pool.json 缺少必要字段: {list(df.columns)}")
                return pd.DataFrame()
        except Exception as e:
            logger.error(f"加载本地缓存股票池失败: {e}")
            return pd.DataFrame()

    def download_stock_kline(self, stock_code, stock_name='',
                             start_date='2023-01-01', end_date=None,
                             force=False) -> pd.DataFrame:
        """下载单只股票的历史K线数据"""
        if end_date is None:
            end_date = datetime.now().strftime('%Y-%m-%d')

        csv_path = os.path.join(self.data_dir, f"{stock_code}.csv")

        # 检查缓存是否需要增量更新
        if not force and os.path.exists(csv_path):
            cached = pd.read_csv(csv_path)
            if not cached.empty and 'date' in cached.columns:
                last_date = pd.to_datetime(cached['date']).max().strftime('%Y-%m-%d')
                if last_date >= end_date:
                    return cached
                start_date = last_date  # 增量更新

        # 获取K线数据
        logger.info(f"下载 {stock_code} {stock_name} ({start_date} ~ {end_date})")
        df = self.fetcher.get_daily_kline(
            stock_code,
            days=(datetime.now() - datetime.strptime(start_date, '%Y-%m-%d')).days + 30
        )

        if df.empty:
            logger.warning(f"{stock_code} 无数据")
            return pd.DataFrame()

        # 过滤日期范围 (date是字符串格式)
        start_str = pd.to_datetime(start_date).strftime('%Y-%m-%d')
        end_str = pd.to_datetime(end_date).strftime('%Y-%m-%d')
        df = df[(df['date'] >= start_str) & (df['date'] <= end_str)]
        df = df.sort_values('date').reset_index(drop=True)

        # 如果有缓存，合并
        if not force and os.path.exists(csv_path):
            cached = pd.read_csv(csv_path)
            if 'date' in cached.columns:
                df = pd.concat([cached, df], ignore_index=True)
                df = df.drop_duplicates(subset=['date'], keep='last')
                df = df.sort_values('date').reset_index(drop=True)

        # 保存
        save_df = df[['date', 'stock_code', 'open', 'high', 'low', 'close',
                       'volume', 'amount', 'change_pct', 'turnover']].copy()
        save_df.to_csv(csv_path, index=False)
        logger.info(f"  保存 {len(save_df)} 条记录 -> {csv_path}")

        return df

    def download_stock_pool(self, top_n=None, start_date='2023-01-01',
                            end_date=None, force=False, delay=0.15) -> dict:
        """批量下载股票池的历史数据"""
        self.login()

        pool = self.get_stock_pool()
        if pool.empty:
            # 回退到本地缓存的股票池
            logger.warning("BaoStock 股票池为空，尝试从本地缓存加载...")
            pool = self._load_cached_stock_pool()
            if pool.empty:
                logger.error("本地缓存的股票池也为空")
                self.logout()
                return {}
            logger.info(f"从本地缓存加载股票池: {len(pool)} 只")

        logger.info(f"股票池: {len(pool)} 只")

        # 保存股票池清单
        self.fetcher.save_stock_pool_manifest(pool)

        if top_n:
            pool = pool.head(top_n)
            logger.info(f"选取前 {top_n} 只")

        results = {}
        total = len(pool)

        for i, (_, row) in enumerate(pool.iterrows()):
            code = str(row['code'])
            name = str(row.get('name', ''))

            logger.info(f"[{i + 1}/{total}] {code} {name}")

            df = self.download_stock_kline(code, name, start_date, end_date, force)
            if not df.empty:
                results[code] = df

            time.sleep(delay)

        self.logout()
        logger.info(f"完成! 共下载 {len(results)} 只股票")
        return results

    def load_cached(self, stock_code) -> pd.DataFrame:
        """加载缓存的K线数据"""
        csv_path = os.path.join(self.data_dir, f"{stock_code}.csv")
        if not os.path.exists(csv_path):
            return pd.DataFrame()
        return pd.read_csv(csv_path)

    def load_all(self, stock_codes=None) -> dict:
        """加载所有缓存的K线数据"""
        results = {}

        if stock_codes:
            files = [f"{code}.csv" for code in stock_codes]
        else:
            files = [f for f in os.listdir(self.data_dir) if f.endswith('.csv')]

        for f in files:
            code = f.replace('.csv', '')
            try:
                df = pd.read_csv(os.path.join(self.data_dir, f))
                if not df.empty:
                    results[code] = df
            except Exception as e:
                logger.warning(f"加载 {f} 失败: {e}")

        logger.info(f"加载 {len(results)} 只股票的缓存数据")
        return results

    def get_trading_dates(self, stock_data=None, min_coverage=0.8) -> list:
        """
        获取交易日列表（宽松模式：至少 min_coverage 比例的股票有数据）

        参数:
            stock_data: {code: DataFrame}
            min_coverage: 最小覆盖率 (默认0.8=80%的股票有数据即视为有效交易日)
        """
        if stock_data is None:
            stock_data = self.load_all()

        if not stock_data:
            return []

        date_sets = []
        for code, df in stock_data.items():
            if 'date' in df.columns:
                date_sets.append(set(pd.to_datetime(df['date']).dt.strftime('%Y-%m-%d')))

        if not date_sets:
            return []

        total_stocks = len(date_sets)
        min_count = max(100, int(total_stocks * min_coverage))  # 至少100只

        # 统计每个日期有多少股票有数据
        date_counter = {}
        for ds in date_sets:
            for d in ds:
                date_counter[d] = date_counter.get(d, 0) + 1

        # 过滤掉不满足覆盖率要求的日期
        valid_dates = [d for d, count in date_counter.items() if count >= min_count]

        return sorted(valid_dates)
