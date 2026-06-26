#!/usr/bin/env python3
"""
A股AI量化交易系统 - 主入口

功能模块:
1. 数据下载: 从 BaoStock 批量下载个股历史K线
2. 策略回测: 基于10策略独立账户的多策略回测系统
3. 每日选股: 10策略联合扫描,输出当日选股推荐
4. 策略排名: 策略绩效排名与对比
5. 系统状态: 数据/账户/策略总览

使用方式:
    python main.py download [--top N] [--start DATE] [--end DATE]
    python main.py download-all                          # 下载全部975只
    python main.py backtest [--start DATE] [--end DATE]  # 多策略回测
    python main.py backtest-single STRATEGY [--start DATE] [--end DATE]  # 单策略回测
    python main.py scan [--top 10]                       # 10策略联合扫描
    python main.py report                                # 每日选股报告
    python main.py rank                                  # 策略排名
    python main.py status                                # 系统状态
"""

import sys
import os
import json
import yaml
import argparse
import logging
from datetime import datetime

# 确保项目根目录在路径中
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger(__name__)


# 策略类映射表 (5个中低频策略)
STRATEGY_MAP = {
    'trend_following': 'TrendFollowingStrategy',
    'mean_reversion': 'MeanReversionStrategy',
    'momentum_breakout': 'MomentumBreakoutStrategy',
    'multi_factor': 'MultiFactorStrategy',
    'oversold_bounce': 'OversoldBounceStrategy',
}


def load_config():
    """加载配置文件"""
    config_path = os.path.join(BASE_DIR, 'config', 'settings.yaml')
    with open(config_path, 'r', encoding='utf-8') as f:
        return yaml.safe_load(f)


def get_strategy_class(strategy_name):
    """根据策略名称获取策略类"""
    class_name = STRATEGY_MAP.get(strategy_name)
    if not class_name:
        raise ValueError(f"未知策略: {strategy_name}")
    from strategies import StrategyBase
    import importlib
    module_name = strategy_name
    if strategy_name == 'closing_strategy':
        module = importlib.import_module(f'strategies.{module_name}')
    else:
        module = importlib.import_module(f'strategies.{module_name}')
    return getattr(module, class_name)


def cmd_download(args):
    """下载历史数据"""
    from historical_loader import HistoricalDataLoader

    loader = HistoricalDataLoader()
    loader.login()

    pool = loader.get_stock_pool()
    if pool.empty:
        print("无法获取股票池!")
        loader.logout()
        return

    print(f"\n股票池: {len(pool)} 只")

    if args.top:
        pool = pool.head(args.top)
        print(f"选取前 {args.top} 只")

    results = loader.download_stock_pool(
        top_n=args.top,
        start_date=args.start,
        end_date=args.end,
        force=args.force,
        delay=args.delay
    )

    loader.logout()
    print(f"\n下载完成! 共 {len(results)} 只股票")


def cmd_download_all(args):
    """下载全部股票数据"""
    from historical_loader import HistoricalDataLoader

    config = load_config()
    loader = HistoricalDataLoader()
    loader.login()

    pool = loader.get_stock_pool()
    if pool.empty:
        print("无法获取股票池!")
        loader.logout()
        return

    print(f"\n股票池: {len(pool)} 只")
    print(f"开始下载全部股票数据...")

    results = loader.download_stock_pool(
        top_n=None,
        start_date=args.start or '2024-01-01',
        end_date=args.end,
        force=args.force,
        delay=args.delay
    )

    loader.logout()
    print(f"\n下载完成! 共 {len(results)} 只股票")


def cmd_backtest(args):
    """运行多策略回测"""
    from strategies_runner import MultiStrategyRunner

    config = load_config()
    strat_config = config.get('strategies', {})
    bt_config = config.get('backtest', {})

    # 创建回测运行器
    runner = MultiStrategyRunner(
        initial_cash=bt_config.get('initial_cash', 100000),
        commission_rate=config['account']['commission_rate'],
        min_commission=config['account']['min_commission'],
        stamp_tax_rate=config['account']['stamp_tax'],
        max_holdings=config['strategy']['max_holdings'],
        position_size_pct=config['strategy']['position_size_pct']
    )

    # 注册所有启用的策略
    for strat_key, strat_cfg in strat_config.items():
        if strat_cfg.get('enabled', False):
            try:
                strategy_cls = get_strategy_class(strat_key)
                strategy = strategy_cls()
                runner.add_strategy(strategy, strat_cfg.get('weight', 1.0))
                print(f"  已注册: {strat_key} (weight={strat_cfg.get('weight', 1.0)})")
            except Exception as e:
                print(f"  跳过 {strat_key}: {e}")

    if not runner.strategies:
        print("没有注册任何策略!")
        return

    # 加载数据
    top_n = getattr(args, 'top_n', None) or bt_config.get('top_n', 300)
    if top_n == 'all':
        top_n = None
    print(f"\n加载历史数据 (top_n={top_n})...")
    runner.load_data(top_n=top_n)

    if not runner.stock_data:
        print("没有历史数据! 请先运行: python main.py download")
        return

    # 运行回测
    result = runner.run(
        start_date=args.start or bt_config.get('start_date'),
        end_date=args.end or bt_config.get('end_date'),
        lookback=bt_config.get('lookback_days', 120)
    )

    # 输出报告
    if not result or not result.get('rankings'):
        print("回测结果为空，请检查回测参数和数据。")
        return

    report_text = runner._generate_report(result['rankings'], runner.get_trading_dates())
    print("\n" + report_text)

    # 保存报告
    report_dir = os.path.join(BASE_DIR, bt_config.get('report_dir', 'reports'))
    runner.save_report(result, report_dir)


def cmd_backtest_single(args):
    """运行单策略回测"""
    from strategies_runner import MultiStrategyRunner

    config = load_config()
    bt_config = config.get('backtest', {})

    strategy_name = args.strategy
    if strategy_name not in STRATEGY_MAP:
        print(f"未知策略: {strategy_name}")
        print(f"可用策略: {', '.join(STRATEGY_MAP.keys())}")
        return

    runner = MultiStrategyRunner(
        initial_cash=bt_config.get('initial_cash', 100000),
        commission_rate=config['account']['commission_rate'],
        min_commission=config['account']['min_commission'],
        stamp_tax_rate=config['account']['stamp_tax'],
        max_holdings=config['strategy']['max_holdings'],
        position_size_pct=config['strategy']['position_size_pct']
    )

    strategy_cls = get_strategy_class(strategy_name)
    strategy = strategy_cls()
    runner.add_strategy(strategy, 1.0)

    print("\n加载历史数据...")
    runner.load_data()

    if not runner.stock_data:
        print("没有历史数据! 请先运行: python main.py download")
        return

    result = runner.run(
        start_date=args.start or bt_config.get('start_date'),
        end_date=args.end or bt_config.get('end_date'),
        lookback=bt_config.get('lookback_days', 120)
    )

    report_text = runner._generate_report(result['rankings'], runner.get_trading_dates())
    print("\n" + report_text)

    report_dir = os.path.join(BASE_DIR, bt_config.get('report_dir', 'reports'))
    runner.save_report(result, report_dir)


def cmd_scan(args):
    """10策略联合扫描选股"""
    from strategies_runner import MultiStrategyRunner
    from historical_loader import HistoricalDataLoader

    config = load_config()
    strat_config = config.get('strategies', {})

    # 创建运行器并注册策略
    runner = MultiStrategyRunner(
        initial_cash=100000,
        commission_rate=config['account']['commission_rate'],
        min_commission=config['account']['min_commission'],
        stamp_tax_rate=config['account']['stamp_tax'],
        max_holdings=config['strategy']['max_holdings'],
        position_size_pct=config['strategy']['position_size_pct']
    )

    for strat_key, strat_cfg in strat_config.items():
        if strat_cfg.get('enabled', False):
            try:
                strategy_cls = get_strategy_class(strat_key)
                strategy = strategy_cls()
                runner.add_strategy(strategy, strat_cfg.get('weight', 1.0))
            except Exception as e:
                print(f"  跳过 {strat_key}: {e}")

    # 加载数据
    print("加载历史数据...")
    runner.load_data()

    if not runner.stock_data:
        print("没有历史数据! 请先运行: python main.py download")
        return

    # 获取扫描日期
    target_date = getattr(args, 'date', None)

    # 过滤数据到目标日期
    loader = HistoricalDataLoader()
    filtered_data = {}
    for code, df in runner.stock_data.items():
        if 'date' in df.columns and len(df) > 0:
            if target_date:
                d = df[df['date'] <= target_date].copy()
                if len(d) >= 30:
                    filtered_data[code] = d
            else:
                filtered_data[code] = df

    if not filtered_data:
        print("无可用数据!")
        return

    runner.stock_data = filtered_data

    if target_date:
        latest_date = target_date
    else:
        latest_dates = {}
        for code, df in filtered_data.items():
            if 'date' in df.columns and len(df) > 0:
                latest_dates[code] = df['date'].iloc[-1]
        latest_date = max(latest_dates.values()) if latest_dates else None

    if not latest_date:
        print("无可用数据!")
        return

    print(f"\n扫描日期: {latest_date}")

    # 各策略独立扫描
    all_signals = {}
    for name, strategy in runner.strategies.items():
        buy_signals = strategy.get_buy_signals(runner.stock_data, latest_date, {}, 100000)
        all_signals[name] = buy_signals[:10]

    # 汇总：被多个策略同时推荐的股票
    stock_scores = {}
    for strat_name, signals in all_signals.items():
        for sig in signals:
            code = sig['stock_code']
            if code not in stock_scores:
                stock_scores[code] = {
                    'code': code,
                    'name': runner.stock_names.get(code, ''),
                    'price': sig.get('price', 0),
                    'strategies': {},
                    'max_score': 0
                }
            stock_scores[code]['strategies'][strat_name] = sig.get('score', sig.get('confidence', 0))
            stock_scores[code]['max_score'] = max(
                stock_scores[code]['max_score'],
                sig.get('score', sig.get('confidence', 0))
            )

    # 按策略覆盖数排序，然后按最高分排序
    ranked = sorted(
        stock_scores.values(),
        key=lambda x: (len(x['strategies']), x['max_score']),
        reverse=True
    )

    top_n = args.top or 10
    print(f"\n{'=' * 70}")
    print(f"  10策略联合选股报告 ({latest_date})")
    print(f"{'=' * 70}")

    for i, stock in enumerate(ranked[:top_n], 1):
        strat_names = ', '.join(stock['strategies'].keys())
        print(f"\n  {i}. {stock['code']} {stock['name']}")
        print(f"     价格: {stock['price']:.2f}  最高分: {stock['max_score']:.1f}")
        print(f"     推荐策略 ({len(stock['strategies'])}个): {strat_names}")

    # 保存报告
    report_dir = os.path.join(BASE_DIR, 'reports')
    os.makedirs(report_dir, exist_ok=True)
    today = datetime.now().strftime('%Y%m%d')
    report_path = os.path.join(report_dir, f'selection_{today}.json')

    report_data = {
        'date': latest_date,
        'selections': [
            {
                'rank': i,
                'code': s['code'],
                'name': s['name'],
                'price': s['price'],
                'strategies': s['strategies'],
                'strategy_count': len(s['strategies']),
                'max_score': s['max_score']
            }
            for i, s in enumerate(ranked[:top_n], 1)
        ]
    }

    with open(report_path, 'w', encoding='utf-8') as f:
        json.dump(report_data, f, ensure_ascii=False, indent=2)
    print(f"\n  报告已保存: {report_path}")


def cmd_report(args):
    """生成每日选股报告 (含指数 + 选股)"""
    from baostock_fetcher import BaoStockFetcher, scan_stocks

    fetcher = BaoStockFetcher()
    fetcher.login()

    print("=" * 60)
    print("  每日选股报告")
    print(f"  日期: {datetime.now().strftime('%Y-%m-%d')}")
    print("=" * 60)

    # 指数行情
    print("\n【主要指数】")
    indices = [
        ('上证指数', 'sh.000001'),
        ('深证成指', 'sz.399001'),
        ('创业板指', 'sz.399006'),
    ]
    for name, code in indices:
        idx_df = fetcher.get_market_benchmark(code, days=5)
        if not idx_df.empty and len(idx_df) >= 2:
            prev_close = float(idx_df.iloc[-2]['close'])
            cur_close = float(idx_df.iloc[-1]['close'])
            change = (cur_close / prev_close - 1) * 100
            arrow = '\u2191' if change >= 0 else '\u2193'
            print(f"  {name}: {cur_close:.2f}  {arrow} {change:+.2f}%")

    # 扫描选股
    pool = fetcher.get_stock_pool()
    if not pool.empty:
        results = scan_stocks(fetcher, top_n=10, stock_pool=pool.head(200))
    else:
        results = []

    print(f"\n{'=' * 60}")
    print(f"【今日推荐 Top 10】")
    for i, stock in enumerate(results, 1):
        print(f"\n  {i}. {stock['code']} {stock['name']}")
        print(f"     价格: {stock['price']:.2f}  涨跌幅: {stock['change_pct']:+.2f}%")
        print(f"     综合评分: {stock['total_score']}")
        print(f"     信号: {', '.join(stock.get('signals', []))}")

    # 保存报告
    report_dir = os.path.join(BASE_DIR, 'reports')
    os.makedirs(report_dir, exist_ok=True)
    today = datetime.now().strftime('%Y%m%d')

    report = {
        'date': today,
        'indices': {},
        'selections': results
    }

    for name, code in indices:
        idx_df = fetcher.get_market_benchmark(code, days=5)
        if not idx_df.empty and len(idx_df) >= 2:
            report['indices'][name] = {
                'close': float(idx_df.iloc[-1]['close']),
                'change_pct': round(float((float(idx_df.iloc[-1]['close']) / float(idx_df.iloc[-2]['close']) - 1) * 100), 2)
            }

    report_path = os.path.join(report_dir, f'selection_{today}.json')
    with open(report_path, 'w', encoding='utf-8') as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"\n  报告已保存: {report_path}")

    fetcher.logout()


def cmd_rank(args):
    """加载最近的回测排名"""
    import glob

    report_dir = os.path.join(BASE_DIR, 'reports')
    if not os.path.exists(report_dir):
        print("无报告目录!")
        return

    # 找最新的排名文件
    ranking_files = sorted(glob.glob(os.path.join(report_dir, 'multi_backtest_*_ranking.json')))
    if not ranking_files:
        print("无排名数据! 请先运行: python main.py backtest")
        return

    latest = ranking_files[-1]
    with open(latest, 'r', encoding='utf-8') as f:
        data = json.load(f)

    print("=" * 70)
    print("  策略绩效排名")
    print(f"  数据来源: {os.path.basename(latest)}")
    print("=" * 70)

    rankings = data.get('rankings', [])
    if rankings:
        print(f"\n{'排名':<5} {'策略':<25} {'收益率%':>10} {'总价值':>14} {'夏普':>8} {'最大回撤%':>10} {'胜率%':>8} {'交易次数':>8}")
        print("-" * 90)
        for r in rankings:
            name = r.get('strategy', 'N/A')[:24]
            print(
                f"{r.get('rank', '?'):<5} {name:<25} {r.get('return_pct', 0):>9.2f}% "
                f"{r.get('total_value', 0):>13,.2f} {r.get('sharpe_ratio', 0):>7.3f} "
                f"{r.get('max_drawdown', 0):>9.2f}% {r.get('win_rate', 0):>7.1f}% {r.get('total_trades', 0):>7}"
            )

    print("\n" + "=" * 70)


def cmd_status(args):
    """查看系统状态"""
    from historical_loader import HistoricalDataLoader

    config = load_config()

    print("=" * 60)
    print("  系统状态")
    print("=" * 60)

    # 数据状态
    loader = HistoricalDataLoader()
    cached = loader.load_all()
    print(f"\n  缓存数据: {len(cached)} 只股票")

    if cached:
        for code, df in list(cached.items())[:5]:
            if 'date' in df.columns:
                print(f"    {code}: {len(df)} 条, {df['date'].iloc[0]} ~ {df['date'].iloc[-1]}")
        if len(cached) > 5:
            print(f"    ... 和 {len(cached)-5} 只更多")

    manifest_path = os.path.join(loader.data_dir, 'stock_pool.json')
    if os.path.exists(manifest_path):
        with open(manifest_path, 'r', encoding='utf-8') as f:
            manifest = json.load(f)
        print(f"  股票池清单: {len(manifest)} 只")

    # 策略状态
    strat_config = config.get('strategies', {})
    enabled = sum(1 for v in strat_config.values() if v.get('enabled', False))
    print(f"  已启用策略: {enabled}/{len(strat_config)}")
    for k, v in strat_config.items():
        status = "ON" if v.get('enabled', False) else "OFF"
        print(f"    [{status}] {k}: {v.get('description', '')}")

    # 报告
    report_dir = os.path.join(BASE_DIR, 'reports')
    if os.path.exists(report_dir):
        reports = [f for f in os.listdir(report_dir) if f.startswith('backtest_') or f.startswith('selection_') or f.startswith('multi_')]
        print(f"  报告文件: {len(reports)} 份")

    # v2 虚拟账户
    v2_state = os.path.join(BASE_DIR, 'account', 'account_state_v2.json')
    if os.path.exists(v2_state):
        with open(v2_state, 'r', encoding='utf-8') as f:
            v2 = json.load(f)
        print(f"\n  v2 虚拟账户:")
        print(f"    现金: {v2.get('cash', 0):,.2f}")
        print(f"    持仓: {len(v2.get('positions', {}))} 只")
        print(f"    累计盈亏: {v2.get('total_profit', 0):+,.2f}")
        print(f"    总交易: {v2.get('total_trades', 0)}")
        print(f"    更新: {v2.get('updated_at', 'N/A')}")

    import glob
    v2_picks = sorted(glob.glob(os.path.join(BASE_DIR, 'knowledge_base', 'daily_pick_*.json')))
    if v2_picks:
        print(f"  v2 选股报告: {len(v2_picks)} 份 (最新: {os.path.basename(v2_picks[-1])})")

    print("=" * 60)


def cmd_run(args):
    """运行 v2 每日流水线 (盘中卖+买)"""
    from daily_runner_v2 import run_intraday_flow, get_trading_date, format_message
    date = getattr(args, 'date', None) or get_trading_date()
    result = run_intraday_flow(date)
    print(format_message(date, result, mode="intraday"))


def cmd_boss(args):
    """已废弃: 原 10-Agent 模式，现统一使用 v2 单账户"""
    if getattr(args, 'report', False):
        import glob
        reports = sorted(glob.glob(os.path.join(BASE_DIR, 'knowledge_base', 'daily_pick_*.json')))
        if not reports:
            print("暂无 v2 选股报告")
            return
        with open(reports[-1], 'r', encoding='utf-8') as f:
            report = json.load(f)
        print(f"最新报告: {report.get('date')} | 评分 {report.get('total_scored')} 只")
        for i, p in enumerate(report.get('top_picks', [])[:5], 1):
            print(f"  #{i} {p.get('code')} 得分={p.get('final_score', 0)}")
        return
    print("boss 命令已废弃，请使用: python main.py run 或 python main.py pick")
    cmd_run(args)


def cmd_monitor(args):
    """v2 监控"""
    from monitor import cmd_monitor as _cmd_monitor
    _cmd_monitor([args.monitor_cmd] if args.monitor_cmd else [])


def cmd_trade(args):
    """执行 v2 交易 (默认盘中卖+买，--sell-only 仅卖出)"""
    from daily_runner_v2 import run_intraday_flow, run_sell_flow, run_picker_flow, get_trading_date, format_message
    date = getattr(args, 'date', None) or get_trading_date()
    if getattr(args, 'sell_only', False):
        result = run_sell_flow(date)
        print(format_message(date, result, mode="sell"))
    elif getattr(args, 'pick_only', False):
        result = run_picker_flow(date)
        print(format_message(date, result, mode="intraday"))
    else:
        result = run_intraday_flow(date)
        print(format_message(date, result, mode="intraday"))


def cmd_optimize(args):
    """策略优化 (v2 周优化)"""
    from optimize_weekly import run_optimization
    run_optimization(quick=getattr(args, 'quick', False))


def cmd_pick(args):
    """多因子量化选股 v2"""
    from trade_engine_v2 import get_account

    if getattr(args, 'reset', False):
        acct = get_account()
        acct.reset()
        print("虚拟账户已重置")
        return

    from global_stock_picker import run_picker
    result = run_picker(
        date=getattr(args, 'date', None),
        top_n=getattr(args, 'top', 10),
        min_score=getattr(args, 'min_score', 45),
    )

    print(f"\n{'='*50}")
    print(f"选股完成: {result['date']}")
    print(f"股票池: {result['total_pool']} | 评分: {result['total_scored']}")
    print(f"总资产: {result['account_value']:,.2f}元")
    print(f"\nTop {getattr(args, 'top', 10)} 推荐:")
    for i, pick in enumerate(result["top_picks"][:getattr(args, 'top', 10)]):
        print(f"  #{i+1} {pick['code']} @ {pick['price']} 得分={pick.get('final_score', pick.get('total_score', 0))}")
    if result.get("buy_actions"):
        print(f"\n买入:")
        for ba in result["buy_actions"]:
            print(f"  {ba['code']} @ {ba['price']} x {ba['shares']}股")
    if result.get("stop_actions"):
        print(f"\n卖出:")
        for sa in result["stop_actions"]:
            print(f"  {sa['code']} @ {sa['price']} 盈亏={sa.get('profit_pct', 0):+.1f}%")


def main():
    parser = argparse.ArgumentParser(description='A股AI量化交易系统')
    subparsers = parser.add_subparsers(dest='command', help='命令')

    # download
    dl_parser = subparsers.add_parser('download', help='下载历史数据')
    dl_parser.add_argument('--top', type=int, default=None, help='下载前N只股票')
    dl_parser.add_argument('--start', type=str, default='2024-01-01', help='开始日期')
    dl_parser.add_argument('--end', type=str, default=None, help='结束日期')
    dl_parser.add_argument('--force', action='store_true', help='强制重新下载')
    dl_parser.add_argument('--delay', type=float, default=0.5, help='请求间隔(秒)')

    # download-all
    dal_parser = subparsers.add_parser('download-all', help='下载全部股票数据')
    dal_parser.add_argument('--start', type=str, default='2024-01-01', help='开始日期')
    dal_parser.add_argument('--end', type=str, default=None, help='结束日期')
    dal_parser.add_argument('--force', action='store_true', help='强制重新下载')
    dal_parser.add_argument('--delay', type=float, default=0.5, help='请求间隔(秒)')

    # backtest
    bt_parser = subparsers.add_parser('backtest', help='运行多策略回测')
    bt_parser.add_argument('--start', type=str, default=None, help='回测开始日期')
    bt_parser.add_argument('--end', type=str, default=None, help='回测结束日期')
    bt_parser.add_argument('--top-n', type=int, default=300,
        help='回测股票数量（默认300只，all=全量）')

    # backtest-single
    bts_parser = subparsers.add_parser('backtest-single', help='运行单策略回测')
    bts_parser.add_argument('strategy', type=str, help='策略名称')
    bts_parser.add_argument('--start', type=str, default=None, help='回测开始日期')
    bts_parser.add_argument('--end', type=str, default=None, help='回测结束日期')

    # scan
    scan_parser = subparsers.add_parser('scan', help='10策略联合扫描选股')
    scan_parser.add_argument('--top', type=int, default=10, help='返回Top N')
    scan_parser.add_argument('--date', type=str, help='选股日期 (默认今日)')

    # report
    subparsers.add_parser('report', help='生成每日选股报告(含指数)')

    # rank
    subparsers.add_parser('rank', help='查看策略排名')

    # status
    subparsers.add_parser('status', help='查看系统状态')

    # run - v2 daily pipeline
    run_parser = subparsers.add_parser('run', help='运行v2每日流水线(选股+买入)')
    run_parser.add_argument('--date', type=str, default=None, help='交易日期')

    # boss - deprecated alias
    boss_parser = subparsers.add_parser('boss', help='[已废弃] 查看v2报告或运行选股')
    boss_parser.add_argument('--date', type=str, default=None, help='交易日期')
    boss_parser.add_argument('--report', action='store_true', help='查看最新v2报告')

    # trade - execute v2 trades
    trade_parser = subparsers.add_parser('trade', help='执行v2交易')
    trade_parser.add_argument('--date', type=str, default=None, help='交易日期')
    trade_parser.add_argument('--sell-only', action='store_true', help='仅执行卖出检查')

    # pick - v2 factor-based stock picker (全局选股器)
    pick_parser = subparsers.add_parser('pick', help='多因子量化选股(v2)')
    pick_parser.add_argument('--date', type=str, default=None, help='选股日期 (YYYY-MM-DD)')
    pick_parser.add_argument('--top', type=int, default=10, help='输出Top N')
    pick_parser.add_argument('--min-score', type=int, default=45, help='最低综合分')
    pick_parser.add_argument('--reset', action='store_true', help='重置虚拟账户')

    # optimize - weekly optimization
    opt_parser = subparsers.add_parser('optimize', help='策略优化（回测+分析）')
    opt_parser.add_argument('--quick', action='store_true', help='快速模式(近3个月)')

    # monitor - real-time monitoring
    mon_parser = subparsers.add_parser('monitor', help='全天候监控')
    mon_sub = mon_parser.add_subparsers(dest='monitor_cmd')
    mon_sub.add_parser('run', help='启动全天候监控(后台运行)')
    mon_sub.add_parser('morning', help='早盘选股报告')
    mon_sub.add_parser('check', help='盘中检查')
    mon_sub.add_parser('review', help='收盘复盘')
    mon_sub.add_parser('status', help='查看监控状态')

    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        return

    commands = {
        'download': cmd_download,
        'download-all': cmd_download_all,
        'backtest': cmd_backtest,
        'backtest-single': cmd_backtest_single,
        'scan': cmd_scan,
        'report': cmd_report,
        'rank': cmd_rank,
        'status': cmd_status,
        'run': cmd_run,
        'boss': cmd_boss,
        'trade': cmd_trade,
        'optimize': cmd_optimize,
        'pick': cmd_pick,
        'monitor': cmd_monitor,
    }

    commands[args.command](args)


if __name__ == '__main__':
    main()
