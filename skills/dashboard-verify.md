---
name: dashboard-verify
description: Verify A-Share Quant Dashboard after code changes — restart Flask, test all APIs, and check each tab renders correctly.
---

# Dashboard 自动验证流程

每次修改 `dashboard/app.py` 或 `dashboard/templates/index.html` 后，执行以下完整验证流程。

## 步骤 1: 检查文件修改是否生效

```bash
# 确认模板文件已更新
grep -c "switchTab\|tab-overview" /disk2/workingFolder/quant/dashboard/templates/index.html

# 确认 app.py 路由完整
grep -c "def api_" /disk2/workingFolder/quant/dashboard/app.py
```

## 步骤 2: 重启 Flask（必须）

Flask 不会自动重载模板，必须重启进程。

```bash
kill $(lsof -i :5890 -t) 2>/dev/null; sleep 1
cd /disk2/workingFolder/quant && nohup python dashboard/app.py > /tmp/dashboard.log 2>&1 &
sleep 3
lsof -i :5890 -t
```

如果 lsof 没有返回 PID，检查日志：`cat /tmp/dashboard.log`

## 步骤 3: 测试所有 API 端点

```bash
curl -s http://localhost:5890/api/summary | python -m json.tool | head -5
curl -s http://localhost:5890/api/picks | python -m json.tool | head -5
curl -s http://localhost:5890/api/holdings | python -m json.tool | head -5
curl -s http://localhost:5890/api/trades | python -m json.tool | head -5
curl -s http://localhost:5890/api/agents | python -m json.tool | head -5
curl -s http://localhost:5890/api/market_overview | python -m json.tool | head -5
curl -s http://localhost:5890/api/positions_monitor | python -m json.tool | head -5
curl -s http://localhost:5890/api/historical_picks | python -m json.tool | head -5
curl -s http://localhost:5890/api/market_news | python -m json.tool | head -5
```

所有 API 应该返回 JSON 数据。如果返回 500 错误，查看 `/tmp/dashboard.log`。

## 步骤 4: 浏览器验证每个 Tab

使用 browser 工具打开 `http://localhost:5890`，然后逐个点击 Tab 并截图验证：

| Tab | 验证要点 |
|-----|----------|
| 总览 | 显示大盘指数表格、热点板块表格、市场情绪卡片、AI 市场情绪卡片、今日选股概览 |
| 今日选股 | 显示选股日期、选股数量、AI 选股推荐表格（含代码/名称/策略/置信度/买入价/止损价/止盈价/无效价/盈亏比/技术面要点） |
| 持仓监控 | 显示持仓股票列表、当前价格、止损/止盈状态 |
| 历史选股 | 显示历史日期选择器、历史选股记录 |
| 交易记录 | 显示交易记录表格 |
| Agent 排名 | 显示 Agent 排名列表 |
| 市场资讯 | 显示新闻列表 |

每个 Tab 检查：
1. 页面内容是否正常显示
2. 表格是否有数据
3. 是否有 JavaScript 错误（browser_console 检查）

## 步骤 5: 检查常见错误

```bash
# 检查 Flask 日志是否有错误
grep -i "error\|traceback" /tmp/dashboard.log | tail -10

# 检查浏览器控制台是否有 JS 错误
# 使用 browser_console 工具
```

## 常见问题

| 问题 | 原因 | 修复 |
|------|------|------|
| Tab 切换后页面空白 | JS 错误导致 load* 函数崩溃 | 检查 browser_console |
| 修改后没有生效 | Flask 未重启 | 重启 Flask 进程 |
| API 返回 500 | Python 代码错误 | 查看 /tmp/dashboard.log traceback |
| 数据为空 | knowledge_base 中没有报告 | 运行 python daily_runner.py 生成数据 |

## 验证完成标准

- [ ] Flask 进程运行在端口 5890
- [ ] 所有 9 个 API 端点返回 JSON 数据（非 500 错误）
- [ ] 7 个 Tab 全部可以正常切换
- [ ] 每个 Tab 内容正确渲染，无空白区域
- [ ] 浏览器控制台无 JavaScript 错误