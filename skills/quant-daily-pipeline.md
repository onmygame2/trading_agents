---
name: quant-daily-pipeline
description: A股量化选股每日流水线 — 数据更新、选股运行、报告生成、cron 调度、故障排查
---

# A股量化选股每日流水线

完整的 daily pipeline 运行、调度和维护指南。

## System Overview

```
data/kline/*.csv (1040 stocks, BaoStock日线)
    ↓ load_all()
daily_runner.py (5策略: trend/mean_reversion/momentum/multi_factor/oversold)
    ↓ buy/sell signals
knowledge_base/daily_YYYYMMDD.json + daily_report_YYYYMMDD.txt
    ↓
account/account_state.json (虚拟账户状态)
    ↓
dashboard (Flask :5890, 读取 knowledge_base/ + account/)
```

- Python 3.8 + venv_akshare (Python 3.11, AKShare)
- 数据源: BaoStock 日线 (data/kline/) + 新浪 API 实时行情
- 5 策略, 权重: trend(1.0), mean_reversion(0.8), momentum(0.9), multi_factor(1.0), oversold(0.8)
- 虚拟账户: 10 万, 万 1 免 5, 0.1% 印花税
- 排除: 科创板 (688/689), 北交所 (8/4 开头), ST, 上市 <60 天

## Daily Workflow

### 1. Update K-line data (盘前, ~08:30)

Update daily kline data to latest trading day using Sina API:

```bash
cd /disk2/workingFolder/quant
python update_kline_sina.py
```

This updates all stocks in data/kline/ with latest trading day data.
Each CSV: date,stock_code,open,high,low,close,volume,amount,change_pct,turnover

### 2. Run daily stock selection (盘前, ~08:40)

```bash
cd /disk2/workingFolder/quant
python daily_runner.py --date YYYY-MM-DD
```

Or use the most recent data:

```bash
python daily_runner.py
```

What it does:
1. Loads all stock data from data/kline/ (via HistoricalDataLoader)
2. Filters: stocks with >= 30 data points, valid date column
3. Runs 5 strategies via StrategyManager:
   - TrendFollowingStrategy (weight 1.0)
   - MeanReversionStrategy (weight 0.8)
   - MomentumBreakoutStrategy (weight 0.9)
   - MultiFactorStrategy (weight 1.0)
   - OversoldBounceStrategy (weight 0.8)
4. Generates sell signals first, then buy signals
5. Saves results to knowledge_base/

Output files:
- `knowledge_base/daily_YYYYMMDD.json` — full structured data
- `knowledge_base/daily_report_YYYYMMDD.txt` — human-readable report
- `account/account_state.json` — updated account state

### 3. Run AI market analysis (optional)

```bash
python ai_analyzer.py
```

This collects market overview (indices, sectors, capital flow) and generates AI sentiment analysis.

### 4. Verify Dashboard

Dashboard reads from knowledge_base/ and account/ directories.
After running the pipeline, verify at http://localhost:5890:

```bash
# Quick check
curl -s http://localhost:5890/api/picks | python -m json.tool | head -5
curl -s http://localhost:5890/api/summary | python -m json.tool | head -5
```

## Cron Jobs

Check existing cron jobs:

```bash
# List all cron jobs
~/.hermes/bin/hermes cron list
```

Expected schedule:
- 08:30 — update kline data
- 08:40 — run daily pipeline + AI analysis
- 09:30–15:00 — intraday monitoring (every 30 min)
- 15:10 — post-market review

To create a cron job for daily pipeline:

```bash
# Example: run daily at 08:30
~/.hermes/bin/hermes cron add --name "update-kline" --schedule "30 8 * * 1-5" \
  "cd /disk2/workingFolder/quant && python update_kline_sina.py"

~/.hermes/bin/hermes cron add --name "daily-pipeline" --schedule "40 8 * * 1-5" \
  "cd /disk2/workingFolder/quant && python daily_runner.py"
```

## Key Files

| File | Purpose |
|------|---------|
| daily_runner.py | Main pipeline: load data → run 5 strategies → save results |
| update_kline_sina.py | Update daily kline data via Sina API |
| ai_analyzer.py | AI market sentiment analysis |
| strategies/ | 5 strategy implementations |
| strategies/manager.py | StrategyManager: merge/dedup signals |
| historical_loader.py | HistoricalDataLoader: load CSV kline data |
| account/account_state.json | Virtual account state |
| knowledge_base/ | Daily JSON + TXT reports |
| data/kline/*.csv | Daily kline data per stock (1040 files) |

## Troubleshooting

| Symptom | Check | Fix |
|---------|-------|-----|
| "没有可用的股票数据" | ls data/kline/ is empty or files are stale | Run `python update_kline_sina.py` |
| 0 buy signals | Market conditions don't meet any strategy threshold | Normal — happens in bearish markets |
| ImportError | Wrong Python environment | Use system Python 3.8 or `source venv_akshare/bin/activate` for AKShare tasks |
| Dashboard shows old data | Pipeline not re-run after data update | Run `python daily_runner.py` |
| Sina API timeout | Network issue | Retry — Sina API is usually reliable without proxy |
| ModuleNotFoundError: akshare | akshare installed in venv, not system | Use `source venv_akshare/bin/activate` first |
| Strategy returns NaN | Stock has too few data points (< 30) | Update kline data to ensure sufficient history |

## Account Rules

- Initial cash: 100,000 RMB
- Commission: 0.01% (no minimum, both sides)
- Stamp duty: 0.1% (sell only)
- Max positions: 5
- Max single position: 20%
- Hard stop loss: -7%
- Take profit: +15%
- Trailing stop: 5% from peak
- Max holding days: 20 trading days