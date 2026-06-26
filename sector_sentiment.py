"""
Sector Sentiment Module for A-Share Quant Trading System

Tracks sector hotness and predicts next-hot sectors using:
  1. Recent price momentum of sectors (from stock kline data)
  2. Volume anomalies by sector
  3. News keyword analysis (simple keyword-based scoring)

Data layout:
  - Kline CSVs:  data/kline/{code}.csv  (date,stock_code,open,high,low,close,volume,amount,change_pct,turnover)
  - Industry map: data/stock_pool.json  (list of {code, code_name, industry_code, industry_name, exchange})

Author: Hermes Agent
"""

import os
import json
import time
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional
import pandas as pd
import numpy as np


# ---------------------------------------------------------------------------
# News keyword map: sector category -> list of hot-topic keywords (Chinese)
# ---------------------------------------------------------------------------
NEWS_KEYWORDS: Dict[str, List[str]] = {
    # AI / Technology
    "AI": ["人工智能", "大模型", "算力", "AI", "芯片", "GPU", "生成式", "深度学习", "智能驾驶", "机器人"],
    "半导体": ["半导体", "芯片", "晶圆", "光刻机", "EDA", "封测", "先进封装", "国产替代"],
    "软件": ["软件", "信创", "操作系统", "数据库", "中间件", "SaaS", "云计算", "云原生"],

    # New Energy
    "新能源": ["光伏", "锂电", "储能", "风电", "氢能", "储能电池", "逆变器", "组件"],
    "新能源汽车": ["电动车", "新能源车", "动力电池", "充电桩", "特斯拉", "比亚迪", "整车"],
    "电池": ["电池", "锂电", "磷酸铁锂", "三元", "固态电池", "钠离子"],

    # Consumer / Daily
    "消费": ["消费", "白酒", "食品饮料", "零售", "电商", "直播", "拼多多", "抖音"],
    "医药": ["医药", "创新药", "CXO", "医疗器械", "生物", "基因", "疫苗", "中药"],
    "旅游": ["旅游", "酒店", "航空", "免税", "出境游", "文旅"],

    # Finance / Insurance
    "金融": ["金融", "银行", "券商", "保险", "信托", "金融科技"],
    "保险": ["保险", "寿险", "财险", "健康险"],

    # Real Estate / Infrastructure
    "房地产": ["房地产", "地产", "物业", "房贷", "城中村"],
    "基建": ["基建", "水泥", "钢铁", "建筑", "工程机械", "一带一路", "高铁"],

    # Materials / Resources
    "有色": ["有色", "稀土", "铜", "铝", "黄金", "锂矿", "钴", "钼"],
    "化工": ["化工", "石化", "新材料", "塑料", "橡胶", "农药", "化肥"],

    # Media / Culture
    "传媒": ["传媒", "游戏", "影视", "短视频", "元宇宙", "VR", "AR", "数字"],
    "军工": ["军工", "航天", "航空发动机", "导弹", "卫星", "国防", "低空经济"],

    # Agriculture
    "农业": ["农业", "种子", "化肥", "粮食", "生猪", "养殖", "粮食安全"],

    # Others
    "低空经济": ["低空经济", "飞行汽车", "eVTOL", "无人机", "直升机"],
    "数据要素": ["数据要素", "数据资产", "数据确权", "数字经济", "数据交易所"],
}


class SectorSentiment:
    """Analyze sector-level momentum, volume anomalies, and news sentiment."""

    def __init__(self, data_dir: str):
        """
        Initialize with path to the data directory.

        Args:
            data_dir: Path to the data directory containing kline/ and stock_pool.json
        """
        self.data_dir = data_dir
        self.kline_dir = os.path.join(data_dir, "kline")

        # Load industry mapping from stock_pool.json
        self._industry_map: Dict[str, str] = {}       # code -> industry_code
        self._stock_names: Dict[str, str] = {}         # code -> code_name
        self._sector_stocks: Dict[str, List[str]] = {} # industry_code -> [codes]
        self._load_industry_mapping()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _load_industry_mapping(self):
        """Load stock -> industry mapping from stock_pool.json."""
        pool_path = os.path.join(self.data_dir, "stock_pool.json")
        if not os.path.exists(pool_path):
            print(f"[SectorSentiment] Warning: {pool_path} not found, sector mapping disabled.")
            return
        with open(pool_path, "r", encoding="utf-8") as f:
            pool = json.load(f)
        for item in pool:
            code = item["code"]
            ind = item.get("industry_code", "未知行业")
            name = item.get("code_name", "")
            self._industry_map[code] = ind
            self._stock_names[code] = name
            self._sector_stocks.setdefault(ind, []).append(code)

    def _load_stock_kline(self, code: str) -> Optional[pd.DataFrame]:
        """Load kline CSV for a single stock code, return DataFrame or None."""
        csv_path = os.path.join(self.kline_dir, f"{code}.csv")
        if not os.path.exists(csv_path):
            return None
        try:
            df = pd.read_csv(csv_path, dtype={"date": str, "stock_code": str})
            return df
        except Exception:
            return None

    def _get_exchange_from_code(self, code: str) -> str:
        """Infer exchange from stock code prefix."""
        prefix = code[:3]
        if prefix in ("600", "601", "603", "605"):
            return "SH"
        elif prefix in ("000", "001"):
            return "SZ_main"
        elif prefix == "002":
            return "SZ_sme"
        elif prefix in ("300", "301"):
            return "SZ_chixnext"
        return "unknown"

    def _get_industry_for_code(self, code: str) -> str:
        """Get industry for a stock code, falling back to prefix-based grouping."""
        if code in self._industry_map:
            return self._industry_map[code]
        # Fallback: group by exchange prefix
        ex = self._get_exchange_from_code(code)
        return f"未知-{ex}"

    def _compute_return_series(self, df: pd.DataFrame, days: int) -> float:
        """Compute N-day cumulative return from the last row."""
        if df is None or len(df) < days + 1:
            return 0.0
        recent = df.tail(days + 1)
        if recent.iloc[0]["close"] == 0:
            return 0.0
        return (recent.iloc[-1]["close"] - recent.iloc[0]["close"]) / recent.iloc[0]["close"]

    def _compute_vol_ratio(self, df: pd.DataFrame, window: int = 5, lookback: int = 20) -> float:
        """Volume ratio: average volume of last `window` days / average volume of last `lookback` days."""
        if df is None or len(df) < lookback:
            return 1.0
        recent_vol = df.tail(window)["volume"].mean()
        hist_vol = df.tail(lookback)["volume"].mean()
        if hist_vol == 0:
            return 1.0
        return recent_vol / hist_vol

    def _price_near_low_ratio(self, df: pd.DataFrame, lookback: int = 20) -> float:
        """How close the current price is to the N-day low (0=at low, 1=at high)."""
        if df is None or len(df) < lookback:
            return 0.5
        recent = df.tail(lookback)
        high = recent["high"].max()
        low = recent["low"].min()
        current = df.iloc[-1]["close"]
        if high == low:
            return 0.5
        return (current - low) / (high - low)


    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def analyze_sector_momentum(self, stock_data: Optional[Dict[str, pd.DataFrame]] = None,
                                date: Optional[str] = None,
                                days_list: List[int] = (5, 10, 20)) -> List[Dict]:
        """
        Calculate sector-level momentum from individual stock data.

        For each sector, compute a weighted momentum score across multiple
        lookback windows, then rank sectors by score descending.

        Args:
            stock_data: Optional pre-loaded dict of code -> DataFrame. If None, loads from disk.
            date: Target date string (YYYY-MM-DD). Uses latest available if None.
            days_list: List of lookback windows for momentum calculation.

        Returns:
            List of dicts sorted by momentum score descending, each containing:
            - sector: industry code
            - momentum_score: weighted composite score
            - returns: dict of window -> return value
            - stock_count: number of stocks in this sector
            - avg_return: simple average of all window returns
        """
        # Load stock_data if not provided
        if stock_data is None:
            stock_data = self._load_all_available_klines(date)

        # Group stocks by sector and compute momentum
        sector_data: Dict[str, Dict] = {}
        for code, df in stock_data.items():
            if df is None or len(df) < max(days_list) + 1:
                continue
            sector = self._get_industry_for_code(code)

            if sector not in sector_data:
                sector_data[sector] = {"stocks": [], "returns": {d: [] for d in days_list}}

            for d in days_list:
                ret = self._compute_return_series(df, d)
                sector_data[sector]["returns"][d].append(ret)

            sector_data[sector]["stocks"].append(code)

        # Compute composite momentum score per sector
        results = []
        weights = [3, 2, 1]  # shorter windows weighted more (5d > 10d > 20d)
        for sector, info in sector_data.items():
            if not info["stocks"]:
                continue
            ret_list = info["returns"]
            scores = []
            all_returns = []
            for d, w in zip(days_list, weights):
                vals = ret_list.get(d, [])
                if vals:
                    avg = np.mean(vals)
                    scores.append(avg * w)
                    all_returns.extend(vals)

            momentum_score = np.mean(scores) if scores else 0.0
            avg_return = np.mean(all_returns) if all_returns else 0.0

            results.append({
                "sector": sector,
                "momentum_score": round(float(momentum_score), 6),
                "returns": {str(k): round(float(np.mean(v)), 6) for k, v in ret_list.items() if v},
                "stock_count": len(info["stocks"]),
                "avg_return": round(float(avg_return), 6),
            })

        # Sort by momentum score descending
        results.sort(key=lambda x: x["momentum_score"], reverse=True)
        return results

    def get_hot_sectors(self, stock_data: Optional[Dict[str, pd.DataFrame]] = None,
                        date: Optional[str] = None,
                        top_n: int = 5) -> List[Dict]:
        """
        Return top N hottest sectors with score, stock_count, avg_return.

        Combines momentum score and volume anomaly ratio for a composite hotness score.

        Args:
            stock_data: Optional pre-loaded dict of code -> DataFrame.
            date: Target date string.
            top_n: Number of top sectors to return.

        Returns:
            List of dicts with sector, hot_score, momentum_score, vol_ratio,
            stock_count, avg_return, top_stocks (top 3 performing stocks).
        """
        if stock_data is None:
            stock_data = self._load_all_available_klines(date)

        # Rebuild sector-level stats including volume
        sector_stats: Dict[str, Dict] = {}
        for code, df in stock_data.items():
            if df is None or len(df) < 21:
                continue
            sector = self._get_industry_for_code(code)
            if sector not in sector_stats:
                sector_stats[sector] = {
                    "returns_5d": [], "returns_10d": [], "vol_ratios": [],
                    "stocks": [], "stock_returns": [],
                }

            ret5 = self._compute_return_series(df, 5)
            ret10 = self._compute_return_series(df, 10)
            vr = self._compute_vol_ratio(df)
            sector_stats[sector]["returns_5d"].append(ret5)
            sector_stats[sector]["returns_10d"].append(ret10)
            sector_stats[sector]["vol_ratios"].append(vr)
            sector_stats[sector]["stocks"].append(code)
            sector_stats[sector]["stock_returns"].append((code, ret5))

        results = []
        for sector, stats in sector_stats.items():
            if not stats["stocks"]:
                continue
            avg_ret = np.mean(stats["returns_5d"]) if stats["returns_5d"] else 0.0
            momentum = np.mean(stats["returns_5d"]) * 0.6 + np.mean(stats["returns_10d"]) * 0.4
            vol_ratio = np.mean(stats["vol_ratios"]) if stats["vol_ratios"] else 1.0

            # Hot score: weighted combination of momentum and volume anomaly
            # Normalize vol_ratio impact: vol_ratio > 1.5 is significant
            vol_factor = max(0, (vol_ratio - 1.0) / 2.0)
            hot_score = momentum + vol_factor * 0.05

            # Get top performing stocks in this sector
            top_stocks = sorted(stats["stock_returns"], key=lambda x: x[1], reverse=True)[:3]

            results.append({
                "sector": sector,
                "hot_score": round(float(hot_score), 6),
                "momentum_score": round(float(momentum), 6),
                "vol_ratio": round(float(vol_ratio), 4),
                "stock_count": len(stats["stocks"]),
                "avg_return": round(float(avg_ret), 6),
                "top_stocks": [(c, round(float(r), 4)) for c, r in top_stocks],
            })

        results.sort(key=lambda x: x["hot_score"], reverse=True)
        return results[:top_n]

    def get_sector_stocks(self, sector_name: str) -> List[str]:
        """
        Return stock codes in a given sector.

        Supports exact match, prefix match (e.g., "A01" matches "A01农业"),
        and partial substring match.

        Args:
            sector_name: Industry code or name to look up.

        Returns:
            List of stock code strings.
        """
        # Exact match
        if sector_name in self._sector_stocks:
            return self._sector_stocks[sector_name]

        # Prefix match (e.g., "A01" -> "A01农业")
        for key, codes in self._sector_stocks.items():
            if key.startswith(sector_name) or sector_name.startswith(key):
                return codes

        # Substring match (case-insensitive)
        lower = sector_name.lower()
        for key, codes in self._sector_stocks.items():
            if lower in key.lower() or key.lower() in lower:
                return codes

        return []

    def predict_next_hot(self, stock_data: Optional[Dict[str, pd.DataFrame]] = None,
                         date: Optional[str] = None) -> List[Dict]:
        """
        Predict sectors about to break out using:
          - Rising volume (vol_ratio > 1.3)
          - Price near recent low (below 40th percentile of recent range)
          - Positive momentum divergence (short-term return > long-term return)

        This captures the pattern: a sector that has been suppressed but is
        starting to accumulate volume with improving short-term momentum.

        Args:
            stock_data: Optional pre-loaded dict of code -> DataFrame.
            date: Target date string.

        Returns:
            List of dicts with sector, confidence, reasoning list.
        """
        if stock_data is None:
            stock_data = self._load_all_for_prediction(date)

        sector_signals: Dict[str, Dict] = {}
        for code, df in stock_data.items():
            if df is None or len(df) < 30:
                continue
            sector = self._get_industry_for_code(code)
            if sector not in sector_signals:
                sector_signals[sector] = {
                    "vol_ratios": [], "price_ratios": [],
                    "ret_5d": [], "ret_10d": [], "ret_20d": [],
                    "stocks": [],
                }

            vr = self._compute_vol_ratio(df)
            pr = self._price_near_low_ratio(df)
            r5 = self._compute_return_series(df, 5)
            r10 = self._compute_return_series(df, 10)
            r20 = self._compute_return_series(df, 20)

            sector_signals[sector]["vol_ratios"].append(vr)
            sector_signals[sector]["price_ratios"].append(pr)
            sector_signals[sector]["ret_5d"].append(r5)
            sector_signals[sector]["ret_10d"].append(r10)
            sector_signals[sector]["ret_20d"].append(r20)
            sector_signals[sector]["stocks"].append(code)

        predictions = []
        for sector, sigs in sector_signals.items():
            if len(sigs["stocks"]) < 3:
                continue

            reasons = []
            score = 0.0

            # Signal 1: Rising volume
            avg_vol = np.mean(sigs["vol_ratios"])
            vol_count_above = sum(1 for v in sigs["vol_ratios"] if v > 1.3)
            vol_pct = vol_count_above / len(sigs["vol_ratios"]) if sigs["vol_ratios"] else 0
            if vol_pct > 0.3 and avg_vol > 1.2:
                score += 0.3
                reasons.append(f"Volume rising: avg ratio={avg_vol:.2f}, {vol_pct:.0%} stocks above 1.3")

            # Signal 2: Price near recent low
            avg_price_ratio = np.mean(sigs["price_ratios"])
            if avg_price_ratio < 0.4:
                score += 0.25
                reasons.append(f"Price near {int(np.mean(sigs['price_ratios'])*100)}-day low (avg ratio={avg_price_ratio:.2f})")
            elif avg_price_ratio < 0.55:
                score += 0.1
                reasons.append(f"Price in lower half of recent range (avg ratio={avg_price_ratio:.2f})")

            # Signal 3: Momentum divergence (5d > 20d means short-term improving)
            avg_r5 = np.mean(sigs["ret_5d"])
            avg_r20 = np.mean(sigs["ret_20d"])
            avg_r10 = np.mean(sigs["ret_10d"])
            if avg_r5 > avg_r20 and avg_r5 > 0:
                divergence = avg_r5 - avg_r20
                score += min(0.25, divergence * 2)
                reasons.append(
                    f"Momentum divergence: 5d={avg_r5:.4f} > 20d={avg_r20:.4f} (gap={divergence:.4f})"
                )

            # Signal 4: Intermediate momentum confirmation
            if avg_r10 > 0 and avg_r5 > avg_r10:
                score += 0.1
                reasons.append(f"Accelerating: 5d={avg_r5:.4f} > 10d={avg_r10:.4f} > 0")

            # Signal 5: Broad participation (many stocks in sector moving together)
            if len(sigs["stocks"]) > 5:
                score += 0.1
                reasons.append(f"Broad sector participation ({len(sigs['stocks'])} stocks)")

            if score > 0.3 and reasons:  # Minimum threshold to report
                predictions.append({
                    "sector": sector,
                    "confidence": round(min(score, 1.0), 4),
                    "reasoning": reasons,
                    "stock_count": len(sigs["stocks"]),
                })

        predictions.sort(key=lambda x: x["confidence"], reverse=True)
        return predictions

    def get_sector_weight_adjust(self, hot_sectors: List[Dict]) -> Dict[str, float]:
        """
        Return weight multipliers for each sector based on hotness ranking.

        Hotter sectors get higher multipliers (1.2x to 1.5x).
        Sectors not in the hot list get a baseline of 1.0x.

        Args:
            hot_sectors: List of sector dicts from get_hot_sectors() or analyze_sector_momentum().

        Returns:
            Dict mapping sector name to weight multiplier.
        """
        if not hot_sectors:
            return {}

        # Normalize hot scores to rank
        n = len(hot_sectors)
        weights = {}

        for rank, sector_info in enumerate(hot_sectors):
            sector = sector_info["sector"]
            # Rank-based weight: top gets 1.5x, bottom of list gets 1.2x
            # Linear interpolation
            ratio = 1.0 - (rank / max(n - 1, 1))  # 1.0 for rank 0, 0.0 for last
            multiplier = 1.2 + ratio * 0.3  # range [1.2, 1.5]
            weights[sector] = round(multiplier, 4)

        return weights

    # ------------------------------------------------------------------
    # Per-stock sentiment score (0-100)
    # ------------------------------------------------------------------

    def get_stock_sentiment(self, code: str, df: Optional[pd.DataFrame],
                            hot_sectors: Optional[List[Dict]] = None) -> Dict[str, Any]:
        """
        Compute a 0-100 sentiment score for a single stock based on:
          1. Sector hotness (is the stock's sector in top hot sectors?)
          2. Individual stock momentum (5-day return)
          3. Volume anomaly (volume ratio vs 20-day avg)
          4. Price position (price near 20-day high/low)

        Args:
            code: Stock code (e.g. "sh.600519").
            df: Kline DataFrame for this stock (with close/volume/high/low columns).
            hot_sectors: Pre-computed hot sectors from get_hot_sectors().

        Returns:
            Dict with 'score' (0-100) and 'reason' (human-readable).
        """
        if hot_sectors is None:
            # Use cached hot_sectors if available, to avoid re-loading klines
            if hasattr(self, '_hot_sectors_cache') and self._hot_sectors_cache:
                hot_sectors = self._hot_sectors_cache
            else:
                hot_sectors = self.get_hot_sectors(top_n=10)

        # 1. Sector hotness score (0-100)
        industry = self._get_industry_for_code(code)
        sector_rank = None
        for idx, hs in enumerate(hot_sectors):
            if hs["sector"] == industry:
                sector_rank = idx
                break

        # Rank-based: top sector = 100, last = 50, not in list = 40
        if sector_rank is not None:
            n = len(hot_sectors)
            sector_score = 100 - (sector_rank / max(n - 1, 1)) * 50  # 100 down to 50
        else:
            sector_score = 40  # neutral-low if sector not in top

        reasons = [f"板块排名: {industry}" + (f" Top{sector_rank+1}" if sector_rank is not None else " 未进前十")]

        # 2. Individual stock metrics (only if df provided)
        momentum_score = 50
        vol_score = 50
        position_score = 50

        if df is not None and len(df) >= 21:
            # 5-day return -> momentum (0-100, 50=neutral)
            ret5 = self._compute_return_series(df, 5)
            momentum_score = min(100, max(0, 50 + ret5 * 500))  # 10% return = 100, -10% = 0
            reasons.append(f"5日涨幅: {ret5*100:+.2f}%")

            # Volume ratio -> volume score (0-100, 50=neutral)
            vr = self._compute_vol_ratio(df)
            vol_score = min(100, max(0, 50 + (vr - 1.0) * 50))  # 2x vol = 100, 0 = 0
            reasons.append(f"量能比: {vr:.2f}")

            # Price position in 20-day range (0-100)
            pos = self._price_near_low_ratio(df, 20)
            position_score = pos * 100
            reasons.append(f"价格位置: {pos*100:.0f}%")

        # Weighted combination
        final_score = (
            sector_score * 0.35 +
            momentum_score * 0.30 +
            vol_score * 0.20 +
            position_score * 0.15
        )

        final_score = round(min(100, max(0, final_score)), 1)
        reason_str = "; ".join(reasons)

        return {
            "score": final_score,
            "reason": reason_str,
            "details": {
                "sector_score": round(sector_score, 1),
                "momentum_score": round(momentum_score, 1),
                "vol_score": round(vol_score, 1),
                "position_score": round(position_score, 1),
                "industry": industry,
                "sector_rank": sector_rank,
            }
        }

    # ------------------------------------------------------------------
    # News keyword analysis
    # ------------------------------------------------------------------

    @staticmethod
    def analyze_news_sentiment(keywords: List[str]) -> Dict[str, float]:
        """
        Simple sentiment scoring based on keyword matches against NEWS_KEYWORDS.

        Each sector category gets a score based on how many of its associated
        keywords appear in the input keyword list. Score is normalized to
        [0, 1] per category.

        Args:
            keywords: List of keyword strings extracted from news text.

        Returns:
            Dict mapping sector category name to sentiment score [0, 1].
            Only categories with score > 0 are included.
        """
        if not keywords:
            return {}

        # Convert to lowercase set for matching
        kw_set = set(kw.lower().strip() for kw in keywords if kw.strip())
        if not kw_set:
            return {}

        sentiment: Dict[str, float] = {}
        for category, cat_keywords in NEWS_KEYWORDS.items():
            matches = 0
            for ck in cat_keywords:
                ck_lower = ck.lower().strip()
                # Exact match or substring match
                if ck_lower in kw_set:
                    matches += 1
                    continue
                # Check if any input keyword contains this category keyword
                for kw in kw_set:
                    if ck_lower in kw or kw in ck_lower:
                        matches += 0.5  # Partial match gets half credit
                        break

            total = len(cat_keywords)
            score = matches / total if total > 0 else 0.0
            if score > 0:
                sentiment[category] = round(min(score, 1.0), 4)

        return sentiment

    # ------------------------------------------------------------------
    # Disk I/O helpers
    # ------------------------------------------------------------------

    def _load_all_available_klines(self, date: Optional[str] = None) -> Dict[str, pd.DataFrame]:
        """Load all available kline CSVs from disk, optionally filtered by date.

        Caches the full (unfiltered) data in-memory so subsequent calls for
        dates >= last_loaded_date can reuse the cache without re-reading disk.
        """
        # Reuse cache if date is on or before what we already loaded
        if hasattr(self, '_kline_cache') and self._kline_cache is not None:
            if date is None or date <= self._kline_cache_date:
                # Filter cached data if needed
                if date and date < self._kline_cache_date:
                    filtered = {}
                    for code, df in self._kline_cache.items():
                        df = df[df["date"] <= date]
                        if not df.empty:
                            filtered[code] = df
                    print(f"[SectorSentiment] Used cached data, filtered to {date} ({len(filtered)} stocks)")
                    return filtered
                print(f"[SectorSentiment] Used cached data ({len(self._kline_cache)} stocks)")
                return self._kline_cache

        stock_data: Dict[str, pd.DataFrame] = {}
        if not os.path.isdir(self.kline_dir):
            print(f"[SectorSentiment] kline directory not found: {self.kline_dir}")
            return stock_data

        # Determine target date: use latest if not specified
        target_date = date
        files = [f for f in os.listdir(self.kline_dir) if f.endswith(".csv")]
        total = len(files)
        loaded = 0

        for fname in files:
            code = fname[:-4]  # strip .csv
            csv_path = os.path.join(self.kline_dir, fname)
            try:
                df = pd.read_csv(csv_path, dtype={"date": str, "stock_code": str})
                if df.empty:
                    continue
                if target_date:
                    # Filter to include data up to target_date
                    df = df[df["date"] <= target_date]
                    if df.empty:
                        continue
                stock_data[code] = df
                loaded += 1
            except Exception:
                continue

        # Store in cache
        self._kline_cache = stock_data
        self._kline_cache_date = target_date or "9999-12-31"

        print(f"[SectorSentiment] Loaded {loaded}/{total} stock kline files"
              + (f" up to {target_date}" if target_date else ""))
        return stock_data

    def _load_all_for_prediction(self, date: Optional[str] = None) -> Dict[str, pd.DataFrame]:
        """Alias for _load_all_available_klines used by predict_next_hot."""
        return self._load_all_available_klines(date)


def main():
    """Demonstrate usage of SectorSentiment module."""
    data_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")

    if not os.path.exists(data_dir):
        print(f"Data directory not found: {data_dir}")
        return

    sentiment = SectorSentiment(data_dir)
    print(f"\n{'='*60}")
    print(f"Sector Sentiment Analysis Demo")
    print(f"{'='*60}\n")

    # Use latest available date (2026-05-14 based on data)
    date = "2026-05-14"
    print(f"Target date: {date}\n")

    # 1. Analyze sector momentum
    print("--- 1. Sector Momentum Ranking (Top 10) ---")
    momentum = sentiment.analyze_sector_momentum(date=date)
    for i, m in enumerate(momentum[:10], 1):
        print(f"  {i:2d}. {m['sector']:20s}  score={m['momentum_score']:>8.4f}  "
              f"avg_ret={m['avg_return']:>7.4f}  stocks={m['stock_count']}")
    print()

    # 2. Get hot sectors
    print("--- 2. Hot Sectors (Top 5) ---")
    hot = sentiment.get_hot_sectors(date=date, top_n=5)
    for h in hot:
        print(f"  {h['sector']:20s}  hot={h['hot_score']:>8.4f}  "
              f"vol_ratio={h['vol_ratio']:.2f}  avg_ret={h['avg_return']:.4f}  "
              f"top_stocks={h['top_stocks']}")
    print()

    # 3. Get stocks in a sector
    print("--- 3. Sector Stocks Example ---")
    if momentum:
        example_sector = momentum[0]["sector"]
        stocks = sentiment.get_sector_stocks(example_sector)
        print(f"  Sector '{example_sector}': {len(stocks)} stocks")
        print(f"  First 5: {stocks[:5]}")
    print()

    # 4. Predict next hot sectors
    print("--- 4. Next-Hot Sector Predictions ---")
    predictions = sentiment.predict_next_hot(date=date)
    for p in predictions[:5]:
        print(f"  {p['sector']:20s}  confidence={p['confidence']:.4f}")
        for r in p["reasoning"][:2]:
            print(f"    -> {r}")
    print()

    # 5. Sector weight adjustments
    print("--- 5. Sector Weight Adjustments ---")
    if hot:
        weights = sentiment.get_sector_weight_adjust(hot)
        for sector, w in weights.items():
            print(f"  {sector:20s}  weight={w:.4f}x")
    print()

    # 6. News keyword sentiment analysis
    print("--- 6. News Sentiment Analysis ---")
    test_keywords = ["人工智能", "大模型", "算力", "光伏", "锂电", "储能", "创新药", "机器人"]
    news_sent = sentiment.analyze_news_sentiment(test_keywords)
    print(f"  Input keywords: {test_keywords}")
    print(f"  Sentiment scores:")
    for cat, score in sorted(news_sent.items(), key=lambda x: x[1], reverse=True):
        bar = "#" * int(score * 20)
        print(f"    {cat:12s}: {score:.4f} {bar}")

    # Broader test
    test_keywords2 = ["房地产", "基建", "水泥", "钢铁", "白酒", "消费", "拼多多", "电商"]
    news_sent2 = sentiment.analyze_news_sentiment(test_keywords2)
    print(f"\n  Input keywords: {test_keywords2}")
    for cat, score in sorted(news_sent2.items(), key=lambda x: x[1], reverse=True):
        bar = "#" * int(score * 20)
        print(f"    {cat:12s}: {score:.4f} {bar}")

    print(f"\n{'='*60}")
    print("Demo complete.")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
