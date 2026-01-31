#!/bin/bash
# V2 Evening Routine - Run at 6:00 PM ET on weekdays
# Cron: 0 18 * * 1-5 /home/ned_lindau/stock-radar/scripts/cron_v2_evening.sh

cd /home/ned_lindau/stock-radar
source venv/bin/activate

echo "=================================="
echo "V2 Evening Routine"
echo "$(date)"
echo "=================================="

# Run evening routine: check stops, snapshot, send report
python3 daily_run.py v2-evening --email >> logs/cron.log 2>&1

echo "Evening routine complete"
