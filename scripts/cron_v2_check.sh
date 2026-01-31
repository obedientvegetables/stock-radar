#!/bin/bash
# V2 Market Hours Check - Run every 30 min during market hours
# Cron: */30 9-16 * * 1-5 /home/ned_lindau/stock-radar/scripts/cron_v2_check.sh

cd /home/ned_lindau/stock-radar
source venv/bin/activate

# Only run during market hours (9:30 AM - 4:00 PM ET)
HOUR=$(TZ="America/New_York" date +%H)
MIN=$(TZ="America/New_York" date +%M)

# Skip if before 9:30 AM
if [ "$HOUR" -eq 9 ] && [ "$MIN" -lt 30 ]; then
    exit 0
fi

echo "=================================="
echo "V2 Market Hours Check"
echo "$(date)"
echo "=================================="

# Check stops and targets
python3 daily_run.py v2-check >> logs/cron.log 2>&1

# Also check for breakouts
python3 daily_run.py v2-breakout >> logs/cron.log 2>&1
