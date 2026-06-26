# A股AI量化交易系统 - 项目上下文

这个文件是项目的完整上下文摘要。每次在这个目录下工作时，先读取它来了解项目状态。

## 一句话概括

基于A股历史数据的 v2 单账户隔夜量化选股系统，虚拟账户10万，万1免5佣金，排除科创板/北交所/ST，每日自动选股。

## 当前状态 (2026-06-03)

- Python 3.8 系统环境 + venv_akshare/ (Python 3.11, AKShare)
- 数据源: **iFind HTTP API** (优先) + 新浪 fallback
- 统一 Provider: `market_data.py` → `ifind_fetcher.py` / `sina_fetcher.py`
- 股票池: ~4361只 (沪深主板+创业板, 排除688/689/北交所/ST)
- K线: data/kline/ 日线 CSV; 分钟按需缓存 data/minute_kline/{code}/
- 统一过滤: market_filter.py (读 config/settings.yaml)
- Dashboard K线: 分时/日K/周K/月K 四档, 本地CSV优先
- 虚拟账户: account/account_state_v2.json
- Dashboard: Flask应用, 端口5890
- Cron: scripts/install_crontab.sh (08:30 K线 / 14:30 选股 / 09:30 卖出 / 周五优化)

## iFind 配置

1. 打开 iFinD 终端 → 超级命令 → 工具 → refresh_token 查询/更新
2. 复制 token 写入环境变量或 `.env`:
   ```bash
   cp .env.example .env
   # 编辑 .env: IFIND_REFRESH_TOKEN=...
   ```
3. 验证连通性: `python scripts/test_ifind_connection.py`
4. 切换 Provider: `config/settings.yaml` → `data.provider: ifind|sina`
5. 无 token 时自动降级新浪，日志标记 `[IFIND-FALLBACK-SINA]`

**注意**: `IFIND_REFRESH_TOKEN` 仅环境变量，勿提交 git (已在 .gitignore)

## 核心架构 (v2)

```
daily_runner_v2.py
  -> global_stock_picker.py
    -> factor_engine_v2.py + factor_data.py
    -> strategies_v2/ (5个filter)
    -> trade_engine_v2.py (虚拟账户)
  -> knowledge_base/daily_pick_*.json
  -> account/trade_log_v2.json
```

## 核心文件

| 文件 | 作用 |
|------|------|
| main.py | CLI入口: download/backtest/pick/run/status/optimize |
| daily_runner_v2.py | v2 Cron入口: 14:30选股 / 09:30卖出 |
| global_stock_picker.py | 选股核心: 因子评分+策略合并+交易 |
| factor_engine_v2.py | 六维因子评分引擎 |
| factor_data.py | 价量/板块/资金/情绪数据采集 |
| strategies_v2/ | 5个隔夜策略filter |
| trade_engine_v2.py | 虚拟交易引擎 (T+1/止损止盈) |
| backtest_overnight.py | v2隔夜策略回测 |
| optimize_weekly.py | 周五策略回测优化 |
| monitor.py | 盘中监控 (check/morning/review) |
| trading_calendar.py | A股交易日历 |
| market_filter.py | 统一市场范围过滤 (settings.yaml) |
| kline_service.py | K线访问层: 日/周/月本地CSV, 分钟按需 |
| stock_pool_builder.py | 股票池候选集 (iFind/BaoStock) |
| scripts/rebuild_stock_pool.py | 重建股票池 |
| scripts/audit_stock_pool.py | 股票池审计 diff |
| update_kline.py | K线增量/初始化 (--init-missing) |
| ifind_fetcher.py | iFind HTTP API 数据获取 |
| market_data.py | 统一 Provider 工厂 |
| sina_fetcher.py | 新浪 API (fallback) |
| dashboard/app.py | Web Dashboard |

## 当前状态 (2026-06-17) — 全策略跟踪版

- **6 策略独立跟踪**：各自回测 + 纸面账户（各 10 万）
- **组合账户 (composite)**：实盘主账户；仅纳入回测正收益策略，按 `weight` 加权合并买入
- **调权重**：修改 `strategies_v2/*.py` 的 `weight` 字段即可影响组合配额
- **回测区间**: 2024-01-01 ~ 2025-12-31 训练验证 | 2026-01-01 起实测
- **DL模型**: 104k样本 (2024-2025) → `data/ml_models/dl_factor_mlp.npz`
- **消息面**: `message_screener.py` (财报YOYNI/ROE + 板块热度 + 新闻缓存)

### 核心策略原理 (2026-06 调研结论)

回测数据证明本策略本质是 **「分散下注 + 涨停基因过滤 + 截断亏损/让盈利奔跑」** 的动量彩票策略，
入场信号(龙回头形态)对单笔胜负无预测力，盈利来自:

1. **涨停基因硬门槛**: 近180日有过涨停才入选。无基因股票回测胜率仅11%/净亏4.3万，有基因42%/净盈4.7万
2. **5仓分散**: 5个递减权重仓位(24/22/20/18/16%)。2→3→5仓收益+23%→+36%→+52%，6仓过度分散回落
3. **涨停继续持股 + 72%止盈 + 12%移动止盈**: 让少数大牛奔跑，单笔可贡献+70%

## 2024-2025 回测 (主线池, 5仓/无冷却/涨停持股)

| 指标 | 数值 |
|------|------|
| 总收益 | **+51.79%** |
| CAGR | **+23.24%** |
| Sharpe | **0.87** |
| 最大回撤 | -35.07% |
| 盈亏比 | 1.30 |
| 胜率 | 36.3% |
| 交易数 | 190 |

命令: `./scripts/run_with_venv.sh backtest_v2.py --start 2024-01-01 --end 2025-12-31 --pool-mode mainline --top-n 5`

**固定基准**: `reports/backtest_v2/summary_benchmark.json` (跑满2年自动更新)。
**改策略后必须对比此基准，避免「改一行掉50个点」不自知。**

**注意**: 最大回撤 -35% 偏大；2026 实测需每日 `python main.py pick` 验证。

## v2 策略状态

| 策略 | 状态 | weight | 说明 |
|------|------|--------|------|
| oversold_reversal | **启用** | 1.0 | 涨停基因龙回头，组合核心 |
| breakout_setup | **启用** | 1.15 | 突破蓄势，独立跟踪 |
| mainline_leader | **启用** | 1.1 | 主线龙头，独立跟踪 |
| late_session_surge | **启用** | 1.05 | 尾盘强收抢筹（原隔夜抢筹已合并移除） |
| sector_leader | **启用** | 1.0 | 板块龙头，独立跟踪 |
| small_cap_volatil | **启用** | 0.95 | 小盘强势，独立跟踪 |

## Dashboard

- 代码: dashboard/app.py + dashboard/templates/index.html
- K线周期: **分时 / 日K / 周K / 月K** (默认日K, 分时按需)
- 日K点击某根K线 → 查看该日分时 (触发 iFind/缓存)
- API: `/api/kline` (本地CSV), `/api/intraday` (按需分钟)
- 启动: `cd /disk2/workingFolder/quant && python dashboard/app.py`
- 访问: http://localhost:5890
- **修改dashboard代码后必须重启Flask进程**

## 交易规则 (2026-06 实盘版，回测=实盘统一)

- 初始资金: 100,000元
- 手续费: 0.01% (免5) | 印花税: 0.1% (仅卖出)
- **最大持仓: 5只** (递减权重 24/22/20/18/16%)
- **硬止损: -8%**
- **止盈: +72%** (让大牛奔跑，靠移动止盈兜底)
- **移动止盈: 峰值盈利≥3%后，回撤12%卖出**
- **最长持仓: 32个交易日**
- **涨停继续持股** (连续涨停≤5天)
- T+1: 买入当日不可卖出
- 参数定义在 `strategies_v2/trade_config.py` 的 `AGGRESSIVE_RULES`，回测与 `trade_engine_v2` 共用

## 排除规则

- 北交所 (8开头/4开头)
- ST/*ST 股票
- **大盘蓝筹/银行保险地产** (市值>420亿 或 国有大行，见 `mainline_pool.EXCLUDE_CODES`)
- 科创板 (688/689) **已纳入** (settings.yaml)
- **无涨停基因股票** (近180日无涨停，硬过滤)

## 自动调度 (Cron)

工作日自动运行，无需手动操作:

| 时间 | 任务 |
|------|------|
| 08:30 | 更新K线 |
| **9:30-15:00 每30分钟** | **盘中交易 (先卖后买)** |
| 周五 20:00 | 策略回测优化 |

安装: `bash scripts/install_crontab.sh`（Cron 经 `scripts/run_with_venv.sh` 使用 `venv_akshare/bin/python`）  
日志: `logs/daily_pick.log` / `logs/daily_sell.log`

**Dashboard 手动触发**: 总览 / 今日选股 / 运维中心 → 「立即选股」「卖出检查」

```bash
cd /disk2/workingFolder/quant

# 查看状态 (含v2账户)
python main.py status

# 重建股票池 (扩池后首次)
python scripts/rebuild_stock_pool.py
python scripts/audit_stock_pool.py

# 为新股票初始化120日K线 (约4300次API, 建议分批)
python update_kline.py --init-missing --top 100
python update_kline.py --init-missing   # 全量

# 更新K线 (增量)
python update_kline.py

# 测试 iFind 连通性
python scripts/test_ifind_connection.py

# v2 选股+买入
python main.py pick
python daily_runner_v2.py

# 次日卖出
python daily_runner_v2.py --sell-only

# v2 统一回测
python backtest_v2.py --start 2024-01-01 --end 2024-12-31 --pool-top 500

# 周优化
python optimize_weekly.py

# 监控
python main.py monitor check

# 启动Dashboard
python dashboard/app.py

# 安装Cron
bash scripts/install_crontab.sh
```

## 已删除/废弃

- `legacy/`, `strategies/` (旧5策略), `strategies_runner.py`, `strategy_account.py`
- `boss_agent.py` / `agents/` / `daily_pipeline.py` 等10-Agent架构
- 根目录 `_*.py` 临时脚本、`optimize_strategies.py`、`optimizer.py`

## 工作流

1. 08:30 更新K线 -> 盘中每30分钟自动卖+买 -> Dashboard查看
2. 强信号出现即可成交，不限 14:30 / 9:30
3. 周五 20:00 策略回测优化
4. 修改策略 -> backtest_overnight 验证 -> pick 试运行
