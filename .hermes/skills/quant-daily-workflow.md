# Quant Trading Daily Workflow Skill

Trigger: User asks about running quant trading pipeline, stock selection, or daily reports for A-share quant system.

## Quick Commands

```bash
cd /disk2/workingFolder/quant

# Run full daily pipeline (stock selection + trades + feishu notification)
python boss_agent.py

# Run specific agent only
python -c "from agents.trend_hunter import TrendHunterAgent; a=TrendHunterAgent(); print(a.run('2026-05-25'))"

# Check account status
python main.py status

# View stock picks from latest report
python -c "import json; r=json.load(open('knowledge_base/boss_report_2026-05-25.json')); [print(f\"{p['code']} {p['name']} score={p['score']}\") for p in r.get('ai_stock_picks',[])]"

# Update K-line data (use sina API - BaoStock is deprecated)
python update_kline_sina.py --workers 3
```

## System Architecture

- 10 strategy agents, each with 100k virtual capital
- Boss agent orchestrates: data loading -> agent analysis -> optimization -> stock picks -> feishu notification
- Trading rules: 0.01% commission (免5), 0.1% stamp tax, max 5 positions, 20% per stock
- Stop loss: -7%, Take profit: +15%, Trailing stop: 5% drawdown, Max holding: 20 days
- Exclusions: 科创板 (688/689), 北交所 (8/4开头), ST stocks, <60 days listed

## Key Files

| File | Purpose |
|------|---------|
| boss_agent.py | Main orchestrator - run this for daily pipeline |
| daily_pipeline.py | Alternative pipeline (no __main__ entry) |
| agents/*.py | 10 strategy agents |
| sina_fetcher.py | Real-time + historical data via Sina API |
| feishu_notify.py | Feishu notification handler |
| trade_engine.py | Virtual trade execution engine |
| boss_optimizer.py | Agent weight optimization |
| dashboard/app.py | Flask dashboard (port 5890) |

## Data Sources

- Sina API (primary): Real-time quotes + historical k-line
- BaoStock (deprecated): Fallback only, often fails
- Local cache: data/kline/*.csv (1039 stocks)

## Feishu Integration

- User Open ID: ou_a2efb39c91ba979f60362822cac05669
- App ID: cli_a9476578e2b95bd3
- Sends: Interactive card (stock picks) + text daily report

## Cron Schedule (recommended)

| Time | Task |
|------|------|
| 08:30 | Pre-market: python boss_agent.py |
| 14:30 | Intra-day monitoring |
| 15:10 | Post-market report |
| Friday 20:00 | Weekly optimization |
