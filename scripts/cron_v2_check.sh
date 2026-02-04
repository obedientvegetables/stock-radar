#!/bin/bash
# V2 Auto Trader - Run every 30 min during market hours (9:30 AM - 4:00 PM ET)
# Auto-enters momentum trades when breakout conditions are met
#
# Crontab entry (every 30 min during market hours):
# */30 9-16 * * 1-5 /home/ned_lindau/stock-radar/scripts/cron_v2_check.sh

PROJECT_DIR="/home/ned_lindau/stock-radar"
LOG_FILE="$PROJECT_DIR/logs/cron.log"

cd "$PROJECT_DIR"
source venv/bin/activate

echo "==================================" >> "$LOG_FILE"
echo "V2 Auto Trader - $(date)" >> "$LOG_FILE"
echo "==================================" >> "$LOG_FILE"

# Run the auto-trade command
python3 daily_run.py v2-auto-trade --email >> "$LOG_FILE" 2>&1

echo "Auto-trade check complete" >> "$LOG_FILE"
echo "" >> "$LOG_FILE"
