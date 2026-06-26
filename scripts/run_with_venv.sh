#!/bin/bash
# 使用项目 venv 执行命令 (Cron / 手动均可用)
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PYTHON="$ROOT/venv_akshare/bin/python"
if [[ ! -x "$PYTHON" ]]; then
  echo "ERROR: venv not found: $PYTHON" >&2
  exit 1
fi
cd "$ROOT"
exec "$PYTHON" "$@"
