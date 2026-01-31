#!/bin/bash
# V2 Breakout Check - Run every 30 min during market hours
# Auto-enters trades when breakouts occur
#
# Crontab (adjust for UTC - market hours are 9:30 AM - 4:00 PM ET):
# */30 14-20 * * 1-5 /home/ned_lindau/stock-radar/scripts/cron_v2_check.sh

cd /home/ned_lindau/stock-radar
source venv/bin/activate

echo "=================================="
echo "V2 Auto Trader - Breakout Check"
echo "$(date)"
echo "=================================="

# Run auto trader breakout check (will auto-enter trades)
python3 -c "
from signals.auto_trader import AutoTrader
trader = AutoTrader()
trader.run_breakout_check(send_emails=True)
" >> logs/cron.log 2>&1

echo "Breakout check complete"
