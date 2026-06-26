---
name: a-stock-quant-trading
description: >
  A股AI量化交易系统: 10种策略的多策略量化回测与选股系统。
  支持每日9点自动生成选股报告、策略排名对比、虚拟账户回测。
  覆盖975只A股(上证/深证/创业板)，排除科创板和北交所。
category: data-science
tags:
  - quant
  - a-stock
  - trading
  - backtest
  - stock-picking
---

# A股AI量化交易系统

## 触发条件

用户说以下任何内容时加载此技能:
- "选股" / "帮我选股" / "今天买什么"
- "回测" / "跑回测" / "策略回测"
- "看排名" / "策略排名"
- "量化" / "量化交易"
- "A股" / "股市分析"
- "今日选股" / "每日选股"
- "看行情" / "大盘"

## 系统位置

所有文件在 `/disk2/workingFolder/quant/` 目录下。

## 核心命令

```bash
cd /disk2/workingFolder/quant

# 查看系统状态
python main.py status

# 下载全部股票数据
python main.py download-all --start 2024-01-01

# 运行多策略回测(全部启用策略)
python main.py backtest --start 2024-01-01

# 运行单策略回测
python main.py backtest-single trend_following --start 2024-01-01

# 10策略联合扫描选股
python main.py scan --top 10

# 生成每日选股报告(含指数行情)
python main.py report

# 查看策略排名
python main.py rank
```

## 10种策略

| 策略代码 | 名称 | 核心逻辑 |
|---------|------|---------|
| trend_following | 趋势跟踪 | 均线多头+MACD金叉+放量突破 |
| mean_reversion | 均值回归 | 超卖反弹+布林带下轨+底部放量 |
| momentum_breakout | 动量突破 | N日新高突破+放量+强势动量 |
| multi_factor | 多因子综合 | 技术+量能+估值+波动率+动量 |
| volume_price | 量价共振 | 放量突破+量价齐升+MACD配合 |
| oversold_bounce | 超跌反弹 | RSI超卖+布林带下轨+反弹确认 |
| dragon_return | 龙回头 | 强势股回调+缩量企稳+支撑位反弹 |
| grid_trading | 低吸网格 | 布林带下轨+均线支撑+低波动收缩 |
| sector_rotation | 板块轮动 | 热点板块+动量领先+放量突破 |
| closing_strategy | 尾盘策略 | 尾盘抢筹+强势收盘+次日惯性上冲 |

## 交易参数

- 初始资金: 100,000元/策略
- 手续费: 0.01%(免5)
- 印花税: 0.1%(仅卖出)
- 最大持仓: 5只/策略
- 单只最大仓位: 20%
- 硬止损: -7%
- 止盈: +15%
- 移动止盈回撤: 5%
- 最大持仓天数: 20个交易日

## 自动选股报告

每日9:00自动生成选股报告，命令:

```bash
cd /disk2/workingFolder/quant && python main.py report
```

## 配置

配置文件: `config/settings.yaml`

关键配置:
- 策略开关和权重在 `strategies` 段
- 账户参数在 `account` 段
- 回测参数在 `backtest` 段

## 注意事项

1. 数据来源为 BaoStock，排除科创板(688)和北交所
2. 每次回测前确保数据已下载: `python main.py status`
3. 选股报告基于最新可用数据生成
4. 所有数据、报告、skill文件均在 `/disk2/workingFolder/quant/` 下