# A股AI量化交易系统 - 架构文档

> 创建于 2026-05-28，持续更新

## 一句话概括

基于A股历史数据的AI驱动量化交易系统，虚拟账户10万，万1免5佣金，排除科创板/北交所/ST股票。每日自动选股 + AI盘前分析 + 记忆系统持续学习。

## 目录结构

```
/disk2/workingFolder/quant/
├── core/                              # 核心模块
│   ├── memory.py                      # Agent记忆系统 (SQLite)
│   ├── market_state.py                # 市场状态追踪器
│   └── ai_analyzer.py                 # AI分析引擎 (盘前/盘后)
├── strategies/                        # 策略库
│   ├── __init__.py
│   ├── base.py                        # 策略基类
│   ├── manager.py                     # 策略管理器
│   ├── trend_following.py             # 趋势跟踪
│   ├── mean_reversion.py              # 均值回归
│   ├── momentum_breakout.py           # 动量突破
│   ├── multi_factor.py                # 多因子综合
│   ├── oversold_bounce.py             # 超跌反弹
│   └── lib/                           # 策略增强库
├── agents/                            # 10个独立Agent (boss_agent.py调用)
│   ├── trend_hunter.py
│   ├── contrarian.py
│   ├── momentum_scalper.py
│   ├── sector_alpha.py
│   ├── grid_master.py
│   ├── dragon_king.py
│   ├── tech_surge.py
│   ├── close_sniper.py
│   ├── value_guard.py
│   └── dividend_king.py
├── dashboard/                         # Dashboard (Flask, 端口5890)
│   ├── app.py
│   └── templates/index.html
├── knowledge_base/                    # 知识库
│   ├── trading_memory.db              # SQLite记忆数据库
│   ├── daily_YYYYMMDD.json            # 每日选股JSON
│   ├── daily_report_YYYYMMDD.txt      # 每日选股报告
│   └── ai_tools.md                    # AI工具参考
├── skills/                            # Skill文档
│   └── quant-memory-skill.md          # 记忆系统Skill
├── data/                              # 数据
│   ├── kline/                         # 日线K线CSV
│   ├── minute_kline/                  # 分钟K线缓存
│   ├── fundamentals/                  # 基本面JSON
│   ├── stock_pool.json                # 股票池 (~1039只)
│   └── stock_industry.json            # 行业分类
├── state/                             # 10个Agent状态文件
├── account/                           # 虚拟账户
│   └── account_state.json
├── reports/                           # 回测报告
├── optimization/                      # 策略优化结果
├── daily_runner.py                    # 每日选股流水线 (核心入口)
├── daily_pipeline.py                  # 统一流水线 (10个Agent)
├── boss_agent.py                      # Boss调度器
├── boss_optimizer.py                  # Agent权重优化器
├── historical_loader.py               # BaoStock历史数据加载
├── sina_fetcher.py                    # 新浪实时行情
├── backtest.py                        # 回测引擎
├── feishu_notify.py                   # 飞书通知 (no-op)
├── AGENTS.md                          # 项目上下文
└── ARCHITECTURE.md                    # 本文档
```

## 核心架构

```
┌─────────────────────────────────────────────────────┐
│                     Cron Scheduler                   │
│  09:00 每日选股 + AI盘前分析 (工作日)                  │
└──────────────┬──────────────────────────────────────┘
               │
               ▼
┌─────────────────────────────────────────────────────┐
│                  daily_runner.py                     │
│                                                      │
│  1. HistoricalDataLoader → 加载K线数据               │
│  2. StrategyManager → 5策略生成信号                   │
│  3. market_state.py → 追踪市场状态                   │
│  4. TradingMemory → 记录信号到记忆系统               │
│  5. AIAnalyzer → 盘前分析 + 信号二次评估             │
│  6. 输出报告 → knowledge_base/                      │
└──────────────┬──────────────────────────────────────┘
               │
               ▼
┌─────────────────────────────────────────────────────┐
│              TradingMemory (SQLite)                  │
│                                                      │
│  signals        - 交易信号记录 + 结果反馈             │
│  market_state   - 每日市场状态快照                    │
│  strategy_perf  - 策略表现统计                       │
│  lessons        - 经验教训                           │
│  stock_memory   - 个股事件记录                       │
└──────────────┬──────────────────────────────────────┘
               │
               ▼
┌─────────────────────────────────────────────────────┐
│              Dashboard (Flask :5890)                 │
│                                                      │
│  概览页 - 市场指数 + 选股信号 + 账户状态              │
│  选股页 - 详细选股列表                               │
│  持仓页 - 虚拟账户持仓                               │
│  回测页 - 策略回测结果                               │
└─────────────────────────────────────────────────────┘
```

## 记忆系统

基于 SQLite 的本地记忆引擎，零外部依赖。

### 5个记忆表

| 表名 | 用途 | 更新频率 |
|------|------|---------|
| signals | 选股/买卖信号记录 | 每日 |
| market_state | 市场状态快照 | 每日 |
| strategy_perf | 策略表现统计 | 每日 |
| lessons | 经验教训 | 事件触发 |
| stock_memory | 个股事件记录 | 事件触发 |

### 核心能力

- **信号追踪**: 记录每个信号的买入价/止损/止盈，后续跟踪结果
- **市场情绪**: 自动判断 bullish/bearish/neutral，关联策略表现
- **策略对比**: 按市场情绪筛选，找到当前环境下最优策略
- **模式洞察**: 自动发现重复出现的盈亏模式
- **经验积累**: 大赚/大亏自动记录为教训，供后续参考

## 交易规则

| 参数 | 值 |
|------|-----|
| 初始资金 | 100,000元 |
| 手续费 | 0.01% (免5) |
| 印花税 | 0.1% (仅卖出) |
| 最大持仓 | 5只 |
| 单只最大仓位 | 20% |
| 硬止损 | -7% |
| 止盈 | +15% |
| 移动止盈 | 回撤5% |
| 最大持仓天数 | 20个交易日 |

## 排除规则

- 科创板 (688/689开头)
- 北交所 (8开头/4开头)
- ST/*ST 股票
- 上市不足60天

## 数据源

| 数据 | 来源 | 说明 |
|------|------|------|
| 历史K线 | BaoStock | 日线级别，覆盖全市场 |
| 实时行情 | 新浪API | 直连无需代理 |
| 分钟K线 | 新浪API | 1/5/15/30/60分钟 |
| 板块数据 | 新浪API | 行业板块涨跌幅 |

## 常用命令

```bash
cd /disk2/workingFolder/quant

# 每日选股 (含记忆系统)
python daily_runner.py

# 指定日期
python daily_runner.py --date 2026-05-28

# AI盘前分析
python -c "from core.ai_analyzer import AIAnalyzer; print(AIAnalyzer().pre_market_analysis()['analysis'])"

# AI盘后复盘
python -c "from core.ai_analyzer import AIAnalyzer; print(AIAnalyzer().post_market_review()['review'])"

# 市场状态追踪
python core/market_state.py

# 记忆系统概览
python -c "
from core.memory import TradingMemory
import os
mem = TradingMemory(db_path=os.path.join('knowledge_base', 'trading_memory.db'))
print(mem.get_memory_summary())
"

# 策略对比排名
python -c "
from core.memory import TradingMemory
import os
mem = TradingMemory(db_path=os.path.join('knowledge_base', 'trading_memory.db'))
for r in mem.get_strategy_comparison(days=90):
    print(f'{r[\"strategy\"]}: 胜率{r[\"win_rate\"]:.0f}% 平均{r[\"avg_pnl_pct\"]:+.1f}%')
"

# 启动Dashboard
python dashboard/app.py
# 访问 http://localhost:5890
```

## Cron 任务

| 时间 | 任务 | 说明 |
|------|------|------|
| 09:00 工作日 | 每日选股 + AI盘前分析 | 运行daily_runner + 市场状态 + AI分析 |

## 迁移指南

如需迁移到其他机器：

1. 复制整个 `/disk2/workingFolder/quant/` 目录
2. 确保 Python 3.8+ 环境，安装依赖: `pip install pandas numpy flask`
3. SQLite 数据库在 `knowledge_base/trading_memory.db`，随目录一起迁移
4. 启动 Dashboard: `python dashboard/app.py`
