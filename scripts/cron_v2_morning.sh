#!/bin/bash
# V2 Morning Routine - Run at 6:30 AM ET on weekdays
# Cron: 30 6 * * 1-5 /home/ned_lindau/stock-radar/scripts/cron_v2_morning.sh

cd /home/ned_lindau/stock-radar
source venv/bin/activate

echo "=================================="
echo "V2 Morning Routine"
echo "$(date)"
echo "=================================="

# Run morning scan and send alert
python3 daily_run.py v2-morning --email >> logs/cron.log 2>&1

echo "Morning routine complete"
