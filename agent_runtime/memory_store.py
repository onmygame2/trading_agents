"""Structured memory store for Agent runtime.

This layer keeps agent execution events and daily briefs separate from the
trading-memory tables, while still using the same local-first SQLite approach.
"""

import json
import os
import sqlite3
from datetime import datetime
from typing import Any, Dict, List, Optional


BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_DB_PATH = os.path.join(BASE_DIR, 'knowledge_base', 'agent_runtime.db')
DAILY_REVIEW_DIR = os.path.join(BASE_DIR, 'knowledge_base', 'daily_reviews')


def _json_dumps(value: Any) -> str:
    return json.dumps(value or {}, ensure_ascii=False, default=str)


def _json_loads(value: Optional[str], default: Any = None) -> Any:
    if not value:
        return default
    try:
        return json.loads(value)
    except Exception:
        return default


class AgentMemoryStore:
    """SQLite-backed memory for agent runs, events, and daily briefs."""

    def __init__(self, db_path: str = DEFAULT_DB_PATH):
        self.db_path = db_path
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute('PRAGMA journal_mode=WAL')
        conn.execute('PRAGMA synchronous=NORMAL')
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS agent_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts TEXT NOT NULL,
                    date TEXT NOT NULL,
                    agent TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    title TEXT NOT NULL,
                    summary TEXT,
                    severity TEXT DEFAULT 'info',
                    payload TEXT
                );

                CREATE TABLE IF NOT EXISTS daily_briefs (
                    date TEXT PRIMARY KEY,
                    created_at TEXT NOT NULL,
                    status TEXT NOT NULL,
                    title TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    action_items TEXT,
                    risk_flags TEXT,
                    metrics TEXT,
                    source_refs TEXT
                );

                CREATE INDEX IF NOT EXISTS idx_agent_events_date
                    ON agent_events(date, id DESC);
                CREATE INDEX IF NOT EXISTS idx_agent_events_agent
                    ON agent_events(agent, id DESC);
            """)

    def log_event(self, agent: str, event_type: str, title: str,
                  summary: str = '', severity: str = 'info',
                  payload: Optional[Dict] = None, date: str = None) -> int:
        now = datetime.now()
        event_date = date or now.strftime('%Y-%m-%d')
        with self._connect() as conn:
            cur = conn.execute("""
                INSERT INTO agent_events
                    (ts, date, agent, event_type, title, summary, severity, payload)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                now.isoformat(timespec='seconds'),
                event_date,
                agent,
                event_type,
                title,
                summary,
                severity,
                _json_dumps(payload),
            ))
            return int(cur.lastrowid)

    def list_events(self, days: int = 14, limit: int = 50,
                    agent: str = None) -> List[Dict]:
        conditions = []
        params: List[Any] = []
        if days:
            conditions.append("date >= date('now', ?)")
            params.append(f'-{int(days)} day')
        if agent:
            conditions.append('agent = ?')
            params.append(agent)
        where = (' WHERE ' + ' AND '.join(conditions)) if conditions else ''
        params.append(int(limit))
        with self._connect() as conn:
            rows = conn.execute(f"""
                SELECT * FROM agent_events
                {where}
                ORDER BY date DESC, id DESC
                LIMIT ?
            """, params).fetchall()
        events = []
        for row in rows:
            item = dict(row)
            item['payload'] = _json_loads(item.get('payload'), {})
            events.append(item)
        return events

    def save_daily_brief(self, brief: Dict) -> Dict:
        date = brief.get('date') or datetime.now().strftime('%Y-%m-%d')
        created_at = datetime.now().isoformat(timespec='seconds')
        stored = {
            'date': date,
            'created_at': created_at,
            'status': brief.get('status', 'ok'),
            'title': brief.get('title') or f'{date} Agent 日报',
            'summary': brief.get('summary', ''),
            'action_items': brief.get('action_items', []),
            'risk_flags': brief.get('risk_flags', []),
            'metrics': brief.get('metrics', {}),
            'source_refs': brief.get('source_refs', []),
        }
        with self._connect() as conn:
            conn.execute("""
                INSERT INTO daily_briefs
                    (date, created_at, status, title, summary, action_items,
                     risk_flags, metrics, source_refs)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(date) DO UPDATE SET
                    created_at=excluded.created_at,
                    status=excluded.status,
                    title=excluded.title,
                    summary=excluded.summary,
                    action_items=excluded.action_items,
                    risk_flags=excluded.risk_flags,
                    metrics=excluded.metrics,
                    source_refs=excluded.source_refs
            """, (
                stored['date'],
                stored['created_at'],
                stored['status'],
                stored['title'],
                stored['summary'],
                _json_dumps(stored['action_items']),
                _json_dumps(stored['risk_flags']),
                _json_dumps(stored['metrics']),
                _json_dumps(stored['source_refs']),
            ))
        self.log_event(
            agent='reviewer',
            event_type='daily_brief',
            title=stored['title'],
            summary=stored['summary'],
            severity='warning' if stored['risk_flags'] else 'info',
            payload={'metrics': stored['metrics'], 'risk_flags': stored['risk_flags']},
            date=date,
        )
        self.write_daily_review_files(stored)
        return stored

    def write_daily_review_files(self, brief: Dict) -> Dict[str, str]:
        """Persist the daily brief as knowledge-base JSON and Markdown files."""
        os.makedirs(DAILY_REVIEW_DIR, exist_ok=True)
        date = brief.get('date') or datetime.now().strftime('%Y-%m-%d')
        json_path = os.path.join(DAILY_REVIEW_DIR, f'{date}.json')
        md_path = os.path.join(DAILY_REVIEW_DIR, f'{date}.md')

        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(brief, f, ensure_ascii=False, indent=2)

        metrics = brief.get('metrics') or {}
        risk_flags = brief.get('risk_flags') or []
        action_items = brief.get('action_items') or []
        source_refs = brief.get('source_refs') or []
        lines = [
            f"# {brief.get('title') or date}",
            "",
            f"- 状态: {brief.get('status', 'ok')}",
            f"- 生成时间: {brief.get('created_at', '')}",
            f"- 组合资产: {metrics.get('total_equity', 0):,.2f}",
            f"- 组合收益: {metrics.get('total_return_pct', 0):+.2f}%",
            f"- 持仓数量: {metrics.get('positions', 0)}",
            f"- 今日候选: {metrics.get('pick_count', 0)}",
            "",
            "## 摘要",
            "",
            brief.get('summary', ''),
            "",
            "## 风险标记",
            "",
        ]
        lines.extend([f"- {item}" for item in risk_flags] or ["- 暂无"])
        lines.extend(["", "## 下一步动作", ""])
        lines.extend([f"- {item}" for item in action_items] or ["- 暂无"])
        lines.extend(["", "## 数据来源", ""])
        lines.extend([
            f"- {ref.get('name', '')}: `{ref.get('path', '')}`"
            for ref in source_refs
            if ref.get('name') or ref.get('path')
        ] or ["- 暂无"])
        lines.append("")

        with open(md_path, 'w', encoding='utf-8') as f:
            f.write('\n'.join(lines))
        return {'json_path': json_path, 'md_path': md_path}

    def get_daily_brief(self, date: str = None) -> Optional[Dict]:
        where = 'WHERE date = ?' if date else ''
        params = [date] if date else []
        sql = f"SELECT * FROM daily_briefs {where} ORDER BY date DESC LIMIT 1"
        with self._connect() as conn:
            row = conn.execute(sql, params).fetchone()
        if not row:
            return None
        item = dict(row)
        for key, default in (
            ('action_items', []),
            ('risk_flags', []),
            ('metrics', {}),
            ('source_refs', []),
        ):
            item[key] = _json_loads(item.get(key), default)
        return item

