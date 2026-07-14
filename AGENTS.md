# Trading Agents 项目上下文

本文件提供给在仓库中工作的代码 Agent。面向用户的说明以 `README.md` 和 `docs/` 为准。

## 项目目标

本地优先的 A 股量化研究、纸面交易与 Agent 复盘系统。当前不包含真实券商执行器，也不承诺盈利。

## 运行环境

- Python 3.11，固定依赖见 `requirements.txt`。
- Windows 使用 `venv_akshare\Scripts\python.exe`。
- Linux 使用 `venv_akshare/bin/python`。
- Dashboard 端口 5890。
- 数据源：本地日 K 为主，新浪全市场快照，BaoStock/AKShare 用于股票池或历史补库。

不要使用存在 NumPy/Pandas ABI 冲突的系统 Python。

## 核心数据流

```text
daily_runner_v2.py
  -> global_stock_picker.py
     -> factor_data.py + factor_engine_v2.py
     -> strategies_v2/
     -> kline_health.py 数据门禁
     -> trade_engine_v2.py
     -> paper_trading_v2.py
  -> agent_runtime/trading_memory_bridge.py

main.py agent review
  -> core/market_state.py
  -> agent_runtime/agents/reviewer.py
  -> core/memory.py + agent_runtime/memory_store.py
```

## 关键边界

- Agent 只做研究、归因和建议，不能绕过确定性风控。
- `top_picks` 是推荐，`buy_picks` 是计划，`buy_actions` 才是成交。
- `preview_only` 模式必须保持实际买卖动作为空。
- 回测与纸面交易必须共用 `strategies_v2/trade_config.py` 和 `trade_engine_v2.py` 的规则。
- 数据覆盖率或新鲜度不达标时禁止新增仓位。
- `simulated_backfill` 不得进入真实统计或 Agent 结论。

## 目录职责

- `agent_runtime/`：Agent 编排、Reviewer、事件存储、记忆桥。
- `core/`：交易记忆和市场状态。
- `dashboard/`：Flask API 与五页前端。
- `strategies_v2/`：六策略、组合配置、交易参数。
- `scripts/`：安装、调度、检查、数据和模型工具。
- `docs/`：用户安装、架构、运维、数据与风险文档。
- 根目录：兼容 CLI/调度的入口与核心引擎。

## 运行态

以下内容不得提交：

- `.env`、`config/llm_config.json`
- `account/`、`state/`、`logs/`
- `data/kline/`、分钟线、模型、新闻和缓存
- `knowledge_base/*.db`、每日推荐和日报
- 非基准回测产物

## 修改后的最低验证

```bash
python -m compileall -q .
python -m unittest discover -s tests -v
python scripts/smoke_check.py
python main.py doctor
```

修改 Dashboard 后必须重启 Flask，并检查：

```text
/api/dashboard/workspace
/api/dashboard/strategy_center
/api/dashboard/memory_center
/api/memory/health
```

修改策略后必须运行固定区间回测，与 `reports/backtest_v2/summary_benchmark.json` 对比收益、回撤、Sharpe 和交易数。
