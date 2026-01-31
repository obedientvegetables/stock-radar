#!/bin/bash
# V2 Morning Routine - Run at 6:30 AM ET on weekdays
# Scans for setups and prepares watchlist
#
# Crontab (adjust for your server timezone - example for UTC):
# 30 11 * * 1-5 /home/ned_lindau/stock-radar/scripts/cron_v2_morning.sh

cd /home/ned_lindau/stock-radar
source venv/bin/activate

echo "=================================="
echo "V2 Auto Trader - Morning Routine"
echo "$(date)"
echo "=================================="

# Run auto trader morning routine
python3 -c "
from signals.auto_trader import AutoTrader
trader = AutoTrader()
trader.run_morning_routine(send_emails=True)
" >> logs/cron.log 2>&1

echo "Morning routine complete"
