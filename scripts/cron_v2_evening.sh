#!/bin/bash
# V2 Evening Routine - Run at 6:00 PM ET on weekdays
# Checks stops/targets, takes snapshot, sends daily report

PROJECT_DIR="/home/ned_lindau/stock-radar"
LOG_FILE="$PROJECT_DIR/logs/cron.log"

cd "$PROJECT_DIR"
source venv/bin/activate

echo "==================================" >> "$LOG_FILE"
echo "V2 Auto Trader - Evening Routine" >> "$LOG_FILE"
echo "$(date)" >> "$LOG_FILE"
echo "==================================" >> "$LOG_FILE"

python3 -c "
from signals.auto_trader import AutoTrader
trader = AutoTrader()
trader.run_evening_routine(send_emails=True)
" >> "$LOG_FILE" 2>&1

echo "Evening routine complete" >> "$LOG_FILE"
echo "" >> "$LOG_FILE"
