---
name: a-share-quant-boss
description: A股AI量化交易系统完整操作指南。10策略虚拟账户交易、Dashboard管理、每日选股报告。
---

# A股AI量化交易系统操作指南

## 系统概述

基于A股历史数据的10策略量化交易系统，虚拟账户10万/agent，万1免5佣金，每日自动选股推送。

## 核心文件

| 文件 | 作用 |
|------|------|
| `main.py` | CLI入口: download/scan/backtest/report/rank/status |
| `daily_pipeline.py` | 统一10万虚拟账户每日交易流水线 |
| `boss_agent.py` | Boss调度器，管理10个Agent各10万 |
| `boss_optimizer.py` | Agent权重动态优化 |
| `sina_fetcher.py` | 新浪实时行情API（直连无需代理） |
| `dashboard/app.py` | Flask Dashboard，端口5890 |
| `feishu_notify.py` | 飞书通知模块 |

## 10个策略Agent

| Agent | 策略 | 权重 |
|-------|------|------|
| trend_hunter | 趋势跟踪 | 1.0 |
| contrarian | 均值回归 | 0.8 |
| momentum_scalper | 动量突破 | 0.9 |
| sector_alpha | 板块轮动 | 0.9 |
| grid_master | 网格交易 | 0.75 |
| dragon_king | 龙回头 | 0.85 |
| tech_surge | 量价共振 | 0.9 |
| close_sniper | 尾盘策略 | 0.85 |
| value_guard | 多因子 | 1.0 |
| dividend_king | 超跌反弹 | 0.8 |

## Cron任务调度

| 任务 | 时间 | Job ID |
|------|------|--------|
| 早盘选股推送 | 周一-五 09:00 | 7c5708891025 |
| 盘中检查 | 周一-五 每30分钟 (9:00-14:30) | df51c179e3e5 |
| 盘后复盘 | 周一-五 15:10 | 869c4e195375 |
| 周度优化 | 周五 20:00 | 37a95df52b30 |

## 常用命令

```bash
cd /disk2/workingFolder/quant

# 查看状态
python main.py status

# 下载数据
python main.py download-all --start 2024-01-01

# 多策略回测
python main.py backtest --start 2024-01-01

# 10策略联合选股
python main.py scan --top 10

# 每日选股报告
python main.py report

# 策略排名
python main.py rank

# 启动Dashboard
python dashboard/app.py
```

## 交易规则

- 初始资金: 100,000元/agent
- 手续费: 0.01% (免5, min_commission=0)
- 印花税: 0.1% (仅卖出)
- 最大持仓: 5只
- 单只最大仓位: 20%
- 硬止损: -7%
- 止盈: +15%
- 移动止盈: 回撤5%
- 最大持仓天数: 20个交易日

## 排除规则

- 科创板 (688/689)
- 北交所 (8开头/4开头)
- ST/*ST 股票
- 上市不足60天

## 数据存储

- `account/` - 虚拟账户状态 + 交易日志
- `state/` - 10个Agent状态文件
- `data/kline/` - K线CSV
- `data/fundamentals/` - 基本面JSON
- `knowledge_base/` - 每日报告
- `boss_optimizer/` - 权重优化状态

## Dashboard

- 代码: `dashboard/app.py` + `dashboard/templates/index.html`
- 启动: `cd /disk2/workingFolder/quant && python dashboard/app.py`
- 访问: http://localhost:5890
- **重要: 修改dashboard代码后必须重启Flask进程才能生效**
- **重要: 修改agent策略后运行 daily_pipeline.py 或 boss_agent.py 生成最新报告**

## 飞书通知

- 飞书APP_SECRET从 `/disk2/.openclaw/workspace/order-system/.env` 读取
- 推送时间: 每个交易日 09:00
- 推送内容: 实时指数、市场概况、Agent收益排名、选股推荐
- User Open ID: ou_a2efb39c91ba979f60362822cac05669

## 工作流

1. 修改策略代码 -> 运行 backtest 验证 -> 启动 dashboard 查看
2. 修改 dashboard -> 重启 Flask 进程 -> 刷新浏览器
3. 每日早间: daily_pipeline.py 自动运行 -> 生成报告 -> 飞书通知
4. 周五晚间: boss_optimizer.py 自动优化权重

## 已知问题

- Python 3.8系统环境，akshare需要3.9+，使用 venv_akshare/ (Python 3.11)
- 服务器在国内，外部CDN (jsdelivr, bootcdn) 被阻止，Dashboard使用零外部JS依赖
- 东方财富API被屏蔽，使用新浪API替代
- 每日报告生成到 knowledge_base/boss_report_YYYY-MM-DD.json
- 最新报告日期取决于上次运行时间
