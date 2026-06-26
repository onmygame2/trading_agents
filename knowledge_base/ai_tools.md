# AI量化交易工具参考

## 有实战记录的框架

### Qlib (微软) - 推荐关注
- GitHub: microsoft/QLib (16k+ stars)
- A股验证年化超额收益: 5-15%
- 因子挖掘 + LightGBM/Transformer模型
- 适合中低频日线级别
- 缺点: 较重，需要GPU训练

### FinRL - 强化学习
- GitHub: AI4Finance-Foundation/FinRL (23k+ stars)
- DRL算法: PPO/A2C/SAC
- A股论文验证: 8-20%年化
- 适合: 研究+实验
- 缺点: 训练复杂，过拟合风险

### OpenBB - 投资研究
- GitHub: OpenBB-finance/OpenBB (20k+ stars)
- 多数据源整合
- 缺点: 偏美股，A股数据有限

### FreqTrade - 策略框架
- GitHub: freqtrade/freqTrade (37k+ stars)
- 加密货币为主，策略框架完善
- 可改造成A股日频

### HuggingFace Transformers
- 时序预测: TFT/N-BEATS
- 新闻情感: FinBERT
- A股应用: 辅助信号

## LLM在量化中的实际用途

1. **财报摘要** - GPT/Claude解析年报/季报
2. **新闻情感** - FinBERT 准确率75-85%
3. **市场情绪** - 分析社交媒体/新闻
4. **策略辅助** - 生成基础策略代码
5. **回测解读** - 分析回测结果，发现模式

## 国内数据源

| 工具 | 类型 | 特点 |
|------|------|------|
| AKShare | 开源API | 数据全，免费 |
| Tushare | 金融数据 | 有积分限制 |
| 新浪API | 实时行情 | 免费无限制 |
| 东方财富API | 资金流向 | 分钟K线 |
| BaoStock | 历史K线 | 日线数据 |

## 我们的选型

- **核心**: 保留5个策略，专注优化
- **AI增强**: LLM市场分析 + 情感分析
- **数据**: 新浪API + BaoStock
- **不引入**: Qlib/FinRL (过重)