#!/bin/bash
# V2 Morning Routine - Run at 6:30 AM ET on weekdays
# Scans for setups and prepares watchlist

PROJECT_DIR="/home/ned_lindau/stock-radar"
LOG_FILE="$PROJECT_DIR/logs/cron.log"

cd "$PROJECT_DIR"
source venv/bin/activate

echo "==================================" >> "$LOG_FILE"
echo "V2 Auto Trader - Morning Routine" >> "$LOG_FILE"
echo "$(date)" >> "$LOG_FILE"
echo "==================================" >> "$LOG_FILE"

python3 -c "
from signals.auto_trader import AutoTrader
trader = AutoTrader()
trader.run_morning_routine(send_emails=True)
" >> "$LOG_FILE" 2>&1

echo "Morning routine complete" >> "$LOG_FILE"
echo "" >> "$LOG_FILE"
