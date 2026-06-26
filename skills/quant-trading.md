# 量化交易操作手册

## 快速命令

```bash
cd /disk2/workingFolder/quant

# 查看系统状态
python main.py status

# 下载/更新数据
python main.py download-all --start 2025-01-01

# 运行回测
python main.py backtest --start 2025-01-01

# 多策略选股
python main.py scan --top 10

# 生成选股报告
python main.py report

# 策略排名
python main.py rank

# 启动Dashboard
python dashboard/app.py
```

## 5个策略

| 策略 | 文件 | 核心逻辑 |
|------|------|---------|
| 趋势跟踪 | trend_following.py | 均线多头 + MACD金叉 + 放量 |
| 均值回归 | mean_reversion.py | RSI超卖 + 布林下轨 + 底部放量 |
| 动量突破 | momentum_breakout.py | 价格突破 + 成交量确认 |
| 多因子 | multi_factor.py | PE/PB/ROE + 技术指标 |
| 超跌反弹 | oversold_bounce.py | RSI/KDJ超卖区域反转 |

## 交易规则

- 初始资金: 100,000元
- 手续费: 0.01% (免5)
- 印花税: 0.1% (仅卖出)
- 最大持仓: 5只
- 单只最大仓位: 20%
- 硬止损: -7%
- 止盈: +15%
- 移动止盈: 回撤5%
- 最大持仓天数: 20个交易日

## 排除规则

- 科创板 (688/689)
- 北交所 (8/4开头)
- ST/*ST 股票
- 上市不足60天

## 每日工作流

1. Cron 09:00 自动运行 daily_runner.py
2. 推送选股报告到 Hermes 聊天
3. Dashboard 实时更新

## 修改策略

1. 编辑 strategies/ 下对应文件
2. 运行 python main.py backtest 验证
3. 运行 python main.py scan 看选股效果
4. Dashboard 查看结果

## 价格目标

每个选股附带:
- buy_price: 建议买入价
- stop_loss: 止损价 (-7%)
- take_profit: 止盈价 (+15%)
- invalid_price: 失效价 (-10%)
- confidence: 置信度 (0-1)
- reasoning: 设定依据