"""v2 盘中监控 - 检查持仓与最新选股报告"""

import json
import os
import sys
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)

ACCOUNT_FILE = os.path.join(BASE_DIR, "account", "account_state_v2.json")
KB_DIR = os.path.join(BASE_DIR, "knowledge_base")
MONITOR_STATE = os.path.join(BASE_DIR, "data", "monitor_state.json")


def _load_account():
    if os.path.exists(ACCOUNT_FILE):
        with open(ACCOUNT_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def _latest_pick_report():
    import glob
    reports = sorted(glob.glob(os.path.join(KB_DIR, "daily_pick_*.json")))
    if not reports:
        return {}
    with open(reports[-1], "r", encoding="utf-8") as f:
        return json.load(f)


def _save_state(payload):
    os.makedirs(os.path.dirname(MONITOR_STATE), exist_ok=True)
    with open(MONITOR_STATE, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)


def cmd_morning():
    report = _latest_pick_report()
    print("=" * 50)
    print(f"早盘报告 {report.get('date', 'N/A')}")
    print(f"评分: {report.get('total_scored', 0)} 只")
    print(f"推荐: {len(report.get('top_picks', []))} 只")
    print(f"买入: {len(report.get('buy_actions', []))} 只")
    for i, pick in enumerate(report.get("top_picks", [])[:5], 1):
        print(f"  #{i} {pick.get('code')} 得分={pick.get('final_score', 0)}")


def cmd_check():
    """盘中检查：止损止盈 + 持仓概览"""
    from trade_engine_v2 import get_account
    from trading_calendar import get_trading_date
    from daily_runner_v2 import run_sell_flow

    date = get_trading_date()
    result = run_sell_flow(date)
    acct = get_account()
    summary = result.get("positions", [])
    sells = result.get("sell_actions", [])
    prices = {p["code"]: p.get("current_price", 0) for p in summary}
    print("=" * 50)
    print(f"盘中检查 {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"现金: {acct.cash:,.2f} | 持仓: {len(summary)} | 本轮卖出: {len(sells)}")
    for s in sells:
        print(f"  卖出 {s['code']} @ {s.get('price')} 盈亏={s.get('profit_pct', 0):+.1f}%")
    for p in summary:
        print(
            f"  {p['code']} {p['shares']}股 "
            f"成本={p['avg_price']:.2f} 现价={p['current_price']:.2f} "
            f"盈亏={p['profit_pct']:+.2f}%"
        )
    _save_state({
        "last_check": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "positions": len(summary),
        "account_value": round(acct.get_total_value(prices), 2),
    })


def cmd_review():
    account = _load_account()
    report = _latest_pick_report()
    print("=" * 50)
    print("收盘复盘")
    print(f"账户更新: {account.get('updated_at', 'N/A')}")
    print(f"累计盈亏: {account.get('total_profit', 0):+.2f}")
    print(f"总交易: {account.get('total_trades', 0)}")
    print(f"最新选股日: {report.get('date', 'N/A')}")


def cmd_status():
    state = {}
    if os.path.exists(MONITOR_STATE):
        with open(MONITOR_STATE, "r", encoding="utf-8") as f:
            state = json.load(f)
    account = _load_account()
    print("=" * 50)
    print("监控状态")
    print(f"上次检查: {state.get('last_check', '从未')}")
    print(f"账户现金: {account.get('cash', 0):,.2f}")
    print(f"持仓数: {len(account.get('positions', {}))}")


def cmd_monitor(argv=None):
    argv = argv or []
    subcmd = argv[0] if argv else "status"
    handlers = {
        "morning": cmd_morning,
        "check": cmd_check,
        "review": cmd_review,
        "status": cmd_status,
        "run": cmd_check,
    }
    handler = handlers.get(subcmd, cmd_status)
    handler()


if __name__ == "__main__":
    cmd_monitor(sys.argv[1:])
