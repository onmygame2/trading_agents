# Contributing

感谢参与改进 Trading Agents。

## 开发流程

1. 从 `main` 创建主题分支。
2. 使用 Python 3.11 创建独立虚拟环境并安装 `requirements.txt`。
3. 不提交 `.env`、账户、日志、K 线、SQLite 数据库或其他本地运行态。
4. 修改交易规则时，同时检查纸面交易与 `backtest_v2.py` 的行为。
5. 运行下面的验证命令并在 PR 中记录结果。

```bash
python -m compileall -q .
python -m unittest discover -s tests -v
python scripts/smoke_check.py
```

策略变更还必须记录测试区间、交易数、收益、最大回撤、Sharpe 及相对固定基准的变化。

## 代码组织

- 用户文档放在 `docs/`，README 只保留项目总览和主要路径。
- 维护脚本放在 `scripts/`，不要继续向根目录添加一次性脚本。
- 策略放在 `strategies_v2/`，Agent 放在 `agent_runtime/`，共享记忆放在 `core/`。
- 根目录只保留兼容 CLI/调度入口和核心运行引擎。
- 测试放在 `tests/`。

## 代码边界

- Agent 可以生成研究结论和参数建议，不能绕过确定性风控直接下单。
- 推荐、计划和成交必须使用不同字段，不得用合成数据冒充真实运行结果。
- 新数据源必须声明时效、复权方式、失败降级和限流行为。
- 新配置不得包含密钥；只提交 `.env.example` 或配置示例。

## Pull Request

PR 应保持单一目的，并说明：

- 为什么需要改动；
- 影响的数据流或交易规则；
- 已运行的测试；
- 兼容性与迁移方式；
- 若涉及策略，列出基准差异。

## 风险说明

请勿在未经 OOS 验证、纸面观察和成交回写验证的情况下，将贡献代码直接用于真实资金交易。
