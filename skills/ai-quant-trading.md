---
name: ai-quant-trading
description: AI量化交易系统 - A股多策略回测 + 每日自动选股。基于BaoStock数据源，4种策略（趋势跟踪/均值回归/动量突破/多因子），虚拟账户10万，万1免5。
category: software-development
---

# AI量化交易系统

## 概述

基于 BaoStock 数据源 + 4策略加权融合 + 回测引擎 的 A 股量化交易系统。
支持数据下载、全市场选股扫描、多策略回测、虚拟账户模拟。

## 数据源

- **BaoStock** (免费，无需API Key)
- 通过 `baostock_fetcher.py` 获取K线数据、股票列表
- 本地CSV缓存：`data/kline/{stock_code}.csv`
- 股票池：`data/stock_pool.json`（排除科创板/北交所/ST）

## 目录结构

```
/disk2/workingFolder/quant/
├── main.py                    # CLI统一入口 (download/scan/backtest/report/status)
├── baostock_fetcher.py        # BaoStock数据抓取 + 技术指标计算 + 全市场扫描
├── historical_loader.py       # 批量下载 + CSV缓存管理（增量更新）
├── backtest.py                # 回测引擎（交易模拟/净值计算/绩效统计）
├── strategies_runner.py       # 策略调度器（信号收集→加权合并→仓位分配→执行）
├── account.py                 # 虚拟账户管理
├── config/
│   └── settings.yaml          # 配置（资金/手续费/策略权重/筛选规则）
├── strategies/
│   ├── __init__.py
│   ├── base.py                # 策略基类
│   ├── manager.py             # 策略管理器（加权置信度合并）
│   ├── trend_following.py     # 趋势跟踪（权重1.0）
│   ├── mean_reversion.py      # 均值回归（权重0.8）
│   ├── momentum_breakout.py   # 动量突破（权重0.9）
│   ├── multi_factor.py        # 多因子综合（权重1.0）
│   └── selector.py            # 选股器
├── data/
│   ├── kline/                 # K线CSV缓存
│   ├── stock_pool.json        # 股票池清单
│   └── market_*.json          # 市场快照
├── account/
│   ├── account_state.json     # 虚拟账户状态
│   └── trade_log.json         # 交易记录
├── reports/                   # 回测/选股报告
├── logs/                      # 运行日志
└── skills/
    └── ai-quant-trading.md    # 本文件
```

## 4大策略

### 1. 趋势跟踪 (权重 1.0)
均线多头排列(MA5>MA10>MA20>MA60) + MACD金叉红柱 + 放量突破

### 2. 均值回归 (权重 0.8)
RSI超卖(<30) + 布林带下轨 + 底部放量

### 3. 动量突破 (权重 0.9)
突破20/60日新高 + 放量(>20日均量1.5x) + 5日涨幅>5%

### 4. 多因子综合 (权重 1.0)
技术(均线+MACD+RSI) + 量能(换手+放量) + 动量(5日/20日涨跌) + 波动率

## 交易规则

- 初始资金：100,000元
- 手续费：0.01%（免5，`min_commission: 0`）
- 印花税：0.05%（仅卖出）
- 最大持仓：5只
- 单笔上限：总资金 20%
- 标的范围：主板(600/601/603/605/000/001/002/003) + 创业板(300/301)
- 排除：科创板(688/689)、北交所(8/4)、ST/*ST、上市<60天

## CLI 命令

```bash
cd /disk2/workingFolder/quant

# 下载数据（增量，自动跳过已缓存）
conda run -n quant python main.py download --top 100 --start 2025-01-01 --delay 0.15

# 全市场选股扫描
conda run -n quant python main.py scan --top 10

# 多策略回测
conda run -n quant python main.py backtest --start 2025-06-01

# 查看账户/选股报告
conda run -n quant python main.py report

# 系统状态
conda run -n quant python main.py status
```

## 回测结果（2025-06 ~ 2026-05, 20只样本）

| 指标 | 数值 |
|------|------|
| 总收益率 | +18.39% |
| 年化收益 | 20.32% |
| 最大回撤 | -6.66% |
| 夏普比率 | 1.41 |
| 胜率 | 50.0% |
| 盈亏比 | 1.78 |
| 交易次数 | 141 |

## 定时任务

每日 9:00（工作日）自动执行：
1. 增量更新K线数据（最近60天）
2. 全市场扫描 Top 10
3. 输出虚拟账户状态
4. 整合为选股日报

## 程序化调用

```python
from baostock_fetcher import BaoStockFetcher
from strategies_runner import StrategyRunner
from backtest import BacktestEngine

# 数据获取
fetcher = BaoStockFetcher()
stock_pool = fetcher.get_stock_pool()  # 过滤后的股票池
kline = fetcher.get_kline('sh.600519')  # 单只K线

# 技术指标
df = fetcher.calculate_indicators(kline)

# 策略回测
runner = StrategyRunner(initial_cash=100000, min_commission=0)
runner.add_strategy(TrendFollowingStrategy())
runner.load_data()
result = runner.run('2025-06-01', '2026-05-14')
```

## 注意事项

1. BaoStock 免费但有限速，批量下载建议 `--delay 0.15`
2. 首次运行需 `download` 建立本地缓存，之后 `scan` 读缓存即可
3. 非交易日数据不更新
4. 选股/回测结果仅供参考，不构成投资建议
5. 虚拟账户仅用于模拟，不涉及真实交易
6. 网络代理：部分环境需配置 `http://127.0.0.1:1935`

## 常见问题

**Q: 下载卡住？**
A: 检查网络/代理，BaoStock需要访问 stock.baostock.com

**Q: 回测交易为0？**
A: 检查 `backtest.py` 的 `run()` 方法是否在信号执行后被调用导致重置。当前版本已修复此bug。

**Q: 如何增加股票池？**
A: `download --top N` 增大N值，默认从stock_pool.json取前N只
