"""
消息面 / 财报 / 财经分析 筛选器

回测: 用基本面(YOYNI/ROE) + 板块热度 + 价量催化剂(涨停/放量) 代理消息面
实盘: 叠加 data/news/ 缓存 + 关键词情绪分析
"""
from __future__ import annotations

import json
import os
import re
from datetime import datetime
from typing import Dict, List, Optional, Tuple

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
NEWS_DIR = os.path.join(BASE_DIR, "data", "news")

POS_WORDS = [
    "业绩", "增长", "盈利", "超预期", "中标", "合同", "回购", "增持", "突破", "新高",
    "涨停", "利好", "强劲", "放量", "分红", "扩产", "订单", "获批", "战略合作",
    "净利润", "营收", "扭亏", "预增", "景气", "龙头",
]
NEG_WORDS = [
    "亏损", "减持", "立案", "警示", "暴跌", "跌停", "利空", "下调", "违规",
    "问询", "质押", "暴雷", "退市", "诉讼", "预亏", "下调评级",
]
EARNINGS_WORDS = ["业绩", "财报", "年报", "季报", "净利润", "营收", "EPS", "分红", "预告", "快报"]


class MessageScreener:
    """个股消息面综合评分 0-100"""

    def __init__(self):
        self._news_cache: Dict[str, dict] = {}
        self._code_names: Dict[str, str] = {}

    def _load_news(self, date: str) -> Optional[dict]:
        if date in self._news_cache:
            return self._news_cache[date]
        path = os.path.join(NEWS_DIR, f"news_{date}.json")
        if not os.path.exists(path):
            self._news_cache[date] = None
            return None
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            self._news_cache[date] = data
            return data
        except Exception:
            self._news_cache[date] = None
            return None

    def _code_name(self, code: str) -> str:
        if code in self._code_names:
            return self._code_names[code]
        try:
            pool_path = os.path.join(BASE_DIR, "data", "stock_pool.json")
            with open(pool_path, "r", encoding="utf-8") as f:
                pool = json.load(f)
            for p in pool:
                c = str(p.get("code", "")).split(".")[-1]
                self._code_names[c] = p.get("code_name", p.get("name", ""))
        except Exception:
            pass
        return self._code_names.get(code, "")

    @staticmethod
    def _keyword_score(text: str) -> Tuple[int, int, bool]:
        if not text:
            return 0, 0, False
        pos = sum(1 for w in POS_WORDS if w in text)
        neg = sum(1 for w in NEG_WORDS if w in text)
        earnings = any(w in text for w in EARNINGS_WORDS)
        return pos, neg, earnings

    def score_fundamental(self, fund: Dict) -> Tuple[float, List[str]]:
        """财报/基本面代理分"""
        if not fund:
            return 45.0, []
        score = 48.0
        tags = []
        yoy = fund.get("yoy_ni") or fund.get("YOYNI")
        if yoy is not None:
            if yoy > 30:
                score += 18
                tags.append(f"净利增{yoy:.0f}%")
            elif yoy > 10:
                score += 12
                tags.append(f"净利增{yoy:.0f}%")
            elif yoy > 0:
                score += 6
            elif yoy < -20:
                score -= 15
                tags.append("业绩下滑")

        roe = fund.get("roe") or fund.get("roeAvg")
        if roe is not None:
            if roe > 15:
                score += 10
                tags.append(f"ROE{roe:.0f}%")
            elif roe > 8:
                score += 5

        eps_g = fund.get("yoy_eps") or fund.get("YOYEPSBasic")
        if eps_g is not None and eps_g > 15:
            score += 8
            tags.append("EPS高增")

        gp = fund.get("gp_margin") or fund.get("gpMargin")
        if gp is not None and gp > 30:
            score += 4

        return min(100, max(0, score)), tags

    def score_catalyst(self, pv: Dict) -> Tuple[float, List[str]]:
        """价量催化剂 — 涨停/放量/突破"""
        if not pv:
            return 40.0, []
        score = 42.0
        tags = []
        chg = pv.get("change_pct", 0) or 0
        vol_r = pv.get("vol_ratio", 1) or 1

        if chg >= 9.5:
            score += 25
            tags.append("涨停")
        elif chg >= 5:
            score += 12
            tags.append(f"大涨{chg:.1f}%")
        elif chg >= 2:
            score += 6
        elif chg < -5:
            score -= 10

        if vol_r >= 2.5:
            score += 10
            tags.append(f"放量{vol_r:.1f}x")
        elif vol_r >= 1.5:
            score += 5

        if pv.get("break_60d"):
            score += 8
            tags.append("60日新高")
        if pv.get("has_limit_up_180d"):
            score += 5
            tags.append("涨停基因")

        mom20 = pv.get("mom_20d", 0) or 0
        if mom20 > 20:
            score += 8
            tags.append(f"20日动量{mom20:.0f}%")
        elif mom20 > 8:
            score += 4

        return min(100, max(0, score)), tags

    def score_sector(self, stock: Dict, sector_data: Dict = None) -> Tuple[float, List[str]]:
        if not sector_data:
            return 50.0, []
        industry = stock.get("industry", "")
        if not industry:
            return 50.0, []
        for i, sec in enumerate(sector_data.get("hot_sectors", [])[:8]):
            if sec.get("name") == industry:
                chg = sec.get("change_pct", 0) or 0
                bonus = max(0, 12 - i * 2) + min(8, chg * 2)
                return min(100, 55 + bonus), [f"热门{industry}"]
        return 48.0, []

    def score_news(self, code: str, date: str) -> Tuple[float, List[str]]:
        """实盘新闻匹配 (有缓存才生效)"""
        data = self._load_news(date)
        if not data:
            return 50.0, []
        name = self._code_name(code)
        code_short = code.split(".")[-1]
        score = 50.0
        tags = []
        hits = 0
        for item in data.get("items", [])[:200]:
            title = item.get("title", "") + " " + item.get("summary", "")
            if code_short not in title and name and name not in title:
                continue
            pos, neg, earnings = self._keyword_score(title)
            hits += 1
            score += pos * 4 - neg * 6
            if earnings:
                tags.append("财报相关")
            if pos > neg:
                tags.append("新闻偏多")
            elif neg > pos:
                tags.append("新闻偏空")

        if hits == 0:
            return 50.0, []
        return min(100, max(0, score)), tags[:3]

    def score(
        self,
        stock: Dict,
        sector_data: Dict = None,
        date: str = None,
    ) -> Dict:
        fund = stock.get("fundamental", {}) or stock.get("fund", {}) or {}
        pv = stock.get("price_volume", {}) or {}
        code = stock.get("code", "")

        f_score, f_tags = self.score_fundamental(fund)
        c_score, c_tags = self.score_catalyst(pv)
        s_score, s_tags = self.score_sector(stock, sector_data)
        n_score, n_tags = self.score_news(code, date or datetime.now().strftime("%Y-%m-%d"))

        # 回测无新闻时提高基本面+催化剂权重
        has_news = n_score != 50.0 or bool(n_tags)
        if has_news:
            total = f_score * 0.30 + c_score * 0.30 + s_score * 0.15 + n_score * 0.25
        else:
            total = f_score * 0.38 + c_score * 0.42 + s_score * 0.20

        tags = list(dict.fromkeys(f_tags + c_tags + s_tags + n_tags))[:5]
        return {
            "message_score": round(min(100, max(0, total)), 1),
            "fund_score": round(f_score, 1),
            "catalyst_score": round(c_score, 1),
            "sector_score": round(s_score, 1),
            "news_score": round(n_score, 1),
            "message_tags": tags,
            "message_pass": total >= 52,
        }

    def score_batch(self, stocks: List[Dict], sector_data: Dict = None, date: str = None) -> None:
        for s in stocks:
            info = self.score(s, sector_data, date)
            s.update(info)


_screener: Optional[MessageScreener] = None


def get_screener() -> MessageScreener:
    global _screener
    if _screener is None:
        _screener = MessageScreener()
    return _screener
