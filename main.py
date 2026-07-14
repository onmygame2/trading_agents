#!/usr/bin/env python3
"""
A股AI量化交易系统 - 主入口 (v2)

使用方式:
    python main.py status                              # 系统状态
    python main.py pick [--top 10]                     # 多因子选股
    python main.py run                                 # 盘中卖+买
    python main.py trade --sell-only                   # 仅卖出检查
    python main.py backtest [--start DATE] [--end DATE]  # v2 策略回测
    python main.py optimize [--quick]                  # 周优化回测
    python main.py download [--top N]                  # 下载K线
    python main.py monitor check                       # 盘中监控
    python main.py agent review                        # Agent 每日复盘
"""

import sys
import os
import json
import yaml
import argparse
import logging
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger(__name__)


def load_config():
    config_path = os.path.join(BASE_DIR, 'config', 'settings.yaml')
    with open(config_path, 'r', encoding='utf-8') as f:
        return yaml.safe_load(f)


def cmd_download(args):
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
    from historical_loader import HistoricalDataLoader

    loader = HistoricalDataLoader()
    loader.login()

    pool = loader.get_stock_pool()
    if pool.empty:
        print("无法获取股票池!")
        loader.logout()
        return

    print(f"\n股票池: {len(pool)} 只")
    print("开始下载全部股票数据...")

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
    """v2 多策略回测"""
    from backtest_v2 import (
        BACKTEST_TRAIN_END,
        default_backtest_range,
        print_ranking,
        run_backtest,
        save_reports,
    )

    logging.getLogger("strategies_v2.manager").setLevel(logging.WARNING)

    if args.quick:
        from datetime import timedelta
        start = (datetime.now() - timedelta(days=90)).strftime("%Y-%m-%d")
        end = datetime.now().strftime("%Y-%m-%d")
        pool_mode = "liquidity"
        pool_top = 200
    else:
        start = args.start
        end = args.end
        if not start and not end:
            start, end = default_backtest_range()
        pool_mode = args.pool_mode
        pool_top = args.pool_top if args.pool_top > 0 else None

    result = run_backtest(
        start=start or "2024-01-01",
        end=end or BACKTEST_TRAIN_END,
        pool_mode=pool_mode,
        pool_top=pool_top,
        min_score=args.min_score,
        top_n=args.top_n,
    )
    print_ranking(result.get("strategies", {}))

    tag = datetime.now().strftime("%Y%m%d_%H%M%S")
    if args.quick:
        tag += "_quick"
    save_reports(result, tag)


def cmd_rank(args):
    """查看最近一次 v2 回测排名"""
    benchmark = os.path.join(BASE_DIR, 'reports', 'backtest_v2', 'summary_benchmark.json')
    if not os.path.exists(benchmark):
        print("无回测数据! 请先运行: python main.py backtest")
        return

    with open(benchmark, 'r', encoding='utf-8') as f:
        data = json.load(f)

    print("=" * 88)
    print("  v2 策略绩效排名 (基准回测)")
    print(f"  区间: {data.get('start')} ~ {data.get('end')}")
    print("=" * 88)

    strategies = data.get('strategies', [])
    print(f"\n{'排名':<4} {'策略':<18} {'收益%':>8} {'CAGR%':>8} {'Sharpe':>7} {'回撤%':>8} {'胜率%':>7} {'交易':>5}")
    print("-" * 88)
    for i, r in enumerate(strategies, 1):
        name = r.get('display_name', r.get('strategy', 'N/A'))[:18]
        print(
            f"{i:<4} {name:<18} {r.get('return_pct', 0):>7.2f}% "
            f"{r.get('cagr_pct', r.get('annual_return_pct', 0)):>7.2f}% "
            f"{r.get('sharpe', 0):>7.3f} {r.get('max_drawdown', 0):>7.2f}% "
            f"{r.get('win_rate', 0):>6.1f}% {r.get('total_trades', 0):>5}"
        )
    print("=" * 88)


def cmd_status(args):
    from historical_loader import HistoricalDataLoader
    from strategies_v2.manager import StrategyManager

    print("=" * 60)
    print("  系统状态 (v2)")
    print("=" * 60)

    loader = HistoricalDataLoader()
    cached = loader.load_all()
    print(f"\n  缓存K线: {len(cached)} 只")

    pool_path = os.path.join(BASE_DIR, 'data', 'stock_pool.json')
    if os.path.exists(pool_path):
        with open(pool_path, 'r', encoding='utf-8') as f:
            pool = json.load(f)
        count = len(pool) if isinstance(pool, list) else len(pool.get('stocks', pool))
        print(f"  股票池: {count} 只")

    mgr = StrategyManager()
    print(f"\n  v2 策略 ({len(mgr.strategies)} 个):")
    for sid, mod in mgr.strategies.items():
        meta = mod.metadata
        enabled = "ON" if meta.get("enabled", True) else "OFF"
        weight = meta.get("weight", 1.0)
        print(f"    [{enabled}] {meta.get('name', sid)} (weight={weight})")

    v2_state = os.path.join(BASE_DIR, 'account', 'account_state_v2.json')
    if os.path.exists(v2_state):
        with open(v2_state, 'r', encoding='utf-8') as f:
            v2 = json.load(f)
        print(f"\n  组合账户 (composite):")
        print(f"    现金: {v2.get('cash', 0):,.2f}")
        print(f"    持仓: {len(v2.get('positions', {}))} 只")
        print(f"    累计盈亏: {v2.get('total_profit', 0):+,.2f}")
        print(f"    更新: {v2.get('updated_at', 'N/A')}")

    import glob
    v2_picks = sorted(glob.glob(os.path.join(BASE_DIR, 'knowledge_base', 'daily_pick_*.json')))
    if v2_picks:
        print(f"  选股报告: {len(v2_picks)} 份 (最新: {os.path.basename(v2_picks[-1])})")

    benchmark = os.path.join(BASE_DIR, 'reports', 'backtest_v2', 'summary_benchmark.json')
    if os.path.exists(benchmark):
        with open(benchmark, 'r', encoding='utf-8') as f:
            bt = json.load(f)
        print(f"  基准回测: {bt.get('start')} ~ {bt.get('end')}")

    print("=" * 60)


def cmd_run(args):
    from daily_runner_v2 import run_intraday_flow, get_trading_date, format_message
    date = getattr(args, 'date', None) or get_trading_date()
    result = run_intraday_flow(date)
    print(format_message(date, result, mode="intraday"))


def cmd_monitor(args):
    from monitor import cmd_monitor as _cmd_monitor
    _cmd_monitor([args.monitor_cmd] if args.monitor_cmd else [])


def cmd_trade(args):
    from daily_runner_v2 import run_intraday_flow, run_sell_flow, get_trading_date, format_message
    date = getattr(args, 'date', None) or get_trading_date()
    if getattr(args, 'sell_only', False):
        result = run_sell_flow(date)
        print(format_message(date, result, mode="sell"))
    else:
        result = run_intraday_flow(date)
        print(format_message(date, result, mode="intraday"))


def cmd_optimize(args):
    from optimize_weekly import run_optimization
    run_optimization(quick=getattr(args, 'quick', False))


def cmd_pick(args):
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
        print("\n买入:")
        for ba in result["buy_actions"]:
            print(f"  {ba['code']} @ {ba['price']} x {ba['shares']}股")
    if result.get("stop_actions"):
        print("\n卖出:")
        for sa in result["stop_actions"]:
            print(f"  {sa['code']} @ {sa['price']} 盈亏={sa.get('profit_pct', 0):+.1f}%")


def cmd_agent(args):
    if args.agent_cmd == 'review':
        date = getattr(args, 'date', None)
        try:
            from core.market_state import track_market_state
            track_market_state(date)
        except Exception as e:
            print(f"市场状态采集跳过: {e}")
        from agent_runtime.orchestrator import run_daily_review
        result = run_daily_review(date=date)
        print("\n" + "=" * 60)
        print(f"  {result.get('title', 'Agent 日报')}")
        print("=" * 60)
        print(result.get('summary', ''))
        if result.get('risk_flags'):
            print("\n风险标记:")
            for item in result['risk_flags']:
                print(f"  - {item}")
        if result.get('action_items'):
            print("\n下一步:")
            for item in result['action_items']:
                print(f"  - {item}")
        print("\n已写入: knowledge_base/daily_reviews/")
        return
    print("未知 Agent 命令")


def cmd_doctor(args):
    """检查并安全初始化本地真实运行态。"""
    from bootstrap_runtime import run_doctor
    result = run_doctor(
        fix=bool(getattr(args, "fix", False)),
        run_first_day=bool(getattr(args, "run_first_day", False)),
    )
    if getattr(args, "json", False):
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return
    print("=" * 60)
    print("  Trading Agents Doctor")
    print("=" * 60)
    print(f"基础运行态: {'就绪' if result['bootstrap_ready'] else '未就绪'}")
    print(f"首日内容:   {'就绪' if result['content_ready'] else '未生成'}")
    print(f"生产运行态: {'就绪' if result['production_ready'] else '未就绪'}")
    print(f"股票池/K线: {result['stock_pool']} / {result['kline'].get('existing', 0)}")
    print(f"纸面账户:   {result['paper_accounts']}")
    if result.get("first_day"):
        first = result["first_day"]
        print(
            f"首日预览:   {first['date']} 推荐 {first['recommendations']}，"
            f"实际成交 {first['actual_buys']}（{first['execution_status']}）"
        )
    if result["next_actions"]:
        print("\n下一步:")
        for item in result["next_actions"]:
            print(f"  - {item}")


def main():
    parser = argparse.ArgumentParser(description='A股AI量化交易系统 (v2)')
    subparsers = parser.add_subparsers(dest='command', help='命令')

    dl_parser = subparsers.add_parser('download', help='下载历史K线')
    dl_parser.add_argument('--top', type=int, default=None, help='下载前N只股票')
    dl_parser.add_argument('--start', type=str, default='2024-01-01', help='开始日期')
    dl_parser.add_argument('--end', type=str, default=None, help='结束日期')
    dl_parser.add_argument('--force', action='store_true', help='强制重新下载')
    dl_parser.add_argument('--delay', type=float, default=0.5, help='请求间隔(秒)')

    dal_parser = subparsers.add_parser('download-all', help='下载全部股票K线')
    dal_parser.add_argument('--start', type=str, default='2024-01-01', help='开始日期')
    dal_parser.add_argument('--end', type=str, default=None, help='结束日期')
    dal_parser.add_argument('--force', action='store_true', help='强制重新下载')
    dal_parser.add_argument('--delay', type=float, default=0.5, help='请求间隔(秒)')

    bt_parser = subparsers.add_parser('backtest', help='v2 多策略回测')
    bt_parser.add_argument('--start', type=str, default=None, help='回测开始日期')
    bt_parser.add_argument('--end', type=str, default=None, help='回测结束日期')
    bt_parser.add_argument('--pool-mode', choices=['mainline', 'sector', 'liquidity', 'full'], default='mainline')
    bt_parser.add_argument('--pool-top', type=int, default=500, help='liquidity 模式子集大小')
    bt_parser.add_argument('--min-score', type=int, default=None)
    bt_parser.add_argument('--top-n', type=int, default=5, help='每策略最大买入数')
    bt_parser.add_argument('--quick', action='store_true', help='近3个月快速回测')

    subparsers.add_parser('rank', help='查看 v2 基准回测排名')
    subparsers.add_parser('status', help='查看系统状态')

    run_parser = subparsers.add_parser('run', help='运行盘中流水线(卖+买)')
    run_parser.add_argument('--date', type=str, default=None, help='交易日期')

    trade_parser = subparsers.add_parser('trade', help='执行交易')
    trade_parser.add_argument('--date', type=str, default=None, help='交易日期')
    trade_parser.add_argument('--sell-only', action='store_true', help='仅执行卖出检查')

    pick_parser = subparsers.add_parser('pick', help='多因子量化选股')
    pick_parser.add_argument('--date', type=str, default=None, help='选股日期')
    pick_parser.add_argument('--top', type=int, default=10, help='输出Top N')
    pick_parser.add_argument('--min-score', type=int, default=40, help='最低综合分')
    pick_parser.add_argument('--reset', action='store_true', help='重置虚拟账户')

    opt_parser = subparsers.add_parser('optimize', help='周优化回测')
    opt_parser.add_argument('--quick', action='store_true', help='快速模式(近3个月)')

    mon_parser = subparsers.add_parser('monitor', help='盘中监控')
    mon_sub = mon_parser.add_subparsers(dest='monitor_cmd')
    mon_sub.add_parser('run', help='启动监控(后台)')
    mon_sub.add_parser('morning', help='早盘报告')
    mon_sub.add_parser('check', help='盘中检查')
    mon_sub.add_parser('review', help='收盘复盘')
    mon_sub.add_parser('status', help='监控状态')

    agent_parser = subparsers.add_parser('agent', help='Agent Runtime')
    agent_sub = agent_parser.add_subparsers(dest='agent_cmd')
    review_parser = agent_sub.add_parser('review', help='生成 Agent 每日复盘')
    review_parser.add_argument('--date', type=str, default=None, help='复盘日期')

    doctor_parser = subparsers.add_parser('doctor', help='检查并初始化真实运行态')
    doctor_parser.add_argument('--fix', action='store_true', help='创建缺失目录、账户和记忆库')
    doctor_parser.add_argument(
        '--run-first-day', action='store_true',
        help='生成真实首日研究预览与 Agent 日报，不产生买卖成交',
    )
    doctor_parser.add_argument('--json', action='store_true', help='输出 JSON')

    args = parser.parse_args()
    if args.command is None:
        parser.print_help()
        return

    commands = {
        'download': cmd_download,
        'download-all': cmd_download_all,
        'backtest': cmd_backtest,
        'rank': cmd_rank,
        'status': cmd_status,
        'run': cmd_run,
        'trade': cmd_trade,
        'optimize': cmd_optimize,
        'pick': cmd_pick,
        'monitor': cmd_monitor,
        'agent': cmd_agent,
        'doctor': cmd_doctor,
    }
    commands[args.command](args)


if __name__ == '__main__':
    main()
