#!/bin/bash
# 使用项目 venv 执行命令 (Cron / 手动均可用)
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
for CANDIDATE in \
  "$ROOT/venv_akshare/bin/python" \
  "$ROOT/.venv/bin/python" \
  "$(command -v python3 2>/dev/null || true)"; do
  if [[ -n "$CANDIDATE" && -x "$CANDIDATE" ]]; then
    PYTHON="$CANDIDATE"
    break
  fi
done
if [[ -z "${PYTHON:-}" ]]; then
  echo "ERROR: Python 3 executable not found" >&2
  exit 1
fi
cd "$ROOT"
export PYTHONPATH="$ROOT${PYTHONPATH:+:$PYTHONPATH}"
exec "$PYTHON" "$@"
