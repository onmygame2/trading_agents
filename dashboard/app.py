"""
Boss Dashboard v2 - A-Share Quant Trading Dashboard with K-line charts

Features:
- Real-time portfolio overview with 10s refresh
- Agent detail: positions, equity curve, trade history
- Stock detail: candlestick chart (1d/1w/1M), minute chart (5m/15m/30m/60m)
- Integrated Ashare data source (Sina + Tencent fallback)

Run: python dashboard/app.py
Access: http://localhost:5890
"""

import os
import sys
import json
import glob
import logging
import datetime
import functools
from datetime import datetime
from typing import Dict, List, Any

import pandas as pd
import numpy as np
from flask import Flask, render_template, jsonify, request

# Add project root to path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)
sys.path.insert(0, os.path.join(PROJECT_ROOT, 'ashare_repo'))

app = Flask(__name__)
app.logger.setLevel(logging.WARNING)

BASE_DIR = PROJECT_ROOT
KNOWLEDGE_DIR = os.path.join(BASE_DIR, 'knowledge_base')
STATE_DIR = os.path.join(BASE_DIR, 'state')
OPTIMIZER_DIR = os.path.join(BASE_DIR, 'boss_optimizer')
ACCOUNT_DIR = os.path.join(BASE_DIR, 'account')
V2_ACCOUNT_STATE = os.path.join(ACCOUNT_DIR, 'account_state_v2.json')
V2_TRADE_LOG = os.path.join(ACCOUNT_DIR, 'trade_log_v2.json')


# Simple in-memory cache
_cache = {}
_cache_ttl = 10  # seconds (shorter for real-time position data)

def cached(fn, ttl=None):
    """Simple TTL cache decorator."""
    ttl = ttl or _cache_ttl
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        key = (fn.__name__, args, tuple(sorted(kwargs.items())))
        now = datetime.now()
        if key in _cache:
            val, ts = _cache[key]
            if (now - ts).total_seconds() < ttl:
                return val
        result = fn(*args, **kwargs)
        _cache[key] = (result, now)
        return result
    return wrapper

# Cached data loaders
@cached
def load_latest_report() -> Dict:
    """Load the most recent boss report."""
    reports = sorted(glob.glob(os.path.join(KNOWLEDGE_DIR, 'boss_report_*.json')))
    if not reports:
        return {}
    with open(reports[-1], 'r', encoding='utf-8') as f:
        return json.load(f)


@cached
def load_all_reports() -> List[Dict]:
    """Load all boss reports sorted by date."""
    reports = []
    for path in sorted(glob.glob(os.path.join(KNOWLEDGE_DIR, 'boss_report_*.json'))):
        try:
            with open(path, 'r', encoding='utf-8') as f:
                report = json.load(f)
                reports.append(report)
        except Exception:
            pass
    return reports


def load_agent_state(agent_name: str) -> Dict:
    """Load agent state file."""
    state_path = os.path.join(STATE_DIR, f'{agent_name}_state.json')
    if os.path.exists(state_path):
        with open(state_path, 'r') as f:
            return json.load(f)
    return {}


def load_all_agent_states() -> Dict[str, Dict]:
    """Load all agent states."""
    states = {}
    for name in os.listdir(STATE_DIR):
        if name.endswith('_state.json'):
            agent_name = name.replace('_state.json', '')
            states[agent_name] = load_agent_state(agent_name)
    return states


def load_optimizer_state() -> Dict:
    """Load optimizer state."""
    state_path = os.path.join(OPTIMIZER_DIR, 'optimizer_state.json')
    if os.path.exists(state_path):
        with open(state_path, 'r') as f:
            return json.load(f)
    return {}


def build_equity_history() -> Dict[str, List[Dict]]:
    """Build equity history from all reports."""
    reports = load_all_reports()
    equity_history = {}

    for report in reports:
        date = report.get('date', '')
        for ar in report.get('agent_reports', []):
            name = ar.get('agent_name', '')
            equity = ar.get('equity', 100000) or 100000
            ret = ar.get('return_pct', 0) or 0
            if name not in equity_history:
                equity_history[name] = []
            equity_history[name].append({
                'date': date,
                'equity': equity,
                'return_pct': ret,
            })

    return equity_history


def load_v2_account() -> Dict:
    """Load v2 virtual account state."""
    if os.path.exists(V2_ACCOUNT_STATE):
        try:
            with open(V2_ACCOUNT_STATE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def load_v2_trade_log() -> List[Dict]:
    """Load v2 trade log."""
    if os.path.exists(V2_TRADE_LOG):
        try:
            with open(V2_TRADE_LOG, 'r', encoding='utf-8') as f:
                data = json.load(f)
                return data if isinstance(data, list) else []
        except Exception:
            pass
    return []


def load_v2_pick_reports() -> List[Dict]:
    """Load all v2 daily pick reports sorted by date."""
    reports = []
    for path in sorted(glob.glob(os.path.join(KNOWLEDGE_DIR, 'daily_pick_*.json'))):
        try:
            with open(path, 'r', encoding='utf-8') as f:
                report = json.load(f)
                report['_path'] = path
                reports.append(report)
        except Exception:
            pass
    return reports


def load_latest_v2_pick() -> Dict:
    """Load the most recent v2 daily pick report."""
    reports = load_v2_pick_reports()
    return reports[-1] if reports else {}


def get_strategy_display_map() -> Dict[str, str]:
    """strategy_id -> 中文名"""
    try:
        from strategies_v2.manager import load_all_strategies
        return {k: v.metadata.get('name', k) for k, v in load_all_strategies().items()}
    except Exception:
        return {}


def transform_v2_pick_item(pick: Dict, rank: int, nm: Dict[str, str]) -> Dict:
    """Map v2 top_picks entry to dashboard pick format."""
    code = str(pick.get('code', ''))
    strategies = pick.get('strategies') or {}
    display_map = get_strategy_display_map()
    strategy_details = []
    if isinstance(strategies, dict):
        for sid, sdata in strategies.items():
            if not isinstance(sdata, dict):
                continue
            strategy_details.append({
                'id': sid,
                'name': display_map.get(sid, sid),
                'score': sdata.get('strategy_score', 0),
                'reason': sdata.get('reason', ''),
                'confidence': sdata.get('confidence', 0),
            })
    strategy_details.sort(key=lambda x: x.get('score', 0), reverse=True)

    strategy_names = [d['name'] for d in strategy_details]
    if not strategy_names:
        src = pick.get('source_strategy_id', '')
        if src:
            strategy_names = [display_map.get(src, src)]
        else:
            import re
            m = re.match(r'\[([^\]]+)\]', pick.get('reason', '') or '')
            if m:
                strategy_names = [m.group(1)]
    pick_mode = pick.get('pick_mode', '')
    primary = pick.get('strategy_name') or pick.get('strategy_id', '')
    if pick_mode == 'factor_watchlist' or pick.get('strategy_id') == 'factor_watchlist':
        display_strategy = '因子观察（非策略强信号，仅供跟踪）'
    elif primary in ('composite', '组合账户', '组合竞技') and strategy_names:
        display_strategy = '组合 → ' + '、'.join(strategy_names)
    elif strategy_names:
        display_strategy = strategy_names[0]
    else:
        display_strategy = display_map.get(primary, primary) or '组合账户'

    confidence = pick.get('confidence', 0)
    if confidence <= 1:
        confidence *= 100

    tech_reasons = []
    for d in strategy_details:
        if d.get('reason'):
            tech_reasons.append(f"[{d['name']}] {d['reason']}")
    if not tech_reasons and pick.get('reason'):
        tech_reasons.append(pick['reason'])

    final_score = pick.get('final_score', pick.get('strategy_score', 0)) or 0
    coverage = pick.get('coverage', len(strategy_details) or 1)
    who = '、'.join(strategy_names) if strategy_names else display_strategy
    why = (
        f"#{rank} 得分 {pick.get('strategy_score', final_score)}；"
        f"来源 [{who}]"
    )
    if pick.get('dl_score') is not None:
        why += f"；DL {float(pick['dl_score']):.2f}"

    sl = pick.get('stop_loss')
    tp = pick.get('take_profit')
    rr = None
    price = pick.get('price', 0) or 0
    if sl and tp and price and price > sl:
        rr = round((tp - price) / (price - sl), 2)

    return {
        'rank': rank,
        'code': code,
        'name': nm.get(code, code),
        'composite_score': round(final_score, 1),
        'final_score': round(final_score, 1),
        'avg_tech_score': round(confidence),
        'avg_fund_score': '-',
        'agent_count': coverage,
        'agents': strategy_names or [display_strategy],
        'strategy': display_strategy,
        'strategy_id': pick.get('strategy_id', 'composite'),
        'strategy_details': strategy_details,
        'tech_reasons': tech_reasons,
        'recommendation': why,
        'news_reasons': [],
        'buy_price': price,
        'stop_loss': sl,
        'take_profit': tp,
        'invalid_price': sl,
        'stop_loss_reason': '硬止损 -7%' if sl else '',
        'take_profit_reason': '止盈 +15%' if tp else '',
        'atr': None,
        'risk_reward_ratio': rr,
    }


def build_v2_strategy_stats() -> List[Dict]:
    """Aggregate v2 strategy contribution from pick reports and trades."""
    strategy_counts = {}
    strategy_pnl = {}
    for report in load_v2_pick_reports():
        for pick in report.get('top_picks', []):
            for name in (pick.get('strategies') or {}).keys():
                strategy_counts[name] = strategy_counts.get(name, 0) + 1

    nm = load_stock_name_map()
    buy_reasons = {}
    for trade in load_v2_trade_log():
        if trade.get('action', '').upper() != 'BUY':
            continue
        code = str(trade.get('code', ''))
        buy_reasons[code] = trade.get('reason', '')

    for trade in load_v2_trade_log():
        if trade.get('action', '').upper() != 'SELL':
            continue
        code = str(trade.get('code', ''))
        pnl = trade.get('profit', 0) or 0
        reason = buy_reasons.get(code, trade.get('reason', ''))
        matched = False
        for name in strategy_counts.keys():
            if name.replace('_', ' ') in reason.lower() or name in reason:
                strategy_pnl[name] = strategy_pnl.get(name, 0) + pnl
                matched = True
                break
        if not matched:
            strategy_pnl['other'] = strategy_pnl.get('other', 0) + pnl

    names = sorted(set(list(strategy_counts.keys()) + list(strategy_pnl.keys())))
    stats = []
    for name in names:
        stats.append({
            'name': name,
            'pick_count': strategy_counts.get(name, 0),
            'realized_pnl': round(strategy_pnl.get(name, 0), 2),
        })
    stats.sort(key=lambda x: (x['pick_count'], x['realized_pnl']), reverse=True)
    return stats


def load_stock_name_map() -> Dict[str, str]:
    """Load code -> name mapping from stock_pool.json."""
    pool_path = os.path.join(BASE_DIR, 'data', 'stock_pool.json')
    name_map = {}
    try:
        with open(pool_path, 'r', encoding='utf-8') as f:
            pool = json.load(f)
        if isinstance(pool, list):
            for s in pool:
                code = str(s.get('code', ''))
                name = s.get('code_name', '')
                if code and name:
                    name_map[code] = name
    except Exception:
        pass
    return name_map


def normalize_agent_name(name: str) -> str:
    """Normalize agent names so state and report names match for dedup.

    State files use PascalCase + _account (e.g. CloseSniperAgent_account)
    Report files use snake_case (e.g. close_sniper)
    """
    mapping = {
        'CloseSniperAgent_account': 'close_sniper',
        'ContrarianAgent_account': 'contrarian',
        'DividendKingAgent_account': 'dividend_king',
        'DragonKingAgent_account': 'dragon_king',
        'GridMasterAgent_account': 'grid_master',
        'MomentumScalperAgent_account': 'momentum_scalper',
        'SectorAlphaAgent_account': 'sector_alpha',
        'TechSurgeAgent_account': 'tech_surge',
        'TrendHunterAgent_account': 'trend_hunter',
        'ValueGuardAgent_account': 'value_guard',
    }
    return mapping.get(name, name)


def load_state_trades() -> List[Dict]:
    """Load all trades from state files (has both buys and sells)."""
    all_trades = []
    state_files = sorted(glob.glob(os.path.join(STATE_DIR, '*_state.json')))
    for sf in state_files:
        try:
            with open(sf, 'r', encoding='utf-8') as f:
                state = json.load(f)
        except Exception:
            continue
        raw_name = state.get('name', os.path.basename(sf).replace('_state.json', ''))
        agent_name = normalize_agent_name(raw_name)
        positions = state.get('positions', {})
        for trade in state.get('trade_history', []):
            all_trades.append({
                'agent': agent_name,
                'date': trade.get('date', ''),
                'timestamp': trade.get('timestamp', ''),
                'code': str(trade.get('code', '')),
                'name': trade.get('name', ''),
                'side': trade.get('side', 'unknown'),
                'price': trade.get('price', 0),
                'shares': trade.get('shares', 0),
                'amount': trade.get('amount', trade.get('cost', 0)),
                'commission': trade.get('commission', 0),
                'tax': trade.get('tax', 0),
                'reason': trade.get('reason', trade.get('message', '')),
                'message': trade.get('message', ''),
                'pnl': trade.get('pnl', 0),
                # Carry position data for PnL calc
                '_positions': positions,
            })
    return all_trades


def load_paper_trade_logs() -> List[Dict]:
    """Load paper trading logs from 6 strategy accounts."""
    trades = []
    display_map = get_strategy_display_map()
    paper_dir = os.path.join(ACCOUNT_DIR, 'paper')
    if not os.path.isdir(paper_dir):
        return trades
    for path in glob.glob(os.path.join(paper_dir, '*_trades.json')):
        strategy_id = os.path.basename(path).replace('_trades.json', '')
        try:
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
        except Exception:
            continue
        if not isinstance(data, list):
            continue
        for trade in data:
            action = str(trade.get('action', '')).upper()
            if action == 'BUY':
                side = 'buy'
            elif action == 'SELL':
                side = 'sell'
            else:
                continue
            dt = trade.get('datetime', '')
            date = trade.get('date', '')
            if not dt and date:
                dt = f"{date} 12:00:00"
            trades.append({
                'agent': display_map.get(strategy_id, strategy_id),
                'strategy_id': strategy_id,
                'date': date,
                'timestamp': dt,
                'code': str(trade.get('code', '')),
                'side': side,
                'price': trade.get('price', 0),
                'shares': trade.get('shares', 0),
                'amount': trade.get('amount', 0),
                'commission': trade.get('commission', 0),
                'tax': trade.get('stamp_tax', trade.get('tax', 0)),
                'reason': trade.get('reason', ''),
                'message': trade.get('reason', ''),
                'pnl': trade.get('profit', trade.get('pnl', 0)),
                '_positions': {},
            })
    return trades


def build_trade_history() -> List[Dict]:
    """Build unified trade history from state files (complete buy+sell records)."""
    name_map = load_stock_name_map()

    # Load trades from state files (these have full history)
    all_trades = load_state_trades()

    # Load v2 trades (primary source for current pipeline)
    display_map = get_strategy_display_map()
    for trade in load_v2_trade_log():
        action = str(trade.get('action', '')).upper()
        if action == 'BUY':
            side = 'buy'
        elif action == 'SELL':
            side = 'sell'
        else:
            side = trade.get('side', 'unknown')
        code = str(trade.get('code', ''))
        strategy_id = trade.get('strategy_id', 'composite')
        agent_name = display_map.get(strategy_id, '组合账户' if strategy_id in ('composite', 'v2_overnight') else strategy_id)
        dt = trade.get('datetime', '')
        date = trade.get('date', '')
        if not dt and date:
                dt = f"{date} 12:00:00"
        all_trades.append({
            'agent': agent_name,
            'strategy_id': strategy_id,
            'date': date,
            'timestamp': dt,
            'code': code,
            'name': name_map.get(code, ''),
            'side': side,
            'price': trade.get('price', 0),
            'shares': trade.get('shares', 0),
            'amount': trade.get('amount', 0),
            'commission': trade.get('commission', 0),
            'tax': trade.get('stamp_tax', trade.get('tax', 0)),
            'reason': trade.get('reason', ''),
            'message': trade.get('reason', ''),
            'pnl': trade.get('profit', trade.get('pnl', 0)),
            '_positions': {},
        })

    # Load paper strategy trades
    all_trades.extend(load_paper_trade_logs())

    # Also load trades from latest boss report (legacy)
    report = load_latest_report()
    report_date = report.get('date', '') if report else ''

    if report:
        for ar in report.get('agent_reports', []):
            raw_agent = ar.get('agent_name', '')
            agent_name = normalize_agent_name(raw_agent)
            for trade in ar.get('trades', []):
                msg = trade.get('message', '')
                action = trade.get('action', '')
                if 'Bought' in msg or '买入' in msg or action == 'buy':
                    side = 'buy'
                elif 'Sold' in msg or '卖出' in msg or action == 'sell':
                    side = 'sell'
                else:
                    side = trade.get('side', 'unknown')

                code = trade.get('code') or trade.get('stock_code', '')
                name = trade.get('name') or trade.get('stock_name', '')
                amount = trade.get('amount') or trade.get('proceeds') or trade.get('cost') or trade.get('total_cost', 0)

                # Skip failed trades (limit-up blocks, etc.)
                if not trade.get('success', True):
                    continue
                # Skip trades with no price or shares (blocked/failed)
                if trade.get('price') is None or trade.get('shares', 0) == 0:
                    continue
                # Skip non-trade messages
                if '涨停' in msg or '跌停' in msg or '无法' in msg or 'skipped' in msg:
                    continue

                all_trades.append({
                    'agent': agent_name,
                    'date': trade.get('date', report_date),
                    'timestamp': trade.get('timestamp', ''),
                    'code': str(code),
                    'name': name,
                    'side': side,
                    'price': trade.get('price', 0),
                    'shares': trade.get('shares', 0),
                    'amount': amount,
                    'commission': trade.get('commission', 0),
                    'tax': trade.get('tax', 0),
                    'reason': trade.get('reason', msg),
                    'message': msg,
                    'pnl': trade.get('pnl', 0),
                    '_positions': {},
                })

    # Build FIFO buy cost tracking per (agent, code) for PnL calculation
    from collections import defaultdict
    buy_queues: dict[tuple, list] = defaultdict(list)  # (agent, code) -> [(price, shares, commission), ...]

    # Sort by date then buy before sell (to process buys first)
    all_trades.sort(key=lambda x: (x.get('date', ''), 0 if x['side'] == 'buy' else 1))

    # Deduplicate and enrich
    seen = set()
    trades = []
    for t in all_trades:
        code = t['code']
        agent = t['agent']
        # Fix name: lookup from stock pool if missing
        if not t.get('name') and code in name_map:
            t['name'] = name_map[code]
        if 'name' not in t:
            t['name'] = name_map.get(code, '')

        # Track buys in FIFO queue for PnL calc
        if t['side'] == 'buy':
            buy_queues[(agent, code)].append({
                'price': t['price'],
                'shares': t['shares'],
                'commission': t.get('commission', 0),
            })

        # Calculate PnL for sell trades using FIFO matching
        if t['side'] == 'sell' and (t.get('pnl') is None or t.get('pnl', 0) == 0):
            key = (agent, code)
            remaining_shares = t['shares']
            total_cost = 0
            total_buy_commission = 0
            while remaining_shares > 0 and buy_queues[key]:
                buy_lot = buy_queues[key][0]
                lot_shares = min(buy_lot['shares'], remaining_shares)
                total_cost += buy_lot['price'] * lot_shares
                total_buy_commission += buy_lot['commission'] * (lot_shares / buy_lot['shares'])
                buy_lot['shares'] -= lot_shares
                remaining_shares -= lot_shares
                if buy_lot['shares'] <= 0:
                    buy_queues[key].pop(0)
            if total_cost > 0:
                avg_cost = total_cost / t['shares']
                pnl = (t['price'] - avg_cost) * t['shares'] - t.get('commission', 0) - t.get('tax', 0) - total_buy_commission
                t['pnl'] = round(pnl, 2)
            if not t.get('reason') and not t.get('message'):
                if t['side'] == 'sell':
                    t['reason'] = f"卖出: 成本 {avg_cost:.2f}, 卖出 {t['price']:.2f}, 盈亏 {pnl:+.2f}"
                else:
                    t['reason'] = f"买入: 价格 {t['price']:.2f}"

        # Fill timestamp for old records
        ts = t.get('timestamp', '')
        if not ts and t['date']:
            ts = t.get('datetime') or f"{t['date']} 12:00:00"
            t['timestamp'] = ts

        # Calculate amount if missing
        if t['amount'] == 0 and t['price'] > 0 and t['shares'] > 0:
            t['amount'] = round(t['price'] * t['shares'], 2)

        dedup_key = (t['agent'], code, round(t['price'], 2), t['shares'], t['side'], t['date'], t.get('timestamp', '')[:16])
        if dedup_key in seen:
            continue
        seen.add(dedup_key)

        # Remove internal fields
        clean = {k: v for k, v in t.items() if not k.startswith('_')}
        clean['amount'] = round(clean['amount'], 2)
        trades.append(clean)

    trades.sort(key=lambda x: x.get('timestamp') or x['date'], reverse=True)
    return trades


def build_holdings_snapshot() -> List[Dict]:
    """Build current holdings from v2 account or legacy boss report."""
    name_map = load_stock_name_map()
    v2_account = load_v2_account()
    positions = v2_account.get('positions', {}) if v2_account else {}

    if positions:
        result = []
        for code, pos in positions.items():
            shares = pos.get('shares', 0)
            avg_cost = pos.get('avg_cost', pos.get('cost_price', 0))
            result.append({
                'code': code,
                'name': pos.get('name', '') or name_map.get(code, code),
                'agents': ['v2_overnight'],
                'total_shares': shares,
                'total_cost': shares * avg_cost,
                'avg_cost': avg_cost,
                'agent_count': 1,
            })
        result.sort(key=lambda x: x['total_shares'], reverse=True)
        return result

    report = load_latest_report()
    holdings = {}

    for ar in report.get('agent_reports', []):
        agent_name = ar.get('agent_name', '')
        perf = ar.get('performance', {})
        positions = perf.get('positions', {})

        for code, pos in positions.items():
            if code not in holdings:
                holdings[code] = {
                    'code': code,
                    'name': pos.get('name', ''),
                    'agents': [],
                    'total_shares': 0,
                    'total_cost': 0,
                }
            holdings[code]['agents'].append(agent_name)
            holdings[code]['total_shares'] += pos.get('shares', 0)
            holdings[code]['total_cost'] += pos.get('shares', 0) * pos.get('avg_cost', 0)

    result = []
    for h in holdings.values():
        h['avg_cost'] = h['total_cost'] / h['total_shares'] if h['total_shares'] > 0 else 0
        h['agent_count'] = len(h['agents'])
        result.append(h)

    result.sort(key=lambda x: (x['agent_count'], x['total_shares']), reverse=True)
    return result


def normalize_stock_code(code: str) -> str:
    """Normalize stock code to sh/sz prefix format for Ashare."""
    code = code.strip()
    if code.startswith('sh') or code.startswith('sz'):
        return code
    code = code.replace('.XSHG', '').replace('.XSHE', '')
    if code.startswith('6'):
        return 'sh' + code
    elif code.startswith(('0', '3')):
        return 'sz' + code
    return code


def enrich_positions_with_realtime(positions: Dict) -> Dict:
    """Add current_price to positions via unified market data Provider."""
    if not positions:
        return positions

    codes = list(positions.keys())
    try:
        from market_data import get_realtime_prices
        price_map = get_realtime_prices(codes)
        app.logger.info(f"Provider 实时价: {len(price_map)}/{len(codes)} 只")
    except Exception as e:
        app.logger.error(f"Failed to fetch realtime prices: {e}", exc_info=True)
        price_map = {}

    enriched = {}
    for code, pos in positions.items():
        raw = code.replace('sh', '').replace('sz', '')
        new_pos = dict(pos)
        if 'current_price' not in new_pos or new_pos.get('current_price') is None:
            matched = raw in price_map
            new_pos['current_price'] = price_map.get(raw, pos.get('avg_cost'))
            if not matched:
                app.logger.warning(f"No price for code={code}, raw={raw}, using fallback={new_pos['current_price']}")
        enriched[code] = new_pos

    return enriched


# ---- SPA Route ----

@app.after_request
def add_no_cache_headers(response):
    """Disable browser caching for dev environment."""
    response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    return response


@app.route('/')
@app.route('/<path:path>')
def index(path=None):
    """SPA - serve index.html for all routes."""
    return render_template('index.html')


# ---- API Routes ----

@app.route('/api/summary')
def api_summary():
    """Get dashboard summary data."""
    v2_account = load_v2_account()
    if v2_account:
        cash = v2_account.get('cash', 100000)
        total_profit = v2_account.get('total_profit', 0)
        positions = v2_account.get('positions', {})
        position_value = sum(
            p.get('shares', 0) * p.get('avg_cost', p.get('cost_price', 0))
            for p in positions.values()
        )
        total_equity = cash + position_value
        v2_pick = load_latest_v2_pick()
        if v2_pick.get('account_value'):
            total_equity = v2_pick['account_value']
        return jsonify({
            'total_equity': round(total_equity, 2),
            'total_return_pct': round(total_profit / 100000 * 100, 2),
            'agent_count': 0,
            'date': (v2_account.get('updated_at') or v2_pick.get('date', ''))[:10],
            'agent_stats': [],
            'strategy_stats': build_v2_strategy_stats(),
            'hot_sectors': [],
            'realtime_market': {},
            'index_quotes': [],
            'source': 'v2',
        })

    report = load_latest_report()

    if not report:
        return jsonify({'error': 'No reports found. Run daily workflow first.'})

    equity_history = build_equity_history()
    optimizer = load_optimizer_state()
    agent_stats = []

    for name, points in equity_history.items():
        if not points:
            continue
        equities = [p['equity'] for p in points]
        cum_return = (equities[-1] - 100000) / 100000 * 100

        max_dd = 0
        peak = equities[0]
        for eq in equities:
            if eq > peak:
                peak = eq
            dd = (eq - peak) / peak * 100
            if dd < max_dd:
                max_dd = dd

        wh = {}
        opt_data = optimizer.get('optimizers', {}).get(name, {})
        wh_list = opt_data.get('weight_history', [])
        if wh_list:
            wh = wh_list[-1]

        agent_stats.append({
            'name': name,
            'cumulative_return': round(cum_return, 2),
            'max_drawdown': round(max_dd, 2),
            'trading_days': len(points),
            'current_equity': equities[-1],
            'current_weights': wh,
        })

    agent_stats.sort(key=lambda x: x['cumulative_return'], reverse=True)

    return jsonify({
        'total_equity': report.get('total_equity', 0),
        'total_return_pct': report.get('total_return_pct', 0),
        'agent_count': report.get('agent_count', 0),
        'date': report.get('date', ''),
        'agent_stats': agent_stats,
        'hot_sectors': report.get('hot_sectors', [])[:5],
        'realtime_market': report.get('realtime_market', {}),
        'index_quotes': report.get('index_quotes', []),
    })


@app.route('/api/equity_history')
def api_equity_history():
    """Get equity curve data for all agents."""
    history = build_equity_history()
    data = {}
    for name, points in history.items():
        dates = [p['date'] for p in points]
        equities = [p['equity'] for p in points]
        data[name] = {
            'dates': dates,
            'equities': equities,
            'returns': [p['return_pct'] for p in points],
        }
    return jsonify(data)


@app.route('/api/trades')
def api_trades():
    """Get trade history with pagination."""
    all_trades = build_trade_history()

    page = int(request.args.get('page', 1))
    per_page = int(request.args.get('per_page', 50))
    agent_filter = request.args.get('agent', '')
    strategy_filter = request.args.get('strategy', '')
    side_filter = request.args.get('side', '')

    if agent_filter:
        all_trades = [t for t in all_trades if t['agent'] == agent_filter]
    if strategy_filter:
        display_map = get_strategy_display_map()
        display_name = display_map.get(strategy_filter, strategy_filter)
        all_trades = [
            t for t in all_trades
            if t.get('strategy_id') == strategy_filter
            or t.get('agent') == strategy_filter
            or t.get('agent') == display_name
        ]
    if side_filter:
        all_trades = [t for t in all_trades if t['side'] == side_filter]

    total = len(all_trades)
    start = (page - 1) * per_page
    end = start + per_page
    trades = all_trades[start:end]

    display_map = get_strategy_display_map()
    strategies = [{'id': 'composite', 'name': '组合账户'}]
    strategies.extend([{'id': k, 'name': v} for k, v in display_map.items()])

    return jsonify({
        'trades': trades,
        'total': total,
        'page': page,
        'per_page': per_page,
        'pages': (total + per_page - 1) // per_page,
        'strategies': strategies,
    })


@app.route('/api/holdings')
def api_holdings():
    """Get current holdings across all agents."""
    holdings = build_holdings_snapshot()
    return jsonify(holdings)


@app.route('/api/optimization')
def api_optimization():
    """Get optimization log."""
    optimizer = load_optimizer_state()
    logs = []
    for name, data in optimizer.get('optimizers', {}).items():
        for entry in data.get('optimization_log', []):
            entry['agent'] = name
            logs.append(entry)
    logs.sort(key=lambda x: x.get('date', ''), reverse=True)
    return jsonify({
        'logs': logs[:100],
        'weekly_reports': optimizer.get('weekly_reports', [])[:12],
    })


@app.route('/api/agents')
def api_agents():
    """List all agents with their positions and equity."""
    report = load_latest_report()
    equity_history = build_equity_history()
    agents = []

    for ar in report.get('agent_reports', []):
        name = ar.get('agent_name', '')
        perf = ar.get('performance', {})
        positions = perf.get('positions', {})

        # Get equity from history
        eq_list = equity_history.get(name, [])
        equity = eq_list[-1]['equity'] if eq_list else ar.get('equity', 100000)
        cum_ret = (equity - 100000) / 100000 * 100 if eq_list else ar.get('return_pct', 0)

        enriched_positions = enrich_positions_with_realtime(positions)

        # Normalize trades for frontend
        raw_trades = ar.get('trades', [])
        report_date = report.get('date', '')
        norm_trades = []
        for t in raw_trades[-20:]:
            msg = t.get('message', '')
            action = t.get('action', '')
            if 'Bought' in msg or '买入' in msg or action == 'buy':
                side = 'buy'
            elif 'Sold' in msg or '卖出' in msg or action == 'sell':
                side = 'sell'
            else:
                side = t.get('side', 'unknown')
            norm_trades.append({
                'action': t.get('action', side),
                'side': side,
                'code': t.get('code') or t.get('stock_code', ''),
                'name': t.get('name') or t.get('stock_name', ''),
                'price': t.get('price', 0),
                'shares': t.get('shares', 0),
                'amount': t.get('amount') or t.get('proceeds') or t.get('cost') or t.get('total_cost', 0),
                'date': t.get('date', report_date),
                'message': msg,
            })

        agents.append({
            'name': name,
            'equity': equity,
            'cumulative_return': round(cum_ret, 2),
            'positions': enriched_positions,
            'trades': norm_trades,
        })

    agents.sort(key=lambda x: x['cumulative_return'], reverse=True)
    return jsonify(agents)


@app.route('/api/v2/strategy_stats')
def api_v2_strategy_stats():
    """Get v2 strategy contribution stats."""
    account = load_v2_account()
    cash = account.get('cash', 0)
    v2_pick = load_latest_v2_pick()
    total_equity = v2_pick.get('account_value') or cash
    return jsonify({
        'strategies': build_v2_strategy_stats(),
        'account': {
            'cash': cash,
            'total_equity': round(total_equity, 2),
            'total_profit': account.get('total_profit', 0),
            'total_trades': account.get('total_trades', 0),
            'updated_at': account.get('updated_at', ''),
        },
    })


@app.route('/api/picks')
def api_picks():
    """Get today's AI stock picks from latest report."""
    nm = load_stock_name_map()

    picks = []
    date = ''
    summary = ''
    index_quotes = []
    hot_sectors = []
    generated_at = ''
    report = {}

    v2_report = load_latest_v2_pick()
    selection_logic = ''
    strategy_hit_counts = {}
    used_v2 = False
    if v2_report:
        used_v2 = True
        date = v2_report.get('date', '')
        generated_at = v2_report.get('timestamp', '')
        top_picks = v2_report.get('top_picks', [])
        picks = [
            transform_v2_pick_item(p, rank, nm)
            for rank, p in enumerate(top_picks[:10], 1)
        ]
        buy_count = len(v2_report.get('buy_actions', []))
        summary = (
            f"股票池 {v2_report.get('total_pool', 0)} 只, "
            f"评分 {v2_report.get('total_scored', 0)} 只"
        )
        if buy_count:
            summary += f", 买入 {buy_count} 只"
        elif not picks:
            summary += ", 今日无达标标的 (组合未出信号)"
        else:
            summary += ", 未执行买入"
        display_map = get_strategy_display_map()
        raw_counts = v2_report.get('strategy_results_count', {})
        strategy_hit_counts = {
            display_map.get(k, k): v for k, v in raw_counts.items()
        }
        pool_mode = v2_report.get('pool_mode', 'liquidity')
        if pool_mode == 'mainline':
            selection_logic = (
                f'扫描池：季度主线 × 放量强势股 ≈ {v2_report.get("scanned_pool", 0)} 只（排除大盘银行蓝筹）；'
                '再经因子评分 + 组合加权（正收益策略池）+ DL 重排取最终推荐。'
                f' 本次评分 {v2_report.get("total_scored", 0)} 只，推荐 {len(picks)} 只。'
            )
        elif pool_mode == 'sector':
            st = v2_report.get('sector_top', 10)
            ps = v2_report.get('per_sector', 10)
            selection_logic = (
                f'扫描池：热门板块 Top{st} × 每板块 Top{ps} ≈ {v2_report.get("scanned_pool", 0)} 只候选；'
                '再经因子评分 + 组合加权（正收益策略池）+ DL 重排取最终推荐。'
                f' 本次评分 {v2_report.get("total_scored", 0)} 只，推荐 {len(picks)} 只。'
            )
        else:
            selection_logic = (
                '实盘选股引擎：global_stock_picker → 组合账户（正收益策略 weight 加权合并），'
                '多策略同股覆盖加分，叠加 DL 因子重排。'
                f' 本次扫描 {v2_report.get("total_scored", 0)} 只，推荐 {len(picks)} 只。'
            )
        if not picks:
            summary += "；请检查 K 线是否更新或稍后重跑 daily_runner_v2"

    if not used_v2 and not picks:
        report = load_latest_report()
        if report:
            date = report.get('date', '')
            picks = report.get('top_picks', [])
            summary = report.get('picks_summary', '')
            index_quotes = report.get('index_quotes', [])
            hot_sectors = report.get('hot_sectors', [])[:5]
            generated_at = report.get('generated_at', '')
            if not picks:
                try:
                    from ai_stock_picker import generate_picks
                    picks = generate_picks(report, max_picks=10)
                except Exception as e:
                    app.logger.warning(f"Failed to generate picks on-the-fly: {e}")

        daily_reports = sorted(glob.glob(os.path.join(KNOWLEDGE_DIR, 'daily_*.json')))
        daily_picks = []
        daily_date = ''
        daily_summary = ''
        if not used_v2 and daily_reports:
            for dr_path in reversed(daily_reports):
                try:
                    with open(dr_path, 'r', encoding='utf-8') as f:
                        daily_report = json.load(f)
                except Exception:
                    continue
                buy_signals = daily_report.get('buy_signals', [])
                if buy_signals:
                    daily_date = daily_report.get('date', '')
                    daily_summary = daily_report.get('summary', {})
                    for rank, sig in enumerate(buy_signals[:10], 1):
                        code = sig.get('stock_code', '')
                        name = sig.get('stock_name', '') or nm.get(code, code)
                        daily_picks.append({
                            'rank': rank,
                            'code': code,
                            'name': name,
                            'composite_score': round(sig.get('confidence', 0) * 100),
                            'avg_tech_score': round(sig.get('confidence', 0) * 100),
                            'avg_fund_score': '-',
                            'agent_count': len(sig.get('original_strategies', [])),
                            'agents': sig.get('original_strategies', [sig.get('strategy', '')]),
                            'tech_reasons': [sig.get('reason', '')] if sig.get('reason') else [],
                            'news_reasons': [],
                            'buy_price': sig.get('buy_price', sig.get('price', 0)),
                            'stop_loss': sig.get('stop_loss'),
                            'take_profit': sig.get('take_profit'),
                            'invalid_price': sig.get('invalid_price'),
                            'stop_loss_reason': sig.get('stop_loss_reason', ''),
                            'take_profit_reason': sig.get('take_profit_reason', ''),
                            'atr': sig.get('atr'),
                            'risk_reward_ratio': sig.get('risk_reward_ratio'),
                        })
                    break

            if daily_picks and (not picks or daily_date >= date):
                picks = daily_picks
                if not date:
                    date = daily_date
                if not summary:
                    summary = daily_summary if isinstance(daily_summary, str) else str(daily_summary)
            elif daily_date and not date:
                date = daily_date

    return jsonify({
        'date': date or '',
        'generated_at': generated_at or report.get('generated_at', ''),
        'picks': picks,
        'summary': summary,
        'index_quotes': index_quotes,
        'hot_sectors': hot_sectors,
        'source': 'v2' if used_v2 else 'legacy',
        'selection_logic': selection_logic,
        'strategy_hit_counts': strategy_hit_counts,
    })

@app.route('/api/agent/<agent_name>')
def api_agent_detail(agent_name):
    """Get detailed info for a specific agent."""
    state = load_agent_state(agent_name)
    optimizer = load_optimizer_state()
    opt_data = optimizer.get('optimizers', {}).get(agent_name, {})

    # Get from latest report
    report = load_latest_report()
    agent_report = {}
    for ar in report.get('agent_reports', []):
        if ar.get('agent_name') == agent_name:
            agent_report = ar
            break

    perf = agent_report.get('performance', state.get('performance', {}))
    positions = enrich_positions_with_realtime(perf.get('positions', {}))
    raw_trades = agent_report.get('trades', [])
    report_date = report.get('date', '')
    # Normalize trades for frontend
    nm = load_stock_name_map()
    trades = []
    for t in raw_trades:
        msg = t.get('message', '')
        action = t.get('action', '')
        if 'Bought' in msg or '买入' in msg or action == 'buy':
            side = 'buy'
        elif 'Sold' in msg or '卖出' in msg or action == 'sell':
            side = 'sell'
        else:
            side = t.get('side', 'unknown')
        # Enrich name from name_map if missing
        code_val = t.get('code') or t.get('stock_code', '')
        name_val = t.get('name') or t.get('stock_name', '')
        if not name_val and code_val in nm:
            name_val = nm[code_val]
        trades.append({
            'action': t.get('action', side),
            'side': side,
            'code': code_val,
            'name': name_val,
            'price': t.get('price', 0),
            'shares': t.get('shares', 0),
            'amount': t.get('amount') or t.get('proceeds') or t.get('cost') or t.get('total_cost', 0),
            'commission': t.get('commission', 0),
            'tax': t.get('tax', 0),
            'pnl': t.get('pnl'),
            'reason': t.get('reason', msg),
            'timestamp': t.get('timestamp', ''),
            'date': t.get('date', report_date),
            'message': msg,
            'success': t.get('success', True),
        })
    equity_history = build_equity_history().get(agent_name, [])

    ph = opt_data.get('performance_history', [])
    cum_return = (ph[-1]['equity'] - 100000) / 100000 * 100 if ph else 0

    return jsonify({
        'name': agent_name,
        'equity': equity_history[-1]['equity'] if equity_history else 100000,
        'cumulative_return': round(cum_return, 2),
        'trading_days': len(equity_history),
        'positions': positions,
        'trades': trades[-50:],
        'equity_history': equity_history[-90:],
        'optimization_log': opt_data.get('optimization_log', []),
        'current_weights': opt_data.get('weight_history', [])[-1] if opt_data.get('weight_history') else {},
    })


# ---- K-line API (kline_service) ----

@app.route('/api/kline/<code>')
def api_kline(code):
    """
    日/周/月 K 线 — 优先本地 CSV，iFind/新浪 fallback
    frequency: 1d (default), 1w, 1M
    """
    raw_code = code.replace('sh', '').replace('sz', '')
    frequency = request.args.get('frequency', '1d')
    count = int(request.args.get('count', 120))

    try:
        from kline_service import get_kline
        bars = get_kline(raw_code, frequency, count)
        if not bars:
            return jsonify({'error': f'No data for {raw_code}', 'code': raw_code}), 404

        stock_name = ''
        pool_path = os.path.join(BASE_DIR, 'data', 'stock_pool.json')
        if os.path.exists(pool_path):
            import json as _json
            with open(pool_path, 'r') as f:
                for item in _json.load(f):
                    if isinstance(item, dict) and item.get('code') == raw_code:
                        stock_name = item.get('name', item.get('code_name', ''))
                        break

        return jsonify({
            'code': raw_code,
            'name': stock_name,
            'frequency': frequency,
            'data': bars,
            'source': 'local',
        })
    except Exception as e:
        return jsonify({'error': str(e), 'code': raw_code}), 500


@app.route('/api/intraday/<code>')
def api_intraday(code):
    """按需分钟 K 线 — 用户点击「分时」或日K某日时触发"""
    raw_code = code.replace('sh', '').replace('sz', '')
    date = request.args.get('date', 'today')
    if date == 'today':
        date = datetime.now().strftime('%Y-%m-%d')

    try:
        from kline_service import get_intraday, get_daily
        from market_data import get_realtime_quote_dict

        bars = get_intraday(raw_code, date)
        if not bars:
            return jsonify({'error': f'No intraday data for {raw_code} on {date}', 'code': raw_code}), 404

        prev_close = None
        daily = get_daily(raw_code, count=5)
        if daily:
            if date == datetime.now().strftime('%Y-%m-%d'):
                rt = get_realtime_quote_dict(raw_code) or {}
                prev_close = float(rt.get('pre_close') or 0) or None
            if not prev_close:
                for b in reversed(daily):
                    if b['t'][:10] < date:
                        prev_close = float(b['c'])
                        break
            if not prev_close and len(daily) >= 2:
                prev_close = float(daily[-2]['c'])
            if not prev_close:
                prev_close = float(daily[0]['o'])

        last = bars[-1]
        pc = prev_close or float(last.get('o') or last['c'])
        change = float(last['c']) - pc
        change_pct = round(change / pc * 100, 2) if pc > 0 else 0

        return jsonify({
            'code': raw_code,
            'date': date,
            'frequency': 'intraday',
            'data': bars,
            'prev_close': pc,
            'change': round(change, 3),
            'change_pct': change_pct,
            'source': 'cache_or_ifind',
        })
    except Exception as e:
        return jsonify({'error': str(e), 'code': raw_code}), 500


@app.route('/api/stock/<code>')
def api_stock(code):
    """Get stock quote from local K-line + realtime provider."""
    raw_code = code.replace('sh', '').replace('sz', '')

    try:
        from kline_service import get_daily
        from market_data import get_realtime_quote_dict

        bars = get_daily(raw_code, count=2)
        rt = get_realtime_quote_dict(raw_code) or {}

        stock_name = ''
        pool_path = os.path.join(BASE_DIR, 'data', 'stock_pool.json')
        if os.path.exists(pool_path):
            import json as _json
            with open(pool_path, 'r') as f:
                for item in _json.load(f):
                    if isinstance(item, dict) and item.get('code') == raw_code:
                        stock_name = item.get('name', item.get('code_name', ''))
                        break

        if bars:
            latest = bars[-1]
            prev = bars[-2] if len(bars) > 1 else latest
            close = float(rt.get('close') or latest['c'])
            pre = float(rt.get('pre_close') or prev['c'])
            change_pct = round((close - pre) / pre * 100, 2) if pre > 0 else 0
            return jsonify({
                'code': raw_code,
                'name': stock_name or rt.get('name', ''),
                'open': float(rt.get('open') or latest['o']),
                'high': float(rt.get('high') or latest['h']),
                'low': float(rt.get('low') or latest['l']),
                'close': close,
                'prev_close': pre,
                'change': round(close - pre, 3),
                'change_pct': change_pct,
                'volume': int(rt.get('volume') or latest['v']),
                'date': latest['t'],
            })

        if rt:
            return jsonify({
                'code': raw_code,
                'name': stock_name or rt.get('name', ''),
                'open': rt.get('open', 0),
                'high': rt.get('high', 0),
                'low': rt.get('low', 0),
                'close': rt.get('close', 0),
                'change_pct': rt.get('change_pct', 0),
                'volume': int(rt.get('volume', 0)),
            })

        return jsonify({'error': f'No data for {raw_code}'}), 404
    except Exception as e:
        return jsonify({'error': str(e), 'code': raw_code}), 500


@app.route('/api/realtime/<code>')
def api_realtime(code):
    """Get real-time quote via unified market data Provider."""
    code = normalize_stock_code(code)
    raw_code = code.replace('sh', '').replace('sz', '')
    try:
        from market_data import get_realtime_quote_dict, get_provider_name
        rt = get_realtime_quote_dict(raw_code)
        if rt:
            return jsonify({
                'code': code,
                'name': rt.get('name', ''),
                'open': rt.get('open', 0),
                'close': rt.get('close', 0),
                'high': rt.get('high', 0),
                'low': rt.get('low', 0),
                'price': rt.get('close', 0),
                'volume': int(rt.get('volume', 0)),
                'amount': rt.get('amount', 0),
                'date': rt.get('date', ''),
                'time': rt.get('time', ''),
                'provider': get_provider_name(),
            })
        return jsonify({'error': 'No data', 'code': code}), 404
    except Exception as e:
        return jsonify({'error': str(e), 'code': code}), 500


@app.route('/api/market_news')
def api_market_news():
    """Get today's market news headlines."""
    try:
        from market_news import MarketNews
        news = MarketNews()
        keyword = request.args.get('keyword', '')
        max_items = int(request.args.get('max', 20))

        if keyword:
            items = news.get_news_by_keyword(keyword, max_items=max_items)
        else:
            items = news.get_today_news(max_items=max_items)

        headlines = []
        for item in items:
            headlines.append({
                'title': item.get('title', '')[:100],
                'summary': item.get('summary', '')[:200],
                'time': item.get('time', ''),
                'source': item.get('source_name', ''),
                'url': item.get('url', '')
            })

        return jsonify({
            'date': datetime.now().strftime('%Y-%m-%d'),
            'count': len(headlines),
            'items': headlines
        })
    except Exception as e:
        return jsonify({'error': str(e), 'items': []}), 500


@app.route('/api/market_news/refresh')
def api_market_news_refresh():
    """Force refresh today's news cache."""
    try:
        from market_news import MarketNews
        news = MarketNews()
        count = news.save_today_news()
        return jsonify({'status': 'ok', 'count': count})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/minute_kline/<code>')
def api_minute_kline(code):
    """兼容旧接口 — 重定向到 /api/intraday"""
    raw_code = code.replace('sh', '').replace('sz', '')
    date = request.args.get('date', 'today')
    try:
        from kline_service import get_intraday
        bars = get_intraday(raw_code, date if date != 'today' else None)
        if not bars:
            return jsonify({'error': f'No minute data for {raw_code}', 'code': raw_code}), 404
        return jsonify({'code': raw_code, 'frequency': 'intraday', 'data': bars})
    except Exception as e:
        return jsonify({'error': str(e), 'code': raw_code}), 500


@app.route('/api/market_overview')
def api_market_overview():
    """Get AI market overview: indices, sentiment, hot sectors."""
    try:
        from ai_analyzer import AIAnalyzer
        analyzer = AIAnalyzer()
        overview = analyzer.get_market_overview()
        # Convert DataFrame indices to dict for JSON serialization
        indices_raw = overview.get('indices', {})
        indices_out = {}
        if hasattr(indices_raw, 'iterrows') and not indices_raw.empty:
            for _, row in indices_raw.iterrows():
                name = str(row.get('name', row.get('code', '')))
                price = float(row.get('close', row.get('price', 0)))
                pct = float(row.get('change_pct', 0))
                indices_out[name] = {'price': round(price, 2), 'change_pct': round(pct, 2)}
        elif isinstance(indices_raw, dict):
            for k, v in indices_raw.items():
                if isinstance(v, dict):
                    price = float(v.get('price', v.get('close', 0)))
                    pct = float(v.get('change_pct', v.get('change', 0)))
                    indices_out[k] = {'price': round(price, 2), 'change_pct': round(pct, 2)}

        sectors = overview.get('sector_hot', [])[:8]
        return jsonify({
            'date': overview.get('date', ''),
            'market_sentiment': overview.get('market_sentiment', 'neutral'),
            'indices': indices_out,
            'sector_hot': sectors,
        })
    except Exception as e:
        app.logger.error(f"Market overview error: {e}", exc_info=True)
        return jsonify({'error': str(e), 'market_sentiment': 'neutral', 'indices': {}, 'sector_hot': []})


@app.route('/api/positions_monitor')
def api_positions_monitor():
    """Monitor holdings or today's picks with real-time prices and alert status."""
    nm = load_stock_name_map()
    display_map = get_strategy_display_map()
    account = load_v2_account()
    positions = account.get('positions', {}) if account else {}
    monitor_date = (account.get('updated_at') or '')[:10]
    mode = 'holdings'

    monitor_items = []
    for code, pos in positions.items():
        buy_price = pos.get('avg_cost', pos.get('cost_price', 0))
        stop_loss = pos.get('stop_loss', buy_price * 0.93)
        take_profit = pos.get('take_profit', buy_price * 1.15)
        invalid_price = stop_loss
        monitor_items.append({
            'code': code,
            'name': pos.get('name', '') or nm.get(code, code),
            'buy_price': buy_price,
            'stop_loss': stop_loss,
            'take_profit': take_profit,
            'invalid_price': invalid_price,
            'strategy': pos.get('strategy', '组合账户'),
            'confidence': pos.get('confidence', 0),
            'shares': pos.get('shares', 0),
        })

    if not monitor_items:
        v2_report = load_latest_v2_pick()
        monitor_date = v2_report.get('date', monitor_date)
        for action in v2_report.get('buy_actions', []):
            if not action.get('ok', True):
                continue
            code = str(action.get('code', ''))
            buy_price = action.get('price', 0)
            pick_match = next(
                (p for p in v2_report.get('top_picks', []) if str(p.get('code')) == code),
                {},
            )
            strategies = pick_match.get('strategies') or {}
            strategy_names = [display_map.get(k, k) for k in strategies.keys()]
            monitor_items.append({
                'code': code,
                'name': nm.get(code, code),
                'buy_price': buy_price,
                'stop_loss': pick_match.get('stop_loss', buy_price * 0.93),
                'take_profit': pick_match.get('take_profit', buy_price * 1.15),
                'invalid_price': pick_match.get('stop_loss', buy_price * 0.93),
                'strategy': '、'.join(strategy_names) if strategy_names else '组合账户',
                'confidence': pick_match.get('confidence', 0),
                'shares': action.get('shares', 0),
            })

    if not monitor_items:
        mode = 'watchlist'
        v2_report = load_latest_v2_pick()
        monitor_date = v2_report.get('date', monitor_date)
        for pick in v2_report.get('top_picks', [])[:10]:
            code = str(pick.get('code', ''))
            buy_price = pick.get('price', 0)
            strategies = pick.get('strategies') or {}
            strategy_names = [display_map.get(k, k) for k in strategies.keys()]
            monitor_items.append({
                'code': code,
                'name': nm.get(code, code),
                'buy_price': buy_price,
                'stop_loss': pick.get('stop_loss', buy_price * 0.93 if buy_price else 0),
                'take_profit': pick.get('take_profit', buy_price * 1.15 if buy_price else 0),
                'invalid_price': pick.get('stop_loss', buy_price * 0.93 if buy_price else 0),
                'strategy': '、'.join(strategy_names) if strategy_names else '组合竞技',
                'confidence': pick.get('confidence', 0),
                'shares': 0,
            })

    monitor = []
    for item in monitor_items:
        code = item['code']
        buy_price = item['buy_price']
        stop_loss = item['stop_loss']
        take_profit = item['take_profit']
        invalid_price = item['invalid_price']

        current_price = buy_price
        realtime_error = True
        try:
            from market_data import get_realtime_prices
            raw_code = code.replace('sh', '').replace('sz', '')
            prices = get_realtime_prices([raw_code])
            if raw_code in prices and prices[raw_code] > 0:
                current_price = prices[raw_code]
                realtime_error = False
        except Exception:
            pass

        if current_price > 0:
            dist_sl_pct = (current_price - stop_loss) / stop_loss * 100 if stop_loss else 0
            dist_tp_pct = (take_profit - current_price) / current_price * 100 if take_profit else 0
            dist_inv_pct = (current_price - invalid_price) / invalid_price * 100 if invalid_price else 0
            change_pct = (current_price - buy_price) / buy_price * 100 if buy_price else 0
        else:
            dist_sl_pct = dist_tp_pct = dist_inv_pct = change_pct = 0

        alert = 'normal'
        if current_price <= stop_loss:
            alert = 'stop_loss'
        elif current_price >= take_profit:
            alert = 'take_profit'
        elif invalid_price and current_price <= invalid_price:
            alert = 'invalid'
        elif abs(dist_sl_pct) < 3:
            alert = 'warning_sl'
        elif dist_tp_pct < 5:
            alert = 'warning_tp'

        monitor.append({
            'code': code,
            'name': item['name'],
            'buy_price': buy_price,
            'current_price': round(current_price, 2),
            'change_pct': round(change_pct, 2),
            'stop_loss': stop_loss,
            'take_profit': take_profit,
            'invalid_price': invalid_price,
            'dist_sl_pct': round(dist_sl_pct, 1),
            'dist_tp_pct': round(dist_tp_pct, 1),
            'dist_inv_pct': round(dist_inv_pct, 1),
            'alert': alert,
            'strategy': item.get('strategy', ''),
            'confidence': item.get('confidence', 0),
            'realtime_error': realtime_error,
            'shares': item.get('shares', 0),
        })

    return jsonify({'date': monitor_date, 'picks': monitor, 'source': 'v2', 'mode': mode})


@app.route('/api/historical_picks')
def api_historical_picks():
    """Get historical picks for a specific date or list of dates."""
    date = request.args.get('date', '')
    nm = load_stock_name_map()

    if date:
        v2_path = os.path.join(KNOWLEDGE_DIR, f'daily_pick_{date}.json')
        if os.path.exists(v2_path):
            with open(v2_path, 'r', encoding='utf-8') as f:
                daily = json.load(f)
            picks = []
            for rank, pick in enumerate(daily.get('top_picks', [])[:10], 1):
                code = str(pick.get('code', ''))
                picks.append({
                    'rank': rank,
                    'code': code,
                    'name': nm.get(code, code),
                    'buy_price': pick.get('price', 0),
                    'stop_loss': pick.get('stop_loss'),
                    'take_profit': pick.get('take_profit'),
                    'strategy': ', '.join((pick.get('strategies') or {}).keys()),
                    'confidence': pick.get('confidence', 0),
                })
            sells = daily.get('stop_actions', [])
            return jsonify({'date': date, 'buys': picks, 'sells': sells, 'source': 'v2'})

        fname = f'daily_{date.replace("-", "")}.json'
        fpath = os.path.join(KNOWLEDGE_DIR, fname)
        if os.path.exists(fpath):
            with open(fpath, 'r', encoding='utf-8') as f:
                daily = json.load(f)
            buys = daily.get('buy_signals', [])
            sells = daily.get('sell_signals', [])
            picks = []
            for rank, sig in enumerate(buys, 1):
                code = sig.get('stock_code', '')
                name = sig.get('stock_name', '') or nm.get(code, code)
                picks.append({
                    'rank': rank, 'code': code, 'name': name,
                    'buy_price': sig.get('buy_price', sig.get('price', 0)),
                    'stop_loss': sig.get('stop_loss'),
                    'take_profit': sig.get('take_profit'),
                    'strategy': sig.get('strategy', ''),
                    'confidence': sig.get('confidence', 0),
                })
            return jsonify({'date': date, 'buys': picks, 'sells': sells})
        return jsonify({'date': date, 'buys': [], 'sells': [], 'error': 'No data for this date'})

    dates = []
    for r in sorted(glob.glob(os.path.join(KNOWLEDGE_DIR, 'daily_pick_*.json'))):
        basename = os.path.basename(r).replace('daily_pick_', '').replace('.json', '')
        if len(basename) == 10:
            dates.append(basename)
    for r in sorted(glob.glob(os.path.join(KNOWLEDGE_DIR, 'daily_*.json'))):
        basename = os.path.basename(r).replace('daily_', '').replace('.json', '')
        if len(basename) == 8:
            formatted = f"{basename[:4]}-{basename[4:6]}-{basename[6:8]}"
            if formatted not in dates:
                dates.append(formatted)
    dates.sort(reverse=True)
    return jsonify({'dates': dates})


# ---- Backtest API (v2 优先) ----

BACKTEST_V2_DIR = os.path.join(BASE_DIR, 'reports', 'backtest_v2')
BACKTEST_DIR = os.path.join(BASE_DIR, 'reports', 'half_year_backtest')
OPTIMIZATION_REPORT = os.path.join(BASE_DIR, 'optimization', 'optimization_report_20260528.json')


BENCHMARK_SUMMARY_PATH = os.path.join(BACKTEST_V2_DIR, 'summary_benchmark.json')


def _max_trading_days(summary: Dict) -> int:
    strats = summary.get('strategies') or []
    if not strats:
        return 0
    return max(s.get('trading_days', 0) for s in strats)


def _load_summary_file(path: str) -> tuple:
    with open(path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    tag = data.get('benchmark_tag') or os.path.basename(path).replace('summary_', '').replace('.json', '')
    return data, tag


def load_latest_v2_backtest() -> tuple:
    """返回 (summary_dict, tag) 或 (None, None) — 按文件时间取最新一份"""
    files = sorted(glob.glob(os.path.join(BACKTEST_V2_DIR, 'summary_2*.json')))
    if not files:
        return None, None
    return _load_summary_file(files[-1])


def load_display_v2_backtest() -> tuple:
    """Dashboard 展示用：优先训练基准，避免近3个月快测覆盖主结果"""
    if os.path.exists(BENCHMARK_SUMMARY_PATH):
        return _load_summary_file(BENCHMARK_SUMMARY_PATH) + ('benchmark',)

    files = sorted(glob.glob(os.path.join(BACKTEST_V2_DIR, 'summary_2*.json')))
    if not files:
        return None, None, 'none'

    scored = []
    for path in files:
        try:
            data, tag = _load_summary_file(path)
            scored.append((_max_trading_days(data), path, data, tag))
        except Exception:
            continue
    if not scored:
        return None, None, 'none'

    scored.sort(key=lambda x: x[0], reverse=True)
    best_td, _best_path, best_data, best_tag = scored[0]
    latest_td, _latest_path, latest_data, latest_tag = scored[-1]

    if best_td >= 200 and latest_td < 120 and best_tag != latest_tag:
        return best_data, best_tag, 'benchmark_fallback'
    return latest_data, latest_tag, 'latest'


def map_v2_strategy(s: Dict) -> Dict:
    """v2 回测结果 -> Dashboard 展示格式"""
    pf = s.get('profit_factor', 0)
    hold_mode = s.get('hold_mode', 'swing')
    max_hold = s.get('max_hold_days', 10)
    if hold_mode == 'overnight':
        sell_logic = f'隔夜: 止损/止盈/移动止盈 | hold≥{max_hold} 强制平'
        desc = s.get('description') or '隔夜策略 | 尾盘买入次日离场'
    else:
        sell_logic = f'波段: -7%止损 +25%止盈 移动止盈6% | 最多持{max_hold}日'
        desc = s.get('description') or f'波段策略 | 最多持有{max_hold}个交易日'
    return {
        'name': s.get('name', ''),
        'display_name': s.get('display_name', s.get('name', '')),
        'final_value': s.get('final_value', 100000),
        'total_return': s.get('return_pct', 0),
        'max_drawdown': abs(s.get('max_drawdown', 0)),
        'annual_return': s.get('cagr_pct', s.get('annual_return_pct', 0)),
        'cagr_pct': s.get('cagr_pct', s.get('annual_return_pct', 0)),
        'trade_count': s.get('total_trades', 0),
        'win_rate': (s.get('win_rate', 0) or 0) / 100.0,
        'win_count': s.get('win_count', 0),
        'lose_count': s.get('lose_count', 0),
        'avg_win': s.get('avg_win', 0),
        'avg_lose': s.get('avg_lose', 0),
        'profit_ratio': pf,
        'profit_factor': pf,
        'avg_hold_days': s.get('avg_hold_days', 2.0),
        'sharpe_ratio': s.get('sharpe', 0),
        'max_positions': s.get('max_positions', 3),
        'monthly_returns': s.get('monthly_returns', {}),
        'hold_mode': hold_mode,
        'max_hold_days': max_hold,
        'description': desc,
        'buy_logic': '盘中强信号即买 (9:30-15:00) | 组合=正收益策略 weight 合并',
        'sell_logic': sell_logic,
        'source': 'v2',
    }


def load_v2_backtest_nav(strategy_name: str, tag: str) -> List[Dict]:
    path = os.path.join(BACKTEST_V2_DIR, f'nav_{strategy_name}_{tag}.json')
    if not os.path.exists(path):
        return []
    with open(path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    nav = data.get('nav', [])
    return [{
        'date': p['date'],
        'total_value': p.get('value', 100000),
        'return_pct': p.get('return_pct', 0),
        'cash': p.get('cash', 0),
        'positions': p.get('positions', 0),
    } for p in nav]


def load_v2_backtest_trades(strategy_name: str, tag: str) -> List[Dict]:
    path = os.path.join(BACKTEST_V2_DIR, f'trades_{strategy_name}_{tag}.json')
    if not os.path.exists(path):
        return []
    with open(path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    trades = []
    for t in data.get('trades', []):
        action = t.get('action', '').upper()
        profit = t.get('profit', 0) or 0
        profit_pct = t.get('profit_pct', 0) or 0
        trades.append({
            'date': t.get('date', ''),
            'action': action.lower(),
            'side': action.lower(),
            'code': t.get('code', ''),
            'price': t.get('price', 0),
            'shares': t.get('shares', 0),
            'amount': t.get('amount', 0),
            'profit': profit,
            'profit_pct': profit_pct,
            'pnl': profit,
            'return_pct': profit_pct,
            'hold_days': t.get('hold_days', 0),
            'reason': t.get('reason', ''),
            'commission': t.get('commission', 0),
            'stamp_tax': t.get('stamp_tax', 0),
        })
    return trades

# Strategy descriptions for display
STRATEGY_DESCRIPTIONS = {
    'trend_following': {
        'name': '趋势跟踪',
        'desc': 'MA5/MA20/MA60多头排列时买入，MA5下穿MA20时卖出。核心逻辑：顺势而为，在上升趋势中持有，趋势逆转时退出。适合单边上涨行情。',
        'buy_logic': '收盘价 > MA20 且 MA5 > MA20 且 MA20 > MA60 且 MACD金叉',
        'sell_logic': 'MA5下穿MA20 或 MACD死叉',
    },
    'mean_reversion': {
        'name': '均值回归',
        'desc': 'RSI超卖(<30)且价格跌破布林带下轨时买入，RSI回到中性区(50-70)或站上布林带中轨时卖出。核心逻辑：价格偏离均值后会回归。适合震荡市。',
        'buy_logic': 'RSI(14) < 30 且 收盘价 < 布林下轨 且 MACD绿柱缩短',
        'sell_logic': 'RSI > 50 且 RSI < 70 且 收盘价 > 布林中轨',
    },
    'momentum_breakout': {
        'name': '动量突破',
        'desc': '价格突破20日高点且放量(量比>1.5)时买入，跌破10日低点时卖出。核心逻辑：突破带来惯性动能，追强不追弱。',
        'buy_logic': '收盘价 > 20日高点 且 成交量/均量 > 1.5 且 RSI(6) > 60',
        'sell_logic': '收盘价 < 10日低点',
    },
    'multi_factor': {
        'name': '多因子',
        'desc': '综合动量、波动率、趋势强度、MACD、均线、量价共振、RSI等多个因子打分排序，买分最高的股票。核心逻辑：多维度综合评估，避免单一指标误判。',
        'buy_logic': '多因子综合得分排名前列(动量+波动率+趋势强度+MACD+均线+量价+RSI)',
        'sell_logic': '得分下降至排名后1/3 或 连续3日得分下滑',
    },
    'oversold_bounce': {
        'name': '超跌反弹',
        'desc': 'RSI极度超卖(<20)且价格较20日均线偏离超过5%时买入，反弹至5%以上收益或RSI回到30以上时卖出。核心逻辑：急跌必有反弹，捕捉超跌后的修复行情。',
        'buy_logic': 'RSI(6) < 20 且 (MA20 - 收盘价)/MA20 > 5% 且 MACD绿柱缩短',
        'sell_logic': '收益率 > 5% 或 RSI(6) > 30',
    },
}

def compute_avg_hold_days(strategy_name: str) -> float:
    """Compute average hold days from buy-sell trade pairs."""
    trades_path = os.path.join(BACKTEST_DIR, f'{strategy_name}_trades.json')
    if not os.path.exists(trades_path):
        return 0
    try:
        with open(trades_path, 'r', encoding='utf-8') as f:
            trades = json.load(f)
        holds = []
        current = {}
        for t in sorted(trades, key=lambda x: x.get('date', '')):
            code = str(t.get('stock_code', t.get('code', '')))
            action = t.get('action', t.get('side', ''))
            date = t.get('date', '')
            if action == 'buy':
                current[code] = date
            elif action == 'sell' and code in current:
                try:
                    d1 = datetime.strptime(current[code], '%Y-%m-%d')
                    d2 = datetime.strptime(date, '%Y-%m-%d')
                    holds.append((d2 - d1).days)
                except ValueError:
                    pass
        return round(sum(holds) / len(holds), 1) if holds else 0
    except Exception:
        return 0

def load_optimized_ranking() -> List[Dict]:
    """Load optimized backtest ranking from optimization report."""
    if not os.path.exists(OPTIMIZATION_REPORT):
        return []
    try:
        with open(OPTIMIZATION_REPORT, 'r', encoding='utf-8') as f:
            opt = json.load(f)
        after = opt.get('after', {})
        before = opt.get('before', {})
        strategies = []
        for name, v in after.items():
            ret = v.get('return_pct', 0) or 0
            dd = abs(v.get('max_drawdown', 0))
            # Compute annualized: ~2.5 years (2024-01 to 2026-05) ≈ 630 trading days
            annual_return = round(ret * (252.0 / 630), 2)
            s = {
                'name': name,
                'final_value': round(100000 * (1 + ret / 100), 2),
                'total_return': ret,
                'max_drawdown': dd,
                'annual_return': annual_return,
                'trade_count': v.get('trades', 0),
                'win_rate': (v.get('win_rate', 0) or 0) / 100.0,
                'win_count': 0,
                'lose_count': 0,
                'avg_hold_days': compute_avg_hold_days(name),
                'sharpe_ratio': v.get('sharpe', 0),
                'blocked_limit_up': 0,
                'blocked_limit_down': 0,
                'max_positions': 0,
                'avg_win': 0,
                'avg_lose': 0,
                'profit_ratio': 0,
                'optimized': True,
                'before_return': before.get(name, {}).get('return_pct', 0),
            }
            if name in STRATEGY_DESCRIPTIONS:
                desc = STRATEGY_DESCRIPTIONS[name]
                s['display_name'] = desc['name']
                s['description'] = desc['desc']
                s['buy_logic'] = desc['buy_logic']
                s['sell_logic'] = desc['sell_logic']
            strategies.append(s)
        strategies.sort(key=lambda x: x['total_return'], reverse=True)
        return strategies
    except Exception:
        return []

def load_backtest_ranking() -> List[Dict]:
    """Load backtest ranking data - always use raw backtest to match NAV curves."""
    ranking_path = os.path.join(BACKTEST_DIR, 'half_year_backtest_ranking.json')
    if os.path.exists(ranking_path):
        with open(ranking_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        trading_days = data.get('trading_days', 252)
        if trading_days <= 0:
            trading_days = 252
        raw_strategies = data.get('strategies', data.get('rankings', []))
        strategies = []
        for r in raw_strategies:
            total_return = r.get('return_pct', r.get('total_return', 0)) or 0
            annual_return = round(total_return * (252.0 / trading_days), 2)
            raw_avg_hold = r.get('avg_hold_days')
            if raw_avg_hold is None or raw_avg_hold == 0:
                strategy_name = r.get('strategy', r.get('name', ''))
                avg_hold = compute_avg_hold_days(strategy_name)
            else:
                avg_hold = raw_avg_hold
            s = {
                'name': r.get('strategy', r.get('name', '')),
                'final_value': r.get('total_value', r.get('final_value', 100000)),
                'total_return': total_return,
                'max_drawdown': r.get('max_drawdown', 0),
                'annual_return': annual_return,
                'trade_count': r.get('total_trades', r.get('trade_count', 0)),
                'win_rate': r.get('win_rate', 0) / 100.0 if r.get('win_rate', 0) > 1 else r.get('win_rate', 0),
                'win_count': r.get('win_trades', r.get('win_count', 0)),
                'lose_count': r.get('lose_trades', r.get('lose_count', 0)),
                'avg_hold_days': avg_hold,
                'sharpe_ratio': r.get('sharpe_ratio', 0),
                'blocked_limit_up': r.get('blocked_buys', r.get('blocked_limit_up', 0)),
                'blocked_limit_down': r.get('blocked_sells', r.get('blocked_limit_down', 0)),
                'max_positions': r.get('max_positions', 0),
                'avg_win': r.get('avg_win', 0),
                'avg_lose': r.get('avg_lose', 0),
                'profit_ratio': r.get('profit_ratio', 0),
            }
            name = s['name']
            if name in STRATEGY_DESCRIPTIONS:
                desc = STRATEGY_DESCRIPTIONS[name]
                s['display_name'] = desc['name']
                s['description'] = desc['desc']
                s['buy_logic'] = desc['buy_logic']
                s['sell_logic'] = desc['sell_logic']
            strategies.append(s)
        return strategies
    return []

def load_backtest_daily_nav(strategy_name: str) -> List[Dict]:
    """Load daily NAV for a strategy."""
    nav_path = os.path.join(BACKTEST_DIR, f'{strategy_name}_daily_nav.json')
    if os.path.exists(nav_path):
        with open(nav_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    return []

def load_backtest_trades(strategy_name: str) -> List[Dict]:
    """Load trade records for a strategy, normalizing field names."""
    trades_path = os.path.join(BACKTEST_DIR, f'{strategy_name}_trades.json')
    if os.path.exists(trades_path):
        with open(trades_path, 'r', encoding='utf-8') as f:
            raw_trades = json.load(f)
        trades = []
        for t in raw_trades:
            trades.append({
                'date': t.get('date', ''),
                'code': t.get('stock_code', t.get('code', '')),
                'name': t.get('stock_name', t.get('name', '')),
                'side': t.get('action', t.get('side', '')),
                'price': t.get('price', 0),
                'shares': t.get('shares', 0),
                'amount': t.get('amount', 0),
                'pnl': t.get('pnl', 0),
                'return_pct': t.get('pnl_pct', t.get('return_pct', 0)),
                'hold_days': t.get('hold_days', t.get('holding_days', 0)),
                'avg_cost': t.get('avg_cost', 0),
                'commission': t.get('commission', 0),
                'stamp_tax': t.get('stamp_tax', 0),
                'reason': t.get('reason', ''),
            })
        return trades
    return []

@app.route('/api/backtest/ranking')
def api_backtest_ranking():
    """Get backtest ranking overview (v2 优先)."""
    summary, tag, report_kind = load_display_v2_backtest()
    latest_summary, latest_tag = load_latest_v2_backtest()
    if summary:
        strategies = [map_v2_strategy(s) for s in summary.get('strategies', [])]
        strategies = [s for s in strategies if s.get('trade_count', 0) > 0]
        strategies.sort(key=lambda x: x['total_return'], reverse=True)
        td = _max_trading_days(summary)
        note = ''
        if latest_summary and latest_tag != tag:
            ltd = _max_trading_days(latest_summary)
            if ltd < 120:
                note = (
                    f'注意：最近一次快测 {latest_summary.get("start", "")}~'
                    f'{latest_summary.get("end", "")}（{ltd}日）收益偏差大，'
                    f'此处展示训练基准 {summary.get("start", "")}~{summary.get("end", "")}'
                )
        return jsonify({
            'source': 'v2',
            'summary_tag': tag,
            'report_kind': report_kind,
            'display_note': note,
            'generated_at': summary.get('generated_at', ''),
            'backtest_dir': BACKTEST_V2_DIR,
            'strategies': strategies,
            'period': f"{summary.get('start', '')} ~ {summary.get('end', '')}",
            'pool_size': summary.get('pool_size', 0),
            'trading_days': td,
            'initial_capital': 100000,
            'commission': '万1免5',
            'stamp_tax': '千1',
            'rules': summary.get('rules', '训练回测 | 激进模式'),
        })

    strategies = load_backtest_ranking()
    return jsonify({
        'source': 'legacy',
        'backtest_dir': BACKTEST_DIR,
        'strategies': strategies,
        'period': '2025-11-03 ~ 2026-05-25',
        'trading_days': 134,
        'initial_capital': 100000,
        'commission': '万1免5',
        'stamp_tax': '千1',
        'rules': '涨停买不进/跌停卖不出/T+1/硬止损-7%/止盈+15%/移动止盈回撤5%/最大持仓5只/最大持仓天数20天',
    })

@app.route('/api/backtest/<strategy_name>')
def api_backtest_detail(strategy_name):
    """Get detailed backtest data for a specific strategy."""
    summary, tag, _kind = load_display_v2_backtest()
    if summary:
        strat_info = {}
        for s in summary.get('strategies', []):
            if s.get('name') == strategy_name:
                strat_info = map_v2_strategy(s)
                break
        if strat_info:
            daily_nav = load_v2_backtest_nav(strategy_name, tag)
            trades = load_v2_backtest_trades(strategy_name, tag)
            sells = [t for t in trades if t.get('side') == 'sell']
            name_map = load_stock_name_map()
            for t in trades:
                code = str(t.get('code', ''))
                if code in name_map:
                    t['name'] = name_map[code]
            return jsonify({
                'strategy': strat_info,
                'daily_nav': daily_nav,
                'trades': trades,
                'trade_count': len(trades),
                'source': 'v2',
            })

    ranking = load_backtest_ranking()
    strat_info = {}
    for s in ranking:
        if s.get('name') == strategy_name:
            strat_info = s
            break

    if not strat_info:
        return jsonify({'error': f'Strategy {strategy_name} not found'}), 404

    daily_nav = load_backtest_daily_nav(strategy_name)
    trades = load_backtest_trades(strategy_name)

    # Enrich trades with stock names
    name_map = load_stock_name_map()
    for t in trades:
        code = str(t.get('code', ''))
        if not t.get('name') and code in name_map:
            t['name'] = name_map[code]

    return jsonify({
        'strategy': strat_info,
        'daily_nav': daily_nav,
        'trades': trades,
        'trade_count': len(trades),
    })

@app.route('/api/backtest/nav_compare')
def api_backtest_nav_compare():
    """Get NAV data for all strategies (for comparison chart)."""
    summary, tag, _kind = load_display_v2_backtest()
    if summary:
        result = {}
        for s in summary.get('strategies', []):
            name = s.get('name', '')
            nav = load_v2_backtest_nav(name, tag)
            if nav:
                result[name] = {
                    'display_name': s.get('display_name', name),
                    'dates': [d['date'] for d in nav],
                    'values': [d['total_value'] for d in nav],
                    'returns': [d['return_pct'] for d in nav],
                }
        return jsonify(result)

    ranking = load_backtest_ranking()
    result = {}
    for s in ranking:
        name = s.get('name', '')
        nav = load_backtest_daily_nav(name)
        if nav:
            result[name] = {
                'display_name': s.get('display_name', name),
                'dates': [d['date'] for d in nav],
                'values': [d['total_value'] for d in nav],
                'returns': [d['return_pct'] for d in nav],
            }
    return jsonify(result)


# ---- Scheduler & Task Runner API ----

@app.route('/api/scheduler/status')
def api_scheduler_status():
    """Cron 自动任务状态 + 最近日志"""
    try:
        from scheduler_status import get_scheduler_status
        return jsonify(get_scheduler_status())
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/tasks')
def api_tasks_list():
    """最近后台任务列表"""
    from task_runner import list_tasks, TASK_LABELS
    limit = request.args.get('limit', 15, type=int)
    return jsonify({
        'tasks': list_tasks(limit),
        'available': [{'type': k, 'label': v} for k, v in TASK_LABELS.items()],
    })


@app.route('/api/tasks/<task_id>')
def api_task_detail(task_id):
    from task_runner import get_task
    task = get_task(task_id)
    if not task:
        return jsonify({'error': '任务不存在'}), 404
    return jsonify(task)


@app.route('/api/tasks/run', methods=['POST'])
def api_task_run():
    """触发后台任务: backtest_v2 / daily_picker / daily_sell / update_kline"""
    from task_runner import submit_task
    body = request.get_json(silent=True) or {}
    task_type = body.get('type', '')
    params = body.get('params', {})
    result = submit_task(task_type, params)
    if not result.get('ok'):
        return jsonify(result), 409
    return jsonify(result)


# ---- Paper Trading v2 API ----

@app.route('/api/v2/paper/ranking')
def api_paper_ranking():
    """5 策略纸面账户排名"""
    try:
        from paper_trading_v2 import init_paper_accounts, build_paper_ranking
        init_paper_accounts()
        strategies = build_paper_ranking()
        return jsonify({
            'strategies': strategies,
            'initial_capital': 100000,
            'updated_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        })
    except Exception as e:
        return jsonify({'error': str(e), 'strategies': []}), 500


@app.route('/api/v2/paper/overview')
def api_paper_overview():
    """纸面净值时序 (各策略 + 组合参考)"""
    try:
        from paper_trading_v2 import load_nav_history, get_strategy_list
        history = load_nav_history(120)
        dates = [h.get('date') for h in history]
        series = {}
        for sid, dname in get_strategy_list().items():
            series[sid] = {'display_name': dname, 'values': [], 'returns': []}
        composite = {'display_name': '组合账户', 'values': [], 'returns': []}
        for h in history:
            for sid in series:
                info = h.get('strategies', {}).get(sid, {})
                series[sid]['values'].append(info.get('value', 100000))
                series[sid]['returns'].append(info.get('return_pct', 0))
            cref = h.get('composite_ref') or {}
            composite['values'].append(cref.get('value', 100000))
            composite['returns'].append(cref.get('return_pct', 0))
        return jsonify({'dates': dates, 'series': series, 'composite': composite})
    except Exception as e:
        return jsonify({'error': str(e), 'dates': [], 'series': {}}), 500


@app.route('/api/v2/paper/<strategy_id>')
def api_paper_detail(strategy_id):
    """单策略纸面详情"""
    try:
        from paper_trading_v2 import compute_paper_stats, get_strategy_list
        if strategy_id not in get_strategy_list():
            return jsonify({'error': '策略不存在'}), 404
        stats = compute_paper_stats(strategy_id)
        trades = []
        log_path = os.path.join(BASE_DIR, 'account', 'paper', f'{strategy_id}_trades.json')
        if os.path.exists(log_path):
            with open(log_path, 'r', encoding='utf-8') as f:
                trades = json.load(f)
        return jsonify({'strategy': stats, 'trades': trades[-100:]})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/v2/arena/compare')
def api_arena_compare():
    """纸面 vs 回测并排对比"""
    paper = []
    backtest = []
    try:
        from paper_trading_v2 import init_paper_accounts, build_paper_ranking
        init_paper_accounts()
        paper = build_paper_ranking()
    except Exception:
        pass
    summary, _tag, _kind = load_display_v2_backtest()
    if summary:
        backtest = [map_v2_strategy(s) for s in summary.get('strategies', [])]
    bt_map = {s['name']: s for s in backtest}
    rows = []
    names = set([p['name'] for p in paper] + list(bt_map.keys()))
    for name in sorted(names):
        p = next((x for x in paper if x['name'] == name), {})
        b = bt_map.get(name, {})
        if name == 'composite':
            continue
        rows.append({
            'name': name,
            'display_name': p.get('display_name') or b.get('display_name', name),
            'paper_return': p.get('return_pct', 0),
            'paper_equity': p.get('equity', 100000),
            'paper_trades': p.get('total_trades', 0),
            'paper_win_rate': p.get('win_rate', 0),
            'backtest_return': b.get('total_return', 0),
            'backtest_sharpe': b.get('sharpe_ratio', 0),
            'backtest_trades': b.get('trade_count', 0),
            'gap': round(p.get('return_pct', 0) - b.get('total_return', 0), 2),
        })
    rows.sort(key=lambda x: x.get('paper_return', 0), reverse=True)
    return jsonify({'rows': rows, 'paper_count': len(paper), 'backtest_count': len(backtest)})


@app.route('/api/memory/signals')
def api_memory_signals():
    """Get trading signal history from memory DB."""
    days = request.args.get('days', 30, type=int)
    strategy = request.args.get('strategy', '')
    signal_type = request.args.get('type', '')  # buy/sell
    try:
        from core.memory import TradingMemory
        mem = TradingMemory(db_path=os.path.join(BASE_DIR, 'knowledge_base', 'trading_memory.db'))
        signals = mem.query_signals(days=days)
        if strategy:
            signals = [s for s in signals if s.get('strategy') == strategy]
        if signal_type:
            signals = [s for s in signals if s.get('signal') == signal_type]
        signals.sort(key=lambda x: x.get('created_at', ''), reverse=True)
        return jsonify({
            'total': len(signals),
            'signals': signals[:100]
        })
    except Exception as e:
        return jsonify({'error': str(e), 'total': 0, 'signals': []})


@app.route('/api/memory/market')
def api_memory_market():
    """Get market state history."""
    days = request.args.get('days', 30, type=int)
    try:
        from core.memory import TradingMemory
        mem = TradingMemory(db_path=os.path.join(BASE_DIR, 'knowledge_base', 'trading_memory.db'))
        history = mem.get_market_history(days=days)
        # Build time series for chart
        chart = []
        sentiment_dist = {'bullish': 0, 'bearish': 0, 'neutral': 0}
        for h in history:
            chart.append({
                'date': h.get('date', ''),
                'sh_index': h.get('sh_index', 0),
                'sh_change_pct': h.get('sh_change_pct', 0),
                'hs300': h.get('hs300', 0),
                'hs300_change_pct': h.get('hs300_change_pct', 0),
                'cyb': h.get('cyb', 0),
                'cyb_change_pct': h.get('cyb_change_pct', 0),
                'sentiment': h.get('sentiment', 'neutral')
            })
            sent = h.get('sentiment', 'neutral')
            sentiment_dist[sent] = sentiment_dist.get(sent, 0) + 1
        return jsonify({
            'history': chart,
            'sentiment_dist': sentiment_dist,
            'total': len(chart)
        })
    except Exception as e:
        return jsonify({'error': str(e), 'history': [], 'sentiment_dist': {}, 'total': 0})


@app.route('/api/memory/strategy')
def api_memory_strategy():
    """Get strategy performance comparison."""
    days = request.args.get('days', 90, type=int)
    try:
        from core.memory import TradingMemory
        mem = TradingMemory(db_path=os.path.join(BASE_DIR, 'knowledge_base', 'trading_memory.db'))
        comparison = mem.get_strategy_comparison(days=days)
        summary = mem.get_memory_summary()
        return jsonify({
            'strategies': comparison,
            'summary': summary
        })
    except Exception as e:
        return jsonify({'error': str(e), 'strategies': [], 'summary': {}})


@app.route('/api/memory/lessons')
def api_memory_lessons():
    """Get lessons learned."""
    days = request.args.get('days', 30, type=int)
    lesson_type = request.args.get('type', '')
    try:
        from core.memory import TradingMemory
        mem = TradingMemory(db_path=os.path.join(BASE_DIR, 'knowledge_base', 'trading_memory.db'))
        lessons = mem.get_lessons(days=days)
        if lesson_type:
            lessons = [l for l in lessons if l.get('lesson_type') == lesson_type]
        lessons.sort(key=lambda x: x.get('created_at', ''), reverse=True)
        return jsonify({
            'total': len(lessons),
            'lessons': lessons[:50]
        })
    except Exception as e:
        return jsonify({'error': str(e), 'total': 0, 'lessons': []})


@app.route('/api/memory/patterns')
def api_memory_patterns():
    """Get pattern insights for a specific stock."""
    code = request.args.get('code', '')
    days = request.args.get('days', 90, type=int)
    try:
        from core.memory import TradingMemory
        mem = TradingMemory(db_path=os.path.join(BASE_DIR, 'knowledge_base', 'trading_memory.db'))
        if code:
            insights = mem.get_pattern_insights(code=code, days=days)
            return jsonify({'code': code, 'patterns': insights})
        else:
            # Return top patterns across all stocks
            return jsonify({'code': '', 'patterns': []})
    except Exception as e:
        return jsonify({'error': str(e), 'patterns': []})


@app.route('/api/memory/stock/<code>')
def api_memory_stock(code):
    """Get memory for a specific stock."""
    days = request.args.get('days', 90, type=int)
    try:
        from core.memory import TradingMemory
        mem = TradingMemory(db_path=os.path.join(BASE_DIR, 'knowledge_base', 'trading_memory.db'))
        history = mem.get_stock_history(code, days=days)
        signals = mem.query_signals(code=code, days=days)
        return jsonify({
            'code': code,
            'history': history,
            'signals': signals,
            'total_signals': len(signals),
            'total_events': len(history)
        })
    except Exception as e:
        return jsonify({'error': str(e), 'history': [], 'signals': []})


if __name__ == '__main__':
    print("=" * 60)
    print("  A股量化选股 Dashboard")
    print("=" * 60)
    print(f"  Access: http://localhost:5890")
    print("=" * 60)
    app.run(host='0.0.0.0', port=5890, debug=False)
