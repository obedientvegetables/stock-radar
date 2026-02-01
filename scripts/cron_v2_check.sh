#!/bin/bash
# V2 Combined Check - Run every 30 min during market hours
# Auto-enters trades for BOTH momentum (breakouts) and mean reversion (oversold bounces)
#
# Crontab (adjust for UTC - market hours are 9:30 AM - 4:00 PM ET):
# */30 14-20 * * 1-5 /home/ned_lindau/stock-radar/scripts/cron_v2_check.sh

cd /home/ned_lindau/stock-radar
source venv/bin/activate

echo "=================================="
echo "V2 Auto Trader - Combined Check"
echo "$(date)"
echo "=================================="

# Run auto trader combined check (momentum + mean reversion)
python3 -c "
from signals.auto_trader import AutoTrader
trader = AutoTrader()

# Run both strategies
print('--- MOMENTUM STRATEGY (70%) ---')
trader.run_breakout_check(send_emails=True)

print()
print('--- MEAN REVERSION STRATEGY (30%) ---')
trader.run_mean_reversion_check(send_emails=True)
" >> logs/cron.log 2>&1

echo "Combined check complete"
