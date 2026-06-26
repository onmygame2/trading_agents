#!/bin/bash
# 安装 v2 量化系统 crontab 自动任务
# 用法: bash scripts/install_crontab.sh

set -e
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
RUNNER="$ROOT/scripts/run_with_venv.sh"
chmod +x "$RUNNER"
LOG_DIR="$ROOT/logs"
mkdir -p "$LOG_DIR"

if [[ ! -x "$ROOT/venv_akshare/bin/python" ]]; then
  echo "ERROR: 请先创建 venv: python3 -m venv venv_akshare && venv_akshare/bin/pip install -r requirements.txt"
  exit 1
fi

CRON_FILE=$(mktemp)
crontab -l 2>/dev/null | grep -v "workingFolder/quant" | grep -v "daily_runner_v2" | grep -v "update_kline.py" | grep -v "optimize_weekly" | grep -v "run_with_venv" > "$CRON_FILE" || true

cat >> "$CRON_FILE" <<EOF
# A股量化 v2 自动任务 ($ROOT)
30 8 * * 1-5 $RUNNER update_kline.py >> $LOG_DIR/kline_update.log 2>&1
# 盘中每30分钟: 先卖后买 (9:30-11:30 / 13:00-15:00)
30 9 * * 1-5 $RUNNER daily_runner_v2.py >> $LOG_DIR/intraday.log 2>&1
0,30 10-11 * * 1-5 $RUNNER daily_runner_v2.py >> $LOG_DIR/intraday.log 2>&1
0,30 13-14 * * 1-5 $RUNNER daily_runner_v2.py >> $LOG_DIR/intraday.log 2>&1
0 15 * * 1-5 $RUNNER daily_runner_v2.py >> $LOG_DIR/intraday.log 2>&1
0 20 * * 5 $RUNNER optimize_weekly.py >> $LOG_DIR/weekly_opt.log 2>&1
EOF

crontab "$CRON_FILE"
rm "$CRON_FILE"
echo "Crontab 已安装 (Python: $ROOT/venv_akshare/bin/python):"
crontab -l | grep -E "quant|run_with_venv|daily_runner|update_kline"
echo ""
echo "盘中日志: $LOG_DIR/intraday.log"
echo "Dashboard: http://localhost:5890"
