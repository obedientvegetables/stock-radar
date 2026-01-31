# Stock Radar v2: Momentum Trading System

## Project Overview

**Goal:** Transform Stock Radar from an insider/sentiment-based signal system into a systematic momentum trading system based on the Minervini SEPA methodology.

**Core Philosophy:** Buy quality stocks in confirmed uptrends at specific entry points, with strict risk management.

**Validation Approach:** Paper trade for 30+ days before using real capital.

---

## What's Changing

### Current System (v1)
- Signals based on: insider buying, options flow, social sentiment
- Problem: Lagging indicators, selects penny stocks, poor quality filters
- Result: -9% portfolio, picking stocks like VNRX at $0.26

### New System (v2)
- Signals based on: Minervini Trend Template + fundamentals + technical breakouts
- Quality filters: Min $10 price, $500M market cap, liquid options
- Holding period: 2-8 weeks (swing trades)
- Automated: Screening, entry detection, position management, alerts

---

## Technical Architecture

### Existing Infrastructure (Keep)
- GCP e2-micro VM (instance-20260119-223954)
- Flask web dashboard
- SQLite database
- Cron job scheduling
- yfinance for market data

### New Components (Build)
- Trend Template screener
- Fundamental data collector (new API integration)
- VCP (Volatility Contraction Pattern) detector
- Breakout detection with volume confirmation
- Automated stop management
- Email/SMS alerts

---

## Phase 1: Foundation (Week 1)

### 1.1 Database Schema Updates

Add new tables:

```sql
-- Trend Template compliance tracking
CREATE TABLE IF NOT EXISTS trend_template (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT NOT NULL,
    date DATE NOT NULL,

    -- Moving averages
    price REAL,
    ma_50 REAL,
    ma_150 REAL,
    ma_200 REAL,

    -- Template criteria (all must be TRUE for compliance)
    price_above_ma50 BOOLEAN,
    price_above_ma150 BOOLEAN,
    price_above_ma200 BOOLEAN,
    ma50_above_ma150 BOOLEAN,
    ma150_above_ma200 BOOLEAN,
    ma200_trending_up BOOLEAN,  -- 30-day slope positive
    price_within_25pct_of_high BOOLEAN,
    price_above_30pct_from_low BOOLEAN,

    -- Relative strength
    rs_rating REAL,  -- 0-100, percentile vs market

    -- Overall compliance
    template_compliant BOOLEAN,

    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(ticker, date)
);

-- Fundamental quality metrics
CREATE TABLE IF NOT EXISTS fundamentals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT NOT NULL,
    date DATE NOT NULL,

    -- Earnings
    eps_growth_quarterly REAL,  -- YoY %
    eps_growth_annual REAL,     -- YoY %
    eps_acceleration BOOLEAN,   -- This Q > Last Q growth

    -- Revenue
    revenue_growth_quarterly REAL,
    revenue_growth_annual REAL,

    -- Margins
    profit_margin REAL,
    margin_expanding BOOLEAN,

    -- Quality score (0-100)
    fundamental_score INTEGER,

    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(ticker, date)
);

-- VCP pattern detection
CREATE TABLE IF NOT EXISTS vcp_patterns (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT NOT NULL,
    date DATE NOT NULL,

    -- Pattern metrics
    num_contractions INTEGER,
    depth_contraction_1 REAL,  -- % depth of first pullback
    depth_contraction_2 REAL,
    depth_contraction_3 REAL,
    current_depth REAL,

    -- Volume
    volume_dry_up BOOLEAN,  -- Volume declining during base

    -- Pivot point
    pivot_price REAL,

    -- Pattern quality
    pattern_valid BOOLEAN,
    pattern_score INTEGER,  -- 0-100

    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(ticker, date)
);

-- Watchlist for breakout monitoring
CREATE TABLE IF NOT EXISTS watchlist (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT NOT NULL,
    added_date DATE NOT NULL,

    -- Entry criteria
    pivot_price REAL,
    stop_price REAL,
    target_price REAL,

    -- Scores
    trend_score INTEGER,
    fundamental_score INTEGER,
    pattern_score INTEGER,
    total_score INTEGER,

    -- Status
    status TEXT DEFAULT 'WATCHING',  -- WATCHING, TRIGGERED, EXPIRED, STOPPED
    triggered_date DATE,
    triggered_price REAL,

    notes TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Alert log
CREATE TABLE IF NOT EXISTS alerts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT NOT NULL,
    alert_type TEXT NOT NULL,  -- BREAKOUT, STOP_HIT, TARGET_HIT, PATTERN_FORMING
    message TEXT,
    sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    delivered BOOLEAN DEFAULT FALSE
);
```

### 1.2 Configuration Updates

Update `utils/config.py`:

```python
# Trend Template Thresholds
MIN_STOCK_PRICE = 10.0
MIN_MARKET_CAP = 500_000_000  # $500M
MIN_AVG_VOLUME = 500_000  # shares/day
RS_MIN_RATING = 70  # Top 30% of market

# Fundamental Thresholds
MIN_EPS_GROWTH = 15  # % YoY
MIN_REVENUE_GROWTH = 10  # % YoY

# VCP Pattern
MAX_BASE_DEPTH = 35  # % max pullback in base
MIN_CONTRACTIONS = 2
MAX_CONTRACTIONS = 5

# Position Sizing
PAPER_PORTFOLIO_SIZE = 50000  # Paper trading starting capital
MAX_POSITION_PCT = 0.20  # Max 20% in single position
MAX_POSITIONS = 6  # Max concurrent positions
DEFAULT_STOP_PCT = 0.07  # 7% stop loss
DEFAULT_TARGET_PCT = 0.20  # 20% profit target

# Alerts
ALERT_EMAIL = True
ALERT_SMS = False  # Requires Twilio setup
```

### 1.3 Stock Universe

Create `collectors/universe.py`:

Fetch S&P 500 + Russell 1000 constituents, filter by:
- Price >= $10
- Market cap >= $500M
- Average volume >= 500K shares/day

---

## Phase 2: Screening Engine (Week 2)

### 2.1 Trend Template Scanner

Create `signals/trend_template.py`:

```python
def check_trend_template(ticker: str, target_date: date) -> TrendTemplateResult:
    """
    Check if stock passes Minervini's 8-point Trend Template.

    Returns:
        TrendTemplateResult with pass/fail for each criterion
    """
    # Get price and MA data
    # Calculate each criterion
    # Return structured result
```

Criteria (ALL must pass):
1. Price > 50-day MA
2. Price > 150-day MA
3. Price > 200-day MA
4. 50-day MA > 150-day MA
5. 150-day MA > 200-day MA
6. 200-day MA trending up (at least 1 month)
7. Price within 25% of 52-week high
8. Price at least 30% above 52-week low

### 2.2 Relative Strength Calculator

Create `signals/relative_strength.py`:

```python
def calculate_rs_rating(ticker: str, lookback: int = 252) -> float:
    """
    Calculate IBD-style relative strength rating.

    Compares stock's 12-month performance to all stocks in universe.
    Returns percentile ranking (0-100).
    """
```

### 2.3 Fundamental Screener

Create `collectors/fundamentals.py`:

Data source options (free tier):
- Financial Modeling Prep API (250 calls/day free)
- Alpha Vantage (5 calls/minute free)
- yfinance (limited fundamental data)

Collect:
- EPS (quarterly and annual)
- Revenue (quarterly and annual)
- Profit margins
- Calculate growth rates and acceleration

---

## Phase 3: Entry Detection (Week 3)

### 3.1 VCP Pattern Detector

Create `signals/vcp_detector.py`:

```python
def detect_vcp(ticker: str, lookback: int = 60) -> VCPPattern:
    """
    Detect Volatility Contraction Pattern.

    Looks for:
    - Multiple contractions (2-5)
    - Each contraction shallower than previous
    - Volume drying up
    - Price near pivot point
    """
```

### 3.2 Breakout Detection

Create `signals/breakout.py`:

```python
def check_breakout(ticker: str) -> BreakoutSignal:
    """
    Check for valid breakout conditions.

    Requirements:
    - Price crosses above pivot
    - Volume >= 1.5x average (confirmation)
    - No earnings within 5 days
    """
```

### 3.3 Earnings Calendar Integration

Create `collectors/earnings.py`:

```python
def get_earnings_date(ticker: str) -> Optional[date]:
    """Get next earnings date for ticker."""

def is_earnings_safe(ticker: str, days: int = 5) -> bool:
    """Check if we're far enough from earnings."""
```

---

## Phase 4: Position Management (Week 4)

### 4.1 Stop Loss Manager

Create `signals/stop_manager.py`:

```python
def calculate_initial_stop(entry_price: float, atr: float) -> float:
    """Calculate initial stop based on ATR or fixed %."""

def update_trailing_stop(
    current_price: float,
    current_stop: float,
    entry_price: float,
    highest_price: float
) -> float:
    """
    Update trailing stop.

    Rules:
    - After +5%: Move to breakeven
    - After +10%: Trail at highest - 10%
    - Never move stop down
    """
```

### 4.2 Paper Trading Engine

Update `utils/paper_trading.py`:

```python
class PaperTradingEngine:
    """
    Manages paper trading portfolio.

    Features:
    - Track positions with entry/stop/target
    - Calculate P&L daily
    - Auto-execute stops and targets
    - Log all actions
    """

    def enter_trade(self, ticker, price, shares, stop, target): ...
    def exit_trade(self, trade_id, price, reason): ...
    def check_stops(self): ...
    def check_targets(self): ...
    def get_portfolio_status(self): ...
```

### 4.3 Automated Trade Logging

Create `utils/trade_logger.py`:

Log every action with timestamp:
- Entry signals
- Actual entries
- Stop adjustments
- Exits (stop, target, manual)
- Daily P&L snapshots

---

## Phase 5: Alerts & Dashboard (Week 5)

### 5.1 Alert System

Create `output/alerts.py`:

```python
def send_alert(alert_type: str, ticker: str, message: str):
    """
    Send alert via configured channels.

    Types:
    - BREAKOUT: New entry opportunity
    - STOP_HIT: Position stopped out
    - TARGET_HIT: Profit target reached
    - WATCHLIST_ADD: New stock added to watchlist
    """
```

### 5.2 Dashboard Redesign

Update `templates/dashboard.html`:

New sections:
1. **Portfolio Overview**: Total value, P&L, open positions
2. **Today's Watchlist**: Stocks near breakout with pivot prices
3. **Position Manager**: Open trades with current stops, days held
4. **Screening Results**: Stocks passing Trend Template today
5. **Recent Alerts**: Last 20 alerts

### 5.3 API Endpoints

Add to `app.py`:

```python
@app.route("/api/v2/watchlist")
@app.route("/api/v2/portfolio")
@app.route("/api/v2/screening-results")
@app.route("/api/v2/enter-trade", methods=["POST"])
@app.route("/api/v2/exit-trade", methods=["POST"])
@app.route("/api/v2/update-stop", methods=["POST"])
```

---

## Phase 6: Automation (Week 6)

### 6.1 Cron Schedule

```
# Morning pre-market (6:00 AM ET)
0 6 * * 1-5 /path/to/daily_run.py morning-v2

# Market hours monitoring (every 15 min, 9:30 AM - 4:00 PM ET)
*/15 9-16 * * 1-5 /path/to/daily_run.py monitor-v2

# Evening analysis (6:00 PM ET)
0 18 * * 1-5 /path/to/daily_run.py evening-v2

# Weekend full scan (Saturday 10:00 AM)
0 10 * * 6 /path/to/daily_run.py weekly-scan
```

### 6.2 CLI Commands

Add to `daily_run.py`:

```python
@cli.command("morning-v2")
def morning_v2():
    """Pre-market routine: update data, check gaps, set alerts."""

@cli.command("monitor-v2")
def monitor_v2():
    """Intraday monitoring: check breakouts, stops, targets."""

@cli.command("evening-v2")
def evening_v2():
    """End of day: update screening, generate watchlist, send report."""

@cli.command("weekly-scan")
def weekly_scan():
    """Full universe scan for new candidates."""
```

---

## Data Flow

```
┌─────────────────────────────────────────────────────────────────┐
│                        DAILY WORKFLOW                           │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  6:00 AM    ┌─────────────┐                                     │
│  Morning    │ Update Data │                                     │
│             │ - Prices    │                                     │
│             │ - MAs       │                                     │
│             │ - Gaps      │                                     │
│             └──────┬──────┘                                     │
│                    │                                            │
│  9:30 AM    ┌──────▼──────┐                                     │
│  Market     │   Monitor   │◄──────────────────────┐             │
│  Open       │ - Breakouts │                       │             │
│             │ - Stops     │     Every 15 min      │             │
│             │ - Targets   │──────────────────────►│             │
│             └──────┬──────┘                                     │
│                    │                                            │
│  4:00 PM    ┌──────▼──────┐    ┌─────────────┐                  │
│  Close      │  Update     │    │   Alerts    │                  │
│             │  Positions  │───►│   Email     │                  │
│             └──────┬──────┘    └─────────────┘                  │
│                    │                                            │
│  6:00 PM    ┌──────▼──────┐    ┌─────────────┐                  │
│  Evening    │   Screen    │    │   Daily     │                  │
│             │ - Trend T   │───►│   Report    │                  │
│             │ - VCP       │    └─────────────┘                  │
│             │ - RS        │                                     │
│             └──────┬──────┘                                     │
│                    │                                            │
│             ┌──────▼──────┐                                     │
│             │  Generate   │                                     │
│             │  Watchlist  │                                     │
│             │  for Next   │                                     │
│             │  Day        │                                     │
│             └─────────────┘                                     │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

---

## Success Metrics

### Paper Trading Period (30+ days)

Track and report:

1. **Win Rate**: % of trades that are profitable
   - Target: > 40%

2. **Profit Factor**: Gross profits / Gross losses
   - Target: > 1.5

3. **Average Win vs Average Loss**
   - Target: Avg Win > 2x Avg Loss

4. **Max Drawdown**: Largest peak-to-trough decline
   - Target: < 15%

5. **Number of Signals**: Trades per week
   - Target: 1-3 quality setups

### Comparison Benchmarks

- SPY (S&P 500)
- MTUM (Momentum ETF)
- SPMO (S&P 500 Momentum ETF)

---

## Risk Management Rules

### Position Sizing

```python
def calculate_position_size(
    portfolio_value: float,
    entry_price: float,
    stop_price: float,
    max_risk_pct: float = 0.02  # 2% of portfolio
) -> int:
    """
    Calculate shares based on risk.

    Risk = (entry - stop) * shares
    Max Risk = portfolio * max_risk_pct
    Shares = Max Risk / (entry - stop)
    """
    risk_per_share = entry_price - stop_price
    max_risk_dollars = portfolio_value * max_risk_pct
    shares = int(max_risk_dollars / risk_per_share)

    # Cap at max position %
    max_shares = int((portfolio_value * MAX_POSITION_PCT) / entry_price)
    return min(shares, max_shares)
```

### Hard Rules (Never Break)

1. **Never average down** on losing positions
2. **Always use stops** - no exceptions
3. **Max 6 positions** at any time
4. **No trading within 5 days of earnings**
5. **No penny stocks** (< $10)
6. **Cut losses at 7-8%** maximum

---

## File Structure

```
stock-radar/
├── app.py                 # Flask dashboard
├── daily_run.py           # CLI entry point
├── requirements.txt
├── .env
│
├── collectors/
│   ├── __init__.py
│   ├── insider.py         # Keep (might use as secondary signal)
│   ├── options.py         # Keep (might use as confirmation)
│   ├── social.py          # Keep (reduced importance)
│   ├── market.py          # Update with more technicals
│   ├── universe.py        # NEW: Stock universe management
│   ├── fundamentals.py    # NEW: EPS, revenue collection
│   └── earnings.py        # NEW: Earnings calendar
│
├── signals/
│   ├── __init__.py
│   ├── insider_signal.py  # Keep (secondary)
│   ├── options_signal.py  # Keep (confirmation)
│   ├── social_signal.py   # Keep (reduced weight)
│   ├── trend_template.py  # NEW: 8-point template check
│   ├── relative_strength.py  # NEW: RS rating
│   ├── vcp_detector.py    # NEW: Pattern detection
│   ├── breakout.py        # NEW: Entry detection
│   ├── stop_manager.py    # NEW: Stop management
│   └── combiner_v2.py     # NEW: V2 signal combination
│
├── utils/
│   ├── __init__.py
│   ├── config.py          # Update with new params
│   ├── db.py              # Update schema
│   ├── trading_calendar.py
│   ├── paper_trading.py   # NEW: Paper trading engine
│   └── trade_logger.py    # NEW: Trade logging
│
├── output/
│   ├── __init__.py
│   ├── formatter.py       # Update for V2 reports
│   ├── emailer.py
│   └── alerts.py          # NEW: Alert system
│
├── templates/
│   ├── dashboard.html     # Redesign
│   └── index.html         # Keep for reference
│
├── scripts/
│   ├── cron_morning.sh    # Update
│   ├── cron_evening.sh    # Update
│   └── cron_monitor.sh    # NEW
│
├── data/
│   └── radar.db
│
└── logs/
    ├── cron.log
    └── trades.log         # NEW
```

---

## Migration Plan

### Week 1: Build alongside v1
- Keep v1 running
- Build v2 components in parallel
- Test v2 in isolation

### Week 2: Database migration
- Add new tables (non-breaking)
- Keep v1 tables intact
- Run both systems

### Week 3-4: Switch to v2
- Update cron jobs to v2
- Update dashboard to v2
- Keep v1 endpoints for comparison

### Week 5+: Paper trading
- Run v2 paper trading
- Track performance daily
- Compare to v1 and benchmarks

---

## Questions to Answer Before Starting

1. **Fundamental Data API**: Which free API to use?
   - Recommendation: Financial Modeling Prep (250/day free)

2. **Starting Capital for Paper Trading**:
   - Recommendation: $50,000 (realistic for validation)

3. **Alert Delivery**: Email only or also SMS?
   - Recommendation: Start with email, add SMS later

4. **Keep v1 Signals as Secondary?**
   - Recommendation: Yes, but weighted much lower

5. **Manual Confirmation vs Auto-Entry**:
   - Recommendation: Alert-based, manual confirmation for paper trading

---

## Next Steps

1. ~~Review this plan and confirm approach~~ ✓ Done
2. ~~Set up Financial Modeling Prep API key (free tier)~~ ✓ Done
3. ~~Disable V1 cron jobs~~ ✓ Done
4. Begin Phase 1 implementation with Claude Code
5. Existing V1 positions (GMGI, UPXI, VNRX) - ignoring, starting fresh with V2
