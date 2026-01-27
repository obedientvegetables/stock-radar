#!/bin/bash
#
# Stock Radar - Midday Exit Check Script
# Runs at 12:00 PM ET during market hours
# Checks open positions for stop/target/time exit conditions
#
# Usage: ./cron_midday.sh
# Cron:  0 12 * * 1-5 /path/to/stock_radar/scripts/cron_midday.sh
#

# Get the directory where this script is located
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

# Ensure logs directory exists
mkdir -p "$PROJECT_DIR/logs"

# Log file
LOG_FILE="$PROJECT_DIR/logs/cron.log"

# Timestamp function
timestamp() {
    date "+%Y-%m-%d %H:%M:%S"
}

# Log function
log() {
    echo "[$(timestamp)] [MIDDAY] $1" >> "$LOG_FILE"
}

# Start
log "=========================================="
log "Starting midday exit check"

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
    log "Midday script finished (skipped)"
    log ""
    exit 0
fi

# Run auto-exit check
log "Running: python3 daily_run.py auto-exit"
python3 daily_run.py auto-exit >> "$LOG_FILE" 2>&1
AUTOEXIT_EXIT=$?

if [ $AUTOEXIT_EXIT -eq 0 ]; then
    log "Auto-exit check completed successfully"
else
    log "ERROR: Auto-exit failed with exit code $AUTOEXIT_EXIT"
fi

log "Midday script finished"
log ""

exit $AUTOEXIT_EXIT
