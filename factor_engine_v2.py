"""
因子评分引擎 v2 - 多因子量化选股系统

功能:
1. 因子标准化 (Z-score + winsorize去极值)
2. 因子打分 (0-100)
3. 维度加权合成
4. 综合排名输出

评分维度:
- 趋势(25%): 均线排列, MACD, 动量, 突破
- 基本面(25%): ROE, 增速, 利润率
- 估值(15%): PE/PB历史分位数
- 板块热度(15%): 行业排名, 概念热度
- 资金面(10%): 大单净流入, 换手率
- 动量/反转(10%): 短期动量, RSI超跌
"""

import os
import json
import logging
import numpy as np
import pandas as pd
from datetime import datetime
from typing import Dict, List, Optional, Any

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
logger = logging.getLogger(__name__)


# ==================== 工具函数 ====================

def winsorize(val, lower=1, upper=99):
    """去极值: 限制在[lower, upper]百分位范围内"""
    if val is None or (isinstance(val, float) and np.isnan(val)):
        return None
    return float(np.clip(val, lower, upper))


def normalize_zscore(values: List[float]) -> List[float]:
    """Z-score标准化"""
    arr = np.array([v for v in values if v is not None], dtype=float)
    if len(arr) < 3:
        return [50.0 for _ in values]
    mean = np.nanmean(arr)
    std = np.nanstd(arr)
    if std == 0:
        return [50.0 for _ in values]
    result = []
    for v in values:
        if v is None:
            result.append(50.0)
        else:
            z = (v - mean) / std
            score = 50 + z * 15  # Z-score映射到[0,100]
            result.append(min(max(score, 0), 100))
    return result


def normalize_rank(values: List[float], reverse=False) -> List[float]:
    """百分位排名标准化 (越靠前分越高)"""
    valid = [(i, v) for i, v in enumerate(values) if v is not None]
    if len(valid) < 2:
        return [50.0 for _ in values]

    sorted_vals = sorted([v for _, v in valid], reverse=not reverse)
    rank = {v: (i + 1) / len(sorted_vals) * 100 for i, v in enumerate(sorted_vals)}

    result = []
    for v in values:
        if v is None:
            result.append(50.0)
        else:
            result.append(rank.get(v, 50.0))
    return result


def sigmoid_score(val, center=0, steepness=0.1):
    """Sigmoid映射到0-100分"""
    try:
        if val is None:
            return 50.0
        return float(100 / (1 + np.exp(-steepness * (val - center))))
    except:
        return 50.0


# ==================== 单维度打分器 ====================

class TrendScorer:
    """趋势维度打分 (权重25%)"""

    @staticmethod
    def score(pv: Dict) -> Dict:
        """根据价量因子计算趋势分"""
        if not pv:
            return {'total': 0, 'sub_scores': {}}

        subs = {}

        # 均线多头排列 (30%)
        if pv.get('ma_bull'):
            subs['ma_alignment'] = 90
        elif pv.get('ma5') and pv.get('ma20') and pv['ma5'] > pv['ma20']:
            subs['ma_alignment'] = 60
        elif pv.get('ma5') and pv.get('ma20') and pv['ma5'] < pv['ma20']:
            subs['ma_alignment'] = 30
        else:
            subs['ma_alignment'] = 50

        # MACD状态 (25%)
        if pv.get('macd_dif'):
            if pv['macd_dif'] > 0:
                subs['macd_status'] = 75 + min(25, pv.get('macd_hist', 0) * 5)
            elif pv.get('macd_golden_cross'):
                subs['macd_status'] = 70
            else:
                subs['macd_status'] = 25
        else:
            subs['macd_status'] = 50

        # 动量方向 (20%)
        mom_20 = pv.get('mom_20d')
        if mom_20 is not None:
            subs['momentum_dir'] = sigmoid_score(mom_20, center=0, steepness=0.5)
        else:
            subs['momentum_dir'] = 50

        # 价格相对均线位置 (15%)
        pos = pv.get('price_vs_ma20')
        if pos is not None:
            subs['price_vs_ma'] = sigmoid_score(pos, center=5, steepness=0.3)
        else:
            subs['price_vs_ma'] = 50

        # 是否突破 (10%)
        subs['breakout'] = 90 if pv.get('break_60d') else 30

        # 加权
        total = (subs['ma_alignment'] * 0.30 +
                 subs['macd_status'] * 0.25 +
                 subs['momentum_dir'] * 0.20 +
                 subs['price_vs_ma'] * 0.15 +
                 subs['breakout'] * 0.10)

        return {'total': round(total), 'sub_scores': subs}


class FundamentalScorer:
    """基本面维度打分 (权重25%)"""

    @staticmethod
    def score(fund: Dict) -> Dict:
        """根据基本面因子计算基本面分"""
        if not fund:
            return {'total': 0, 'sub_scores': {}}

        subs = {}

        # ROE (30%)
        roe = fund.get('roe')
        if roe is not None:
            # ROE > 20% 满分, > 10% 良好, < 0 差
            if roe > 0.20:
                subs['roe_score'] = 90 + min(10, (roe - 0.20) * 50)
            elif roe > 0.15:
                subs['roe_score'] = 75
            elif roe > 0.10:
                subs['roe_score'] = 60
            elif roe > 0.05:
                subs['roe_score'] = 45
            elif roe > 0:
                subs['roe_score'] = 30
            else:
                subs['roe_score'] = 15
        else:
            subs['roe_score'] = 50

        # 净利润增速 (25%)
        yoy = fund.get('yoy_ni')
        if yoy is not None:
            subs['growth_score'] = sigmoid_score(yoy * 100, center=15, steepness=0.08)
        else:
            subs['growth_score'] = 50

        # 净利率 (20%)
        margin = fund.get('np_margin')
        if margin is not None:
            subs['margin_score'] = sigmoid_score(margin * 100, center=15, steepness=0.5)
        else:
            subs['margin_score'] = 50

        # 资产负债率 (15%)
        liab = fund.get('liability_ratio')
        if liab is not None:
            # 30%-60%比较合理
            if 0.3 <= liab <= 0.6:
                subs['liab_score'] = 80
            elif liab < 0.3:
                subs['liab_score'] = 70
            elif liab < 0.7:
                subs['liab_score'] = 60
            else:
                subs['liab_score'] = 30
        else:
            subs['liab_score'] = 50

        # EPS增长 (10%)
        eps_yoy = fund.get('yoy_eps')
        if eps_yoy is not None:
            subs['eps_growth'] = sigmoid_score(eps_yoy * 100, center=10, steepness=0.08)
        else:
            subs['eps_growth'] = 50

        total = (subs['roe_score'] * 0.30 +
                 subs['growth_score'] * 0.25 +
                 subs['margin_score'] * 0.20 +
                 subs['liab_score'] * 0.15 +
                 subs['eps_growth'] * 0.10)

        return {'total': round(total), 'sub_scores': subs}


class ValuationScorer:
    """估值维度打分 (权重15%)"""

    @staticmethod
    def score(fund: Dict, pv: Dict) -> Dict:
        """根据估值因子计算估值分"""
        if not fund:
            return {'total': 0, 'sub_scores': {}}

        subs = {}

        # PE合理区间 (60%)
        pe = fund.get('pe')
        if pe is not None:
            # PE在10-30之间比较合理
            if 10 <= pe <= 20:
                subs['pe_score'] = 85
            elif 20 < pe <= 30:
                subs['pe_score'] = 75
            elif 30 < pe <= 45:
                subs['pe_score'] = 60
            elif 45 < pe <= 60:
                subs['pe_score'] = 45
            elif pe > 60:
                subs['pe_score'] = 25
            elif pe > 0:
                subs['pe_score'] = 70
            else:
                subs['pe_score'] = 30
        else:
            subs['pe_score'] = 50

        # PB合理区间 (40%)
        pb = fund.get('pb')
        if pb is not None:
            if 1 <= pb <= 3:
                subs['pb_score'] = 85
            elif 3 < pb <= 5:
                subs['pb_score'] = 70
            elif 5 < pb <= 8:
                subs['pb_score'] = 55
            elif pb > 8:
                subs['pb_score'] = 30
            elif pb > 0:
                subs['pb_score'] = 60
            else:
                subs['pb_score'] = 30
        else:
            subs['pb_score'] = 50

        total = subs['pe_score'] * 0.60 + subs['pb_score'] * 0.40

        return {'total': round(total), 'sub_scores': subs}


class SectorScorer:
    """板块热度打分 (权重15%)"""

    @staticmethod
    def score(sector_data: Dict, stock_industry: str = '') -> Dict:
        """根据板块因子计算板块热度分"""
        subs = {}

        hot_sectors = sector_data.get('hot_sectors', [])
        cold_sectors = sector_data.get('cold_sectors', [])

        # 行业板块排名 (60%)
        if stock_industry and hot_sectors:
            hot_names = {s['name'] for s in hot_sectors}
            if stock_industry in hot_names:
                rank = next((i for i, s in enumerate(hot_sectors) if s['name'] == stock_industry), 10)
                subs['industry_rank'] = max(55, 100 - rank * 4)
            else:
                cold_names = {s['name'] for s in cold_sectors}
                if stock_industry in cold_names:
                    subs['industry_rank'] = 20
                else:
                    subs['industry_rank'] = 50
        else:
            subs['industry_rank'] = 50

        # 整体板块环境 (40%)
        if hot_sectors:
            top_change = hot_sectors[0].get('change_pct', 0)
            if top_change > 3:
                subs['env_score'] = 85
            elif top_change > 1:
                subs['env_score'] = 70
            else:
                subs['env_score'] = 50
        else:
            subs['env_score'] = 50

        total = subs['industry_rank'] * 0.60 + subs['env_score'] * 0.40

        return {'total': round(total), 'sub_scores': subs}


class CapitalScorer:
    """资金面打分 (权重10%)"""

    @staticmethod
    def score(capital_data: Dict, pv: Dict) -> Dict:
        """根据资金面因子计算资金分"""
        subs = {}

        # 北向资金趋势 (40%)
        trend = capital_data.get('north_trend', 'unknown')
        if trend == 'inflow':
            subs['north_trend'] = 75
        elif trend == 'outflow':
            subs['north_trend'] = 30
        else:
            subs['north_trend'] = 50

        # 换手率变化 (35%)
        vol_ratio = pv.get('vol_ratio', 1.0)
        if vol_ratio is not None:
            if 1.5 < vol_ratio < 3:
                subs['turnover'] = 85  # 温和放量
            elif 3 < vol_ratio < 5:
                subs['turnover'] = 65  # 明显放量
            elif vol_ratio > 5:
                subs['turnover'] = 35  # 放量过大
            elif vol_ratio < 0.5:
                subs['turnover'] = 55  # 缩量
            else:
                subs['turnover'] = 60
        else:
            subs['turnover'] = 50

        # 价格位置 (25%) - 是否在底部区域积累资金
        pos = pv.get('price_pos', 50)
        if pos is not None:
            if pos < 20:
                subs['position'] = 75  # 低位可能有资金建仓
            elif pos > 80:
                subs['position'] = 35  # 高位可能出货
            else:
                subs['position'] = 60
        else:
            subs['position'] = 50

        total = (subs['north_trend'] * 0.40 +
                 subs['turnover'] * 0.35 +
                 subs['position'] * 0.25)

        return {'total': round(total), 'sub_scores': subs}


class MomentumReversalScorer:
    """动量/反转打分 (权重10%)"""

    @staticmethod
    def score(pv: Dict, fund: Dict) -> Dict:
        """动量+反转复合打分"""
        if not pv:
            return {'total': 0, 'sub_scores': {}}

        subs = {}

        # 短期动量 (40%)
        mom_5 = pv.get('mom_5d', 0)
        if mom_5 is not None:
            # 2-8%的短期涨幅最佳
            if 2 <= mom_5 <= 8:
                subs['short_momentum'] = 85
            elif 0 < mom_5 < 2:
                subs['short_momentum'] = 70
            elif mom_5 > 8 and mom_5 <= 15:
                subs['short_momentum'] = 55
            elif mom_5 > 15:
                subs['short_momentum'] = 30  # 短期涨幅过大
            elif mom_5 > -5:
                subs['short_momentum'] = 50
            else:
                subs['short_momentum'] = 35
        else:
            subs['short_momentum'] = 50

        # 反转信号 (40%) - RSI超跌 + 缩量
        rsi = pv.get('rsi', 50)
        if rsi is not None:
            if rsi < 25:
                subs['reversal'] = 80  # 严重超卖
            elif rsi < 35:
                subs['reversal'] = 65  # 超卖
            elif rsi > 75:
                subs['reversal'] = 25  # 超买
            else:
                subs['reversal'] = 50
        else:
            subs['reversal'] = 50

        # 量价配合 (20%)
        mom_20 = pv.get('mom_20d', 0)
        vol_r = pv.get('vol_ratio', 1)
        if mom_20 is not None and vol_r is not None:
            if mom_20 > 0 and vol_r > 1:
                subs['vol_price'] = 80  # 量价齐升
            elif mom_20 > 0 and vol_r < 1:
                subs['vol_price'] = 45  # 量缩价涨，可能见顶
            elif mom_20 < 0 and vol_r < 1:
                subs['vol_price'] = 60  # 缩量下跌，可能企稳
            else:
                subs['vol_price'] = 40  # 放量下跌
        else:
            subs['vol_price'] = 50

        total = (subs['short_momentum'] * 0.40 +
                 subs['reversal'] * 0.40 +
                 subs['vol_price'] * 0.20)

        return {'total': round(total), 'sub_scores': subs}


# ==================== 综合评分器 ====================

class FactorEngine:
    """
    多因子评分引擎
    
    维度权重:
    - 趋势: 25%
    - 基本面: 25%
    - 估值: 15%
    - 板块: 15%
    - 资金面: 10%
    - 动量/反转: 10%
    """

    WEIGHTS = {
        'trend': 0.25,
        'fundamental': 0.25,
        'valuation': 0.15,
        'sector': 0.15,
        'capital': 0.10,
        'momentum': 0.10,
    }

    def __init__(self):
        self.stock_industry_cache = self._load_stock_industry()

    def _load_stock_industry(self) -> Dict[str, str]:
        """加载股票-行业映射 (code -> industry_name string)"""
        path = os.path.join(BASE_DIR, 'data', 'stock_industry.json')
        if os.path.exists(path):
            try:
                with open(path, 'r') as f:
                    raw = json.load(f)
                # Handle both {code: "industry"} and {code: {"industryName": "..."}}
                return {code: (info.get('industryName', '') if isinstance(info, dict) else info)
                        for code, info in raw.items()}
            except:
                pass
        return {}

    def score_stock(self, code: str, pv: Dict, fund: Dict,
                    sector_data: Dict, capital_data: Dict) -> Dict:
        """
        对单只股票进行综合评分
        
        Returns: {
            'code': '600519',
            'price': 1275.98,
            'total_score': 72,
            'dimensions': {
                'trend': {'score': 65, 'weight': 0.25, 'weighted': 16.25, 'sub_scores': {...}},
                'fundamental': {...},
                ...
            }
        }
        """
        # 各维度打分
        trend = TrendScorer.score(pv)
        fundamental = FundamentalScorer.score(fund)
        valuation = ValuationScorer.score(fund, pv)

        industry = fund.get('industry', '') or self.stock_industry_cache.get(code, '')
        sector = SectorScorer.score(sector_data, industry)

        capital = CapitalScorer.score(capital_data, pv)
        momentum = MomentumReversalScorer.score(pv, fund)

        dimensions = {
            'trend': {'score': trend['total'], 'weight': self.WEIGHTS['trend'],
                      'sub_scores': trend['sub_scores']},
            'fundamental': {'score': fundamental['total'], 'weight': self.WEIGHTS['fundamental'],
                           'sub_scores': fundamental['sub_scores']},
            'valuation': {'score': valuation['total'], 'weight': self.WEIGHTS['valuation'],
                         'sub_scores': valuation['sub_scores']},
            'sector': {'score': sector['total'], 'weight': self.WEIGHTS['sector'],
                      'sub_scores': sector['sub_scores']},
            'capital': {'score': capital['total'], 'weight': self.WEIGHTS['capital'],
                       'sub_scores': capital['sub_scores']},
            'momentum': {'score': momentum['total'], 'weight': self.WEIGHTS['momentum'],
                        'sub_scores': momentum['sub_scores']},
        }

        # 加权总分
        total = sum(d['score'] * d['weight'] for d in dimensions.values())

        return {
            'code': code,
            'price': pv.get('price', fund.get('pe', 0) or 0),
            'total_score': round(total),
            'dimensions': dimensions,
            'industry': industry,
            # Pass through for strategy filtering
            'price_volume': pv,
        }

    def score_batch(self, stocks_data: List[Dict],
                    sector_data: Dict, capital_data: Dict) -> List[Dict]:
        """
        批量评分，返回排名
        
        stocks_data: [{'code': '600519', 'pv': {...}, 'fund': {...}}, ...]
        """
        results = []
        for sd in stocks_data:
            try:
                r = self.score_stock(
                    code=sd['code'],
                    pv=sd.get('pv', {}),
                    fund=sd.get('fund', {}),
                    sector_data=sector_data,
                    capital_data=capital_data,
                )
                results.append(r)
            except Exception as e:
                logger.warning(f"评分失败 {sd.get('code')}: {e}")

        # 按总分降序排序
        results.sort(key=lambda x: x['total_score'], reverse=True)

        # 添加排名
        for i, r in enumerate(results):
            r['rank'] = i + 1

        return results

    def get_top_picks(self, results: List[Dict], top_n: int = 10) -> List[Dict]:
        """获取前N名推荐"""
        return results[:top_n]

    def filter_by_threshold(self, results: List[Dict], min_score: int = 50) -> List[Dict]:
        """过滤低于最低分的股票"""
        return [r for r in results if r['total_score'] >= min_score]


# ==================== 批量采集+评分 ====================

def collect_and_score(stock_pool: List[str],
                      sector_data: Dict = None,
                      capital_data: Dict = None,
                      top_n: int = 20,
                      min_score: int = 45) -> Dict:
    """
    采集因子+评分的一站式函数
    
    Returns: {
        'timestamp': '2026-06-10 09:00:00',
        'total_stocks': 1040,
        'scored_count': 980,
        'top_picks': [...],
        'sector_data': {...},
        'capital_data': {...},
    }
    """
    from factor_data import FactorCollector, SectorFactors, CapitalFactors

    # 采集市场数据
    logger.info("采集市场数据...")
    if sector_data is None:
        sector_data = SectorFactors.get_sector_summary()
    if capital_data is None:
        capital_data = CapitalFactors.get_capital_summary()

    # 批量采集个股因子
    engine = FactorEngine()
    scored = []
    total = len(stock_pool)

    for i, code in enumerate(stock_pool):
        if (i + 1) % 100 == 0:
            logger.info(f"进度: {i+1}/{total}")

        try:
            factors = FactorCollector.collect_for_stock(code)
            if not factors:
                continue

            pv = factors.get('price_volume', {})
            fund = factors.get('fundamental', {})

            r = engine.score_stock(
                code=code,
                pv=pv,
                fund=fund,
                sector_data=sector_data,
                capital_data=capital_data,
            )
            scored.append(r)
        except Exception as e:
            if i < 3:
                logger.warning(f"处理失败 {code}: {e}")

    # 排序+过滤
    scored.sort(key=lambda x: x['total_score'], reverse=True)
    scored = [s for s in scored if s['total_score'] >= min_score]

    # 添加排名
    for i, r in enumerate(scored):
        r['rank'] = i + 1

    return {
        'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'total_stocks': total,
        'scored_count': len(scored),
        'top_picks': scored[:top_n],
        'sector_data': sector_data,
        'capital_data': capital_data,
        'min_score': min_score,
    }


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)

    from factor_data import get_stock_pool, FactorCollector, SectorFactors, CapitalFactors

    pool = get_stock_pool()
    print(f"股票池: {len(pool)} 只")

    result = collect_and_score(pool, top_n=10)

    print(f"\n{'='*60}")
    print(f"综合评分结果 (共{result['scored_count']}只达标)")
    print(f"{'='*60}")

    for p in result['top_picks'][:10]:
        dims = p['dimensions']
        print(f"\n#{p['rank']} {p['code']} @ {p['price']}")
        print(f"  综合分: {p['total_score']}")
        for dim_name, dim_data in dims.items():
            dim_names = {
                'trend': '趋势', 'fundamental': '基本面', 'valuation': '估值',
                'sector': '板块', 'capital': '资金', 'momentum': '动量/反转'
            }
            cn = dim_names.get(dim_name, dim_name)
            print(f"  {cn}: {dim_data['score']}")
        print(f"  行业: {p.get('industry', 'N/A')}")
