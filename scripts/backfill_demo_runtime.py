#!/usr/bin/env python3
"""
生成日频演示运行数据。

用途:
- 在无可用真实 K 线/交易记录时，为 Dashboard 提供一段明确标记的回放数据。
- 所有生成内容都带 source=simulated_backfill，不伪造成真实实盘。
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
import random
from datetime import datetime, timedelta
from typing import Dict, List

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data")
KLINE_DIR = os.path.join(DATA_DIR, "kline")
KNOWLEDGE_DIR = os.path.join(BASE_DIR, "knowledge_base")
ACCOUNT_DIR = os.path.join(BASE_DIR, "account")
PAPER_DIR = os.path.join(ACCOUNT_DIR, "paper")
PAPER_NAV_DIR = os.path.join(BASE_DIR, "state", "paper_nav")
BACKFILL_META = os.path.join(DATA_DIR, "simulated_backfill_meta.json")

INITIAL_CASH = 100000.0
BUY_WEIGHTS = [0.24, 0.22, 0.20, 0.18, 0.16]
STRATEGIES = {
    "oversold_reversal": "超跌企稳",
    "breakout_setup": "突破蓄势",
    "mainline_leader": "主线龙头",
    "late_session_surge": "尾盘抢筹",
    "sector_leader": "板块龙头跟随",
    "small_cap_volatil": "小盘强势",
}


def business_dates(start: str, end: str) -> List[str]:
    cur = datetime.strptime(start, "%Y-%m-%d")
    end_dt = datetime.strptime(end, "%Y-%m-%d")
    dates = []
    while cur <= end_dt:
        if cur.weekday() < 5:
            dates.append(cur.strftime("%Y-%m-%d"))
        cur += timedelta(days=1)
    return dates


def load_pool(limit: int) -> List[Dict]:
    with open(os.path.join(DATA_DIR, "stock_pool.json"), "r", encoding="utf-8") as f:
        pool = json.load(f)
    records = []
    for item in pool:
        code = str(item.get("code", "")).zfill(6)
        if not code or code.startswith(("4", "8", "920")):
            continue
        name = item.get("name") or item.get("code_name") or code
        records.append({"code": code, "name": name, "industry": item.get("industry") or item.get("industry_name", "")})
        if len(records) >= limit:
            break
    return records


def generate_kline(records: List[Dict], start: str, end: str):
    os.makedirs(KLINE_DIR, exist_ok=True)
    dates = business_dates(start, end)
    for idx, rec in enumerate(records):
        rnd = random.Random(int(rec["code"]) + 20260701)
        price = rnd.uniform(6, 38) * (1 + idx / max(len(records), 1) * 0.25)
        rows = []
        prev_close = price
        trend = rnd.uniform(-0.0005, 0.0018)
        amp = rnd.uniform(0.012, 0.035)
        for i, ds in enumerate(dates):
            seasonal = math.sin((i + idx) / 17.0) * amp
            shock = rnd.gauss(0, amp * 0.55)
            # 给少部分股票制造“涨停基因”，便于现有策略能选出候选。
            if i in (55 + idx % 9, 95 + idx % 13) and idx % 4 == 0:
                shock += rnd.uniform(0.065, 0.105)
            change = max(-0.095, min(0.105, trend + seasonal + shock))
            close = max(2.0, prev_close * (1 + change))
            open_price = prev_close * (1 + rnd.gauss(0, amp * 0.25))
            high = max(open_price, close) * (1 + abs(rnd.gauss(0, amp * 0.35)))
            low = min(open_price, close) * (1 - abs(rnd.gauss(0, amp * 0.35)))
            volume = int(rnd.uniform(2_000_000, 60_000_000) * (1 + abs(change) * 8))
            amount = volume * close
            rows.append({
                "date": ds,
                "stock_code": rec["code"],
                "open": round(open_price, 2),
                "high": round(high, 2),
                "low": round(low, 2),
                "close": round(close, 2),
                "volume": volume,
                "amount": round(amount, 2),
                "change_pct": round(change * 100, 2),
                "source": "simulated_backfill",
            })
            prev_close = close
        with open(os.path.join(KLINE_DIR, f"{rec['code']}.csv"), "w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            writer.writeheader()
            writer.writerows(rows)


def read_close(code: str, date: str) -> float:
    path = os.path.join(KLINE_DIR, f"{code}.csv")
    with open(path, "r", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    for row in reversed(rows):
        if row["date"] <= date:
            return float(row["close"])
    return float(rows[-1]["close"])


def pick_candidates(records: List[Dict], date: str, day_idx: int, top_n: int = 8) -> List[Dict]:
    scored = []
    for i, rec in enumerate(records[:120]):
        price = read_close(rec["code"], date)
        rnd = random.Random(int(rec["code"]) * 31 + day_idx)
        score = 55 + rnd.random() * 35 + (8 if i % 4 == day_idx % 4 else 0)
        scored.append((score, rec, price))
    scored.sort(key=lambda x: x[0], reverse=True)
    strategies = ["oversold_reversal", "breakout_setup", "mainline_leader", "late_session_surge", "sector_leader", "small_cap_volatil"]
    picks = []
    for rank, (score, rec, price) in enumerate(scored[:top_n], 1):
        picks.append({
            "rank": rank,
            "code": rec["code"],
            "name": rec["name"],
            "price": round(price, 2),
            "final_score": round(score, 2),
            "total_score": round(score, 2),
            "strategy_name": strategies[(rank + day_idx) % len(strategies)],
            "strategies": {strategies[(rank + day_idx) % len(strategies)]: round(score, 2)},
            "stop_loss": round(price * 0.92, 2),
            "take_profit": round(price * 1.18, 2),
            "invalid_price": round(price * 0.96, 2),
            "reason": "历史回放演示: 涨停基因/量价改善/主线题材共振",
            "source": "simulated_backfill",
        })
    return picks


def buy_position(account: Dict, pick: Dict, date: str, rank: int, strategy_id: str = "composite") -> Dict | None:
    code = pick["code"]
    if code in account["positions"] or len(account["positions"]) >= len(BUY_WEIGHTS):
        return None
    price = pick["price"]
    target = account_value(account, date) * BUY_WEIGHTS[min(rank, len(BUY_WEIGHTS) - 1)]
    amount = min(account["cash"], target)
    shares = int(amount / (price * 100)) * 100
    if shares <= 0:
        return None
    cost = shares * price
    commission = cost * 0.0001
    account["cash"] -= cost + commission
    account["positions"][code] = {
        "shares": shares,
        "avg_price": price,
        "buy_date": date,
        "high_price": price,
        "reason": "simulated_backfill: " + pick["reason"],
        "hold_days": 0,
        "last_hold_date": date,
        "source": "simulated_backfill",
    }
    account["total_trades"] += 1
    return {
        "action": "BUY",
        "code": code,
        "name": pick["name"],
        "price": price,
        "shares": shares,
        "amount": round(cost, 2),
        "commission": round(commission, 2),
        "date": date,
        "datetime": f"{date} 14:30:00",
        "reason": "simulated_backfill: 历史回放买入",
        "strategy_id": strategy_id,
        "source": "simulated_backfill",
    }


def maybe_sell(account: Dict, date: str, strategy_id: str = "composite") -> List[Dict]:
    trades = []
    for code, pos in list(account["positions"].items()):
        price = read_close(code, date)
        pos["hold_days"] += 1
        pos["last_hold_date"] = date
        pos["high_price"] = max(pos.get("high_price", pos["avg_price"]), price)
        change = (price / pos["avg_price"] - 1) if pos["avg_price"] else 0
        reason = ""
        if change <= -0.08:
            reason = "simulated_backfill: 回放止损"
        elif change >= 0.12:
            reason = "simulated_backfill: 回放止盈"
        elif pos["hold_days"] >= 4 and int(code[-1]) % 3 == 0:
            reason = "simulated_backfill: 回放调仓"
        if not reason:
            continue
        shares = pos["shares"]
        amount = shares * price
        commission = amount * 0.0001
        stamp_tax = amount * 0.001
        profit = amount - shares * pos["avg_price"] - commission - stamp_tax
        account["cash"] += amount - commission - stamp_tax
        account["total_profit"] += profit
        account["total_trades"] += 1
        del account["positions"][code]
        trades.append({
            "action": "SELL",
            "code": code,
            "price": round(price, 2),
            "shares": shares,
            "amount": round(amount, 2),
            "commission": round(commission, 2),
            "stamp_tax": round(stamp_tax, 2),
            "profit": round(profit, 2),
            "profit_pct": round(profit / (shares * pos["avg_price"]) * 100, 2),
            "hold_days": pos["hold_days"],
            "date": date,
            "datetime": f"{date} 09:35:00",
            "reason": reason,
            "strategy_id": strategy_id,
            "source": "simulated_backfill",
        })
    return trades


def account_value(account: Dict, date: str) -> float:
    value = account["cash"]
    for code, pos in account["positions"].items():
        value += pos["shares"] * read_close(code, date)
    return value


def write_daily_report(date: str, picks: List[Dict], account: Dict, trades: List[Dict]):
    os.makedirs(KNOWLEDGE_DIR, exist_ok=True)
    report = {
        "timestamp": f"{date} 14:32:00",
        "date": date,
        "total_pool": 300,
        "scanned_pool": 120,
        "pool_mode": "simulated_backfill",
        "summary": "历史回放演示数据，非真实实盘成交。",
        "top_picks": picks,
        "buy_actions": [t for t in trades if t["action"] == "BUY"],
        "stop_actions": [t for t in trades if t["action"] == "SELL"],
        "sell_actions": [t for t in trades if t["action"] == "SELL"],
        "account_value": round(account_value(account, date), 2),
        "source": "simulated_backfill",
    }
    with open(os.path.join(KNOWLEDGE_DIR, f"daily_pick_{date}.json"), "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)


def backfill_runtime(records: List[Dict], start: str, end: str):
    os.makedirs(ACCOUNT_DIR, exist_ok=True)
    account = {
        "cash": INITIAL_CASH,
        "positions": {},
        "total_trades": 0,
        "total_profit": 0.0,
        "created_at": start,
        "strategy_id": "composite",
        "display_name": "组合账户",
        "source": "simulated_backfill",
    }
    trade_log = []
    dates = business_dates(start, end)
    for day_idx, date in enumerate(dates):
        trades = maybe_sell(account, date, "composite")
        picks = pick_candidates(records, date, day_idx)
        for rank, pick in enumerate(picks[:5]):
            trade = buy_position(account, pick, date, rank, "composite")
            if trade:
                trades.append(trade)
        trade_log.extend(trades)
        write_daily_report(date, picks, account, trades)
    account["updated_at"] = f"{dates[-1]} 15:10:00" if dates else datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    account["account_value"] = round(account_value(account, dates[-1]), 2) if dates else INITIAL_CASH
    with open(os.path.join(ACCOUNT_DIR, "account_state_v2.json"), "w", encoding="utf-8") as f:
        json.dump(account, f, ensure_ascii=False, indent=2)
    with open(os.path.join(ACCOUNT_DIR, "trade_log_v2.json"), "w", encoding="utf-8") as f:
        json.dump(trade_log, f, ensure_ascii=False, indent=2)


def backfill_paper_runtime(records: List[Dict], start: str, end: str):
    os.makedirs(PAPER_DIR, exist_ok=True)
    os.makedirs(PAPER_NAV_DIR, exist_ok=True)
    accounts = {
        sid: {
            "cash": INITIAL_CASH,
            "positions": {},
            "total_trades": 0,
            "total_profit": 0.0,
            "created_at": start,
            "strategy_id": sid,
            "display_name": display,
            "source": "simulated_backfill",
        }
        for sid, display in STRATEGIES.items()
    }
    trade_logs = {sid: [] for sid in STRATEGIES}
    dates = business_dates(start, end)

    for day_idx, date in enumerate(dates):
        all_picks = pick_candidates(records, date, day_idx, top_n=36)
        price_hint = {}
        for sid, account in accounts.items():
            trades = maybe_sell(account, date, sid)
            sid_picks = [p for p in all_picks if p.get("strategy_name") == sid]
            # 如果当天 top 候选没有覆盖该策略，按固定偏移补一个候选，确保纸面账户有样本。
            if not sid_picks:
                sid_index = list(STRATEGIES).index(sid)
                rec = records[(day_idx * 7 + sid_index * 11) % len(records)]
                price = read_close(rec["code"], date)
                sid_picks = [{
                    "code": rec["code"],
                    "name": rec["name"],
                    "price": round(price, 2),
                    "strategy_name": sid,
                    "final_score": 70 + sid_index,
                    "reason": "历史回放演示: 分策略纸面样本补齐",
                }]
            for rank, pick in enumerate(sid_picks[:2]):
                trade = buy_position(account, pick, date, rank, sid)
                if trade:
                    trades.append(trade)
            trade_logs[sid].extend(trades)
            for code in account["positions"]:
                price_hint[code] = read_close(code, date)

        snapshot = {"date": date, "strategies": {}, "composite_ref": None, "source": "simulated_backfill"}
        for sid, account in accounts.items():
            value = account_value(account, date)
            snapshot["strategies"][sid] = {
                "display_name": STRATEGIES[sid],
                "value": round(value, 2),
                "cash": round(account["cash"], 2),
                "return_pct": round((value / INITIAL_CASH - 1) * 100, 2),
                "positions": len(account["positions"]),
                "total_profit": round(account["total_profit"], 2),
                "source": "simulated_backfill",
            }
        composite_path = os.path.join(ACCOUNT_DIR, "account_state_v2.json")
        if os.path.exists(composite_path):
            with open(composite_path, "r", encoding="utf-8") as f:
                composite = json.load(f)
            cval = account_value(composite, date)
            snapshot["composite_ref"] = {
                "value": round(cval, 2),
                "return_pct": round((cval / INITIAL_CASH - 1) * 100, 2),
            }
        with open(os.path.join(PAPER_NAV_DIR, f"{date}.json"), "w", encoding="utf-8") as f:
            json.dump(snapshot, f, ensure_ascii=False, indent=2)

    final_date = dates[-1] if dates else end
    for sid, account in accounts.items():
        account["updated_at"] = f"{final_date} 15:10:00"
        with open(os.path.join(PAPER_DIR, f"{sid}.json"), "w", encoding="utf-8") as f:
            json.dump(account, f, ensure_ascii=False, indent=2)
        with open(os.path.join(PAPER_DIR, f"{sid}_trades.json"), "w", encoding="utf-8") as f:
            json.dump(trade_logs[sid], f, ensure_ascii=False, indent=2)


def seed_memory(records: List[Dict], start: str, end: str):
    import sys
    sys.path.insert(0, BASE_DIR)
    from core.memory import TradingMemory

    mem = TradingMemory(db_path=os.path.join(KNOWLEDGE_DIR, "trading_memory.db"))
    strategies = ["oversold_reversal", "breakout_setup", "mainline_leader", "late_session_surge", "sector_leader", "small_cap_volatil"]
    dates = business_dates(start, end)
    sentiments = ["neutral", "bullish", "neutral", "bullish", "neutral", "bearish"]
    for day_idx, date in enumerate(dates):
        mem.log_market_state({
            "date": date,
            "sh_index": round(3100 + day_idx * 11 + math.sin(day_idx) * 18, 2),
            "sh_change_pct": round(math.sin(day_idx / 2) * 0.8, 2),
            "hs300": round(3600 + day_idx * 8 + math.cos(day_idx) * 12, 2),
            "hs300_change_pct": round(math.cos(day_idx / 2) * 0.65, 2),
            "cyb": round(1850 + day_idx * 9 + math.sin(day_idx / 1.7) * 20, 2),
            "cyb_change_pct": round(math.sin(day_idx / 1.8) * 1.1, 2),
            "sentiment": sentiments[day_idx % len(sentiments)],
            "hot_sectors": ["AI算力", "机器人", "低空经济"] if day_idx % 2 == 0 else ["新能源", "消费电子", "军工"],
            "market_breadth": round(0.48 + (day_idx % 5) * 0.06, 2),
            "volume_ratio": round(0.9 + (day_idx % 4) * 0.12, 2),
            "volatility": round(1.8 + (day_idx % 3) * 0.4, 2),
            "source": "simulated_backfill",
        })
        picks = pick_candidates(records, date, day_idx, top_n=6)
        for pick in picks:
            mem.log_signal({
                "date": date,
                "code": pick["code"],
                "name": pick["name"],
                "strategy": pick["strategy_name"],
                "signal": "buy",
                "price": pick["price"],
                "confidence": min(0.95, pick["final_score"] / 100),
                "stop_loss": pick["stop_loss"],
                "take_profit": pick["take_profit"],
                "invalid_price": pick["invalid_price"],
                "risk_reward": 1.8,
                "reason": "simulated_backfill: Agent 回放信号，非真实实盘。",
                "tech_reasons": ["涨停基因", "量价改善", "主线共振"],
                "source": "simulated_backfill",
            })
        for s_idx, strategy in enumerate(strategies):
            mem.update_strategy_perf(strategy, date, {
                "market_sentiment": sentiments[day_idx % len(sentiments)],
                "total_signals": 2 + (s_idx + day_idx) % 3,
                "realized_signals": 1 + (s_idx + day_idx) % 2,
                "win_count": 1 + (1 if (s_idx + day_idx) % 3 == 0 else 0),
                "loss_count": 0 if (s_idx + day_idx) % 4 else 1,
                "avg_win_pct": 3.2 + s_idx * 0.4,
                "avg_loss_pct": -1.8,
                "avg_hold_days": 2.5 + (s_idx % 3),
                "sharpe": 0.8 + s_idx * 0.12,
                "max_drawdown": -2.0 - s_idx * 0.3,
                "total_pnl_pct": round((s_idx + 1) * 0.35 + day_idx * 0.08, 2),
                "source": "simulated_backfill",
            })
    lesson_templates = [
        ("market_insight", "缩量上涨阶段优先保留主线共振", "回放期内主线题材延续性好，单纯超跌信号需要降低权重。"),
        ("strategy_insight", "突破蓄势在温和放量环境更稳定", "纸面和回测均显示，突破策略在成交量温和放大时偏差更小。"),
        ("risk_insight", "连续高开后需要避免追高", "回放样本中高开后冲高回落容易触发隔日调仓，需加入开盘涨幅过滤。"),
    ]
    for idx, (lesson_type, title, desc) in enumerate(lesson_templates):
        mem.log_lesson({
            "date": dates[min(idx, len(dates) - 1)] if dates else end,
            "strategy": strategies[idx],
            "lesson_type": lesson_type,
            "title": title,
            "description": "simulated_backfill: " + desc,
            "pattern": desc,
            "tags": ["simulated_backfill", "agent_replay", "日频"],
            "severity": 6 + idx,
            "source": "simulated_backfill",
        })


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--kline-start", default="2025-09-01")
    parser.add_argument("--start", default="2026-06-24")
    parser.add_argument("--end", default=datetime.now().strftime("%Y-%m-%d"))
    parser.add_argument("--stocks", type=int, default=300)
    args = parser.parse_args()

    records = load_pool(args.stocks)
    generate_kline(records, args.kline_start, args.end)
    backfill_runtime(records, args.start, args.end)
    backfill_paper_runtime(records, args.start, args.end)
    seed_memory(records, args.start, args.end)
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(BACKFILL_META, "w", encoding="utf-8") as f:
        json.dump({
            "source": "simulated_backfill",
            "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "kline_start": args.kline_start,
            "runtime_start": args.start,
            "runtime_end": args.end,
            "stocks": len(records),
            "note": "演示/回放数据，非真实实盘成交。",
        }, f, ensure_ascii=False, indent=2)
    print(f"simulated_backfill ok: stocks={len(records)} runtime={args.start}~{args.end}")


if __name__ == "__main__":
    main()
