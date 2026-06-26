# 深度学习因子选股方案

## 目标

用深度学习从 **36 维因子**（六维评分 + 价量技术指标 + 基本面 + 板块/大盘上下文）中学习「未来 5 日是否跑赢 1%」的概率，为 6 个 v2 策略提供 **DL 门控** 和 **分数加成**，减少规则策略的误杀/漏选。

## 架构

```
K线/基本面 → FactorEngine 六维评分
                    ↓
            extract_features (36维)
                    ↓
         NumPy MLP [64→32→sigmoid]  ← 可升级 PyTorch
                    ↓
            dl_score ∈ [0,1]
                    ↓
    策略 filter → DL门控(min_dl) → 分数加成 → 买入
```

## 因子清单 (36维)

| 类别 | 字段 |
|------|------|
| 六维评分 | trend, fundamental, valuation, sector, capital, momentum, total_score |
| 价量 | rsi, macd_dif/hist, vol_ratio, change_pct, mom_5d/10d/20d, volatility, price_pos, boll_width |
| 形态 | ma_bull, break_60d, macd_golden, pos_in_day, limit_up 基因 |
| 基本面 | pe, pb, roe, market_cap, yoy_ni, gp_margin |
| 市场 | north_flow, turnover, sector_change, index_change, sentiment |

## 标签定义

- **二分类**: 未来 5 个交易日收益 > 1% → label=1
- 可扩展: 分位数排序 (Learning to Rank)、多任务 (涨跌幅回归 + 分类)

## 模型

| 项 | 当前实现 | 升级路径 |
|----|----------|----------|
| 网络 | NumPy MLP 2层 | `torch.nn.Sequential` |
| 损失 | Binary Cross-Entropy | Focal Loss / RankNet |
| 正则 | L2 + Dropout 0.15 | BatchNorm + Early Stop |
| 存储 | `data/ml_models/dl_factor_mlp.npz` | `.pt` + ONNX |

## 与策略集成

每个策略 `metadata` 可配置:

```python
"use_dl": True,          # 启用 DL 门控
"min_dl_score": 0.52,    # 最低 DL 概率
"dl_boost": 15,          # 通过后 strategy_score += dl * boost
```

- **已验证策略** (overnight/swing): `use_dl: False` 或低门槛
- **待优化策略** (突破/板块/超跌): `use_dl: True`, `min_dl_score: 0.52`

## 训练流程

```bash
# 1. 构建数据集 (Top500, 2023-2025, 约10-20分钟)
python scripts/build_dl_dataset.py --pool-top 500

# 2. 训练 MLP
python scripts/train_dl_factor.py --epochs 100

# 3. 回测验证 (DL 门控后)
python backtest_v2.py --pool-top 500
```

## 推理接入点

1. `global_stock_picker.run_picker()` — 对 scored 列表批量推理，传入 `StrategyManager.run_all(dl_scores=...)`
2. `StrategyManager` — 对 `use_dl` 策略做门控和加分
3. `_apply_dl_rerank()` — 组合账户 final_score 叠加 DL

## 迭代计划

1. **Phase 1** (当前): NumPy MLP + 规则策略 DL 门控
2. **Phase 2**: 安装 PyTorch，换 GRU/Transformer 处理时序 K 线
3. **Phase 3**: 按策略分头 (multi-task)，隔夜/波段/反弹各一个输出头
4. **Phase 4**: 在线学习 — 每周用最新 K 线增量 fine-tune

## 注意事项

- 防止过拟合: 时间序列切分 (train 2023-2024, val 2025)，不用随机 shuffle 做最终评估
- A 股 T+1: 标签用 close→close，与实盘一致
- 基本面缺失填 0，模型靠价量因子补偿
