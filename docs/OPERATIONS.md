# 日常运行与排错

## 自动任务

Windows：

```powershell
powershell -ExecutionPolicy Bypass -File scripts/install_windows_tasks.ps1
```

Linux：

```bash
bash scripts/install_crontab.sh
```

默认任务链：

- 08:30：使用全市场快照更新日 K。
- 09:30–15:00：交易时段每 30 分钟先卖后买。
- 15:15：记录市场状态并生成 Agent 日报。
- 周五 20:00：运行策略优化。

`daily_runner_v2.py` 会检查交易日和交易时段，即使操作系统误触发也不会在非交易时段成交。

## 常用命令

```bash
python main.py status
python main.py doctor
python main.py pick --top 10
python daily_runner_v2.py
python daily_runner_v2.py --sell-only
python main.py agent review
python main.py backtest --start 2024-01-01 --end 2025-12-31
python main.py rank
```

## 日志

- `logs/kline_update.log`：日 K 快照。
- `logs/intraday.log`：盘中交易。
- `logs/agent_review.log`：Agent 复盘。
- `logs/weekly_opt.log`：周优化。

Dashboard 运维中心也会显示安装状态、上次运行时间、日志尾部和最近错误。

## 常见问题

### NumPy/Pandas ABI 错误

若出现 `numpy.dtype size changed`，说明运行了错误的 Python。使用：

```powershell
.\venv_akshare\Scripts\python.exe scripts\smoke_check.py
```

不要在损坏的系统 Python 中继续安装覆盖依赖。

### K 线历史接口超时

日常更新应使用：

```bash
python update_kline.py --snapshot
```

`akshare` 和 `baostock` 后端主要用于首次历史补库。上游不可用时，数据门禁会禁止新增仓位。

### Dashboard 内容为空

```bash
python main.py doctor --fix --run-first-day
```

随后检查 `/api/dashboard/workspace`。首日非交易时段只会出现研究推荐，不会出现成交。

### Dashboard 代码更新后仍显示旧内容

确保端口 5890 只有一个 Flask 进程，并使用项目虚拟环境重启 `dashboard/app.py`。

### 调度未安装

`python main.py doctor` 会列出安装提示。Windows 需要当前用户具备创建任务计划的权限；Linux 用户需要可写入自身 crontab。

## 备份

账户、记忆库和状态属于本地运行态。升级前至少备份：

```text
account/
knowledge_base/*.db
state/
config/llm_config.json
```

不要把这些文件提交到公开仓库。

