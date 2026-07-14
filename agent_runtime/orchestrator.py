#!/usr/bin/env python3
"""Local Agent runtime orchestrator.

MVP scope:
- run a deterministic daily review agent;
- persist a structured daily brief;
- expose small helper functions for Dashboard APIs.
"""

import argparse
import json
from datetime import datetime
from typing import Dict

from agent_runtime.agents.reviewer import DailyReviewer
from agent_runtime.memory_store import AgentMemoryStore


class AgentOrchestrator:
    """Coordinates local agents and stores their outputs."""

    def __init__(self, store: AgentMemoryStore = None):
        self.store = store or AgentMemoryStore()

    def run_daily_review(self, date: str = None) -> Dict:
        run_date = date or datetime.now().strftime('%Y-%m-%d')
        self.store.log_event(
            agent='orchestrator',
            event_type='run_started',
            title='开始每日复盘',
            summary=f'运行日期 {run_date}',
            payload={'date': run_date},
            date=run_date,
        )
        try:
            brief = DailyReviewer().run(date=run_date)
            stored = self.store.save_daily_brief(brief)
            self.store.log_event(
                agent='orchestrator',
                event_type='run_completed',
                title='每日复盘完成',
                summary=stored.get('summary', ''),
                severity='warning' if stored.get('risk_flags') else 'info',
                payload={'status': stored.get('status')},
                date=run_date,
            )
            return stored
        except Exception as exc:
            self.store.log_event(
                agent='orchestrator',
                event_type='run_failed',
                title='每日复盘失败',
                summary=str(exc),
                severity='error',
                payload={'error': str(exc)},
                date=run_date,
            )
            raise

    def latest_brief(self) -> Dict:
        return self.store.get_daily_brief()


def run_daily_review(date: str = None) -> Dict:
    return AgentOrchestrator().run_daily_review(date=date)


def get_latest_brief() -> Dict:
    return AgentOrchestrator().latest_brief()


def main() -> int:
    parser = argparse.ArgumentParser(description='Run local Agent runtime tasks')
    parser.add_argument('task', choices=['daily-review'], nargs='?', default='daily-review')
    parser.add_argument('--date', default=None)
    args = parser.parse_args()

    if args.task == 'daily-review':
        result = run_daily_review(date=args.date)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

