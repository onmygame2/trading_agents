# A股AI量化交易系统 - 完整规划 v2.1

## 当前状态

项目已有基础框架：5个策略、回测引擎、新浪数据源、Dashboard、虚拟账户等。
本规划在现有基础上，补齐AI分析模块、价格目标体系、自动化推送。

## 一、最新AI量化交易工具调研 (截至2026年5月)

### 1.1 有实战记录的开源框架

| 工具 | Stars | 特点 | 实战A股记录 | 适用性 |
|------|-------|------|------------|--------|
| **Qlib (微软)** | 16k+ | AI量化平台，因子挖掘+模型训练，LightGBM/Transformer | 多篇文章验证A股超额收益5-15%年化 | 高 - 已适配A股 |
| **FinRL** | 23k+ | 强化学习量化，DRL(PPO/A2C/SAC) | 论文+Kaggle竞赛，A股年化8-20% | 中 - 需改造 |
| **OpenBB** | 20k+ | 投资研究平台，多数据源整合 | 社区活跃，美股为主 | 低 - 偏美股 |
| **FreqTrade** | 37k+ | 加密货币策略框架 | 大量实盘用户，日频级别 | 中 - 需改A股 |
| **Backtrader** | 13k+ | Python回测框架 | 广泛使用，策略灵活 | 已有替代方案 |
| **Stable-Baselines3** | 11k+ | RL算法库(PPO/A2C/DQN) | 与FinRL配合使用 | 底层依赖 |
| **HuggingFace Transformers** | 120k+ | NLP+时间序列 | 新闻情感+时序预测 | 可用 |
| **PyTorch Forecasting** | 10k+ | 时序预测(TFT/N-BEATS/NBEATSx) | 价格/波动率预测 | 可用 |

### 1.2 国内AI量化实战

| 平台/工具 | 特点 | 实战情况 |
|----------|------|---------|
| 聚宽(JQData) | 内置ML因子，日活10万+ | 散户+半专业 |
| 米筐(RiceQuant) | AI策略模板 | 机构为主 |
| AKShare | 开源数据接口 | 数据获取 |
| Tushare | 金融数据社区 | 数据获取 |
| 个人方案 | Qlib因子+自研策略+新浪API | 最务实路线 |

### 1.3 LLM在量化中的应用

| 用途 | 工具 | 效果 |
|------|------|------|
| 财报摘要 | GPT/Claude + PDF解析 | 高质量摘要 |
| 新闻情感 | FinBERT/LLM | 准确率75-85% |
| 市场情绪 | LLM分析社交媒体 | 辅助信号 |
| 策略生成 | Codex/Claude Code | 可生成基础策略 |
| 回测分析 | LLM解读回测结果 | 发现模式+建议 |

### 1.4 我们的技术选型

基于现有基础设施：
- **核心策略**：保留5个策略（趋势跟踪、均值回归、动量突破、多因子、超跌反弹）
- **AI增强**：LLM市场分析 + 新闻情感 + 技术面综合
- **数据源**：新浪API（实时）+ BaoStock（历史）
- **推送**：Hermes聊天窗口（每日9:00）
- **不引入**：Qlib/FinRL（过重），专注现有策略优化+AI分析

## 二、系统架构

```
每日9:00推送流程:
1. 更新K线数据 (新浪日线)
2. 运行5个策略选股
3. AI分析市场概况
4. 综合生成选股报告
5. 推送Hermes聊天
```

### 2.1 目录结构

```
quant/
├── strategies/                 # 5个策略
│   ├── base.py                # 基类 (含价格目标)
│   ├── trend_following.py     # 趋势跟踪
│   ├── mean_reversion.py      # 均值回归
│   ├── momentum_breakout.py   # 动量突破
│   ├── multi_factor.py        # 多因子
│   └── oversold_bounce.py     # 超跌反弹
├── daily_runner.py            # 每日选股流水线
├── ai_analyzer.py             # [新增] AI市场分析
├── ai_stock_picker.py         # 已有，改造加入价格目标
├── sina_fetcher.py            # 新浪行情
├── update_kline_sina.py       # K线更新
├── dashboard/                 # Web仪表板
├── data/                      # 数据
│   ├── kline/
│   ├── fundamentals/
│   └── stock_pool.json
├── knowledge_base/            # [新增] 知识库
│   ├── ai_analysis_*.json     # AI分析记录
│   ├── daily_picks_*.json     # 每日选股
│   └── ai_tools.md            # AI工具文档
├── skills/                    # [新增] Skill文档
│   └── quant-trading.md       # 量化交易操作手册
├── account/                   # 虚拟账户
├── state/                     # 策略状态
└── reports/                   # 回测报告
```

## 三、价格目标体系

每个选股附带：
- buy_price: 建议买入价
- stop_loss: 止损价 (-7%)
- take_profit: 止盈价 (+15%)
- invalid_price: 失效价 (-10%)
- confidence: 置信度 (0-1)
- reasoning: 设定依据

## 四、交易规则

- 初始资金: 100,000元
- 手续费: 0.01% (免5, min=0)
- 印花税: 0.1% (仅卖出)
- 最大持仓: 5只
- 单只最大仓位: 20%
- 硬止损: -7%
- 止盈: +15%
- 移动止盈: 回撤5%
- 最大持仓天数: 20个交易日

### 排除规则
- 科创板 (688/689)
- 北交所 (8/4开头)
- ST/*ST 股票
- 上市不足60天

## 五、实施计划

### Phase 1: 基础建设
- [ ] 创建 skills/quant-trading.md (操作手册)
- [ ] 创建 knowledge_base/ 目录 + AI工具文档
- [ ] 改造 strategies/base.py 添加价格目标方法

### Phase 2: 价格目标体系
- [ ] 5个策略添加价格目标计算
- [ ] 改造 ai_stock_picker.py 整合价格目标
- [ ] 改造 Dashboard 展示价格目标

### Phase 3: AI分析模块
- [ ] 创建 ai_analyzer.py
- [ ] 集成到每日流程

### Phase 4: 自动化
- [ ] 配置Cron任务 (每日9:00)
- [ ] Hermes推送选股报告
- [ ] 端到端测试