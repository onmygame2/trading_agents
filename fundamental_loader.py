"""
基本面数据加载器 - BaoStock 财报数据

数据维度:
1. 盈利能力: ROE, 净利率, 毛利率, EPS
2. 成长能力: 净利润增速, EPS增速, 资产增速
3. 偿债能力: 流动比率, 资产负债率
4. 营运能力: 应收账款周转率, 存货周转率
5. 现金流: 每股经营现金流, 资产负债结构
6. 行业信息: 所属行业, 二级行业
7. 杜邦分析: ROE分解

用法:
    loader = FundamentalLoader(data_dir)
    loader.cache_all()                    # 批量缓存所有股票
    data = loader.get_fundamentals(code)  # 获取单只股票基本面
    pool = loader.get_stock_pool()        # 获取带基本面的股票池
"""
import os
import json
import time
import baostock as bs
import pandas as pd
from datetime import datetime
from typing import Dict, List, Optional

CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data', 'fundamentals')


class FundamentalLoader:
    """基本面数据加载器"""

    def __init__(self, data_dir: str = None):
        self.data_dir = data_dir or os.path.join(
            os.path.dirname(os.path.abspath(__file__)), 'data'
        )
        self.fund_dir = os.path.join(self.data_dir, 'fundamentals')
        self.industry_file = os.path.join(self.data_dir, 'stock_industry.json')
        self.bs_logged = False

    @staticmethod
    def _normalize_code(code: str) -> str:
        """Convert bare code (e.g. '600519') to BaoStock format (e.g. 'sh.600519')."""
        if '.' in code:
            return code  # already has exchange prefix
        prefix = code[:3]
        if prefix in ('600', '601', '603', '605', '688', '689'):
            return f'sh.{code}'
        elif prefix in ('000', '001', '002', '300', '301'):
            return f'sz.{code}'
        elif code.startswith(('4', '8')):
            return f'bj.{code}'
        return code  # fallback: return as-is

    def _ensure_login(self):
        if not self.bs_logged:
            bs.login()
            self.bs_logged = True

    def logout(self):
        if self.bs_logged:
            bs.logout()
            self.bs_logged = False

    # ---- 数据查询 ----

    def _query_profit(self, code: str, year: str = '2025') -> dict:
        """盈利能力: ROE, 净利率, 毛利率, EPS, 净利润, 营收"""
        self._ensure_login()
        rs = bs.query_profit_data(code=code, year=year)
        rows = []
        while rs.next():
            rows.append(rs.get_row_data())
        if not rows:
            return {}
        result = {}
        for i, f in enumerate(rs.fields):
            val = rows[0][i]
            try:
                val = float(val) if val else None
            except:
                pass
            result[f] = val
        return result

    def _query_growth(self, code: str, year: str = '2025') -> dict:
        """成长能力: 净利润增速, EPS增速, 净资产增速, 总资产增速"""
        self._ensure_login()
        rs = bs.query_growth_data(code=code, year=year)
        rows = []
        while rs.next():
            rows.append(rs.get_row_data())
        if not rows:
            return {}
        result = {}
        for i, f in enumerate(rs.fields):
            val = rows[0][i]
            try:
                val = float(val) if val else None
            except:
                pass
            result[f] = val
        return result

    def _query_balance(self, code: str, year: str = '2025') -> dict:
        """偿债能力: 流动比率, 速动比率, 资产负债率"""
        self._ensure_login()
        rs = bs.query_balance_data(code=code, year=year)
        rows = []
        while rs.next():
            rows.append(rs.get_row_data())
        if not rows:
            return {}
        result = {}
        for i, f in enumerate(rs.fields):
            val = rows[0][i]
            try:
                val = float(val) if val else None
            except:
                pass
            result[f] = val
        return result

    def _query_operation(self, code: str, year: str = '2025') -> dict:
        """营运能力: 应收账款周转率, 存货周转率"""
        self._ensure_login()
        rs = bs.query_operation_data(code=code, year=year)
        rows = []
        while rs.next():
            rows.append(rs.get_row_data())
        if not rows:
            return {}
        result = {}
        for i, f in enumerate(rs.fields):
            val = rows[0][i]
            try:
                val = float(val) if val else None
            except:
                pass
            result[f] = val
        return result

    def _query_cashflow(self, code: str, year: str = '2025') -> dict:
        """现金流量"""
        self._ensure_login()
        rs = bs.query_cash_flow_data(code=code, year=year)
        rows = []
        while rs.next():
            rows.append(rs.get_row_data())
        if not rows:
            return {}
        result = {}
        for i, f in enumerate(rs.fields):
            val = rows[0][i]
            try:
                val = float(val) if val else None
            except:
                pass
            result[f] = val
        return result

    def _query_dupont(self, code: str, year: str = '2025') -> dict:
        """杜邦分析"""
        self._ensure_login()
        rs = bs.query_dupont_data(code=code, year=year)
        rows = []
        while rs.next():
            rows.append(rs.get_row_data())
        if not rows:
            return {}
        result = {}
        for i, f in enumerate(rs.fields):
            val = rows[0][i]
            try:
                val = float(val) if val else None
            except:
                pass
            result[f] = val
        return result

    def _query_industry(self, code: str) -> dict:
        """行业分类"""
        self._ensure_login()
        rs = bs.query_stock_industry(code=code)
        rows = []
        while rs.next():
            rows.append(rs.get_row_data())
        if not rows:
            return {}
        result = {}
        for i, f in enumerate(rs.fields):
            result[f] = rows[0][i]
        return result

    # ---- 单只股票完整基本面 ----

    def get_fundamentals(self, code: str, year: str = '2025') -> dict:
        """获取单只股票完整基本面数据"""
        # Normalize code to BaoStock format (e.g. '600519' -> 'sh.600519')
        bs_code = self._normalize_code(code)
        cache_file = os.path.join(self.fund_dir, f'{code}_fund_{year}.json')

        # 优先读缓存
        if os.path.exists(cache_file):
            age = time.time() - os.path.getmtime(cache_file)
            if age < 86400 * 7:  # 7天内的缓存
                with open(cache_file, 'r') as f:
                    return json.load(f)

        # 查BaoStock
        try:
            data = {
                'code': bs_code,
                'year': year,
                'updated': datetime.now().strftime('%Y-%m-%d'),
                'profit': self._query_profit(bs_code, year),
                'growth': self._query_growth(bs_code, year),
                'balance': self._query_balance(bs_code, year),
                'operation': self._query_operation(bs_code, year),
                'cashflow': self._query_cashflow(bs_code, year),
                'dupont': self._query_dupont(bs_code, year),
                'industry': self._query_industry(bs_code),
            }

            os.makedirs(self.fund_dir, exist_ok=True)
            with open(cache_file, 'w') as f:
                json.dump(data, f, ensure_ascii=False)

            time.sleep(0.1)  # 避免请求过快
            return data
        except Exception as e:
            print(f"  [WARN] 基本面查询失败 {code}: {e}")
            return {}

    # ---- 批量缓存 ----

    def cache_all(self, stock_codes: List[str] = None, year: str = '2025'):
        """批量缓存所有股票基本面"""
        if stock_codes is None:
            stock_codes = self._get_stock_codes()

        total = len(stock_codes)
        print(f"  开始缓存 {total} 只股票基本面数据...")

        for i, code in enumerate(stock_codes):
            self.get_fundamentals(code, year)
            if (i + 1) % 100 == 0:
                print(f"    进度: {i+1}/{total} ({(i+1)*100//total}%)")

        print(f"  缓存完成!")
        self.logout()

    def _get_stock_codes(self) -> List[str]:
        """从已有CSV数据获取股票代码"""
        # Try data/kline first, then data
        kline_dir = os.path.join(self.data_dir, 'kline')
        if os.path.exists(kline_dir):
            return [f.replace('.csv', '') for f in os.listdir(kline_dir) if f.endswith('.csv')]
        if os.path.exists(self.data_dir):
            return [f.replace('.csv', '') for f in os.listdir(self.data_dir) if f.endswith('.csv')]
        return []

    # ---- 基本面打分引擎 ----

    def score_fundamentals(self, code: str, price: float = 0, year: str = '2025') -> dict:
        """
        对单只股票进行基本面综合打分 (0-100)

        打分维度:
        1. 盈利能力 (30分): ROE > 15%得满分, NP利润率, 毛利率
        2. 成长能力 (25分): 净利润增速 > 20%得满分
        3. 估值合理 (20分): PE/PB合理区间 (通过EPS/价格计算)
        4. 财务健康 (15分): 资产负债率 < 60%, 流动比率 > 1.5
        5. 营运效率 (10分): 周转率
        """
        data = self.get_fundamentals(code, year)
        if not data:
            return {'total_score': 0, 'details': {}, 'reason': '无基本面数据'}

        details = {}
        reasons = []

        # 1. 盈利能力 (30分)
        profit = data.get('profit', {})
        roe = profit.get('roeAvg', 0) or 0
        np_margin = profit.get('npMargin', 0) or 0
        gp_margin = profit.get('gpMargin', 0) or 0
        eps = profit.get('epsTTM', 0) or 0

        profit_score = 0
        if roe > 0.25:
            profit_score += 12
        elif roe > 0.15:
            profit_score += 10
        elif roe > 0.10:
            profit_score += 7
        elif roe > 0.05:
            profit_score += 4
        elif roe > 0:
            profit_score += 2

        if np_margin > 0.3:
            profit_score += 10
        elif np_margin > 0.2:
            profit_score += 7
        elif np_margin > 0.1:
            profit_score += 4
        elif np_margin > 0:
            profit_score += 2

        if gp_margin > 0.7:
            profit_score += 8
        elif gp_margin > 0.5:
            profit_score += 5
        elif gp_margin > 0.3:
            profit_score += 3

        details['profit_score'] = profit_score
        if roe > 0.15:
            reasons.append(f'ROE高({roe:.1%})')

        # 2. 成长能力 (25分)
        growth = data.get('growth', {})
        yoy_ni = growth.get('YOYNI', 0) or 0
        yoy_eps = growth.get('YOYEPSBasic', 0) or 0

        growth_score = 0
        if yoy_ni > 0.5:
            growth_score += 12
        elif yoy_ni > 0.3:
            growth_score += 10
        elif yoy_ni > 0.2:
            growth_score += 8
        elif yoy_ni > 0.1:
            growth_score += 5
        elif yoy_ni > 0:
            growth_score += 2

        if yoy_eps > 0.3:
            growth_score += 13
        elif yoy_eps > 0.2:
            growth_score += 10
        elif yoy_eps > 0.1:
            growth_score += 7
        elif yoy_eps > 0:
            growth_score += 3

        details['growth_score'] = growth_score
        if yoy_ni > 0.2:
            reasons.append(f'净利润增速高({yoy_ni:.1%})')
        if yoy_eps > 0.2:
            reasons.append(f'EPS增速高({yoy_eps:.1%})')

        # 3. 估值合理性 (20分) - 通过PE估算
        valuation_score = 0
        if eps > 0 and price > 0:
            pe = price / eps
            if pe > 0 and pe < 10:
                valuation_score = 18
                reasons.append(f'PE低估({pe:.1f}x)')
            elif pe < 20:
                valuation_score = 15
                reasons.append(f'PE合理({pe:.1f}x)')
            elif pe < 30:
                valuation_score = 12
            elif pe < 50:
                valuation_score = 8
            elif pe < 100:
                valuation_score = 4
            else:
                valuation_score = 2
        else:
            valuation_score = 10  # 未知算中性

        details['valuation_score'] = valuation_score

        # 4. 财务健康 (15分)
        balance = data.get('balance', {})
        liability_ratio = balance.get('liabilityToAsset', 1) or 1
        current_ratio = balance.get('currentRatio', 0) or 0

        health_score = 0
        if liability_ratio < 0.3:
            health_score += 8
            reasons.append(f'负债率极低({liability_ratio:.1%})')
        elif liability_ratio < 0.5:
            health_score += 7
        elif liability_ratio < 0.6:
            health_score += 5
        elif liability_ratio < 0.8:
            health_score += 3
        else:
            health_score += 1

        if current_ratio > 3:
            health_score += 7
        elif current_ratio > 1.5:
            health_score += 5
        elif current_ratio > 1:
            health_score += 3

        details['health_score'] = health_score

        # 5. 营运效率 (10分)
        operation = data.get('operation', {})
        nr_turn = operation.get('NRTurnRatio', 0) or 0

        operation_score = 0
        if nr_turn > 20:
            operation_score += 5
        elif nr_turn > 10:
            operation_score += 4
        elif nr_turn > 5:
            operation_score += 3
        elif nr_turn > 0:
            operation_score += 2

        details['operation_score'] = operation_score

        # 行业加分
        industry = data.get('industry', {})
        industry_name = industry.get('industryName', '')
        details['industry'] = industry_name

        total = min(profit_score + growth_score + valuation_score + health_score + operation_score, 100)

        return {
            'total_score': total,
            'details': details,
            'reasons': reasons,
            'roe': roe,
            'eps': eps,
            'pe': price / eps if eps > 0 and price > 0 else None,
            'yoy_ni': yoy_ni,
            'yoy_eps': yoy_eps,
            'industry': industry_name,
            'reason': '; '.join(reasons) if reasons else '基本面一般'
        }

    # ---- 行业信息 ----

    def get_industry_map(self) -> Dict[str, str]:
        """获取所有股票的行业映射"""
        cache_file = self.industry_file
        if os.path.exists(cache_file):
            with open(cache_file, 'r') as f:
                return json.load(f)

        codes = self._get_stock_codes()
        industry_map = {}
        self._ensure_login()
        for i, code in enumerate(codes):
            try:
                rs = bs.query_stock_industry(code=code)
                rows = []
                while rs.next():
                    rows.append(rs.get_row_data())
                if rows:
                    for row in rows:
                        idx = rs.fields.index('industryName') if 'industryName' in rs.fields else -1
                        code_idx = rs.fields.index('code')
                        if idx >= 0 and row[idx]:
                            industry_map[row[code_idx]] = row[idx]
            except:
                pass
            if (i + 1) % 100 == 0:
                print(f"    行业数据: {i+1}/{len(codes)}")

        os.makedirs(os.path.dirname(cache_file), exist_ok=True)
        with open(cache_file, 'w') as f:
            json.dump(industry_map, f, ensure_ascii=False)

        return industry_map


if __name__ == '__main__':
    loader = FundamentalLoader()

    # 测试单只股票
    print("=== 茅台基本面 ===")
    score = loader.score_fundamentals('sh.600519', price=1500)
    print(json.dumps(score, ensure_ascii=False, indent=2))

    loader.logout()
