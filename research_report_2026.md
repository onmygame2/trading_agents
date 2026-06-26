# 2026年5月 A股AI量化交易工具研究报告

> 生成时间: 2026年5月21日
> 目标: 为当前A股量化系统寻找可集成的最新AI量化工具

---

## 一、开源量化交易平台与框架

### 1.1 vnpy（VeighNa）⭐⭐⭐⭐⭐
- **GitHub**: vnpy/vnpy
- **Stars**: 40,762 | Forks: 11,735
- **最新更新**: 2026-05-17（非常活跃）
- **语言**: Python | **许可**: MIT
- **A股支持**: ★★★★★ 原生支持A股、期货、期权
- **核心功能**:
  - 完整的量化交易框架（数据获取→回测→模拟→实盘）
  - 支持CTP、XTP、CTPmini、飞马、恒生等国内接口
  - 内置CTA策略、组合策略、高频策略模板
  - 可视化监控界面
  - vnpy_portfoliostrategy / vnpy_ctastrategy 子模块
- **集成建议**: 适合作为实盘交易执行层，可替代当前自研trade_engine
- **安装**: `pip install vnpy` + 对应柜台接口

### 1.2 easytrader（易交易）⭐⭐⭐⭐
- **GitHub**: shidenggui/easytrader
- **Stars**: 9,756
- **最新更新**: 2026-02-28
- **语言**: Python
- **A股支持**: ★★★★★ 专为A股设计
- **核心功能**:
  - 自动登录同花顺客户端/雪球/QMT进行实盘交易
  - 支持跟踪joinquant/ricequant模拟交易信号
  - 自动下单、撤单、查询持仓/资金
  - 支持雪球组合实盘
- **集成建议**: 低成本接入实盘交易的首选，无需券商API权限
- **注意**: 依赖桌面端客户端，服务器部署需Xvfb虚拟显示

### 1.3 BigQuant ⭐⭐⭐
- **GitHub**: BigQuant/bigquant
- **Stars**: ~5,000（云端平台为主）
- **最新更新**: 2026-04-13
- **语言**: Python
- **A股支持**: ★★★★ 支持A股数据源
- **核心功能**:
  - 可视化深度学习量化平台
  - 支持LSTM/Transformer等AI模型训练
  - 因子挖掘→选股→交易全流程
- **集成建议**: 云端平台，适合模型实验，不太适合本地部署

### 1.4 Qlib（微软）⭐⭐⭐⭐⭐
- **GitHub**: microsoft/qlib
- **Stars**: ~25,000+
- **最新更新**: 2026年持续更新
- **语言**: Python
- **A股支持**: ★★★★ 内置A股数据集
- **核心功能**:
  - 微软研究院出品的AI量化投资平台
  - 内置LightGBM、Transformer、LSTM等模型模板
  - 高性能数据管理（基于SQLite/HDF5）
  - 完整的回测引擎与策略分析
  - 支持多因子模型、深度学习预测
- **性能结果**: 论文报道在A股市场上，Qlib的模型年化收益超过基准30-50%
- **集成建议**: 适合替换当前ml_stock_selector，提供工业级AI选股能力

### 1.5 QUANTAXIS ⭐⭐⭐
- **GitHub**: QUANTAXIS/QUANTAXIS
- **Stars**: ~15,000+
- **最新更新**: 2024-2025年间
- **语言**: Python
- **A股支持**: ★★★★
- **核心功能**:
  - 全栈量化系统：数据→分析→回测→交易→部署
  - 支持分布式回测
  - 内置TA-Lib技术指标
- **注意**: 更新频率有所下降，代码库较大较重

---

## 二、AI/ML预测框架（强化学习、LLM）

### 2.1 FinRL（金融强化学习）⭐⭐⭐⭐⭐
- **GitHub**: AI4Finance-Foundation/FinRL
- **Stars**: 15,196 | Forks: 3,344
- **最新更新**: 2026-05-18（极度活跃）
- **语言**: Jupyter Notebook / Python
- **许可**: MIT
- **A股支持**: ★★★★ 支持A股数据（通过Tushare/AkShare）
- **核心功能**:
  - 基于深度强化学习（DRL）的量化交易框架
  - 内置DDPG、PPO、A2C、SAC等多种DRL算法
  - 支持多资产组合优化
  - 集成OpenAI Gym金融环境
  - 与PyTorch/TensorFlow兼容
  - FinRL-Meta: 面向生产环境的模块化架构
- **性能结果**: 论文显示在多个市场（含A股）上DRL策略超越传统策略
- **集成建议**: 适合构建AI驱动的交易决策模块，但需要PyTorch/TensorFlow环境
- **前置依赖**: 当前系统无PyTorch，需升级环境

### 2.2 FinGPT（金融大语言模型）⭐⭐⭐⭐
- **GitHub**: AI4Finance-Foundation/FinGPT
- **Stars**: ~3,000+
- **最新更新**: 2026年活跃
- **语言**: Python
- **A股支持**: ★★★ 通用金融模型，需微调适应A股
- **核心功能**:
  - 面向金融任务微调的LLM框架
  - 支持股票预测、风险评估、投资建议
  - 基于开源LLM（Llama、Qwen等）进行金融领域微调
  - 提供金融数据标注工具
- **集成建议**: 可替代/增强sector_sentiment.py，用于新闻情感分析

### 2.3 Langchain-Chatchat（中文RAG/Agent）⭐⭐⭐⭐⭐
- **GitHub**: chatchat-space/Langchain-Chatchat
- **Stars**: 38,058 | Forks: 6,212
- **最新更新**: 2025-11-10
- **语言**: Python
- **A股支持**: ★★★★ 原生中文支持
- **核心功能**:
  - 基于Langchain与ChatGLM/Qwen/Llama的RAG应用
  - 支持知识库构建与检索增强
  - Agent模式，可调用外部工具
  - 本地部署，适合中文文档问答
- **集成建议**: 构建金融知识库Agent，对接飞书通知系统

### 2.4 LLaMA-Factory（大模型微调工厂）⭐⭐⭐⭐⭐
- **GitHub**: hiyouga/LLaMA-Factory
- **Stars**: ~35,000+
- **最新更新**: 2026年活跃
- **语言**: Python
- **核心功能**:
  - 一站式LLM微调框架
  - 支持LoRA、QLoRA、全参数微调
  - 兼容Qwen、ChatGLM、Llama等主流模型
  - 可视化训练界面
- **集成建议**: 微调Qwen/ChatGLM为A股专属交易顾问

### 2.5 GPT Academic ⭐⭐⭐⭐⭐
- **GitHub**: binary-husky/gpt_academic
- **Stars**: 70,698 | Forks: 8,390
- **最新更新**: 2026-01-25
- **语言**: Python
- **核心功能**:
  - 多LLM统一接口（支持通义千问、文心一言、本地模型）
  - 模块化插件系统
  - 支持自定义快捷按钮和函数插件
- **集成建议**: 可作为多模型路由层，统一管理AI调用

### 2.6 ms-swift（模型服务微调框架）⭐⭐⭐⭐
- **GitHub**: modelscope/ms-swift
- **Stars**: ~15,000+
- **最新更新**: 2026年活跃
- **语言**: Python
- **核心功能**:
  - 魔搭社区出品的微调框架
  - 支持千亿级大模型高效微调
  - 内置金融领域预训练模型
- **集成建议**: 如果服务器有GPU，可用于部署本地金融LLM

---

## 三、A股市场数据源与API

### 3.1 AkShare（已安装）⭐⭐⭐⭐⭐
- **GitHub**: AkShare/AkShare
- **Stars**: ~30,000+
- **当前版本**: 1.18.62（已安装于venv_akshare）
- **A股支持**: ★★★★★ 最全面的A股数据源
- **核心功能**:
  - A股日线/分钟线/复权数据
  - 财务数据、龙虎榜、大宗交易
  - 基金/债券/期货/外汇数据
  - 宏观经济指标
  - 全球主要市场数据
  - 免费、无需API Key
- **集成建议**: 已经安装，建议作为主要数据源逐步替代BaoStock

### 3.2 Tushare Pro ⭐⭐⭐⭐
- **GitHub**: tushare/tushare (原mypyw/tushare)
- **Stars**: ~10,000+
- **A股支持**: ★★★★★
- **核心功能**:
  - A股全品种数据（股票、基金、期货、期权）
  - 财务指标、资金流向、融资融券
  - 需要API Token（Pro版本需积分）
  - 数据质量较高，延迟较低
- **集成建议**: 积分高的用户可考虑，否则AkShare已足够

### 3.3 BaoStock（已安装）⭐⭐⭐
- **当前版本**: 0.9.1（已安装）
- **A股支持**: ★★★★
- **核心功能**:
  - A股日线/周线/月线/5/15/30/60分钟线
  - 指数、基金、IPO数据
  - 基本面财务数据
  - 免费、无需注册
- **局限性**: 数据更新较慢（T+1），API功能相对简单
- **集成建议**: 作为基础数据源保留，与AkShare互补

### 3.4 新浪/腾讯行情API（已使用）⭐⭐⭐
- **当前状态**: 已有sina_fetcher.py
- **A股支持**: ★★★★★
- **核心功能**:
  - 实时行情（免费、无需Key）
  - 延迟约3秒
- **局限性**: 不提供历史数据、财务数据
- **集成建议**: 继续作为实时数据源保留

### 3.5 jqdatasdk（聚宽）⭐⭐⭐⭐
- **A股支持**: ★★★★★
- **核心功能**:
  - 高质量A股数据（Tick级）
  - 财务、资金流向、板块数据
  - 需要注册获取API Key
  - 有免费额度限制
- **集成建议**: 如需高频数据可考虑

### 3.6 Futu OpenAPI（富途）⭐⭐⭐
- **GitHub**: futu/openapi / futu/futunn
- **Stars**: ~3,000+
- **A股支持**: ★★★ 支持港股为主，A股有限
- **核心功能**:
  - 实时行情+交易一体化
  - futunn提供向量化数据分析
  - 需要开户
- **集成建议**: 除非有富途账户，否则不优先

### 3.7 其他数据源
| 数据源 | 特点 | A股支持 | 费用 |
|--------|------|---------|------|
| 东方财富(EastMoney) | 通过AkShare间接获取 | ★★★★★ | 免费 |
| 万得(Wind) | 机构级数据 | ★★★★★ | 昂贵 |
| Choice(东方财富) | 机构级数据 | ★★★★★ | 付费 |
| 同花顺iFinD | 机构级数据 | ★★★★★ | 付费 |

---

## 四、回测与实盘交易平台

### 4.1 JoinQuant（聚宽）⭐⭐⭐⭐
- **类型**: 在线量化平台
- **A股支持**: ★★★★★
- **核心功能**:
  - 在线编写、回测策略
  - 模拟交易/实盘交易
  - 社区策略分享
  - 提供jqdatasdk本地数据接口
- **集成建议**: 适合策略快速验证，easytrader可跟踪其模拟信号

### 4.2 RiceQuant（米筐）⭐⭐⭐⭐
- **类型**: 在线量化平台
- **A股支持**: ★★★★★
- **核心功能**:
  - 完整的回测引擎
  - 支持股票、基金、期货
  - 提供API进行本地开发
- **集成建议**: 策略验证平台

### 4.3 vnpy（回测+实盘）⭐⭐⭐⭐⭐
- **Stars**: 40,762
- **见1.1节**
- **优势**: 开源、完整流程、国内柜台全覆盖
- **集成建议**: 最推荐的本地实盘方案

### 4.4 backtrader ⭐⭐⭐⭐
- **Stars**: ~15,000+
- **语言**: Python
- **核心功能**:
  - 灵活的Python回测框架
  - 支持多数据源、多策略
  - 内置丰富的技术指标
  - 社区活跃
- **A股支持**: ★★★ 通用框架，需自行接入A股数据
- **集成建议**: 可替换当前backtest.py，提供更专业的回测能力

### 4.5 Zipline（Quantopian）⭐⭐⭐
- **Stars**: ~10,000+
- **注意**: 原Quantopian已关闭，社区维护版本功能受限
- **A股支持**: ★★ 默认美股，A股适配困难
- **建议**: 不推荐用于A股

---

## 五、中文金融新闻情感分析工具

### 5.1 Chinese-Roberta/Chinese-MacBERT ⭐⭐⭐⭐⭐
- **来源**: HuggingFace + hfl/chinese-roberta-wwm-ext
- **Stars**: ~3,000+
- **A股支持**: ★★★★ 通用中文NLP，可微调金融任务
- **核心功能**:
  - 中文预训练语言模型
  - 支持文本分类、情感分析、NER
  - 可与transformers库直接集成
- **集成建议**: 微调后用于金融新闻情感分析，替代当前纯规则方法

### 5.2 FinBERT（金融BERT）⭐⭐⭐⭐
- **来源**: Prosai/finbert (HuggingFace)
- **Stars**: ~1,500+
- **A股支持**: ★★★ 英文金融模型，中文需微调
- **核心功能**:
  - 专为金融文本预训练的BERT
  - 金融情感分析（正面/负面/中性）
  - 事件分类
- **集成建议**: 英文版适合分析英文财报，中文需基于Chinese-Roberta微调

### 5.3 Langchain-Chatchat + 知识库 ⭐⭐⭐⭐
- **见2.3节** (38,058 Stars)
- **集成建议**: 构建金融RAG系统，分析新闻、公告、研报

### 5.4 自研方案（基于transformers）⭐⭐⭐⭐
- **HuggingFace Transformers**: 160,830 Stars（2026-05-21更新）
- **方案**:
  1. 下载 Chinese-Roberta-wwm-ext 预训练模型
  2. 使用金融新闻数据集（如新浪财经、东方财富新闻）微调
  3. 集成到sector_sentiment.py
- **推荐模型**:
  - hfl/chinese-roberta-wwm-ext（中文最强RoBERTa）
  - THUDM/chatglm3-6b（对话式，可做新闻总结）
  - Qwen/Qwen2.5-7B（通用能力强，适合多任务）

---

## 六、针对当前系统的集成建议

### 6.1 立即可集成（无需大改动）

| 工具 | 当前状态 | 建议操作 |
|------|----------|----------|
| AkShare | 已安装 v1.18.62 | 替换baostock_fetcher部分逻辑，获取更丰富的数据 |
| easytrader | 未安装 | `pip install easytrader`，接入同花顺实盘 |
| backtrader | 未安装 | `pip install backtrader`，增强回测能力 |

### 6.2 中期集成（需环境升级）

| 工具 | 需要 | 建议 |
|------|------|------|
| Qlib | 安装PyTorch | 替换ml_stock_selector，提升选股能力 |
| FinRL | 安装PyTorch + gym | 构建DRL交易Agent |
| Chinese-Roberta | 安装transformers | 增强sector_sentiment.py |
| vnpy | 单独环境 | 作为实盘交易执行层 |

### 6.3 长期规划

| 方向 | 工具 | 目标 |
|------|------|------|
| LLM交易顾问 | LLaMA-Factory + Qwen | 微调A股专属交易大模型 |
| RAG金融知识库 | Langchain-Chatchat | 构建研报+新闻+公告知识库 |
| 实盘交易 | vnpy + XTP接口 | 接入券商柜台实盘 |
| 多策略AI融合 | FinRL + Qlib | RL决策 + 深度学习选股 |

### 6.4 推荐优先级排序

```
第一优先级（本周）:
  1. 深入使用AkShare（已安装），丰富数据维度
  2. 安装easytrader，打通实盘通道

第二优先级（本月）:
  3. 升级Python至3.10+，安装PyTorch
  4. 部署Qlib，重构选股模块
  5. 用Chinese-Roberta增强情感分析

第三优先级（本季度）:
  6. 部署vnpy，建立实盘交易能力
  7. 实验FinRL DRL策略
  8. 微调Qwen/ChatGLM构建AI交易顾问
```

---

## 七、环境升级清单

当前环境: Python 3.8.17, 无PyTorch/TensorFlow

```bash
# 推荐升级（在服务器上）:
# 1. 升级Python至3.10（或保留3.8，部分库兼容）
# 2. 创建AI专用venv:
python3.10 -m venv ~/quant_ai
source ~/quant_ai/bin/activate
pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu
pip install pyqlib[all]          # Qlib
pip install finrl               # FinRL
pip install transformers         # HuggingFace
pip install sentence-transformers # 中文句子嵌入
pip install vnpy                # VeighNa
pip install easytrader           # 实盘交易
pip install backtrader           # 专业回测
```

---

## 八、关键项目数据汇总

| 项目 | Stars | 更新频率 | A股支持 | 类型 |
|------|-------|----------|---------|------|
| vnpy | 40,762 | 极活跃 | ★★★★★ | 全栈平台 |
| easytrader | 9,756 | 活跃 | ★★★★★ | 实盘交易 |
| AkShare | 30,000+ | 极活跃 | ★★★★★ | 数据源 |
| Qlib | 25,000+ | 极活跃 | ★★★★ | AI量化 |
| FinRL | 15,196 | 极活跃 | ★★★★ | 强化学习 |
| Langchain-Chatchat | 38,058 | 活跃 | ★★★★ | RAG/Agent |
| HuggingFace Transformers | 160,830 | 极活跃 | ★★★ | ML框架 |
| GPT Academic | 70,698 | 活跃 | ★★★ | 多模型接口 |
| backtrader | 15,000+ | 稳定 | ★★★ | 回测引擎 |
| Tushare | 10,000+ | 活跃 | ★★★★★ | 数据源 |
