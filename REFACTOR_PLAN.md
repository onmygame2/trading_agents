# A股中低频量化交易系统 - 重构规划 v2.0

## 一句话概括

基于日线级别的中低频A股量化交易系统，虚拟账户10万，万1免5佣金，5大精选策略，每天自动选股并在聊天窗口推送。

## 核心变更 (vs v1)

| 项目 | v1 (旧) | v2 (新) |
|------|---------|---------|
| 交易频率 | 盘中高频+分钟线 | 日线中低频 |
| 策略数量 | 10个Agent | 5个精选策略 |
| 通知方式 | 飞书（已禁用） | 聊天窗口 |
| 持仓周期 | 1-20天 | 3-20天 |
| 分析频率 | 盘中每30分钟 | 每日1次（盘后） |
| 推送时间 | 08:30早盘 | 09:00开盘前 |
| 数据源 | BaoStock+新浪日/分钟线 | BaoStock+新浪日线 |
| 历史数据 | 2024-01-01至今 | 最近半年（重新下载） |
| Boss Agent | 10个Agent各10万 | 5个策略独立账户 |

## 保留的5个策略

| 排名 | 策略 | 核心逻辑 | 为什么适合中低频 |
|------|------|---------|-----------------|
| 1 | 趋势跟踪 | 均线/ADX趋势过滤 | 经典中长线，持仓跟随趋势 |
| 2 | 动量突破 | 价格突破+成交量确认 | 日线突破信号，持有至动量衰竭 |
| 3 | 多因子 | PE/PB/ROE + 技术指标 | 基本面+技术面综合，天然中低频 |
| 4 | 均值回归 | Bollinger Band/RSI超卖 | 统计套利，偏离均值回归 |
| 5 | 超跌反弹 | RSI/KDJ超卖区域反转 | 超卖后的反弹行情 |

## 删除的5个策略及原因

| 策略 | 原因 |
|------|------|
| grid_trading (网格) | 偏短线震荡，不适合中低频 |
| closing_strategy (尾盘) | 日内T+1策略 |
| dragon_return (龙回头) | 短线追涨，需要盯盘 |
| sector_rotation (板块轮动) | 需要高频监控板块变化 |
| volume_price (量价共振) | 偏短线爆发信号 |

## 目录结构 (重构后)

```
quant/
├── main.py                      # CLI入口: download/backtest/scan/report/status
├── daily_runner.py              # 每日选股流水线（替代daily_pipeline.py + boss_agent.py）
├── backtest.py                  # 回测引擎（复用）
├── historical_loader.py         # BaoStock历史K线下载
├── sina_fetcher.py              # 新浪实时行情API
├── data_fetcher.py              # AKShare数据下载
├── baostock_fetcher.py          # BaoStock数据抓取+指标计算
├── trade_engine.py              # 虚拟交易引擎
├── position_manager.py          # 仓位管理
├── fundamental_loader.py        # 基本面数据
├── performance_tracker.py       # 绩效跟踪
├── monitor.py                   # 删除（盘中监控不再需要）
├── boss_agent.py                # 删除（简化为daily_runner.py）
├── boss_optimizer.py            # 删除（不需要优化10个Agent权重）
├── strategies_runner.py         # 多策略回测运行器
├── factor_engine.py             # 因子引擎
├── ml_stock_selector.py         # ML选股器
├── update_kline_data.py         # K线数据更新
├── build_stock_pool.py          # 构建股票池
├── sector_sentiment.py          # 板块情绪分析
├── strategy_ranker.py           # 策略排名
├── optimizer.py                 # 策略参数优化
├── optimize_strategies.py       # 策略优化
├── feishu_notify.py             # 保留为空文件（兼容旧代码）
│
├── strategies/                  # 5个策略类（供回测使用）
│   ├── trend_following.py       # 趋势跟踪
│   ├── momentum_breakout.py     # 动量突破
│   ├── multi_factor.py          # 多因子
│   ├── mean_reversion.py        # 均值回归
│   └── oversold_bounce.py       # 超跌反弹
│
├── dashboard/                   # Web仪表板（全面优化）
│   ├── app.py
│   └── templates/
│       └── index.html
│
├── data/
│   ├── kline/                   # 日线K线CSV
│   ├── fundamentals/            # 基本面JSON
│   ├── stock_pool.json          # 股票池
│   └── stock_industry.json      # 行业分类
│
├── account/
│   └── account_state.json       # 虚拟账户状态
│
├── state/                       # 5个策略状态文件
│   ├── trend_following_state.json
│   ├── momentum_breakout_state.json
│   ├── multi_factor_state.json
│   ├── mean_reversion_state.json
│   └── oversold_bounce_state.json
│
├── knowledge_base/              # 每日选股记录
│   └── daily_pick_YYYYMMDD.json
│
├── reports/                     # 回测报告
│   └── backtest_YYYYMMDD.json
│
├── .hermes/
│   └── skills/
│       └── quant-trading.md     # 量化交易Skill文档
│
└── AGENTS.md                    # 项目上下文
```

## 交易规则

- 初始资金: 100,000元（每个策略独立账户）
- 手续费: 0.01%（免5, min_commission=0）
- 印花税: 0.1%（仅卖出）
- 最大持仓: 5只/策略
- 单只最大仓位: 20%
- 硬止损: -7%
- 止盈: +15%
- 移动止盈: 回撤5%
- 最大持仓天数: 20个交易日
- 最小持仓天数: 3个交易日（中低频）

## 排除规则

- 科创板 (688/689)
- 北交所 (8开头/4开头)
- ST/*ST 股票
- 上市不足60天

## 每日工作流

1. 盘后更新数据（新浪日线）
2. 运行5个策略选股
3. 生成选股报告到 knowledge_base/
4. 更新虚拟账户状态
5. Dashboard实时更新

## 回测计划

- 时间范围: 最近半年
- 每个策略独立账户10万
- 输出: 总收益、胜率、夏普比率、最大回撤、交易次数
- 根据回测结果调整策略参数

## 重构步骤

### Phase 1: 清理 (已完成)
- [x] 删除所有飞书相关Cron任务
- [x] 禁用飞书通知
- [x] 更新记忆为中低频模式

### Phase 2: 数据清理
- [ ] 清除 data/kline/ 所有K线数据
- [ ] 清除 data/fundamentals/ 所有基本面数据
- [ ] 清除 data/minute_kline/ 目录（不再需要）
- [ ] 清除 account/ 和 state/ 所有历史状态
- [ ] 清除 knowledge_base/ 和 reports/ 历史数据
- [ ] 清除 optimization/ 和 boss_optimizer/ 历史数据

### Phase 3: 代码精简
- [ ] 删除 agents/ 目录（不再需要10个Agent）
- [ ] 删除不再需要的策略文件
- [ ] 删除 monitor.py、boss_agent.py、boss_optimizer.py
- [ ] 删除 strategies/ 中不需要的5个策略
- [ ] 创建 daily_runner.py（简化版流水线）

### Phase 4: 数据重建
- [ ] 下载最近半年日线K线数据
- [ ] 下载基本面数据
- [ ] 重新构建股票池

### Phase 5: 回测验证
- [ ] 运行5个策略的独立回测
- [ ] 根据回测结果调整参数
- [ ] 生成回测报告

### Phase 6: Dashboard优化
- [ ] 后端API重构（5个策略，新增价格目标字段）
- [ ] 前端界面全面优化
- [ ] 展示：策略排名、选股列表、交易记录、持仓状态、绩效图表

### Phase 7: Skill文档
- [ ] 创建 .hermes/skills/quant-trading.md
- [ ] 更新 AGENTS.md

### Phase 8: 配置Cron任务
- [ ] 创建每日选股任务（09:00）
