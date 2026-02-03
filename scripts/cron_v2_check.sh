#!/bin/bash
# V2 Combined Check - Run every 30 min during market hours (9:30 AM - 4:00 PM ET)
# Auto-enters trades for BOTH momentum (breakouts) and mean reversion (oversold bounces)

PROJECT_DIR="/home/ned_lindau/stock-radar"
LOG_FILE="$PROJECT_DIR/logs/cron.log"

cd "$PROJECT_DIR"
source venv/bin/activate

echo "==================================" >> "$LOG_FILE"
echo "V2 Auto Trader - Combined Check" >> "$LOG_FILE"
echo "$(date)" >> "$LOG_FILE"
echo "==================================" >> "$LOG_FILE"

python3 -c "
from signals.auto_trader import AutoTrader
trader = AutoTrader()

# Run both strategies
print('--- MOMENTUM STRATEGY (70%) ---')
trader.run_breakout_check(send_emails=True)

print()
print('--- MEAN REVERSION STRATEGY (30%) ---')
trader.run_mean_reversion_check(send_emails=True)
" >> "$LOG_FILE" 2>&1

echo "Combined check complete" >> "$LOG_FILE"
echo "" >> "$LOG_FILE"
