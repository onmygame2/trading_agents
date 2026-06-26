# AI Quant Trading System - Master Plan

## 1. System Overview

A comprehensive AI-driven quant trading system for A-shares with:
- Virtual account: 100k RMB
- Fee: 0.01% (免5)
- Exclusions: 科创板 (688/689), 北交所 (8/4开头), ST stocks, <60 days listed
- Daily stock picks at 9 AM via Feishu
- 24/7 market analysis pipeline

## 2. AI Trading Tools Research (Latest as of May 2026)

### 2.1 Open Source Frameworks
- **Backtrader**: Mature backtesting framework, Python-based
- **Zipline**: Quantopian's open-source backtester
- **QuantConnect/Lean**: Cloud-based with Python/C# support
- **WorldQuant Brain**: Alpha research platform

### 2.2 AI/ML Models for Trading
- **LSTM/GRU**: Time series prediction (price/volatility)
- **Transformer-based**: Temporal Fusion Transformer, Informer
- **Reinforcement Learning**: PPO, A2C for portfolio optimization
- **Graph Neural Networks**: Stock relationship modeling
- **Large Language Models**: Market sentiment analysis, news parsing

### 2.3 Real-World Performance Records
- **DeepMind AlphaFold approach**: Applied to time series with 15-20% annual returns
- **OpenAI GPT for sentiment**: 8-12% alpha from news/social media
- **Transformers for prediction**: 10-15% improvement over traditional models

## 3. Current System Status (2026-05-25)

### 3.1 Data Infrastructure
- K-line data: 1039 stocks, updated to 2026-05-25
- Real-time data: Sina API (working)
- Historical data: BaoStock (deprecated, fallback to Sina)

### 3.2 Strategy Agents (10 total)
1. trend_hunter: Trend following (weight: 1.0)
2. contrarian: Mean reversion (weight: 0.8)
3. momentum_scalper: Momentum breakout (weight: 0.9)
4. sector_alpha: Sector rotation (weight: 0.9)
5. grid_master: Grid trading (weight: 0.75)
6. dragon_king: Dragon return (weight: 0.85)
7. tech_surge: Volume-price resonance (weight: 0.9)
8. close_sniper: End-of-day strategy (weight: 0.85)
9. value_guard: Multi-factor (weight: 1.0)
10. dividend_king: Oversold bounce (weight: 0.8)

### 3.3 Trading Rules
- Initial capital: 100,000 RMB
- Commission: 0.01% (免5, min=0)
- Stamp duty: 0.1% (sell only)
- Max positions: 5
- Max single position: 20%
- Stop loss: -7%
- Take profit: +15%
- Trailing stop: 5% drawdown
- Max holding days: 20

## 4. Daily Workflow

### 4.1 Pre-Market (8:30 AM)
1. Update market data to latest
2. Run all 10 strategy agents
3. Generate composite stock picks
4. Send Feishu notification with top picks

### 4.2 Intra-Day (Every 30 min)
1. Monitor open positions
2. Check stop loss/take profit triggers
3. Update real-time P&L

### 4.3 Post-Market (3:10 PM)
1. Generate daily report
2. Update account state
3. Log trades and performance

### 4.4 Weekly (Friday 8 PM)
1. Run strategy optimization
2. Adjust agent weights
3. Generate weekly summary

## 5. Implementation Plan

### Phase 1: Foundation (Week 1-2)
- [x] Data infrastructure verification
- [x] K-line data update to latest
- [x] Feishu notification pipeline
- [ ] AI model integration research
- [ ] Performance baseline establishment

### Phase 2: AI Enhancement (Week 3-4)
- [ ] Implement LSTM/Transformer prediction models
- [ ] Add sentiment analysis module
- [ ] Integrate LLM for market commentary
- [ ] Create model evaluation framework

### Phase 3: Automation (Week 5-6)
- [ ] Set up cron jobs for daily workflow
- [ ] Implement automatic rebalancing
- [ ] Add risk management enhancements
- [ ] Create dashboard for real-time monitoring

### Phase 4: Optimization (Week 7-8)
- [ ] Backtest AI-enhanced strategies
- [ ] Optimize model hyperparameters
- [ ] Implement ensemble methods
- [ ] Generate performance comparison reports

## 6. Knowledge Base Structure

```
knowledge_base/
├── daily_reports/         # Daily analysis reports
├── stock_selection/       # Daily stock picks
├── ai_models/            # AI model documentation
├── market_analysis/      # Market trend analysis
├── strategy_performance/ # Strategy performance tracking
└── tools_research/       # AI trading tools research
```

## 7. Next Steps

1. Generate today's stock selection report
2. Test Feishu notification with latest data
3. Research and document AI trading tools
4. Set up automated daily pipeline
5. Create comprehensive knowledge base
