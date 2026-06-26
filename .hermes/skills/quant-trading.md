# A股中低频量化交易系统 - Skill

Trigger: User asks about A-share quant trading, strategy backtesting, stock selection, portfolio management, daily workflow, or dashboard for the system at `/disk2/workingFolder/quant`.

## 1. System Overview

A daily-frequency (中低频) quantitative trading system for China A-shares. It runs 10 independent strategy agents, each with its own virtual account of 100k RMB. A Boss Agent orchestrates the full pipeline: data update -> strategy scan -> trade execution -> optimization -> reporting.

**Key characteristics:**
- **Frequency**: Daily (日频) — signals generated once per trading day
- **Account**: Virtual (虚拟盘), no real money involved
- **Capital**: 100,000 RMB per strategy account
- **Strategies**: 10 strategy agents, each independent with own capital and positions
- **Data sources**: BaoStock (historical K-line download) + Sina API (real-time quotes + K-line update)
- **Python env**: System Python 3.8 + `venv_akshare` (Python 3.11)
- **No Feishu**: All communication via chat, no Lark/Feishu integration

## 2. Directory Structure

```
/disk2/workingFolder/quant/
├── main.py                  # CLI entry: download, backtest, scan, report, rank, status, boss, monitor
├── backtest.py              # Event-driven backtest engine (T+1, limit-up/down support)
├── trade_engine.py          # Virtual trade execution: buy/sell, PnL, position management
├── boss_agent.py            # Boss Agent orchestrator (multi-agent independent accounts)
├── daily_pipeline.py        # Daily trading pipeline (old single-account mode)
├── strategies_runner.py     # Multi-strategy runner for backtest & scan
├── historical_loader.py     # BaoStock data loader (batch download K-line)
├── baostock_fetcher.py      # BaoStock API wrapper
├── update_kline_sina.py     # Sina API K-line updater
├── optimizer.py             # Strategy weight optimizer
├── boss_optimizer.py        # Boss-level optimizer state
├── monitor.py               # Full-day market monitor
├── feishu_notify.py         # Feishu notification (not used)
├── config/
│   └── settings.yaml        # All configuration: account, strategies, market rules
├── strategies/
│   ├── base.py              # StrategyBase: indicators, scoring framework
│   ├── manager.py           # Strategy manager
│   ├── selector.py          # Stock selector
│   ├── trend_following.py   # 趋势跟踪策略
│   ├── momentum_breakout.py # 动量突破策略
│   ├── multi_factor.py      # 多因子综合策略
│   ├── mean_reversion.py    # 均值回归策略
│   └── oversold_bounce.py   # 超跌反弹策略
├── dashboard/
│   ├── app.py               # Flask web dashboard (port 5890)
│   └── templates/
│       └── index.html       # SPA frontend
├── data/
│   ├── kline/               # Cached daily K-line CSVs
│   ├── minute_kline/        # 5min/15min/30min K-line JSONs
│   ├── fundamentals/        # Financial fundamentals JSONs
│   ├── news/                # Daily news JSONs
│   ├── sentiment/           # Market sentiment snapshots
│   └── stock_pool.json      # Stock pool manifest
├── state/                   # Agent state files (*_state.json)
├── knowledge_base/          # Boss reports (boss_report_*.json)
├── reports/                 # Backtest & selection reports
├── boss_optimizer/          # Optimizer state
└── ashare_repo/             # Ashare data source (Sina/Tencent fallback)
```

## 3. Strategy Descriptions (5 Core Strategies)

### 3.1 trend_following — 趋势跟踪
- **Logic**: MA bullish alignment (MA5 > MA10 > MA20), MACD golden cross with expanding histogram, price above 20-day MA, volume confirmation
- **Scoring**: MA alignment (30pts), MACD golden cross (25pts), price above MA20 (20pts), volume surge (25pts)
- **Best for**: Unilateral trending markets, chase trend but not overbought
- **Threshold**: Score >= 60 to trigger buy signal

### 3.2 momentum_breakout — 动量突破
- **Logic**: Price breaks N-day high (20/60 day), significant volume expansion (>2x average), strong short-term momentum (5-day gain 3%-15%)
- **Scoring**: 20-day breakout (35pts), 60-day breakout (15pts), volume surge (25pts), short-term momentum (25pts)
- **Best for**: Strong bull markets, chasing breakout leaders
- **Threshold**: Score >= 55 to trigger buy signal

### 3.3 multi_factor — 多因子综合
- **Logic**: 5-dimension composite scoring — Technical (30%), Volume (20%), Value (15%), Volatility (15%), Momentum (20%)
- **Scoring**: Each dimension scored independently, then weighted sum. Includes MA system, MACD, RSI, volume ratio, PE/PB percentile, ATR volatility, price momentum
- **Best for**: All-market conditions, steady risk-adjusted returns
- **Threshold**: Composite score >= 65 to trigger buy signal

### 3.4 mean_reversion — 均值回归
- **Logic**: RSI oversold (<30) or price touches Bollinger lower band, price far below 20-day MA (>2 std dev), volume contraction then expansion (bottom volume surge), volatility contraction breakout
- **Scoring**: RSI oversold (30pts), Bollinger lower band (25pts), volume bottom surge (25pts), mean reversion distance (20pts)
- **Best for**: Range-bound markets, bottom-fishing rebounds
- **Threshold**: Score >= 55 to trigger buy signal

### 3.5 oversold_bounce — 超跌反弹
- **Logic**: RSI < 30 extreme oversold, price at Bollinger lower band, bottom volume surge (selling pressure released), KDJ low-level golden cross, short-term drop >15%
- **Scoring**: RSI oversold (30pts), Bollinger lower band (20pts), bottom volume (20pts), short-term drop depth (20pts), bounce confirmation (10pts)
- **Best for**: Fast bounce after extreme oversold conditions
- **Threshold**: Score >= 50 to trigger buy signal

### Additional strategies in config (enabled but not core):
- `closing_strategy`: 尾盘抢筹 + 强势收盘 + 次日惯性上冲
- `dragon_return`: 龙回头：强势股回调 + 缩量企稳 + 支撑位反弹
- `grid_trading`: 低吸网格：布林带下轨 + 均线支撑 + 低波动收缩
- `sector_rotation`: 板块轮动：热点板块 + 动量领先 + 放量突破
- `volume_price`: 量价共振：放量突破 + 量价齐升 + MACD配合

## 4. Trading Rules

| Rule | Value |
|------|-------|
| Initial capital | 100,000 RMB |
| Commission rate | 0.01% (万分之一), no minimum fee (免5) |
| Stamp tax | 0.1% (卖出千分之一, buy exempt) |
| Max holdings | 5 stocks per account |
| Position size | 20% per stock (max) |
| Stop loss | -7% from entry |
| Take profit | +15% from entry |
| Trailing stop | 5% drawdown from peak |
| Min holding period | 3 trading days |
| Max holding period | 20 trading days |
| Trade settlement | T+1 (buy today, sell tomorrow) |
| Limit up/down | 主板 ±10%, 创业板/科创板 ±20% |
| Limit up rule | Cannot buy at limit-up price |

## 5. Exclusion Rules

Stocks are excluded from the trading pool if:

| Rule | Details |
|------|---------|
| 科创板 | Codes starting with 688 or 689 |
| 北交所 | Codes starting with 8 or 4 |
| ST stocks | Stock name contains "ST", "*ST", or "S" |
| New listings | Listed < 60 trading days |

**Included prefixes**: 600, 601, 603, 605 (Shanghai main), 000, 001, 002, 003 (Shenzhen main), 300, 301 (ChiNext/GEM)

## 6. Common Commands

All commands run from `/disk2/workingFolder/quant`.

### 6.1 Activate Python Environment

```bash
cd /disk2/workingFolder/quant
source venv_akshare/bin/activate   # Python 3.11 env with all dependencies
```

### 6.2 Data Download

```bash
# Download top N stocks (default full pool from BaoStock)
python main.py download --top 100 --start 2024-01-01 --end 2026-05-27

# Download ALL stocks in pool
python main.py download-all --start 2024-01-01 --end 2026-05-27

# Force re-download (skip cache)
python main.py download --top 50 --force

# Adjust request delay (default 0.5s) to avoid rate limiting
python main.py download --top 100 --delay 1.0

# Update K-line via Sina API (faster, recommended)
python update_kline_sina.py --workers 3
```

### 6.3 Backtest

```bash
# Multi-strategy backtest (all enabled strategies, top 300 stocks)
python main.py backtest --start 2024-01-01 --end 2026-05-27

# Multi-strategy backtest with specific stock count
python main.py backtest --start 2024-06-01 --end 2026-05-27 --top-n 500

# Single strategy backtest
python main.py backtest-single trend_following --start 2024-01-01 --end 2026-05-27

# Available strategies for backtest-single:
#   trend_following | mean_reversion | momentum_breakout | multi_factor | oversold_bounce
```

Reports are saved to `reports/multi_backtest_YYYYMMDD_HHMMSS.*`

### 6.4 Stock Selection (Scan)

```bash
# 10-strategy joint scan (returns top 10)
python main.py scan --top 10

# Scan for specific date
python main.py scan --top 15 --date 2026-05-27

# Generate daily report (index overview + stock picks)
python main.py report
```

Selection reports saved to `reports/selection_YYYYMMDD.json`

### 6.5 Dashboard (Web UI)

```bash
# Start dashboard
python dashboard/app.py

# Access in browser
# http://localhost:5890

# Dashboard features:
# - Portfolio overview with 10s auto-refresh
# - Agent detail: positions, equity curve, trade history
# - Stock detail: candlestick chart (1d/1w/1M), minute chart (5m/15m/30m/60m)
# - Real-time prices via Sina API
```

### 6.6 Status & Ranking

```bash
# System status overview (data count, strategies, reports)
python main.py status

# View latest strategy ranking from backtest
python main.py rank
```

### 6.7 Trading Pipeline

```bash
# Boss Agent: multi-agent independent account mode (recommended)
python main.py boss

# Boss Agent for specific date
python main.py boss --date 2026-05-27

# Old single-account mode (legacy)
python main.py run --date 2026-05-27

# Execute trades (selection + buy/sell + review)
python main.py trade --date 2026-05-27

# Weekly optimization (strategy weights + parameters)
python main.py optimize
```

### 6.8 Monitor

```bash
# Start full-day monitoring (background)
python main.py monitor run

# Morning pre-market scan
python main.py monitor morning

# Intra-day check
python main.py monitor check

# Post-market review
python main.py monitor review

# Monitor status
python main.py monitor status
```

## 7. Daily Workflow

### Pre-market (08:30 - 09:15)

```
1. Activate environment
   cd /disk2/workingFolder/quant && source venv_akshare/bin/activate

2. Update K-line data
   python update_kline_sina.py --workers 3

3. Run daily pipeline (Boss Agent)
   python main.py boss

4. Review scan results
   python main.py scan --top 10
   python main.py report
```

### Market hours (09:30 - 15:00)

```
1. Monitor positions
   python main.py monitor check

2. Watch dashboard for real-time PnL
   # http://localhost:5890
```

### Post-market (15:00 - 15:30)

```
1. Post-market review
   python main.py monitor review

2. Check daily report
   cat knowledge_base/boss_report_$(date +%Y-%m-%d).json

3. Update state
   python main.py status
```

### Weekly (Friday 20:00)

```
1. Run backtest on recent data
   python main.py backtest --start 2025-01-01 --end $(date +%Y-%m-%d)

2. Review strategy ranking
   python main.py rank

3. Optimize strategy weights
   python main.py optimize
```

## 8. Configuration File

`config/settings.yaml` is the single source of truth. Key sections:

```yaml
account:
  commission_rate: 0.0001    # 万分之一
  initial_cash: 100000       # 初始资金
  min_commission: 0          # 免5
  stamp_tax: 0.001           # 卖出千分之一

strategy:
  max_holdings: 5            # 最大持仓
  position_size_pct: 0.2     # 单只仓位
  stop_loss: -0.07           # 止损
  take_profit: 0.15          # 止盈
  trailing_stop: 0.05        # 回撤止盈
  max_holding_days: 20       # 最长持仓

market:
  exclude_prefixes: ['688', '689', '8', '4']
  exclude_st: true
  min_listing_days: 60

backtest:
  start_date: '2024-01-01'
  lookback_days: 120
  report_dir: reports
```

## 9. Troubleshooting

### Data download fails

```
Problem: BaoStock returns empty data or connection timeout
Solution:
  1. Check network: ping baostock.com
  2. Use Sina API instead: python update_kline_sina.py --workers 3
  3. Increase delay: python main.py download --delay 2.0
  4. Check if BaoStock requires login: verify historical_loader.py login()
```

### Backtest shows no data

```
Problem: "没有历史数据! 请先运行: python main.py download"
Solution:
  1. Run download first: python main.py download --top 300
  2. Check data directory: ls data/kline/ | wc -l
  3. Check stock_pool.json exists: cat data/stock_pool.json | python -m json.tool | head
  4. Verify data date range matches backtest --start/--end
```

### Dashboard won't start

```
Problem: Port 5890 already in use or Flask import error
Solution:
  1. Kill existing: lsof -i :5890 && kill -9 <PID>
  2. Check dependencies: pip install flask pandas numpy
  3. Start with debug: python dashboard/app.py 2>&1 | head -50
  4. Try different port: edit dashboard/app.py line with app.run(port=5890)
```

### Strategy returns no signals

```
Problem: Scan returns empty or very few stocks
Solution:
  1. Check data freshness: python main.py status
  2. Verify enough data points: each strategy needs 30-120 days of data
  3. Lower scoring threshold in strategy code (e.g., 55 -> 45)
  4. Check excluded stocks filter: verify stock_pool.json doesn't filter too aggressively
  5. Ensure current_date matches latest data date
```

### Trade execution blocked by limit-up

```
Problem: "涨停无法买入" in trade log
Solution:
  This is intentional — system cannot buy at limit-up price.
  The stock will be skipped for today. Check again tomorrow.
  This is correct A-share trading behavior simulation.
```

### Stale data / old reports

```
Problem: Dashboard shows old data
Solution:
  1. Clear Flask cache: restart dashboard (python dashboard/app.py)
  2. Force data refresh: python update_kline_sina.py --workers 3 --force
  3. Delete old reports: rm reports/selection_*.json (regenerate with python main.py report)
```

### Python environment issues

```
Problem: ModuleNotFoundError or version conflict
Solution:
  1. Always use venv_akshare: source venv_akshare/bin/activate
  2. Reinstall deps: pip install -r requirements.txt (if exists)
  3. Key packages: baostock, pandas, numpy, flask, pyyaml, requests
  4. Check Python version: python --version (should be 3.11 in venv_akshare)
```

### Sina API rate limit

```
Problem: Sina API returns empty or 403
Solution:
  1. Check Referer header in sina_fetcher.py (must be finance.sina.com.cn)
  2. Reduce batch size: edit batch_size in dashboard/app.py or sina_fetcher.py
  3. Add delay between requests
  4. Fall back to BaoStock: python main.py download --force
```

## 10. Quick Reference

| Task | Command |
|------|---------|
| Download data | `python main.py download --top 300` |
| Update via Sina | `python update_kline_sina.py --workers 3` |
| Multi-strategy backtest | `python main.py backtest --start 2024-01-01` |
| Single strategy backtest | `python main.py backtest-single trend_following` |
| Daily scan | `python main.py scan --top 10` |
| Daily report | `python main.py report` |
| Run trading day | `python main.py boss` |
| Strategy ranking | `python main.py rank` |
| System status | `python main.py status` |
| Start dashboard | `python dashboard/app.py` |
| Weekly optimization | `python main.py optimize` |
| Monitor (background) | `python main.py monitor run` |

## 11. Notes

- **No real money**: This is a virtual trading system for research and learning only
- **No Feishu**: Daily reports are output to console and saved as JSON files in `reports/` and `knowledge_base/`
- **T+1 rule**: Stocks bought today cannot be sold until tomorrow (A-share rule)
- **100 round-lot**: A-share minimum trade unit is 100 shares
- **Strategy weights**: Optimized automatically by `optimizer.py`, stored in `config/settings.yaml` and `boss_optimizer/optimizer_state.json`
- **All dates in YYYY-MM-DD format**
