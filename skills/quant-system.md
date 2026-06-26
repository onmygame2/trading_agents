---
name: quant-system
description: A股AI量化交易系统 - 10策略Agent架构 + Boss调度 + 虚拟账户10万 + 万1免5。每日自动选股，飞书推送。
category: software-development
---

# A股AI量化交易系统操作指南

## 快速开始

```bash
cd /disk2/workingFolder/quant

# 查看系统状态
python main.py status

# 运行Boss Agent (10策略联合选股+交易)
python boss_agent.py --date 2026-05-21

# 选股扫描 (Top N)
python main.py scan --top 10

# 多策略回测
python main.py backtest --start 2024-01-01

# 启动Dashboard
python dashboard/app.py
# 访问: http://localhost:5890
```

## 架构概览

Boss Agent管理10个独立Agent，每个10万虚拟资金，总计100万。

```
Boss Agent (boss_agent.py)
├── trend_hunter     (趋势跟踪)     权重 0.5/0.3/0.2
├── value_guard      (多因子)       权重 0.25/0.55/0.2
├── momentum_scalper (动量突破)     权重 0.6/0.15/0.25
├── sector_alpha     (板块轮动)     权重 0.3/0.25/0.45
├── contrarian       (均值回归)     权重 0.45/0.35/0.2
├── dragon_king      (龙回头)       权重 0.65/0.15/0.2
├── grid_master      (网格交易)     权重 0.55/0.3/0.15
├── dividend_king    (超跌反弹)     权重 0.2/0.6/0.2
├── tech_surge       (量价共振)     权重 0.55/0.2/0.25
└── close_sniper     (尾盘策略)     权重 0.6/0.15/0.25
```

## 核心文件

| 文件 | 作用 |
|------|------|
| boss_agent.py | Boss调度器 (主要入口) |
| main.py | CLI统一入口 |
| daily_pipeline.py | 单账户流水线 |
| strategy_agent.py | Agent基类 |
| agents/ | 10个策略Agent实现 |
| factor_engine.py | 15+ Alpha因子 |
| ml_stock_selector.py | ML选股器 |
| sina_fetcher.py | 新浪实时数据 |
| fundamental_loader.py | 基本面数据 |
| sector_sentiment.py | 板块情绪分析 |
| monitor.py | 盘中监控 |
| feishu_notify.py | 飞书通知 |
| boss_optimizer.py | Agent权重优化 |
| dashboard/ | Flask Web仪表盘 |

## 交易规则

- 初始资金: ¥100,000 (每Agent独立)
- 手续费: 0.01% 万1免5
- 印花税: 0.1% (仅卖出)
- 最大持仓: 5只
- 硬止损: -7%
- 止盈: +15%
- 移动止盈: 回撤5%
- 排除: 科创板/北交所/ST/上市<60天

## 数据源

- BaoStock: 历史K线 (T+1延迟)
- 新浪API: 实时行情 (直连可用)
- AkShare: 备用数据源 (venv_akshare/ Python 3.11)

## 目录结构

```
quant/
├── PLANNING.md                 # 总体规划
├── knowledge_base/             # 知识库 + 每日报告
│   ├── ai_tools_2026.md       # AI工具参考
│   └── boss_report_*.json     # 每日Boss报告
├── skills/                     # 本地Skill文档
│   └── quant-system.md        # 本文件
├── agents/                     # 10策略Agent
├── dashboard/                  # Flask Dashboard
├── data/                       # 数据缓存
│   ├── kline/                  # K线CSV (1039只)
│   ├── fundamentals/           # 基本面JSON
│   └── stock_pool.json         # 股票池
├── state/                      # Agent状态文件
├── reports/                    # 回测/选股报告
├── optimization/               # 策略优化结果
└── venv_akshare/               # Python 3.11环境
```

## 定时任务

| 任务 | 时间 | 命令 |
|------|------|------|
| 早盘选股 | 08:30 | `python main.py monitor morning` |
| 盘中检查 | 每30min | `python main.py monitor check` |
| 盘后复盘 | 15:10 | `python main.py monitor review` |
| 周度优化 | 周五20:00 | `python main.py optimize` |

## 注意事项

1. 修改dashboard代码后必须重启Flask进程
2. 修改Agent策略后运行 boss_agent.py 生成新报告
3. 服务器CDN不可用，Dashboard零外部依赖
4. BaoStock数据有T+1延迟，早盘用缓存数据
5. 新浪API直连可用，无需代理
