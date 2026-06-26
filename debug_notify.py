import json, traceback

with open('knowledge_base/boss_report_2026-05-21.json') as f:
    report = json.load(f)

# Check ALL reasons fields
for ar in report.get('agent_reports', []):
    name = ar.get('agent_name', '')
    for sig in ar.get('top_5_signals', []):
        reasons = sig.get('reasons', [])
        if not isinstance(reasons, list):
            print(f"NOT-A-LIST reasons: Agent={name} code={sig.get('code','')} type={type(reasons).__name__} val={repr(reasons)[:100]}")
        elif len(reasons) > 0:
            for i, r in enumerate(reasons):
                if not isinstance(r, str):
                    print(f"NON-STR REASON: Agent={name} code={sig.get('code','')} idx={i} type={type(r).__name__} val={repr(r)[:100]}")

# Now try the exact _send_feishu_notification build
try:
    from feishu_notify import send_message, USER_OPEN_ID
except:
    pass

msg_lines = []
date = report.get('date', '')
equity = report.get('total_equity', 0)
ret = report.get('total_return_pct', 0)

msg_lines.append(f"A股量化日报 {date}")
msg_lines.append("")
msg_lines.append(f"总资金: {equity:,.0f} ({ret:+.2f}%)")

# Section 1 - buys
today_buys = []
for ar in report.get('agent_reports', []):
    agent_name = ar.get('agent_name', '')
    for t in ar.get('trades', []):
        msg = t.get('message', '')
        if msg.startswith('Bought'):
            today_buys.append({'agent': agent_name, 'trade': t, 'signals': ar.get('top_5_signals', [])})

if today_buys:
    msg_lines.append("")
    msg_lines.append("今日买入推荐:")
    for item in today_buys:
        t = item['trade']
        code = t.get('code', '')
        name = t.get('name', '')
        price = t.get('price', 0)
        shares = t.get('shares', 0)
        cost = t.get('cost', price * shares)
        agent = item['agent']
        reasons = []
        for sig in item['signals']:
            sig_code = sig.get('code', sig.get('stock_code', ''))
            if sig_code == code:
                reasons = sig.get('reasons', [])
                break
        reason_text = '; '.join(reasons[:2]) if reasons else '策略自动选股'
        msg_lines.append(f"  [{agent}] {code} {name} {price:.2f} {shares}股 {cost:,.0f} 理由: {reason_text}")

# Section 2 - agent ranking
msg_lines.append("")
msg_lines.append("Agent收益排名:")
all_agents = sorted(report.get('agent_reports', []), key=lambda x: x.get('return_pct', 0) or 0, reverse=True)
for i, a in enumerate(all_agents, 1):
    name = a.get('agent_name', '')
    eq = a.get('equity', 100000) or 100000
    r = a.get('return_pct', 0) or 0
    pos = a.get('positions', 0) or len(a.get('positions', {}))
    medal = ['1', '2', '3'][i-1] if i <= 3 else f"{i:>2}."
    emoji = "GREEN" if r > 0 else ("RED" if r < 0 else "GRAY")
    msg_lines.append(f"  {medal} {name} {emoji} {r:+.2f}% | {eq:,.0f} | 持仓{pos}")

# Section 3 - top signals (THIS IS WHERE IT CRASHES)
msg_lines.append("")
msg_lines.append("各Agent Top选股:")
for ar in report.get('agent_reports', [])[:6]:
    name = ar.get('agent_name', '')
    top5 = ar.get('top_5_signals', [])[:3]
    if top5:
        picks = []
        for sig in top5:
            code = sig.get('code', sig.get('stock_code', ''))
            name_sig = sig.get('name', '')
            score_val = sig.get('total_score', sig.get('score', 0))
            if isinstance(score_val, (int, float)) and score_val != score_val:
                score_val = 0
            reasons = sig.get('reasons', [])
            reason_short = reasons[0] if reasons else ''
            print(f"DEBUG: Agent={name} code={code} reason_short type={type(reason_short).__name__} val={repr(reason_short)[:60]}")
            try:
                if isinstance(reason_short, str):
                    reason_short = reason_short[:30]
                else:
                    reason_short = str(reason_short)[:30]
            except Exception as e:
                print(f"SLICE ERROR: {e} on {repr(reason_short)[:60]}")
            picks.append(f"{code}{name_sig}({score_val:.0f}){reason_short}".rstrip())
        msg_lines.append(f"  [{name}] {' | '.join(picks)}")

# Section 4 - consensus
consensus = report.get('consensus_holdings', [])[:5]
if consensus:
    msg_lines.append("")
    msg_lines.append("共识持仓:")
    for h in consensus:
        agents_count = len(h.get('agents', []))
        agent_names = ', '.join(h.get('agents', [])[:3])
        msg_lines.append(f"  {h.get('code', '')} ({h.get('name', '')}) - {agents_count}个Agent({agent_names})")

# Section 5 - hot sectors
import re
msg_lines.append("")
msg_lines.append("热门板块:")
for s in report.get('hot_sectors', [])[:3]:
    sector = re.sub(r'^[A-Z]+\d+', '', s.get('sector', ''))
    score = s.get('hot_score', s.get('score', 0))
    msg_lines.append(f"  {sector}: {score:.2f}")

# Section 6 - indices
indices = report.get('index_quotes', [])
if indices:
    msg_lines.append("")
    msg_lines.append("指数行情:")
    for ix in indices:
        name = ix.get('name', '')
        close = ix.get('close', 0)
        chg = ix.get('change_pct', 0)
        msg_lines.append(f"  {name}: {close:.2f} ({chg:+.2f}%)")

rt = report.get('realtime_market', {})
if rt:
    msg_lines.append("")
    msg_lines.append(f"市场: 涨{rt.get('up', 0)}/跌{rt.get('down', 0)}/平{rt.get('flat', 0)}")

msg = '\n'.join(msg_lines)
print(f"\nMessage built OK, length={len(msg)}")

# Now try sending
print("\n--- Attempting to send ---")
try:
    ok = send_message(USER_OPEN_ID, msg)
    print(f"Send result: {ok}")
except Exception as e:
    traceback.print_exc()
