#!/bin/bash
#
# Stock Radar - Morning Collection Script
# Runs at 8:00 AM ET to collect fresh insider data before market open
#
# Usage: ./cron_morning.sh
# Cron:  0 8 * * 1-5 /path/to/stock_radar/scripts/cron_morning.sh
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
    echo "[$(timestamp)] [MORNING] $1" >> "$LOG_FILE"
}

# Start
log "=========================================="
log "Starting morning collection"

# Change to project directory
cd "$PROJECT_DIR" || {
    log "ERROR: Could not cd to $PROJECT_DIR"
    exit 1
}

# Run morning collection (insider data)
log "Running: python3 daily_run.py morning --count 100"
python3 daily_run.py morning --count 100 >> "$LOG_FILE" 2>&1
EXIT_CODE=$?

if [ $EXIT_CODE -eq 0 ]; then
    log "Morning collection completed successfully"
else
    log "ERROR: Morning collection failed with exit code $EXIT_CODE"
fi

log "Morning script finished"
log ""

exit $EXIT_CODE
