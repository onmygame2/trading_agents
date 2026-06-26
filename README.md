# A股AI量化交易系统

## 项目概述

基于10种A股实战策略的多策略量化回测与选股系统。每个策略拥有独立账户(10万初始资金)，支持策略间绩效排名和对比。

## 特性

- **10种策略**: 趋势跟踪、均值回归、动量突破、多因子、量价共振、超跌反弹、龙回头、低吸网格、板块轮动、尾盘策略
- **多策略独立回测**: 每个策略独立资金池、独立持仓、独立交易记录
- **策略排名**: 收益率、夏普比率、最大回撤、胜率等多维度对比
- **10策略联合选股**: 多策略交叉验证，被多个策略同时推荐的股票优先级最高
- **每日选股报告**: 自动生成包含指数行情和选股推荐的日报
- **975只A股覆盖**: 上证主板 + 深证主板 + 创业板 (排除科创板和北交所)

## 环境要求

```
Python 3.8+
pandas, numpy, pyyaml, baostock
```

## 快速开始

```bash
cd /disk2/workingFolder/quant

# 1. 查看系统状态
python main.py status

# 2. 下载全部股票数据 (约975只, 需要几分钟)
python main.py download-all --start 2024-01-01

# 3. 运行多策略回测
python main.py backtest --start 2024-01-01

# 4. 运行单策略回测
python main.py backtest-single trend_following --start 2024-01-01

# 5. 10策略联合扫描选股
python main.py scan --top 10

# 6. 生成每日选股报告(含指数)
python main.py report

# 7. 查看策略排名
python main.py rank
```

## 命令说明

| 命令 | 说明 |
|------|------|
| `download [--top N]` | 下载前N只股票历史K线数据 |
| `download-all` | 下载全部股票数据 |
| `backtest` | 运行所有启用策略的回测 |
| `backtest-single <策略名>` | 运行单策略回测 |
| `scan [--top N]` | 10策略联合扫描选股 |
| `report` | 生成每日选股报告(含指数行情) |
| `rank` | 查看最近一次回测的策略排名 |
| `status` | 查看系统状态(数据/策略/报告) |

## 策略列表

| 策略 | 名称 | 核心逻辑 | 权重 |
|------|------|---------|------|
| trend_following | 趋势跟踪 | 均线多头+MACD金叉+放量突破 | 1.0 |
| mean_reversion | 均值回归 | 超卖反弹+布林带下轨+底部放量 | 0.8 |
| momentum_breakout | 动量突破 | N日新高突破+放量+强势动量 | 0.9 |
| multi_factor | 多因子综合 | 技术+量能+估值+波动率+动量 | 1.0 |
| volume_price | 量价共振 | 放量突破+量价齐升+MACD配合 | 0.9 |
| oversold_bounce | 超跌反弹 | RSI超卖+布林带下轨+底部放量+反弹确认 | 0.8 |
| dragon_return | 龙回头 | 强势股回调+缩量企稳+支撑位反弹 | 0.85 |
| grid_trading | 低吸网格 | 布林带下轨+均线支撑+低波动收缩 | 0.75 |
| sector_rotation | 板块轮动 | 热点板块+动量领先+放量突破 | 0.9 |
| closing_strategy | 尾盘策略 | 尾盘抢筹+强势收盘+次日惯性上冲 | 0.85 |

## 交易规则

- 初始资金: 100,000元 / 策略
- 手续费: 万分之一 (0.01%), 免5
- 印花税: 千分之一 (0.1%), 仅卖出
- 最大持仓: 5只 / 策略
- 单只最大仓位: 20%
- 硬止损: -7%
- 止盈: +15%
- 移动止盈回撤: 5%
- 最大持仓天数: 20个交易日

## 配置文件

`config/settings.yaml` - 包含所有配置:
- 账户参数 (初始资金、手续费、税费)
- 市场过滤 (排除科创板/北交所/ST股)
- 策略参数 (仓位、止损、止盈)
- 各策略开关和权重
- 回测参数 (日期范围、回看天数)

## 目录结构

```
quant/
  main.py                 # 主入口
  strategies_runner.py    # 多策略回测运行器
  strategy_account.py     # 单策略独立账户管理
  strategy_ranker.py      # 策略排名与收益分析
  historical_loader.py    # 历史数据加载器
  baostock_fetcher.py     # BaoStock数据获取
  config/
    settings.yaml         # 配置文件
  strategies/
    __init__.py           # 策略包入口
    base.py               # 策略基类
    manager.py            # 策略管理器
    trend_following.py    # 趋势跟踪
    mean_reversion.py     # 均值回归
    momentum_breakout.py  # 动量突破
    multi_factor.py       # 多因子综合
    volume_price.py       # 量价共振
    oversold_bounce.py    # 超跌反弹
    dragon_return.py      # 龙回头
    grid_trading.py       # 低吸网格
    sector_rotation.py    # 板块轮动
    closing_strategy.py   # 尾盘策略
  data/
    kline/                # 个股K线CSV
    stock_pool.json       # 股票池清单
  reports/                # 回测/选股报告输出
```

## 免责声明

本系统仅供学习和研究使用，不构成任何投资建议。股市有风险，投资需谨慎。

## 自动任务

每日9:00自动执行选股扫描，生成当日选股报告。
