# Agent 记忆系统 Skill

## 触发条件
- 记录/查询交易信号历史
- 追踪市场状态
- 分析策略表现
- 复盘经验教训

## 核心 API

```python
from core.memory import TradingMemory
mem = TradingMemory(db_path='knowledge_base/trading_memory.db')
```

### 信号记忆
```python
# 记录信号
mem.log_signal({
    'date': '2026-05-28', 'code': '600637',
    'strategy': 'trend_following', 'signal': 'buy',
    'price': 10.5, 'confidence': 0.85
})

# 更新结果
mem.update_signal_outcome(signal_id, {
    'outcome': 'profit', 'exit_price': 12.0,
    'pnl_pct': 14.3, 'hold_days': 5
})

# 查询信号
mem.query_signals(code='600637', days=30)
mem.get_signal_stats(strategy='trend_following', days=90)
```

### 市场状态
```python
from core.market_state import track_market_state
state = track_market_state('2026-05-28')

mem.get_market_state('2026-05-28')
mem.get_market_history(days=30)
mem.get_sentiment_distribution(days=60)
```

### 策略表现
```python
mem.get_strategy_comparison(days=90)  # 策略排名
mem.get_best_strategy_for_market('bullish')  # 最佳策略
```

### 经验教训
```python
mem.log_lesson({
    'date': '2026-05-28', 'lesson_type': 'big_win',
    'title': '板块轮动捕捉成功',
    'description': 'XX板块连续3日领涨...',
    'pattern': '板块+动量突破组合',
    'tags': ['板块轮动', '动量'],
    'severity': 8
})
```

### 模式洞察
```python
mem.get_pattern_insights(code='600637', days=30)
```

## 已知 Pitfalls
- 非交易日 (周六日) 不运行 track_market_state
- 新浪API在盘前(9:00前)无实时数据，用前日数据填充
- 策略名称必须与 actual strategy name 一致
