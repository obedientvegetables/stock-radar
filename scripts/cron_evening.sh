#!/bin/bash
#
# Stock Radar - Evening Pipeline Script
# Runs at 4:30 PM ET after market close
# Skips execution on non-trading days
#
# Usage: ./cron_evening.sh
# Cron:  30 16 * * 1-5 /path/to/stock_radar/scripts/cron_evening.sh
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
    echo "[$(timestamp)] [EVENING] $1" >> "$LOG_FILE"
}

# Start
log "=========================================="
log "Starting evening pipeline"

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
    log "Evening script finished (skipped)"
    log ""
    exit 0
fi

# Run evening pipeline
log "Running: python3 daily_run.py evening"
python3 daily_run.py evening >> "$LOG_FILE" 2>&1
EVENING_EXIT=$?

if [ $EVENING_EXIT -eq 0 ]; then
    log "Evening pipeline completed successfully"
else
    log "ERROR: Evening pipeline failed with exit code $EVENING_EXIT"
fi

# Send email report
log "Running: python3 daily_run.py email"
python3 daily_run.py email >> "$LOG_FILE" 2>&1
EMAIL_EXIT=$?

if [ $EMAIL_EXIT -eq 0 ]; then
    log "Email sent successfully"
else
    log "WARNING: Email failed with exit code $EMAIL_EXIT"
fi

log "Evening script finished"
log ""

# Return non-zero if the main pipeline failed
exit $EVENING_EXIT
