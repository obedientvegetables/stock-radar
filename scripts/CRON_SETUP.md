# Stock Radar - Cron Setup Guide

Automation setup for daily data collection and signal generation.

## Quick Start

### Mac (Local Development)

1. Make scripts executable:
```bash
chmod +x ~/stock_radar/scripts/cron_morning.sh
chmod +x ~/stock_radar/scripts/cron_evening.sh
```

2. Edit crontab:
```bash
crontab -e
```

3. Add these lines (adjust path if needed):
```cron
# Stock Radar - Morning collection at 8:00 AM ET
0 8 * * 1-5 /Users/nedlindau/stock_radar/scripts/cron_morning.sh

# Stock Radar - Evening pipeline at 4:30 PM ET
30 16 * * 1-5 /Users/nedlindau/stock_radar/scripts/cron_evening.sh
```

4. Verify cron is enabled:
```bash
crontab -l
```

### Linux (Cloud Server)

Same steps as Mac. For servers in UTC timezone, adjust times:

```cron
# Stock Radar - Morning collection at 8:00 AM ET = 13:00 UTC (or 12:00 UTC during DST)
0 13 * * 1-5 /home/user/stock_radar/scripts/cron_morning.sh

# Stock Radar - Evening pipeline at 4:30 PM ET = 21:30 UTC (or 20:30 UTC during DST)
30 21 * * 1-5 /home/user/stock_radar/scripts/cron_evening.sh
```

## Timezone Notes

### Eastern Time (ET)
- **EST (Nov-Mar)**: UTC-5
- **EDT (Mar-Nov)**: UTC-4

### Time Conversions

| ET Time | UTC (Winter/EST) | UTC (Summer/EDT) |
|---------|------------------|------------------|
| 8:00 AM | 13:00            | 12:00            |
| 4:30 PM | 21:30            | 20:30            |

### Best Practice for Cloud

Set your server to ET timezone to avoid DST confusion:

```bash
# Check current timezone
timedatectl

# Set to Eastern Time
sudo timedatectl set-timezone America/New_York
```

## Mac-Specific: launchd Alternative

If cron doesn't work reliably on your Mac (sleep issues), use launchd instead.

### Create Morning Agent

Create `~/Library/LaunchAgents/com.stockradar.morning.plist`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.stockradar.morning</string>
    <key>ProgramArguments</key>
    <array>
        <string>/Users/nedlindau/stock_radar/scripts/cron_morning.sh</string>
    </array>
    <key>StartCalendarInterval</key>
    <dict>
        <key>Hour</key>
        <integer>8</integer>
        <key>Minute</key>
        <integer>0</integer>
    </dict>
    <key>StandardOutPath</key>
    <string>/Users/nedlindau/stock_radar/logs/launchd_morning.log</string>
    <key>StandardErrorPath</key>
    <string>/Users/nedlindau/stock_radar/logs/launchd_morning.log</string>
</dict>
</plist>
```

### Create Evening Agent

Create `~/Library/LaunchAgents/com.stockradar.evening.plist`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.stockradar.evening</string>
    <key>ProgramArguments</key>
    <array>
        <string>/Users/nedlindau/stock_radar/scripts/cron_evening.sh</string>
    </array>
    <key>StartCalendarInterval</key>
    <dict>
        <key>Hour</key>
        <integer>16</integer>
        <key>Minute</key>
        <integer>30</integer>
    </dict>
    <key>StandardOutPath</key>
    <string>/Users/nedlindau/stock_radar/logs/launchd_evening.log</string>
    <key>StandardErrorPath</key>
    <string>/Users/nedlindau/stock_radar/logs/launchd_evening.log</string>
</dict>
</plist>
```

### Load the Agents

```bash
launchctl load ~/Library/LaunchAgents/com.stockradar.morning.plist
launchctl load ~/Library/LaunchAgents/com.stockradar.evening.plist
```

### Manage Agents

```bash
# Check status
launchctl list | grep stockradar

# Unload (disable)
launchctl unload ~/Library/LaunchAgents/com.stockradar.morning.plist
launchctl unload ~/Library/LaunchAgents/com.stockradar.evening.plist

# Reload after editing
launchctl unload ~/Library/LaunchAgents/com.stockradar.morning.plist
launchctl load ~/Library/LaunchAgents/com.stockradar.morning.plist
```

## Testing

### Test Scripts Manually

```bash
# Test morning collection
./scripts/cron_morning.sh

# Test evening pipeline (will skip if not a trading day)
./scripts/cron_evening.sh

# Check logs
tail -50 logs/cron.log
```

### Test Trading Day Detection

```bash
cd ~/stock_radar
python3 -c "
from utils.trading_calendar import is_trading_day
from datetime import date
print(f'Today ({date.today()}): {is_trading_day()}')
"
```

## Monitoring

### Check Logs

```bash
# Recent activity
tail -100 ~/stock_radar/logs/cron.log

# Watch live
tail -f ~/stock_radar/logs/cron.log

# Search for errors
grep -i error ~/stock_radar/logs/cron.log
```

### Health Check

```bash
python3 daily_run.py health
```

## Troubleshooting

### Cron Not Running

1. Check cron service:
```bash
# Mac
sudo launchctl list | grep cron

# Linux
systemctl status cron
```

2. Check cron logs:
```bash
# Mac
log show --predicate 'process == "cron"' --last 1h

# Linux
grep CRON /var/log/syslog
```

### Python Not Found

Add Python path to crontab:
```cron
PATH=/usr/local/bin:/usr/bin:/bin
0 8 * * 1-5 /path/to/scripts/cron_morning.sh
```

Or use full Python path in scripts:
```bash
/usr/local/bin/python3 daily_run.py morning
```

### Mac Sleep Issues

Your Mac must be awake for cron/launchd to run. Options:

1. **Keep laptop open** during trading hours
2. **Use Power Nap** (System Preferences > Energy Saver)
3. **Schedule wake** using `pmset`:
```bash
# Wake at 7:55 AM on weekdays
sudo pmset repeat wakeorpoweron MTWRF 07:55:00
```

### Missing Dependencies

Ensure virtual environment is activated in scripts if using one:
```bash
source /path/to/venv/bin/activate
python3 daily_run.py morning
```

## Google Cloud Migration

When you're ready to move to GCP:

1. Create a Compute Engine VM (e2-micro is sufficient)
2. Set timezone to America/New_York
3. Clone repo and install dependencies
4. Copy `.env` file with credentials
5. Set up cron using the Linux instructions above
6. The scripts are designed to work identically

The evening script already handles non-trading days, so you can leave it running 24/7.
