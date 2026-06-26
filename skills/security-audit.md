---
name: security-audit
description: 安全合规审查：在涉及网络请求、爬虫、外部API调用、代码执行前进行安全与合法性检查。用于任何需要获取外部数据、爬取网页、下载代码、执行未经验证代码的场景。
---

# 安全合规审查

## 触发条件

在以下操作**之前**必须先执行本审查流程：
- 爬取网页内容 / 网页数据采集
- 调用外部 API（特别是未经白名单的）
- 下载并执行远程代码
- 管道输出到解释器（curl | python 等）
- 克隆第三方仓库并分析
- 访问金融数据接口

## 审查清单

### 1. 法律合规性
- [ ] 目标网站/服务是否有 robots.txt？是否允许爬取？
- [ ] 数据来源是否明确授权？（如 AKShare 是开源合法的数据封装库，GitHub API 是官方公开接口）
- [ ] 是否涉及个人隐私数据？
- [ ] 是否违反目标网站的服务条款？

### 2. 频率限制
- [ ] 是否遵守目标接口的 rate limit？
- [ ] 请求间隔是否 >= 1秒？（金融数据至少 2-3秒）
- [ ] 是否实现指数退避重试？

### 3. 代码执行安全
- [ ] 绝不允许 `curl | python3` 这种管道到解释器的操作
- [ ] 远程下载的内容必须先保存到文件，检查后再执行
- [ ] 优先使用 `--max-time` 和 `--connect-timeout` 限制网络超时

### 4. 数据使用
- [ ] 只采集公开、已授权的数据
- [ ] 不存储敏感凭证
- [ ] 金融数据仅用于分析，不用于欺诈

## 安全操作模板

### 正确的网络数据采集流程

```bash
# Step 1: 先检查 robots.txt（如果适用）
curl -sL --connect-timeout 10 --max-time 20 "https://example.com/robots.txt"

# Step 2: 下载到文件，不直接管道到解释器
curl -sL --connect-timeout 10 --max-time 30 \
  "https://api.example.com/data" \
  -o /tmp/downloaded_data.json

# Step 3: 检查文件内容
head -100 /tmp/downloaded_data.json

# Step 4: 确认安全后再处理
python3 /path/to/your/script.py /tmp/downloaded_data.json
```

### 正确的 GitHub 仓库分析流程

```bash
# Step 1: 使用官方 API（合法公开接口）
curl -sL --connect-timeout 10 --max-time 30 \
  "https://api.github.com/repos/owner/repo" \
  -o /tmp/repo_info.json

# Step 2: 下载 README
curl -sL --connect-timeout 10 --max-time 30 \
  "https://raw.githubusercontent.com/owner/repo/main/README.md" \
  -o /tmp/repo_readme.md

# Step 3: 读取分析（不调用管道）
cat /tmp/repo_readme.md
```

## 白名单数据源

以下数据源已确认为合法开源/官方API：
- AKShare (开源金融数据封装库)
- GitHub API (官方公开接口)
- GitHub Raw Content (raw.githubusercontent.com)
- 各交易所公开行情数据

## 禁止行为

- 管道远程内容到解释器：`curl | python3` (HIGH 风险)
- 无速率限制的批量爬取
- 绕过认证机制访问数据
- 存储或传输用户凭证
- 爬取个人数据或未公开信息

## 审查结论模板

```
审查结果: PASS / NEEDS_REVIEW / BLOCKED

风险点:
1. ...

建议措施:
1. ...
```
