#!/bin/bash
# V2 Evening Routine - Run at 6:00 PM ET on weekdays
# Checks stops/targets, takes snapshot, sends daily report
#
# Crontab (adjust for UTC):
# 0 23 * * 1-5 /home/ned_lindau/stock-radar/scripts/cron_v2_evening.sh

cd /home/ned_lindau/stock-radar
source venv/bin/activate

echo "=================================="
echo "V2 Auto Trader - Evening Routine"
echo "$(date)"
echo "=================================="

# Run auto trader evening routine
python3 -c "
from signals.auto_trader import AutoTrader
trader = AutoTrader()
trader.run_evening_routine(send_emails=True)
" >> logs/cron.log 2>&1

echo "Evening routine complete"
