"""
回测收益计算单元测试

测试目标：
1. 收益计算函数（total_return, max_drawdown, sharpe, annual_return）
2. 排名表与净值曲线数据一致性
3. Dashboard 年化收益计算

运行方式：
  python test_backtest_metrics.py
  python test_backtest_metrics.py --quick  (只跑核心用例)
"""

import json
import math
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta

import numpy as np
import pandas as pd

# Add project root
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, PROJECT_ROOT)


def make_nav_series(dates, values):
    """Build a daily_nav list from parallel date/value arrays."""
    return [{'date': d, 'total_value': v, 'cash': v, 'position_value': 0}
            for d, v in zip(dates, values)]


def generate_dates(start, count):
    if isinstance(start, str):
        start = datetime.strptime(start, '%Y-%m-%d')
    return [(start + timedelta(days=i)).strftime('%Y-%m-%d') for i in range(count)]


# ── Core metric helpers (mirror backtest.py & strategy_ranker.py) ──────────

def compute_total_return(nav_list, initial_cash):
    """(final / initial - 1) * 100"""
    if not nav_list:
        return 0.0
    return (nav_list[-1]['total_value'] / initial_cash - 1) * 100


def compute_max_drawdown(nav_list):
    """Peak-to-trough drawdown in percent (negative value)."""
    values = [d['total_value'] for d in nav_list]
    if len(values) < 2:
        return 0.0
    peak = np.maximum.accumulate(values)
    dd = (np.array(values) - peak) / peak * 100
    return float(dd.min())


def compute_sharpe(nav_list, risk_free_annual=0.03):
    """Annualized Sharpe from daily NAV values."""
    values = [d['total_value'] for d in nav_list]
    if len(values) < 2:
        return 0.0
    daily_returns = np.diff(values) / values[:-1]
    daily_rf = risk_free_annual / 252
    excess = daily_returns - daily_rf
    std = np.std(excess, ddof=1)
    if std < 1e-10:
        return 0.0
    return float((np.mean(excess) / std) * np.sqrt(252))


def compute_annual_return(total_return_pct, trading_days):
    """Simple annualized return = total_return * (252 / days) — dashboard style."""
    if trading_days <= 0:
        return 0.0
    return total_return_pct * (252.0 / trading_days)


def compute_compound_annual_return(initial, final, trading_days):
    """CAGR style annual return — strategy_ranker.py style."""
    if trading_days <= 0:
        return 0.0
    years = trading_days / 252.0
    if years < 0.001:
        years = 0.001
    return ((final / initial) ** (1.0 / years) - 1) * 100


# ── Test Cases ────────────────────────────────────────────────────────────

class TestArithmeticSeries(unittest.TestCase):
    """已知等差数列的精确值校验."""

    def test_flat_line(self):
        """全为10万的常数序列 → return=0, dd=0, sharpe≈0."""
        dates = generate_dates('2025-01-01', 60)
        nav = make_nav_series(dates, [100000.0] * 60)
        self.assertAlmostEqual(compute_total_return(nav, 100000), 0.0, places=4)
        self.assertAlmostEqual(compute_max_drawdown(nav), 0.0, places=4)
        # sharpe should be 0 because std==0
        self.assertAlmostEqual(compute_sharpe(nav), 0.0, places=4)

    def test_linear_up(self):
        """等差递增 100k → 106k (60天, 每天 +100)."""
        dates = generate_dates('2025-01-01', 60)
        values = [100000.0 + i * 100 for i in range(60)]
        nav = make_nav_series(dates, values)
        ret = compute_total_return(nav, 100000)
        expected_ret = (105900 / 100000 - 1) * 100  # 5.9%
        self.assertAlmostEqual(ret, expected_ret, places=4)
        # Linear up → no drawdown
        self.assertAlmostEqual(compute_max_drawdown(nav), 0.0, places=4)
        # Sharpe should be positive
        self.assertGreater(compute_sharpe(nav), 0)

    def test_linear_down(self):
        """等差递减 100k → 94k (60天, 每天 -100)."""
        dates = generate_dates('2025-01-01', 60)
        values = [100000.0 - i * 100 for i in range(60)]
        nav = make_nav_series(dates, values)
        ret = compute_total_return(nav, 100000)
        expected_ret = (94100 / 100000 - 1) * 100  # -5.9%
        self.assertAlmostEqual(ret, expected_ret, places=4)
        # Drawdown should be negative and significant
        dd = compute_max_drawdown(nav)
        self.assertLess(dd, -5.0)
        self.assertLess(compute_sharpe(nav), 0)

    def test_up_then_down_triangle(self):
        """先升后降三角形：100k → 110k → 95k."""
        dates = generate_dates('2025-01-01', 100)
        values = []
        for i in range(50):
            values.append(100000 + i * 200)  # 100k → 110k
        for i in range(50):
            values.append(110000 - i * 300)  # 110k → 95k
        nav = make_nav_series(dates, values)
        ret = compute_total_return(nav, 100000)
        # Final is 95300 (110000 - 49*300) → (95300/100000-1)*100 = -4.7%
        self.assertAlmostEqual(ret, -4.7, places=4)
        # Max drawdown: from peak 110k down to 95300 → (95300-110000)/110000 = -13.36%
        dd = compute_max_drawdown(nav)
        self.assertAlmostEqual(dd, (95300 - 110000) / 110000 * 100, places=2)


class TestAnnualReturn(unittest.TestCase):
    """年化收益两种计算方式的校验."""

    def test_simple_annual_return(self):
        """134天 +7.1% → 年化约 13.35%."""
        ann = compute_annual_return(7.1, 134)
        self.assertAlmostEqual(ann, 13.35, places=1)

    def test_cagr_annual_return(self):
        """CAGR: 100k → 107100, 134 days."""
        ann = compute_compound_annual_return(100000, 107100, 134)
        # (1.071 ^ (252/134) - 1) * 100 ≈ 13.5%
        expected = ((107100 / 100000) ** (252 / 134) - 1) * 100
        self.assertAlmostEqual(ann, expected, places=2)

    def test_negative_annual_return(self):
        """亏损的年化."""
        ann = compute_annual_return(-19.02, 134)
        # -19.02 * 252 / 134 = -35.79
        expected = -19.02 * (252 / 134)
        self.assertAlmostEqual(ann, expected, places=2)


class TestNavVsRankingConsistency(unittest.TestCase):
    """净值曲线与排名表数据一致性校验."""

    def test_synthetic_consistency(self):
        """人工构造数据验证：排名 return_pct == (nav_last / nav_first - 1) * 100."""
        dates = generate_dates('2025-01-01', 50)
        # Simulate: 100k → 115k
        values = [100000 + i * 300 for i in range(50)]
        nav = make_nav_series(dates, values)

        nav_return = (nav[-1]['total_value'] / nav[0]['total_value'] - 1) * 100
        metric_return = compute_total_return(nav, 100000)
        self.assertAlmostEqual(nav_return, metric_return, places=4)

    def test_drawdown_consistency(self):
        """净值下降必须有负收益 + 负回撤."""
        dates = generate_dates('2025-01-01', 50)
        values = [100000 - i * 200 for i in range(50)]
        nav = make_nav_series(dates, values)
        ret = compute_total_return(nav, 100000)
        dd = compute_max_drawdown(nav)
        self.assertLess(ret, 0)
        self.assertLess(dd, 0)
        # For monotonic decrease, drawdown at end = total_return
        # peak = 100000, last = 90100, dd = (90100-100000)/100000*100 = -9.9%
        # total_return = (90100/100000-1)*100 = -9.9%
        # They should be equal for monotonic decrease from start
        self.assertAlmostEqual(dd, ret, places=1)

    def test_curve_direction_matches_return_sign(self):
        """核心规则：曲线终点 > 起点 → return > 0, 反之亦然."""
        test_cases = [
            ([100000, 110000], True),   # up → positive
            ([100000, 90000], False),    # down → negative
            ([100000, 100000], True),    # flat → zero (>= 0)
        ]
        for values, expect_positive in test_cases:
            dates = generate_dates('2025-01-01', len(values))
            nav = make_nav_series(dates, values)
            ret = compute_total_return(nav, values[0])
            if expect_positive:
                self.assertGreaterEqual(ret, 0,
                    f"Values {values} should have non-negative return, got {ret}")
            else:
                self.assertLess(ret, 0,
                    f"Values {values} should have negative return, got {ret}")


class TestSharpeProperties(unittest.TestCase):
    """夏普比率基本性质."""

    def test_constant_nav_sharpe_zero(self):
        """常数净值 → sharpe = 0 (std=0 case)."""
        dates = generate_dates('2025-01-01', 30)
        nav = make_nav_series(dates, [50000.0] * 30)
        self.assertAlmostEqual(compute_sharpe(nav), 0.0, places=4)

    def test_steady_up_sharpe_positive(self):
        """有波动的上升趋势 → sharpe > 0."""
        dates = generate_dates('2025-01-01', 60)
        rng = np.random.RandomState(42)
        # Daily return ~0.2% +/- 0.5% → clear positive drift with noise
        returns = 0.002 + rng.randn(59) * 0.005
        values = (np.cumprod([1.0] + returns) * 100000).tolist()
        nav = make_nav_series(dates, values)
        self.assertGreater(compute_sharpe(nav), 0)

    def test_steady_down_sharpe_negative(self):
        """有波动的下降趋势 → sharpe < 0."""
        dates = generate_dates('2025-01-01', 60)
        rng = np.random.RandomState(42)
        # Daily return ~-0.2% +/- 0.5% → clear negative drift with noise
        returns = -0.002 + rng.randn(59) * 0.005
        values = (np.cumprod([1.0] + returns) * 100000).tolist()
        nav = make_nav_series(dates, values)
        self.assertLess(compute_sharpe(nav), 0)

    def test_volatile_same_mean(self):
        """相同均值但不同波动 → 波动大 sharpe 低 (数学确定性)."""
        # Sharpe = (mean - rf) / std * sqrt(252)
        # If mean > rf and mean is the same, then higher std => lower Sharpe.
        # Build two NAV series with identical mean daily return but different volatility.
        dates = generate_dates('2025-01-01', 500)
        rng1 = np.random.RandomState(100)
        rng2 = np.random.RandomState(200)
        base_return = 0.001  # 0.1% daily
        # Low vol: +/- 0.2%
        low_rets = base_return + rng1.randn(499) * 0.002
        # High vol: +/- 2%
        high_rets = base_return + rng2.randn(499) * 0.02
        low_nav = make_nav_series(dates, (np.cumprod([1.0] + low_rets) * 100000).tolist())
        high_nav = make_nav_series(dates, (np.cumprod([1.0] + high_rets) * 100000).tolist())
        low_sharpe = compute_sharpe(low_nav)
        high_sharpe = compute_sharpe(high_nav)
        # With 500 samples and 10x vol difference, Sharpe ordering is deterministic
        self.assertGreater(low_sharpe, high_sharpe,
            f"Low vol Sharpe ({low_sharpe:.4f}) should > High vol Sharpe ({high_sharpe:.4f})")


class TestRealBacktestData(unittest.TestCase):
    """对真实回测数据进行一致性检查."""

    def _get_backtest_dir(self):
        return os.path.join(PROJECT_ROOT, 'reports', 'half_year_backtest')

    def test_ranking_matches_daily_nav(self):
        """排名表的 return_pct 必须与 daily_nav 首尾比值一致."""
        bdir = self._get_backtest_dir()
        if not os.path.exists(bdir):
            self.skipTest("half_year_backtest dir not found")

        ranking_path = os.path.join(bdir, 'half_year_backtest_ranking.json')
        if not os.path.exists(ranking_path):
            self.skipTest("ranking file not found")

        with open(ranking_path) as f:
            data = json.load(f)

        rankings = data.get('rankings', data.get('strategies', []))
        for r in rankings:
            name = r.get('strategy', r.get('name', ''))
            ranking_return = r.get('return_pct', 0)

            nav_path = os.path.join(bdir, f'{name}_daily_nav.json')
            if not os.path.exists(nav_path):
                continue
            with open(nav_path) as f:
                nav = json.load(f)
            if len(nav) < 2:
                continue

            nav_return = (nav[-1]['total_value'] / nav[0]['total_value'] - 1) * 100
            # Allow 0.2% tolerance (trailing precision)
            self.assertAlmostEqual(
                ranking_return, nav_return, places=1,
                msg=f"{name}: ranking return {ranking_return}% != nav return {nav_return}%"
            )

    def test_curve_direction_matches_return(self):
        """净值曲线方向必须与收益率符号一致."""
        bdir = self._get_backtest_dir()
        if not os.path.exists(bdir):
            self.skipTest("half_year_backtest dir not found")

        for f in os.listdir(bdir):
            if not f.endswith('_daily_nav.json'):
                continue
            nav_path = os.path.join(bdir, f)
            with open(nav_path) as fh:
                nav = json.load(fh)
            if len(nav) < 2:
                continue
            first_val = nav[0]['total_value']
            last_val = nav[-1]['total_value']
            ret = compute_total_return(nav, first_val)
            if last_val > first_val:
                self.assertGreaterEqual(ret, 0, f"{f}: curve up but return={ret}%")
            elif last_val < first_val:
                self.assertLess(ret, 0, f"{f}: curve down but return={ret}%")
            else:
                self.assertAlmostEqual(ret, 0, places=4, msg=f"{f}: flat curve")

    def test_drawdown_is_negative(self):
        """最大回撤应该是负值（或0表示无回撤）."""
        bdir = self._get_backtest_dir()
        if not os.path.exists(bdir):
            self.skipTest("half_year_backtest dir not found")

        for f in os.listdir(bdir):
            if not f.endswith('_daily_nav.json'):
                continue
            nav_path = os.path.join(bdir, f)
            with open(nav_path) as fh:
                nav = json.load(fh)
            dd = compute_max_drawdown(nav)
            self.assertLessEqual(dd, 0, f"{f}: drawdown should be <= 0, got {dd}")

    def test_trade_count_matches(self):
        """排名表交易次数应与 trades.json 文件行数一致."""
        bdir = self._get_backtest_dir()
        if not os.path.exists(bdir):
            self.skipTest("half_year_backtest dir not found")

        ranking_path = os.path.join(bdir, 'half_year_backtest_ranking.json')
        if not os.path.exists(ranking_path):
            self.skipTest("ranking file not found")

        with open(ranking_path) as f:
            data = json.load(f)

        for r in data.get('rankings', []):
            name = r.get('strategy', r.get('name', ''))
            ranking_trades = r.get('total_trades', 0)

            trades_path = os.path.join(bdir, f'{name}_trades.json')
            if not os.path.exists(trades_path):
                continue
            with open(trades_path) as f:
                trades = json.load(f)
            self.assertEqual(
                len(trades), ranking_trades,
                msg=f"{name}: ranking trades={ranking_trades} but file has {len(trades)}"
            )


class TestEdgeCases(unittest.TestCase):
    """边界情况."""

    def test_empty_nav(self):
        self.assertAlmostEqual(compute_total_return([], 100000), 0)
        self.assertAlmostEqual(compute_max_drawdown([]), 0)
        self.assertAlmostEqual(compute_sharpe([]), 0)

    def test_single_point_nav(self):
        nav = [{'date': '2025-01-01', 'total_value': 100000}]
        self.assertAlmostEqual(compute_total_return(nav, 100000), 0)
        self.assertAlmostEqual(compute_max_drawdown(nav), 0)
        self.assertAlmostEqual(compute_sharpe(nav), 0)

    def test_two_points_up(self):
        nav = [
            {'date': '2025-01-01', 'total_value': 100000},
            {'date': '2025-01-02', 'total_value': 105000},
        ]
        self.assertAlmostEqual(compute_total_return(nav, 100000), 5.0, places=4)
        self.assertAlmostEqual(compute_max_drawdown(nav), 0.0, places=4)

    def test_two_points_down(self):
        nav = [
            {'date': '2025-01-01', 'total_value': 100000},
            {'date': '2025-01-02', 'total_value': 95000},
        ]
        self.assertAlmostEqual(compute_total_return(nav, 100000), -5.0, places=4)
        self.assertAlmostEqual(compute_max_drawdown(nav), -5.0, places=4)

    def test_zero_initial(self):
        """初始资金为0时不报错."""
        nav = [{'date': '2025-01-01', 'total_value': 5000}]
        # Division by zero → should handle gracefully
        try:
            ret = compute_total_return(nav, 0)
            self.assertTrue(math.isinf(ret) or math.isnan(ret))
        except ZeroDivisionError:
            pass  # acceptable


if __name__ == '__main__':
    quick = '--quick' in sys.argv
    if quick:
        # Only run synthetic tests (no file I/O)
        loader = unittest.TestLoader()
        suite = unittest.TestSuite()
        suite.addTests(loader.loadTestsFromTestCase(TestArithmeticSeries))
        suite.addTests(loader.loadTestsFromTestCase(TestAnnualReturn))
        suite.addTests(loader.loadTestsFromTestCase(TestEdgeCases))
        suite.addTests(loader.loadTestsFromTestCase(TestSharpeProperties))
    else:
        suite = unittest.TestLoader().loadTestsFromModule(sys.modules[__name__])

    unittest.TextTestRunner(verbosity=2).run(suite)
