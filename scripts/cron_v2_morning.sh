#!/bin/bash
#
# Stock Radar V2 - Morning Breakout Check Script
# Runs at 6:30 AM ET before market open
# Checks watchlist for potential breakouts and manages stops
#
# Usage: ./cron_v2_morning.sh
# Cron:  30 6 * * 1-5 /path/to/stock_radar/scripts/cron_v2_morning.sh
#

# Get the directory where this script is located
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

# Ensure logs directory exists
mkdir -p "$PROJECT_DIR/logs"

# Log file
LOG_FILE="$PROJECT_DIR/logs/cron_v2.log"

# Timestamp function
timestamp() {
    date "+%Y-%m-%d %H:%M:%S"
}

# Log function
log() {
    echo "[$(timestamp)] [V2-MORNING] $1" >> "$LOG_FILE"
}

# Start
log "=========================================="
log "Starting V2 morning check"

# Change to project directory
cd "$PROJECT_DIR" || {
    log "ERROR: Could not cd to $PROJECT_DIR"
    exit 1
}

# Check if today is a trading day
IS_TRADING_DAY=$(python3 -c "
from utils.trading_calendar import is_trading_day
print('yes' if is_trading_day() else 'no')
" 2>/dev/null)

if [ "$IS_TRADING_DAY" != "yes" ]; then
    log "Skipping: Not a trading day"
    log "V2 morning script finished (skipped)"
    log ""
    exit 0
fi

# Run the morning check (breakouts + stop management)
log "Running: python3 daily_run.py v2-morning"
python3 daily_run.py v2-morning >> "$LOG_FILE" 2>&1
MORNING_EXIT=$?

if [ $MORNING_EXIT -eq 0 ]; then
    log "V2 morning check completed successfully"
else
    log "ERROR: V2 morning check failed with exit code $MORNING_EXIT"
fi

log "V2 morning script finished"
log ""

exit $MORNING_EXIT
