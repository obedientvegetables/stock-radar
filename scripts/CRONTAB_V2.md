# V2 Crontab Configuration

Add these lines to your crontab (`crontab -e`):

```cron
# Stock Radar V2 - Minervini Momentum System
# All times are in server timezone (likely UTC)
# Adjust for your timezone - examples below are for US Eastern

# Morning scan at 6:30 AM ET (11:30 UTC during EST)
30 11 * * 1-5 /home/ned_lindau/stock-radar/scripts/cron_v2_morning.sh >> /home/ned_lindau/stock-radar/logs/cron.log 2>&1

# Market hours check every 30 min (9:30 AM - 4:00 PM ET)
# 14:30 - 21:00 UTC during EST
30 14 * * 1-5 /home/ned_lindau/stock-radar/scripts/cron_v2_check.sh >> /home/ned_lindau/stock-radar/logs/cron.log 2>&1
0,30 15-20 * * 1-5 /home/ned_lindau/stock-radar/scripts/cron_v2_check.sh >> /home/ned_lindau/stock-radar/logs/cron.log 2>&1
0 21 * * 1-5 /home/ned_lindau/stock-radar/scripts/cron_v2_check.sh >> /home/ned_lindau/stock-radar/logs/cron.log 2>&1

# Evening routine at 6:00 PM ET (23:00 UTC during EST)
0 23 * * 1-5 /home/ned_lindau/stock-radar/scripts/cron_v2_evening.sh >> /home/ned_lindau/stock-radar/logs/cron.log 2>&1
```

## Setup Steps

1. Make scripts executable:
```bash
chmod +x /home/ned_lindau/stock-radar/scripts/cron_v2_*.sh
```

2. Create logs directory if needed:
```bash
mkdir -p /home/ned_lindau/stock-radar/logs
```

3. Add cron jobs:
```bash
crontab -e
# Paste the cron lines above
```

4. Verify cron is running:
```bash
crontab -l
```

## Time Zone Notes

GCP VMs typically run in UTC. Adjust the times above based on:
- EST (Eastern Standard Time): UTC-5
- EDT (Eastern Daylight Time): UTC-4

Market hours are 9:30 AM - 4:00 PM ET.

## Monitoring

Check cron logs:
```bash
tail -f /home/ned_lindau/stock-radar/logs/cron.log
```

Check recent cron executions:
```bash
grep CRON /var/log/syslog | tail -20
```

## Disabling V2 Crons

To disable (without removing):
```bash
crontab -e
# Comment out lines with # at the start
```
