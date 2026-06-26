# A股量化选股系统 v2 - 操作手册

基于多因子评分 + 策略共振的自动化选股系统。虚拟账户10万，每日自动选股并执行虚拟交易。

## 快速开始

```bash
cd /disk2/workingFolder/quant

# 查看系统状态
python3 main.py status

# 执行选股（Top 10）
python3 main.py pick --top 10

# 重置虚拟账户
python3 main.py pick --reset

# 查看今日报告
cat knowledge_base/daily_pick_$(date +%Y-%m-%d).md
```

## 系统架构

```
main.py pick
  └── global_stock_picker.py (选股入口)
        ├── factor_data.py (数据采集)
        │     ├── PriceVolumeFactors (价量因子 - K线数据)
        │     ├── FundamentalFactors (基本面因子)
        │     ├── SectorFactors (板块因子 - 本地行业映射+新浪行情)
        │     ├── SentimentFactors (市场情绪)
        │     ├── CapitalFactors (资金面 - 北向资金)
        │     └── FactorCollector (统一收集器)
        ├── factor_engine_v2.py (因子评分引擎)
        │     ├── TrendScorer (趋势 25%)
        │     ├── FundamentalScorer (基本面 25%)
        │     ├── ValuationScorer (估值 15%)
        │     ├── SectorScorer (板块 15%)
        │     ├── CapitalScorer (资金 10%)
        │     └── MomentumReversalScorer (动量/反转 10%)
        ├── strategies_v2/ (策略层 - 5策略)
        │     ├── trend_sector.py (趋势板块共振)
        │     ├── momentum_break.py (动量突破)
        │     ├── value_growth.py (价值成长)
        │     ├── oversold_bounce.py (超跌反弹)
        │     ├── capital_flow.py (资金流向)
        │     └── manager.py (策略管理器 - 合并/去重)
        └── trade_engine_v2.py (虚拟账户交易)
```

## 数据源

| 数据 | 来源 | 说明 |
|------|------|------|
| 日线K线 | BaoStock (data/kline/) | 历史数据 |
| 实时行情 | 新浪API (sina_fetcher.py) | 直连无需代理 |
| 行业分类 | data/stock_industry.json | 本地缓存，83个行业 |
| 北向资金 | 新浪API (已失效404) | 暂时不可用 |

## 核心文件

| 文件 | 作用 |
|------|------|
| `main.py` | CLI入口，`pick` 命令触发选股 |
| `global_stock_picker.py` | 选股主控，协调因子+策略+交易 |
| `factor_data.py` | 所有数据采集类 |
| `factor_engine_v2.py` | 多因子评分引擎 |
| `strategies_v2/` | 5个策略实现 |
| `trade_engine_v2.py` | 虚拟账户 (10万，万1免5，0.1%印花税) |
| `daily_runner_v2.py` | Cron定时任务入口 |
| `sina_fetcher.py` | 新浪实时行情抓取 |

## 数据存储

| 路径 | 内容 |
|------|------|
| `data/kline/` | 日线K线CSV |
| `data/stock_pool.json` | 股票池 |
| `data/stock_industry.json` | 行业映射 (code -> {industryName, name}) |
| `data/factor_cache/` | 因子缓存JSON |
| `knowledge_base/` | 每日选股报告 |
| `account_v2/` | 虚拟账户状态 |

## 交易规则

- 初始资金: 100,000元
- 手续费: 0.01% (免5, min_commission=0)
- 印花税: 0.1% (仅卖出)
- 最大持仓: 5只
- 单只最大仓位: 20%
- 硬止损: -7%
- 止盈: +15%
- 移动止盈: 回撤5%
- 最大持仓天数: 20个交易日

## 排除规则

- 科创板 (688/689开头)
- 北交所 (8/4开头)
- ST/*ST 股票
- 上市不足60天

## Cron 定时任务

- **A股每日9点选股** (c0ee6faf28d5): 周一至周五 09:00 自动运行 `daily_runner_v2.py`

## 常见故障

| 问题 | 原因 | 解决 |
|------|------|------|
| `unhashable type: 'dict'` | stock_industry.json嵌套dict未展平 | 确保 factor_engine_v2.py 已修复 |
| 板块数据为空 | `get_realtime_quotes()`返回DataFrame | 确保 factor_data.py 已修复 iterrows |
| 北向资金 404 | 新浪API失效 | 暂时跳过，不影响选股 |
| 选股结果为0 | 缓存过期或数据源异常 | `rm -f data/factor_cache/sector_*.json` |

## 修改策略后的流程

1. 修改 `strategies_v2/` 下策略文件
2. 清理缓存: `rm -rf /disk2/workingFolder/quant/strategies_v2/__pycache__`
3. 测试: `python3 main.py pick --top 5`
4. 查看报告: `cat knowledge_base/daily_pick_*.md`

## 转移注意事项

- 整个 `/disk2/workingFolder/quant/` 目录可直接迁移
- 所有数据、缓存、报告都在此目录下
- 需要 Python 3.11 + AKShare venv (venv_akshare/)
- Cron 任务需要在新环境重新设置
