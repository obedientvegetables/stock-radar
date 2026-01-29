#!/bin/bash
#
# Stock Radar V2 - Evening Scan Script
# Runs at 6:00 PM ET after market close
# Scans for momentum setups and emails report
#
# Usage: ./cron_v2_evening.sh
# Cron:  0 18 * * 1-5 /path/to/stock_radar/scripts/cron_v2_evening.sh
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
    echo "[$(timestamp)] [V2-EVENING] $1" >> "$LOG_FILE"
}

# Start
log "=========================================="
log "Starting V2 evening scan"

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
    log "V2 evening script finished (skipped)"
    log ""
    exit 0
fi

# Step 1: Update universe (weekly on Mondays)
DAY_OF_WEEK=$(date +%u)
if [ "$DAY_OF_WEEK" -eq 1 ]; then
    log "Monday - Updating stock universe"
    python3 daily_run.py v2-universe >> "$LOG_FILE" 2>&1
    UNIVERSE_EXIT=$?
    if [ $UNIVERSE_EXIT -eq 0 ]; then
        log "Universe update completed"
    else
        log "WARNING: Universe update failed with exit code $UNIVERSE_EXIT"
    fi
fi

# Step 2: Run the full evening scan
log "Running: python3 daily_run.py v2-evening"
python3 daily_run.py v2-evening >> "$LOG_FILE" 2>&1
EVENING_EXIT=$?

if [ $EVENING_EXIT -eq 0 ]; then
    log "V2 evening scan completed successfully"
else
    log "ERROR: V2 evening scan failed with exit code $EVENING_EXIT"
fi

log "V2 evening script finished"
log ""

exit $EVENING_EXIT
