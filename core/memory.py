"""
Agent 记忆系统

轻量级 SQLite + JSONL 记忆引擎，适合量化交易场景。

设计灵感来自 SuperMemory/Memori 架构，但本地化实现，零外部依赖。

记忆类型:
1. signal_memory  - 交易信号记忆 (选股/买卖信号的后续跟踪)
2. market_memory  - 市场状态记忆 (每日市场快照 + 情绪)
3. strategy_memory - 策略表现记忆 (每个策略在不同市场状态下的表现)
4. lesson_memory  - 经验教训 (大赚/大亏的模式总结)
5. stock_memory   - 个股记忆 (个股行为模式记录)

用法:
    from core.memory import TradingMemory
    mem = TradingMemory(db_path='knowledge_base/trading_memory.db')
    
    # 记录信号
    mem.log_signal({
        'date': '2026-05-28',
        'code': '600637',
        'strategy': 'trend_following',
        'signal': 'buy',
        'price': 10.5,
        'confidence': 0.85
    })
    
    # 查询历史表现
    results = mem.query_signal_results(code='600637', days=30)
    
    # 记录市场状态
    mem.log_market_state({
        'date': '2026-05-28',
        'sh_index': 4098.11,
        'sh_change_pct': 0.11,
        'sentiment': 'neutral',
        'hot_sectors': ['房屋建筑业', ...]
    })
    
    # 获取策略在特定市场状态下的胜率
    win_rate = mem.get_strategy_win_rate('trend_following', market_state='neutral')
"""

import sqlite3
import json
import os
import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
from collections import defaultdict


class TradingMemory:
    """量化交易记忆系统"""

    def __init__(self, db_path: str = 'knowledge_base/trading_memory.db'):
        self.db_path = db_path
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self._init_db()

    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        return conn

    def _init_db(self):
        """初始化数据库表"""
        conn = self._get_conn()
        conn.executescript("""
            -- 交易信号记忆
            CREATE TABLE IF NOT EXISTS signals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT NOT NULL,
                code TEXT NOT NULL,
                name TEXT,
                strategy TEXT NOT NULL,
                signal TEXT NOT NULL,  -- buy/sell/hold
                price REAL,
                confidence REAL,
                stop_loss REAL,
                take_profit REAL,
                invalid_price REAL,
                risk_reward REAL,
                reason TEXT,
                tech_reasons TEXT,  -- JSON array
                outcome TEXT,  -- realized: profit/loss/break_even/invalid
                exit_date TEXT,
                exit_price REAL,
                pnl_pct REAL,
                hold_days INTEGER,
                created_at TEXT DEFAULT (datetime('now'))
            );

            -- 市场状态记忆
            CREATE TABLE IF NOT EXISTS market_state (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT UNIQUE NOT NULL,
                sh_index REAL,
                sh_change_pct REAL,
                hs300 REAL,
                hs300_change_pct REAL,
                cyb REAL,
                cyb_change_pct REAL,
                sentiment TEXT,  -- bullish/bearish/neutral
                hot_sectors TEXT,  -- JSON array
                market_breadth REAL,  -- 上涨家数占比
                volume_ratio REAL,  -- 成交量比
                volatility REAL,  -- 波动率
                extra TEXT,  -- JSON: additional fields
                created_at TEXT DEFAULT (datetime('now'))
            );

            -- 策略表现记忆 (聚合统计)
            CREATE TABLE IF NOT EXISTS strategy_perf (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                strategy TEXT NOT NULL,
                date TEXT NOT NULL,
                market_sentiment TEXT,
                total_signals INTEGER DEFAULT 0,
                realized_signals INTEGER DEFAULT 0,
                win_count INTEGER DEFAULT 0,
                loss_count INTEGER DEFAULT 0,
                avg_win_pct REAL,
                avg_loss_pct REAL,
                avg_hold_days REAL,
                sharpe REAL,
                max_drawdown REAL,
                total_pnl_pct REAL,
                extra TEXT,  -- JSON
                UNIQUE(strategy, date)
            );

            -- 经验教训记忆
            CREATE TABLE IF NOT EXISTS lessons (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT NOT NULL,
                code TEXT,
                strategy TEXT,
                lesson_type TEXT NOT NULL,  -- big_win/big_loss/market_insight/strategy_insight
                title TEXT NOT NULL,
                description TEXT,
                pattern TEXT,  -- 可复用的模式描述
                tags TEXT,  -- JSON array of tags
                severity INTEGER DEFAULT 5,  -- 1-10
                created_at TEXT DEFAULT (datetime('now'))
            );

            -- 个股记忆
            CREATE TABLE IF NOT EXISTS stock_memory (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                code TEXT NOT NULL,
                date TEXT NOT NULL,
                event_type TEXT NOT NULL,  -- breakout/reversal/earnings/volume_surge/pattern
                description TEXT,
                price REAL,
                volume REAL,
                context TEXT,  -- JSON: market context at the time
                outcome TEXT,  -- 后续表现
                created_at TEXT DEFAULT (datetime('now')),
                UNIQUE(code, date, event_type)
            );

            -- 索引
            CREATE INDEX IF NOT EXISTS idx_signals_date ON signals(date);
            CREATE INDEX IF NOT EXISTS idx_signals_code ON signals(code);
            CREATE INDEX IF NOT EXISTS idx_signals_strategy ON signals(strategy);
            CREATE INDEX IF NOT EXISTS idx_signals_outcome ON signals(outcome);
            CREATE INDEX IF NOT EXISTS idx_market_date ON market_state(date);
            CREATE INDEX IF NOT EXISTS idx_strategy_perf_strategy ON strategy_perf(strategy);
            CREATE INDEX IF NOT EXISTS idx_lessons_type ON lessons(lesson_type);
            CREATE INDEX IF NOT EXISTS idx_stock_memory_code ON stock_memory(code);
        """)
        conn.commit()
        conn.close()

    # ==================== Signal Memory ====================

    def log_signal(self, signal: Dict) -> int:
        """记录交易信号"""
        conn = self._get_conn()
        try:
            tech_reasons = json.dumps(signal.get('tech_reasons', []), ensure_ascii=False)
            cursor = conn.execute("""
                INSERT INTO signals (date, code, name, strategy, signal, price, confidence,
                    stop_loss, take_profit, invalid_price, risk_reward, reason, tech_reasons)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                signal.get('date'),
                signal.get('code'),
                signal.get('name'),
                signal.get('strategy'),
                signal.get('signal', 'buy'),
                signal.get('price'),
                signal.get('confidence'),
                signal.get('stop_loss'),
                signal.get('take_profit'),
                signal.get('invalid_price'),
                signal.get('risk_reward'),
                signal.get('reason'),
                tech_reasons
            ))
            conn.commit()
            return cursor.lastrowid
        finally:
            conn.close()

    def update_signal_outcome(self, signal_id: int, outcome: Dict):
        """更新信号结果 (回测/实盘后的结果反馈)"""
        conn = self._get_conn()
        try:
            conn.execute("""
                UPDATE signals SET outcome=?, exit_date=?, exit_price=?, pnl_pct=?, hold_days=?
                WHERE id=?
            """, (
                outcome.get('outcome'),  # profit/loss/break_even/invalid
                outcome.get('exit_date'),
                outcome.get('exit_price'),
                outcome.get('pnl_pct'),
                outcome.get('hold_days'),
                signal_id
            ))
            conn.commit()
        finally:
            conn.close()

    def query_signals(self, code: str = None, strategy: str = None,
                      signal_type: str = None, days: int = 30,
                      has_outcome: bool = None) -> List[Dict]:
        """查询信号历史"""
        conn = self._get_conn()
        try:
            conditions = []
            params = []
            if code:
                conditions.append("code=?")
                params.append(code)
            if strategy:
                conditions.append("strategy=?")
                params.append(strategy)
            if signal_type:
                conditions.append("signal=?")
                params.append(signal_type)
            if days:
                since = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')
                conditions.append("date>=?")
                params.append(since)
            if has_outcome is not None:
                if has_outcome:
                    conditions.append("outcome IS NOT NULL")
                else:
                    conditions.append("outcome IS NULL")

            where = " WHERE " + " AND ".join(conditions) if conditions else ""
            rows = conn.execute(f"SELECT * FROM signals{where} ORDER BY date DESC, id DESC", params)
            return [dict(r) for r in rows.fetchall()]
        finally:
            conn.close()

    def get_signal_stats(self, strategy: str = None, days: int = 90) -> Dict:
        """获取信号统计"""
        conn = self._get_conn()
        try:
            since = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')
            where = "WHERE date >= ?"
            params = [since]
            if strategy:
                where += " AND strategy = ?"
                params.append(strategy)

            total = conn.execute(f"SELECT COUNT(*) FROM signals {where}", params).fetchone()[0]
            with_outcome = conn.execute(
                f"SELECT COUNT(*) FROM signals {where} AND outcome IS NOT NULL", params
            ).fetchone()[0]
            wins = conn.execute(
                f"SELECT COUNT(*) FROM signals {where} AND outcome = 'profit'", params
            ).fetchone()[0]
            losses = conn.execute(
                f"SELECT COUNT(*) FROM signals {where} AND outcome = 'loss'", params
            ).fetchone()[0]

            avg_pnl_row = conn.execute(
                f"SELECT AVG(pnl_pct), AVG(hold_days) FROM signals {where} AND outcome IS NOT NULL", params
            ).fetchone()
            avg_pnl = avg_pnl_row[0] or 0
            avg_hold = avg_pnl_row[1] or 0

            win_rate = wins / (wins + losses) * 100 if (wins + losses) > 0 else 0

            return {
                'total_signals': total,
                'realized': with_outcome,
                'pending': total - with_outcome,
                'wins': wins,
                'losses': losses,
                'win_rate': win_rate,
                'avg_pnl_pct': avg_pnl,
                'avg_hold_days': avg_hold,
                'period_days': days
            }
        finally:
            conn.close()

    # ==================== Market State Memory ====================

    def log_market_state(self, state: Dict):
        """记录市场状态"""
        conn = self._get_conn()
        try:
            hot_sectors = json.dumps(state.get('hot_sectors', []), ensure_ascii=False)
            extra = json.dumps({k: v for k, v in state.items()
                               if k not in ['date', 'sh_index', 'sh_change_pct', 'hs300',
                                           'hs300_change_pct', 'cyb', 'cyb_change_pct',
                                           'sentiment', 'hot_sectors', 'market_breadth',
                                           'volume_ratio', 'volatility']},
                              ensure_ascii=False)
            conn.execute("""
                INSERT OR REPLACE INTO market_state
                (date, sh_index, sh_change_pct, hs300, hs300_change_pct, cyb, cyb_change_pct,
                 sentiment, hot_sectors, market_breadth, volume_ratio, volatility, extra)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                state['date'],
                state.get('sh_index'),
                state.get('sh_change_pct'),
                state.get('hs300'),
                state.get('hs300_change_pct'),
                state.get('cyb'),
                state.get('cyb_change_pct'),
                state.get('sentiment'),
                hot_sectors,
                state.get('market_breadth'),
                state.get('volume_ratio'),
                state.get('volatility'),
                extra
            ))
            conn.commit()
        finally:
            conn.close()

    def get_market_state(self, date: str) -> Optional[Dict]:
        """获取指定日期的市场状态"""
        conn = self._get_conn()
        try:
            row = conn.execute("SELECT * FROM market_state WHERE date=?", (date,)).fetchone()
            if not row:
                return None
            d = dict(row)
            if d.get('hot_sectors'):
                d['hot_sectors'] = json.loads(d['hot_sectors'])
            if d.get('extra'):
                d['extra'].update(json.loads(d['extra']))
                del d['extra']
            return d
        finally:
            conn.close()

    def get_market_history(self, days: int = 30) -> List[Dict]:
        """获取市场历史"""
        conn = self._get_conn()
        try:
            since = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')
            rows = conn.execute(
                "SELECT * FROM market_state WHERE date >= ? ORDER BY date DESC", (since,)
            )
            result = []
            for r in rows.fetchall():
                d = dict(r)
                if d.get('hot_sectors'):
                    d['hot_sectors'] = json.loads(d['hot_sectors'])
                result.append(d)
            return result
        finally:
            conn.close()

    def get_sentiment_distribution(self, days: int = 60) -> Dict:
        """获取情绪分布"""
        conn = self._get_conn()
        try:
            since = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')
            rows = conn.execute(
                "SELECT sentiment, COUNT(*) as cnt FROM market_state WHERE date >= ? GROUP BY sentiment",
                (since,)
            )
            total = sum(r[1] for r in rows.fetchall())
            return {r[0]: round(r[1] / total * 100, 1) for r in rows} if total > 0 else {}
        finally:
            conn.close()

    # ==================== Strategy Performance ====================

    def update_strategy_perf(self, strategy: str, date: str, perf: Dict):
        """更新策略每日表现"""
        conn = self._get_conn()
        try:
            extra = json.dumps({k: v for k, v in perf.items()
                               if k not in ['strategy', 'date', 'market_sentiment',
                                           'total_signals', 'realized_signals',
                                           'win_count', 'loss_count',
                                           'avg_win_pct', 'avg_loss_pct',
                                           'avg_hold_days', 'sharpe',
                                           'max_drawdown', 'total_pnl_pct']},
                              ensure_ascii=False)
            conn.execute("""
                INSERT OR REPLACE INTO strategy_perf
                (strategy, date, market_sentiment, total_signals, realized_signals,
                 win_count, loss_count, avg_win_pct, avg_loss_pct, avg_hold_days,
                 sharpe, max_drawdown, total_pnl_pct, extra)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                strategy, date, perf.get('market_sentiment'),
                perf.get('total_signals', 0), perf.get('realized_signals', 0),
                perf.get('win_count', 0), perf.get('loss_count', 0),
                perf.get('avg_win_pct'), perf.get('avg_loss_pct'),
                perf.get('avg_hold_days'), perf.get('sharpe'),
                perf.get('max_drawdown'), perf.get('total_pnl_pct'),
                extra
            ))
            conn.commit()
        finally:
            conn.close()

    def get_strategy_win_rate(self, strategy: str, market_sentiment: str = None,
                               days: int = 90) -> Dict:
        """获取策略在特定市场状态下的胜率"""
        conn = self._get_conn()
        try:
            since = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')
            where = "WHERE strategy=? AND date>=?"
            params = [strategy, since]
            if market_sentiment:
                where += " AND market_sentiment=?"
                params.append(market_sentiment)

            row = conn.execute(f"""
                SELECT SUM(total_signals) as total,
                       SUM(realized_signals) as realized,
                       SUM(win_count) as wins,
                       SUM(loss_count) as losses,
                       AVG(total_pnl_pct) as avg_pnl
                FROM strategy_perf {where}
            """, params).fetchone()

            total = row[1] or 0
            wins = row[2] or 0
            losses = row[3] or 0
            win_rate = wins / (wins + losses) * 100 if (wins + losses) > 0 else 0

            return {
                'strategy': strategy,
                'market_sentiment': market_sentiment or 'all',
                'total_signals': row[0] or 0,
                'wins': wins,
                'losses': losses,
                'win_rate': win_rate,
                'avg_pnl_pct': row[4] or 0,
                'period_days': days
            }
        finally:
            conn.close()

    def get_strategy_comparison(self, days: int = 90) -> List[Dict]:
        """策略对比排名"""
        conn = self._get_conn()
        try:
            since = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')
            rows = conn.execute("""
                SELECT strategy,
                       SUM(total_signals) as total,
                       SUM(win_count) as wins,
                       SUM(loss_count) as losses,
                       AVG(total_pnl_pct) as avg_pnl
                FROM strategy_perf WHERE date >= ?
                GROUP BY strategy ORDER BY avg_pnl DESC
            """, (since,))

            result = []
            for r in rows.fetchall():
                total = r[2] or 0
                wins = r[3] or 0
                losses = r[4] or 0
                win_rate = wins / (wins + losses) * 100 if (wins + losses) > 0 else 0
                result.append({
                    'strategy': r[0],
                    'total_signals': r[1] or 0,
                    'wins': wins,
                    'losses': losses,
                    'win_rate': win_rate,
                    'avg_pnl_pct': r[5] or 0
                })
            return result
        finally:
            conn.close()

    # ==================== Lessons Learned ====================

    def log_lesson(self, lesson: Dict) -> int:
        """记录经验教训"""
        conn = self._get_conn()
        try:
            tags = json.dumps(lesson.get('tags', []), ensure_ascii=False)
            cursor = conn.execute("""
                INSERT INTO lessons (date, code, strategy, lesson_type, title,
                    description, pattern, tags, severity)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                lesson.get('date'), lesson.get('code'), lesson.get('strategy'),
                lesson.get('lesson_type', 'strategy_insight'),
                lesson.get('title'), lesson.get('description'),
                lesson.get('pattern'), tags,
                lesson.get('severity', 5)
            ))
            conn.commit()
            return cursor.lastrowid
        finally:
            conn.close()

    def query_lessons(self, lesson_type: str = None, tags: List[str] = None,
                      days: int = 90, limit: int = 20) -> List[Dict]:
        """查询经验教训"""
        conn = self._get_conn()
        try:
            conditions = []
            params = []
            if days:
                since = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')
                conditions.append("date>=?")
                params.append(since)
            if lesson_type:
                conditions.append("lesson_type=?")
                params.append(lesson_type)

            where = " WHERE " + " AND ".join(conditions) if conditions else ""
            rows = conn.execute(
                f"SELECT * FROM lessons{where} ORDER BY severity DESC, date DESC LIMIT ?",
                params + [limit]
            )
            result = []
            for r in rows.fetchall():
                d = dict(r)
                if d.get('tags'):
                    d['tags'] = json.loads(d['tags'])
                result.append(d)
            return result
        finally:
            conn.close()

    # ==================== Stock Memory ====================

    def log_stock_event(self, event: Dict):
        """记录个股事件"""
        conn = self._get_conn()
        try:
            context = json.dumps(event.get('context', {}), ensure_ascii=False)
            conn.execute("""
                INSERT OR REPLACE INTO stock_memory
                (code, date, event_type, description, price, volume, context, outcome)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                event.get('code'), event.get('date'), event.get('event_type'),
                event.get('description'), event.get('price'), event.get('volume'),
                context, event.get('outcome')
            ))
            conn.commit()
        finally:
            conn.close()

    def get_stock_history(self, code: str, days: int = 90) -> List[Dict]:
        """获取个股历史事件"""
        conn = self._get_conn()
        try:
            since = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')
            rows = conn.execute(
                "SELECT * FROM stock_memory WHERE code=? AND date>=? ORDER BY date DESC",
                (code, since)
            )
            result = []
            for r in rows.fetchall():
                d = dict(r)
                if d.get('context'):
                    d['context'] = json.loads(d['context'])
                result.append(d)
            return result
        finally:
            conn.close()

    # ==================== Cross-Analysis ====================

    def get_best_strategy_for_market(self, sentiment: str) -> Optional[Dict]:
        """获取当前市场情绪下表现最好的策略"""
        conn = self._get_conn()
        try:
            row = conn.execute("""
                SELECT strategy,
                       SUM(win_count) as wins,
                       SUM(loss_count) as losses,
                       AVG(total_pnl_pct) as avg_pnl
                FROM strategy_perf
                WHERE market_sentiment=?
                GROUP BY strategy
                HAVING SUM(win_count) + SUM(loss_count) >= 3
                ORDER BY avg_pnl DESC
                LIMIT 1
            """, (sentiment,)).fetchone()

            if not row:
                return None

            wins = row[1] or 0
            losses = row[2] or 0
            return {
                'strategy': row[0],
                'wins': wins,
                'losses': losses,
                'win_rate': wins / (wins + losses) * 100,
                'avg_pnl_pct': row[3] or 0,
                'market_sentiment': sentiment
            }
        finally:
            conn.close()

    def get_pattern_insights(self, code: str = None, days: int = 30) -> Dict:
        """获取模式洞察 - 最近的市场模式总结"""
        signals = self.query_signals(code=code, days=days, has_outcome=True)
        if not signals:
            return {'message': 'Insufficient data for pattern analysis'}

        # Analyze patterns
        outcomes = [s for s in signals if s.get('outcome')]
        if not outcomes:
            return {'message': 'No realized outcomes yet'}

        avg_pnl = sum(s.get('pnl_pct', 0) for s in outcomes) / len(outcomes)
        best_strategy = defaultdict(list)
        for s in outcomes:
            best_strategy[s['strategy']].append(s.get('pnl_pct', 0))

        strategy_avg = {k: sum(v)/len(v) for k, v in best_strategy.items()}

        return {
            'total_signals': len(signals),
            'realized': len(outcomes),
            'avg_pnl_pct': avg_pnl,
            'strategy_avg_pnl': strategy_avg,
            'best_strategy': max(strategy_avg, key=strategy_avg.get) if strategy_avg else None
        }

    # ==================== Summary ====================

    def get_memory_summary(self) -> Dict:
        """获取记忆系统总览"""
        conn = self._get_conn()
        try:
            signal_count = conn.execute("SELECT COUNT(*) FROM signals").fetchone()[0]
            market_count = conn.execute("SELECT COUNT(*) FROM market_state").fetchone()[0]
            strategy_count = conn.execute("SELECT COUNT(DISTINCT strategy) FROM strategy_perf").fetchone()[0]
            lesson_count = conn.execute("SELECT COUNT(*) FROM lessons").fetchone()[0]
            stock_count = conn.execute("SELECT COUNT(DISTINCT code) FROM stock_memory").fetchone()[0]

            # Latest entries
            latest_signal = conn.execute("SELECT date, code, strategy, signal FROM signals ORDER BY id DESC LIMIT 1").fetchone()
            latest_market = conn.execute("SELECT date, sentiment FROM market_state ORDER BY id DESC LIMIT 1").fetchone()

            return {
                'signals': signal_count,
                'market_snapshots': market_count,
                'strategies_tracked': strategy_count,
                'lessons': lesson_count,
                'stocks_tracked': stock_count,
                'latest_signal': dict(latest_signal) if latest_signal else None,
                'latest_market': dict(latest_market) if latest_market else None,
                'db_path': self.db_path
            }
        finally:
            conn.close()
