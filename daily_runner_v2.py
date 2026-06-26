"""
每日选股 Cron 任务 — 盘中不限时点

执行逻辑:
- 默认/ --intraday: 先检查卖出(止损止盈)，再选股+买入
- --sell-only: 仅卖出检查
- --pick-only: 仅选股+买入

Cron: 交易时段每30分钟触发 (见 scripts/install_crontab.sh)

用法:
    python daily_runner_v2.py              # 盘中：卖+买
    python daily_runner_v2.py --sell-only  # 仅卖出
    python daily_runner_v2.py --pick-only # 仅选股买入
"""

import os
import sys
import json
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)

import logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s'
)
logger = logging.getLogger(__name__)


def get_trading_date():
    """获取当前交易日（非交易日取前一交易日）"""
    from trading_calendar import get_trading_date as _get_trading_date
    return _get_trading_date()


def run_picker_flow(date: str):
    """选股+买入"""
    from global_stock_picker import run_picker
    result = run_picker(
        date=date, top_n=10, min_score=40,
        pool_mode="mainline",
    )
    return result


def run_sell_flow(date: str):
    """卖出检查 (止损/止盈/纸面账户)"""
    from trade_engine_v2 import get_account

    acct = get_account()
    if not acct.positions:
        stop_actions = []
        current_prices = {}
    else:
        position_codes = list(acct.positions.keys())
        from market_data import get_realtime_prices
        current_prices = get_realtime_prices(position_codes)

        from factor_data import PriceVolumeFactors
        for code in position_codes:
            if code not in current_prices or current_prices[code] <= 0:
                try:
                    pv = PriceVolumeFactors.compute(code)
                    if pv:
                        current_prices[code] = pv.get('price', 0)
                except Exception:
                    pass

        acct.advance_hold_days(date)
        stop_actions = acct.check_stop_loss_take_profit(current_prices, date)
        acct.save()

    paper_results = {}
    try:
        from paper_trading_v2 import run_paper_sell
        paper_results = run_paper_sell(date)
    except Exception as e:
        logger.warning("纸面卖出跳过: %s", e)

    if not current_prices and acct.positions:
        from market_data import get_realtime_prices
        current_prices = get_realtime_prices(list(acct.positions.keys()))

    return {
        'date': date,
        'sell_actions': stop_actions,
        'account_value': round(acct.get_total_value(current_prices), 2),
        'positions': acct.get_positions_summary(current_prices) if current_prices else [],
        'paper': paper_results,
    }


def run_intraday_flow(date: str):
    """盘中一轮：先卖后买"""
    from trading_session import session_label, trade_datetime
    logger.info("=== 盘中交易 [%s] %s ===", session_label(), trade_datetime())

    sell_result = run_sell_flow(date)
    pick_result = run_picker_flow(date)

    merged = dict(pick_result)
    merged['sell_actions'] = sell_result.get('sell_actions', [])
    merged['sell_flow'] = sell_result
    if sell_result.get('sell_actions'):
        logger.info("本轮卖出 %d 笔", len(sell_result['sell_actions']))
    if pick_result.get('buy_actions'):
        logger.info("本轮买入 %d 笔", len(pick_result['buy_actions']))
    return merged


def format_message(date: str, result: dict, mode: str = "intraday") -> str:
    """构建通知消息"""
    picks = result.get("top_picks", [])
    buys = result.get("buy_actions", [])
    sells = result.get("sell_actions", result.get("stop_actions", []))

    lines = []
    if mode == "sell":
        lines.append(f"📊 A股量化卖出检查 {result.get('date', date)}")
    else:
        from trading_session import session_label
        lines.append(f"📊 A股量化盘中交易 {result.get('date', date)} [{session_label()}]")
    lines.append("")
    lines.append(f"总资产: {result.get('account_value', 0):,.0f}元")
    lines.append("")

    if sells:
        lines.append("💰 卖出:")
        for s in sells:
            lines.append(f"  {s['code']} @ {s.get('price', 0)} 盈亏={s.get('profit_pct', 0):+.1f}% ({s.get('reason', '')})")
        lines.append("")

    if mode != "sell":
        lines.append(f"股票池: {result.get('total_pool', 0)}只 | 评分: {result.get('total_scored', 0)}只")
        lines.append("")

        if picks:
            lines.append("🏆 Top 5 推荐:")
            for i, p in enumerate(picks[:5]):
                score = p.get('final_score', p.get('strategy_score', 0))
                lines.append(f"  #{i+1} {p['code']} @ {p['price']} 得分={score}")
            lines.append("")

        if buys:
            lines.append("🛒 买入:")
            for b in buys:
                lines.append(f"  {b['code']} @ {b['price']} x {b['shares']}股 = {b.get('amount', 0):,.0f}元")
            lines.append("")

        positions = result.get('positions') or []
        if positions and not buys and not sells:
            lines.append("📋 持仓:")
            for p in positions[:5]:
                lines.append(f"  {p['code']} {p['shares']}股 盈亏={p.get('profit_pct', 0):+.1f}%")
            lines.append("")

    report_path = os.path.join(BASE_DIR, 'knowledge_base', f"daily_pick_{date}.md")
    if os.path.exists(report_path):
        lines.append(f"📄 详细报告: knowledge_base/daily_pick_{date}.md")

    return '\n'.join(lines)


def run():
    import argparse
    from trading_calendar import is_trading_day
    from trading_session import is_trading_session

    parser = argparse.ArgumentParser(description="盘中选股/交易 Cron 运行器")
    parser.add_argument("--date", default=None, help="日期 (YYYY-MM-DD)")
    parser.add_argument("--sell-only", action="store_true", help="仅卖出检查")
    parser.add_argument("--pick-only", action="store_true", help="仅选股+买入")
    parser.add_argument("--force", action="store_true", help="非交易日/非交易时段也强制执行")
    args = parser.parse_args()

    date = args.date or get_trading_date()

    if not args.force and not is_trading_day(date):
        print(f"⏸ 非交易日 {date}，跳过 (加 --force 可强制执行)")
        return

    if not args.force and not is_trading_session():
        print(f"⏸ 非交易时段 {datetime.now().strftime('%H:%M')}，跳过 (加 --force 可强制执行)")
        return

    if args.sell_only:
        result = run_sell_flow(date)
        msg = format_message(date, result, mode="sell")
    elif args.pick_only:
        result = run_picker_flow(date)
        msg = format_message(date, result, mode="intraday")
    else:
        result = run_intraday_flow(date)
        msg = format_message(date, result, mode="intraday")

    print(msg)


if __name__ == '__main__':
    try:
        run()
    except Exception as e:
        print(f"❌ 运行失败: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
