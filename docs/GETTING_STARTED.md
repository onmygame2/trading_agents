# 安装与首次运行

## 环境要求

- Windows 10/11 或常见 Linux 发行版
- Python 3.11
- 可访问新浪、BaoStock 或 AKShare 数据接口的网络
- 建议至少 4 GB 可用磁盘空间保存日 K 缓存

不要使用系统中已混装多个 NumPy/Pandas 版本的 Python。项目固定 `numpy==1.26.4` 和 `pandas==2.2.2`，应始终从虚拟环境运行。

## Windows

```powershell
git clone https://github.com/onmygame2/trading_agents.git
cd trading_agents
powershell -ExecutionPolicy Bypass -File scripts/setup_windows.ps1
.\venv_akshare\Scripts\python.exe main.py doctor --fix
```

## Linux

```bash
git clone https://github.com/onmygame2/trading_agents.git
cd trading_agents
python3.11 -m venv venv_akshare
venv_akshare/bin/pip install --upgrade pip
venv_akshare/bin/pip install -r requirements.txt
venv_akshare/bin/python main.py doctor --fix
```

## 准备数据

```bash
python scripts/rebuild_stock_pool.py
python update_kline.py --init-missing --backend akshare
python update_kline.py --snapshot
```

首次补齐全部历史 K 线可能受到第三方接口限流。可以分批执行：

```bash
python update_kline.py --init-missing --top 200 --offset 0 --backend akshare
python update_kline.py --init-missing --top 200 --offset 200 --backend akshare
```

日常更新使用 `--snapshot`，通过全市场批量快照追加最近交易日，不需要逐股请求。

## 生成首日内容

```bash
python main.py doctor --fix --run-first-day
```

该命令会初始化组合账户、六个纸面账户、SQLite 记忆库，生成最新交易日的研究推荐和 Agent 日报。若当前不在交易时段，结果标记为 `preview_only`，实际买卖动作保持为空。

## 启动 Dashboard

```bash
python dashboard/app.py
```

浏览器访问 http://localhost:5890。正常情况下，工作台应显示：

- 当前账户和持仓；
- 最新推荐及执行状态；
- Agent 日报；
- 六个策略的纸面盘和回测对比；
- 数据、记忆和调度状态。

## 验收

```bash
python main.py doctor
python scripts/health_check.py
python scripts/smoke_check.py
```

`doctor` 的 `production_ready` 只有在基础账户、首日内容、K 线门槛和全部调度任务均满足时才为 `true`。

