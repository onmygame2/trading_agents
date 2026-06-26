# A股AI量化交易系统 - 总体规划

> 创建: 2026-05-21
> 目标: 基于现有系统构建全天候A股AI量化交易分析平台
> 约束: 虚拟账户10万，万1免5，排除科创板/北交所/ST

---

## 一、系统定位

**你是谁:** Boss，管理10个Agent"员工"，每个独立10万资金（总计100万虚拟）
**做什么:** 全天候分析A股市场，每日09:00推送选股报告
**怎么做:** 技术分析 + 基本面 + 情绪分析 + AI辅助决策

---

## 二、现有系统状态

### 已具备的能力
- [x] 1039只股票K线数据 (2024-01-02 ~ 2026-05-14)
- [x] 10策略Agent架构 (boss_agent.py + agents/)
- [x] Flask Dashboard (端口5890，零外部CDN)
- [x] 飞书通知集成
- [x] 新浪财经实时数据 (直连可用)
- [x] 基本面数据缓存 (BaoStock)
- [x] 市场新闻模块 (market_news.py)
- [x] 纯NumPy ML选股器 (ml_stock_selector.py)
- [x] 15+ Alpha因子引擎 (factor_engine.py)
- [x] Boss优化器 (自动调整Agent权重)

### 需要改进的
- [ ] 数据更新自动化 (当前停在2026-05-14)
- [ ] 情绪分析打分 (当前仅提取新闻标题)
- [ ] 股票池自动维护 (ST/新上市过滤)
- [ ] 因子库增强 (引入Qlib核心因子)
- [ ] ML模型定期重训
- [ ] 24/7全天候监控调度
- [ ] 知识库统一整理

---

## 三、10策略Agent一览

| Agent | 策略 | Tech/Fund/Sent | 特点 |
|-------|------|---------------|------|
| trend_hunter | 趋势跟踪 | 0.5/0.3/0.2 | 均线多头 + MACD + 放量突破 |
| contrarian | 均值回归 | 0.45/0.35/0.2 | 超卖反弹 + 布林带 + 底部放量 |
| momentum_scalper | 动量突破 | 0.6/0.15/0.25 | N日新高 + 放量 + 强势动量 |
| sector_alpha | 板块轮动 | 0.3/0.25/0.45 | 热点板块 + 动量领先 |
| grid_master | 网格交易 | 0.55/0.3/0.15 | 震荡市 + 机械执行 |
| dragon_king | 龙回头 | 0.65/0.15/0.2 | 强势股回调 + 缩量企稳 |
| tech_surge | 量价共振 | 0.55/0.2/0.25 | 放量突破 + MACD配合 |
| close_sniper | 尾盘策略 | 0.6/0.15/0.25 | 尾盘拉升 + 次日溢价 |
| value_guard | 多因子 | 0.25/0.55/0.2 | 低估值 + 高ROE + 财务健康 |
| dividend_king | 超跌反弹 | 0.2/0.6/0.2 | 高分红 + 防御配置 |

---

## 四、交易规则

- 初始资金: ¥100,000 (每Agent独立)
- 手续费: 0.01% 万1免5 (min_commission=0)
- 印花税: 0.1% (仅卖出)
- 最大持仓: 5只
- 单只最大仓位: 20%
- 硬止损: -7%
- 止盈: +15%
- 移动止盈: 回撤5%
- 最大持仓天数: 20个交易日
- 排除: 科创板(688/689)、北交所(83/87/43)、ST/*ST、上市<60天

---

## 五、核心文件

| 文件 | 作用 |
|------|------|
| boss_agent.py | Boss调度器 (10Agent各10万) |
| daily_pipeline.py | 统一账户流水线 |
| main.py | CLI入口 |
| dashboard/app.py | Flask Dashboard后端 |
| dashboard/templates/index.html | Dashboard前端 |
| market_news.py | 市场新闻获取 |
| factor_engine.py | 15+ Alpha因子 |
| ml_stock_selector.py | ML选股器 |
| sina_fetcher.py | 新浪实时数据 |
| fundamental_loader.py | 基本面数据 |
| sector_sentiment.py | 板块情绪分析 |
| monitor.py | 盘中监控 |
| feishu_notify.py | 飞书通知 |
| boss_optimizer.py | Agent权重优化 |

---

## 六、实施路线图

### 阶段0: 知识库整理 (2026-05-21)

**目标:** 建立清晰的文档体系

- [x] AI量化工具调研 (research_report_2026.md)
- [ ] 创建 PLANNING.md (本文件)
- [ ] 统一 skills/quant-system.md
- [ ] 更新 knowledge_base/ai_tools_2026.md

### 阶段1: 数据层加固

**目标:** 数据自动更新 + 质量保障

- [ ] 每日盘后自动更新K线数据 (update_kline_data.py)
- [ ] 实时数据增强 (扩展sina_fetcher)
- [ ] 新闻情绪打分引擎 (market_news.py 增强)
- [ ] 股票池自动维护 (ST/新上市/退市过滤)
- [ ] 数据健康检查脚本

### 阶段2: 策略层优化

**目标:** 增强选股能力和风控

- [ ] Qlib风格因子增强 (动量/反转/波动率/换手率)
- [ ] ML选股器重训 (使用最新数据)
- [ ] Boss优化器改进 (更智能的权重调整)
- [ ] 策略回测验证 (2024-2026全量数据)
- [ ] 风控强制执行 (止损/仓位/熔断)

### 阶段3: 全天候监控

**目标:** 自动化运行

- [ ] 早盘08:30: 数据更新 + 选股 + 飞书推送
- [ ] 盘中09:30-14:30: 每30分钟持仓检查
- [ ] 盘后15:10: 日报 + 复盘
- [ ] 周五20:00: 周度优化
- [ ] Dashboard实时刷新

### 阶段4: AI增强 (持续迭代)

**目标:** 利用AI提升分析质量

- [ ] LLM市场解读 (结合新闻 + 技术指标)
- [ ] 情绪分析模型 (Chinese-Roberta)
- [ ] 策略自动发现 (基于历史表现)
- [ ] 智能风险提示

---

## 七、最新AI量化工具参考

详见: research_report_2026.md

核心推荐:
1. **vnpy** (40,762 stars) - 实盘交易框架
2. **Qlib** (微软) - AI量化平台
3. **FinRL** (15,196 stars) - 强化学习交易
4. **easytrader** (9,756 stars) - 低门槛实盘
5. **AkShare** (已安装) - A股数据源

---

## 八、Cron定时任务

| 任务 | 时间 | Job ID |
|------|------|--------|
| 早盘选股 | 工作日 08:30 | (待设置) |
| 盘中监控 | 09:00-14:30 每30min | (待设置) |
| 盘后复盘 | 工作日 15:10 | (待设置) |
| 周度优化 | 周五 20:00 | (待设置) |

---

## 九、目录结构

```
/disk2/workingFolder/quant/
├── PLANNING.md                  # 总体规划 (本文件)
├── research_report_2026.md      # AI工具调研
├── AGENTS.md                    # 项目上下文
├── knowledge_base/              # 知识库
│   ├── ai_tools_2026.md         # AI工具参考
│   └── boss_report_*.json       # 每日报告
├── skills/                      # 本地Skill文档
│   └── quant-system.md          # 系统操作指南
├── agents/                      # 10策略Agent
├── dashboard/                   # Flask Dashboard
├── data/                        # 数据缓存
│   ├── kline/                   # K线CSV (1039只)
│   ├── fundamentals/            # 基本面JSON
│   ├── stock_pool.json          # 股票池
│   └── news/                    # 新闻缓存
├── state/                       # Agent状态
├── account/                     # 虚拟账户
├── reports/                     # 回测/选股报告
├── optimization/                # 策略优化结果
├── boss_optimizer/              # 优化器状态
├── venv_akshare/                # Python 3.11环境
└── *.py                         # 核心Python模块
```

---

## 十、快速命令

```bash
cd /disk2/workingFolder/quant

# 查看状态
python main.py status

# 运行Boss Agent (10策略)
python boss_agent.py --date 2026-05-21

# 选股扫描
python main.py scan --top 10

# 启动Dashboard
python dashboard/app.py

# 访问Dashboard
http://localhost:5890
```

---

## 十一、环境说明

- 系统Python: 3.8.17
- AKShare环境: venv_akshare/ (Python 3.11)
- 无PyTorch/TensorFlow (后续需安装)
- 网络: 中国服务器，CDN不可用，新浪API直连
- 代理: http://127.0.0.1:1935 (部分API被拦截)
