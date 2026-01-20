# Stock Radar

A simple, automated system that identifies stocks likely to move based on convergence of:
- **Insider buying** (primary signal) - SEC Form 4 filings
- **Unusual options activity** (primary signal) - Call volume anomalies
- **Social media velocity** (confirmation signal) - Reddit/Stocktwits acceleration

## Philosophy

**Only trade when multiple independent signals align.**

This system is designed for minimal daily time investment (~10 min/day reviewing an email). The goal is 0-2 high-conviction picks per day, not a fire hose of mediocre signals.

## Quick Start

```bash
# 1. Clone and enter directory
cd ~/stock_radar

# 2. Create virtual environment
python3 -m venv venv
source venv/bin/activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Configure
cp .env.example .env
# Edit .env with your settings (email, SEC user agent)

# 5. Initialize database
python3 -m utils.db

# 6. Test the system
python3 daily_run.py status
```

## Project Structure

```
stock_radar/
├── collectors/          # Data collection modules
│   ├── insider.py       # SEC EDGAR Form 4 parser
│   ├── options.py       # Options flow from yfinance
│   ├── social.py        # Reddit + Stocktwits
│   └── market.py        # Price data
│
├── signals/             # Signal scoring logic
│   ├── insider_signal.py
│   ├── options_signal.py
│   ├── social_signal.py
│   └── combiner.py      # Combines signals, makes decisions
│
├── output/              # Output generation
│   ├── emailer.py       # SMTP email delivery
│   └── formatter.py     # Email content formatting
│
├── utils/               # Shared utilities
│   ├── config.py        # Configuration management
│   └── db.py            # Database operations
│
├── data/                # Database and cached data
│   └── radar.db         # SQLite database
│
├── logs/                # Daily logs
│
├── tests/               # Unit tests
│
├── daily_run.py         # Main CLI entry point
└── validate_insider.py  # Validation script for Phase 1.5
```

## Daily Usage

```bash
# Morning (8 AM ET) - Collect overnight insider filings
python3 daily_run.py morning

# Evening (4:30 PM ET) - Run full pipeline
python3 daily_run.py evening

# Manual commands
python3 daily_run.py status      # Check system health
python3 daily_run.py score       # Run scoring for today
python3 daily_run.py top         # Show top signals
python3 daily_run.py email       # Send daily email
python3 daily_run.py email --preview  # Preview without sending
```

## Signal Scoring

### Insider Signal (0-30 points)
- Any insider buy in 14 days: +5
- Each additional unique buyer: +3 (max +9)
- CEO or CFO buying: +8
- Buy value > $500k: +4
- Buy value > $1M: +4 more

### Options Signal (0-25 points)
- Call volume 2-3x average: +8
- Call volume 3-5x average: +12
- Call volume >5x average: +18
- Low put/call ratio (<0.5): +4
- Near-term expiration focus: +3

### Social Signal (0-20 points)
- Velocity > 100%: +6
- Velocity > 200%: +10
- Sentiment > 0.3: +4
- Bullish ratio > 65%: +3
- Cross-platform confirmation: +3

### Decision Rules
- **TRADE**: (insider >= 15 OR options >= 15) AND social >= 10
- **WATCH**: insider >= 10 OR options >= 10
- **NONE**: No primary signals

## Configuration

Copy `.env.example` to `.env` and configure:

```bash
# Required: Email for daily reports
EMAIL_SMTP_SERVER=smtp.gmail.com
EMAIL_USERNAME=your-email@gmail.com
EMAIL_PASSWORD=your-app-password
EMAIL_TO=your-email@gmail.com

# Required: SEC EDGAR access (use your email)
SEC_USER_AGENT=YourName your-email@example.com
```

## CLI Commands

```bash
# System
python3 daily_run.py status           # Check system health
python3 daily_run.py init             # Initialize/reset database

# Daily workflow
python3 daily_run.py morning          # Collect insider data
python3 daily_run.py evening          # Full pipeline (collect + score)
python3 daily_run.py score            # Run scoring only
python3 daily_run.py top              # Show top signals
python3 daily_run.py explain TICKER   # Show signal breakdown

# Email
python3 daily_run.py email --preview  # Preview email
python3 daily_run.py email --test     # Test email config
python3 daily_run.py email            # Send daily email

# Individual signals
python3 daily_run.py insider-collect  # Collect SEC Form 4 data
python3 daily_run.py insider-top      # Top insider buying scores
python3 daily_run.py insider-score TICKER

python3 daily_run.py options-collect  # Collect options data
python3 daily_run.py options-top      # Top options scores
python3 daily_run.py options-unusual  # Unusual activity

python3 daily_run.py social-collect   # Collect Reddit/Stocktwits
python3 daily_run.py social-top       # Top social scores
python3 daily_run.py social-trending  # Trending tickers

# Validation
python3 daily_run.py validate-backfill  # Fetch historical insider data
python3 daily_run.py validate-calculate # Calculate returns for events
python3 daily_run.py validate           # Run full validation analysis
python3 daily_run.py validate-report    # Show latest validation report
```

## Validation (Phase 1.5)

Before trusting the system, validate that insider buying actually predicts returns:

```bash
# Step 1: Backfill historical insider data (takes a while)
python3 daily_run.py validate-backfill --months 6

# Step 2: Calculate returns for each insider buy event
python3 daily_run.py validate-calculate

# Step 3: Run statistical analysis
python3 daily_run.py validate
```

The validation analyzes:
- Average excess returns at 1, 3, 5, 10, 20 days
- Win rate vs SPY benchmark
- Statistical significance (p-values)
- Segmentation by insider type (CEO/CFO vs Directors)
- Segmentation by buy size ($100k-$500k vs >$1M)

**Decision Criteria:**
- PROCEED if: 5-day excess return > 0.5% with p < 0.10
- PROCEED if: CEO/CFO buys show > 1% excess return
- STOP if: excess returns are negative or not significant

## Development Phases

- [x] Phase 0: Setup & Structure
- [x] Phase 1: Insider Trading Signal
- [x] Phase 1.5: Validation Gate
- [x] Phase 2: Options Flow Signal
- [x] Phase 3: Social Velocity Signal
- [x] Phase 4: Signal Combiner
- [x] Phase 5: Output System
- [ ] Phase 6: Automation
- [ ] Phase 7: Paper Trading
