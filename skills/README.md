# 量化系统 Skill 索引

所有Skill已迁移到 Hermes Agent 技能系统，以下是索引：

## 核心Skill

| Skill | 说明 | 触发词 |
|-------|------|--------|
| `quant-quick-start` | 快速上手：核心命令、目录结构、状态查询 | "量化"、"status"、"怎么开始" |
| `quant-data` | 数据管理：K线下载、股票池、新浪API、AKShare | "下载数据"、"股票池"、"数据源" |
| `quant-trading` | 交易操作：Boss Agent、账户管理、交易规则 | "运行交易"、"Boss Agent"、"清空状态" |
| `quant-strategies` | 策略管理：10策略Agent、因子引擎、修改策略 | "策略"、"Agent"、"因子"、"修改策略" |
| `quant-dashboard` | Dashboard：Flask启动、K线图、前端修改 | "dashboard"、"仪表盘"、"K线图" |
| `quant-workflow` | 每日工作流：早盘/盘中/盘后、飞书、cron | "早盘"、"飞书"、"定时任务"、"报告" |
| `quant-backtest` | 回测与优化：回测引擎、性能指标、周度优化 | "回测"、"优化"、"排名" |
| `quant-troubleshoot` | 故障排查：已知Bug、常见错误、修复记录 | "报错"、"bug"、"不工作"、"崩溃" |

## 本地文件

| 文件 | 说明 |
|------|------|
| `ai-quant-trading.md` | AI量化工具调研文档 (知识库) |
| `security-audit.md` | 安全合规审查清单 |
| `quant-research-data.json` | AI工具调研原始数据 |
| `quant-research-report.md` | AI工具调研报告 |

## 注意事项

- 所有Skill通过 Hermes Agent 自动加载，不需要手动读取本目录
- 修改策略后记得运行 `quant-strategies` 中的工作流
- 修改dashboard后记得 `pkill -f "python dashboard/app.py" && python dashboard/app.py`
