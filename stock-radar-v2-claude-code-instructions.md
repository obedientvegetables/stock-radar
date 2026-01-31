# Claude Code Instructions: Stock Radar v2

## Overview

You are building Stock Radar v2, a momentum-based stock trading signal system. The user has an existing codebase (v1) that uses insider trading signals, options flow, and social sentiment. The new system (v2) will use Minervini's SEPA methodology for systematic momentum trading.

**Key principle**: Paper trade first. The system should simulate trades with virtual money for 30+ days before any real capital is used.

---

## Project Context

### Current Repository Location
- **Remote**: Private GitHub repo (user will provide access)
- **Production**: GCP VM at `/home/ned_lindau/stock-radar`
- **VM Details**: instance-20260119-223954, IP: 34.10.246.252

### Existing Stack
- Python 3.x with Flask
- SQLite database at `data/radar.db`
- yfinance for market data
- Cron jobs for automation
- Running on GCP e2-micro VM

### What Works (Keep)
- Flask app structure
- Database connection utilities
- Market data collection via yfinance
- Email sending via Gmail SMTP
- Cron scheduling infrastructure
- Basic dashboard template structure

### What's Broken (Replace)
- Signal scoring logic (insider/options/social combination)
- Stock selection criteria (selecting penny stocks)
- The "Stock of the Day" algorithm

---

## Implementation Phases

### Phase 1: Foundation (Start Here)

**Goal**: Update database schema and configuration for v2.

#### Task 1.1: Update Database Schema

Add to `utils/db.py` SCHEMA variable:

```sql
-- Trend Template compliance tracking
CREATE TABLE IF NOT EXISTS trend_template (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT NOT NULL,
    date DATE NOT NULL,
    price REAL,
    ma_50 REAL,
    ma_150 REAL,
    ma_200 REAL,
    price_above_ma50 BOOLEAN,
    price_above_ma150 BOOLEAN,
    price_above_ma200 BOOLEAN,
    ma50_above_ma150 BOOLEAN,
    ma150_above_ma200 BOOLEAN,
    ma200_trending_up BOOLEAN,
    price_within_25pct_of_high BOOLEAN,
    price_above_30pct_from_low BOOLEAN,
    rs_rating REAL,
    template_compliant BOOLEAN,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(ticker, date)
);

-- Fundamental quality metrics
CREATE TABLE IF NOT EXISTS fundamentals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT NOT NULL,
    date DATE NOT NULL,
    eps_growth_quarterly REAL,
    eps_growth_annual REAL,
    eps_acceleration BOOLEAN,
    revenue_growth_quarterly REAL,
    revenue_growth_annual REAL,
    profit_margin REAL,
    margin_expanding BOOLEAN,
    fundamental_score INTEGER,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(ticker, date)
);

-- VCP pattern detection
CREATE TABLE IF NOT EXISTS vcp_patterns (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT NOT NULL,
    date DATE NOT NULL,
    num_contractions INTEGER,
    depth_contraction_1 REAL,
    depth_contraction_2 REAL,
    depth_contraction_3 REAL,
    current_depth REAL,
    volume_dry_up BOOLEAN,
    pivot_price REAL,
    pattern_valid BOOLEAN,
    pattern_score INTEGER,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(ticker, date)
);

-- Watchlist for breakout monitoring
CREATE TABLE IF NOT EXISTS watchlist_v2 (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT NOT NULL,
    added_date DATE NOT NULL,
    pivot_price REAL,
    stop_price REAL,
    target_price REAL,
    trend_score INTEGER,
    fundamental_score INTEGER,
    pattern_score INTEGER,
    total_score INTEGER,
    status TEXT DEFAULT 'WATCHING',
    triggered_date DATE,
    triggered_price REAL,
    notes TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Paper trading v2 (separate from v1 trades table)
CREATE TABLE IF NOT EXISTS paper_trades_v2 (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT NOT NULL,
    entry_date DATE NOT NULL,
    entry_price REAL NOT NULL,
    shares INTEGER NOT NULL,
    position_value REAL NOT NULL,
    stop_price REAL NOT NULL,
    target_price REAL NOT NULL,
    current_stop REAL,
    highest_price REAL,
    exit_date DATE,
    exit_price REAL,
    exit_reason TEXT,
    return_pct REAL,
    return_dollars REAL,
    days_held INTEGER,
    status TEXT DEFAULT 'OPEN',
    notes TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Alert log
CREATE TABLE IF NOT EXISTS alerts_v2 (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT NOT NULL,
    alert_type TEXT NOT NULL,
    message TEXT,
    sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    delivered BOOLEAN DEFAULT FALSE
);

-- Portfolio snapshots for tracking
CREATE TABLE IF NOT EXISTS portfolio_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date DATE NOT NULL,
    cash REAL NOT NULL,
    positions_value REAL NOT NULL,
    total_value REAL NOT NULL,
    daily_pnl REAL,
    daily_pnl_pct REAL,
    open_positions INTEGER,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(date)
);

-- Add indexes
CREATE INDEX IF NOT EXISTS idx_trend_template_ticker_date ON trend_template(ticker, date);
CREATE INDEX IF NOT EXISTS idx_fundamentals_ticker_date ON fundamentals(ticker, date);
CREATE INDEX IF NOT EXISTS idx_vcp_patterns_ticker_date ON vcp_patterns(ticker, date);
CREATE INDEX IF NOT EXISTS idx_watchlist_v2_status ON watchlist_v2(status);
CREATE INDEX IF NOT EXISTS idx_paper_trades_v2_status ON paper_trades_v2(status);
```

#### Task 1.2: Update Configuration

Add to `utils/config.py`:

```python
# === V2 CONFIGURATION ===

# Quality Filters
MIN_STOCK_PRICE = float(os.getenv("MIN_STOCK_PRICE", "10.0"))
MIN_MARKET_CAP = float(os.getenv("MIN_MARKET_CAP", "500000000"))  # $500M
MIN_AVG_VOLUME = int(os.getenv("MIN_AVG_VOLUME", "500000"))  # shares/day
RS_MIN_RATING = int(os.getenv("RS_MIN_RATING", "70"))  # Top 30%

# Fundamental Thresholds
MIN_EPS_GROWTH = float(os.getenv("MIN_EPS_GROWTH", "15"))  # %
MIN_REVENUE_GROWTH = float(os.getenv("MIN_REVENUE_GROWTH", "10"))  # %

# VCP Pattern Settings
MAX_BASE_DEPTH = float(os.getenv("MAX_BASE_DEPTH", "35"))  # %
MIN_CONTRACTIONS = int(os.getenv("MIN_CONTRACTIONS", "2"))
MAX_CONTRACTIONS = int(os.getenv("MAX_CONTRACTIONS", "5"))

# V2 Position Sizing
V2_PORTFOLIO_SIZE = float(os.getenv("V2_PORTFOLIO_SIZE", "50000"))
V2_MAX_POSITION_PCT = float(os.getenv("V2_MAX_POSITION_PCT", "0.20"))
V2_MAX_POSITIONS = int(os.getenv("V2_MAX_POSITIONS", "6"))
V2_MAX_RISK_PER_TRADE = float(os.getenv("V2_MAX_RISK_PER_TRADE", "0.02"))  # 2%
V2_DEFAULT_STOP_PCT = float(os.getenv("V2_DEFAULT_STOP_PCT", "0.07"))  # 7%
V2_DEFAULT_TARGET_PCT = float(os.getenv("V2_DEFAULT_TARGET_PCT", "0.20"))  # 20%

# Breakout Confirmation
VOLUME_BREAKOUT_MULTIPLIER = float(os.getenv("VOLUME_BREAKOUT_MULTIPLIER", "1.5"))
EARNINGS_BUFFER_DAYS = int(os.getenv("EARNINGS_BUFFER_DAYS", "5"))

# API Keys (user needs to set these)
FMP_API_KEY = os.getenv("FMP_API_KEY")  # Financial Modeling Prep
```

---

### Phase 2: Screening Engine

**Goal**: Build the Trend Template screener and RS rating calculator.

#### Task 2.1: Create `signals/trend_template.py`

```python
"""
Minervini Trend Template Scanner

Checks stocks against the 8-point Trend Template criteria.
ALL criteria must pass for a stock to be considered.
"""

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Optional
import yfinance as yf

@dataclass
class TrendTemplateResult:
    ticker: str
    date: date
    price: float

    # Moving averages
    ma_50: float
    ma_150: float
    ma_200: float

    # Individual criteria (True = pass)
    c1_price_above_ma50: bool
    c2_price_above_ma150: bool
    c3_price_above_ma200: bool
    c4_ma50_above_ma150: bool
    c5_ma150_above_ma200: bool
    c6_ma200_trending_up: bool
    c7_within_25pct_of_high: bool
    c8_above_30pct_from_low: bool

    # Overall
    passes_template: bool
    criteria_passed: int  # out of 8

    # Additional context
    rs_rating: Optional[float] = None
    distance_from_high_pct: Optional[float] = None
    distance_from_low_pct: Optional[float] = None


def check_trend_template(ticker: str, target_date: Optional[date] = None) -> TrendTemplateResult:
    """
    Check if a stock passes the Minervini Trend Template.

    The 8 criteria:
    1. Price > 50-day MA
    2. Price > 150-day MA
    3. Price > 200-day MA
    4. 50-day MA > 150-day MA
    5. 150-day MA > 200-day MA
    6. 200-day MA trending up (1+ months)
    7. Price within 25% of 52-week high
    8. Price at least 30% above 52-week low
    """
    if target_date is None:
        target_date = date.today()

    # Fetch historical data (need 252 trading days for 52-week high/low + MA calculation)
    stock = yf.Ticker(ticker)
    hist = stock.history(period="15mo")  # ~315 days to ensure we have enough

    if len(hist) < 200:
        raise ValueError(f"Insufficient data for {ticker}: only {len(hist)} days")

    # Get current price and MAs
    current_price = hist['Close'].iloc[-1]
    ma_50 = hist['Close'].rolling(50).mean().iloc[-1]
    ma_150 = hist['Close'].rolling(150).mean().iloc[-1]
    ma_200 = hist['Close'].rolling(200).mean().iloc[-1]

    # 200-day MA from 30 days ago (to check if trending up)
    ma_200_30d_ago = hist['Close'].rolling(200).mean().iloc[-30] if len(hist) >= 230 else ma_200

    # 52-week high and low
    high_52w = hist['High'].tail(252).max()
    low_52w = hist['Low'].tail(252).min()

    # Calculate criteria
    c1 = current_price > ma_50
    c2 = current_price > ma_150
    c3 = current_price > ma_200
    c4 = ma_50 > ma_150
    c5 = ma_150 > ma_200
    c6 = ma_200 > ma_200_30d_ago  # Trending up
    c7 = current_price >= high_52w * 0.75  # Within 25% of high
    c8 = current_price >= low_52w * 1.30  # At least 30% above low

    criteria = [c1, c2, c3, c4, c5, c6, c7, c8]

    return TrendTemplateResult(
        ticker=ticker,
        date=target_date,
        price=current_price,
        ma_50=ma_50,
        ma_150=ma_150,
        ma_200=ma_200,
        c1_price_above_ma50=c1,
        c2_price_above_ma150=c2,
        c3_price_above_ma200=c3,
        c4_ma50_above_ma150=c4,
        c5_ma150_above_ma200=c5,
        c6_ma200_trending_up=c6,
        c7_within_25pct_of_high=c7,
        c8_above_30pct_from_low=c8,
        passes_template=all(criteria),
        criteria_passed=sum(criteria),
        distance_from_high_pct=((high_52w - current_price) / high_52w) * 100,
        distance_from_low_pct=((current_price - low_52w) / low_52w) * 100
    )
```

#### Task 2.2: Create `signals/relative_strength.py`

```python
"""
Relative Strength Rating Calculator

Calculates IBD-style RS rating by comparing stock performance
to all stocks in the universe.
"""

from datetime import date, timedelta
from typing import List, Dict
import yfinance as yf


def calculate_rs_rating(
    ticker: str,
    universe: List[str],
    lookback_days: int = 252
) -> float:
    """
    Calculate relative strength rating (0-100).

    Compares the stock's 12-month performance to all stocks
    in the universe and returns the percentile ranking.

    RS Rating of 90 means the stock outperformed 90% of stocks.
    """
    # Get performance for target stock
    target_perf = _get_performance(ticker, lookback_days)
    if target_perf is None:
        return 0.0

    # Get performance for all stocks in universe
    performances = []
    for t in universe:
        perf = _get_performance(t, lookback_days)
        if perf is not None:
            performances.append(perf)

    if not performances:
        return 50.0  # Default if no comparison available

    # Calculate percentile
    below = sum(1 for p in performances if p < target_perf)
    percentile = (below / len(performances)) * 100

    return round(percentile, 1)


def _get_performance(ticker: str, days: int) -> Optional[float]:
    """Get % performance over specified days."""
    try:
        stock = yf.Ticker(ticker)
        hist = stock.history(period=f"{days + 30}d")  # Buffer for missing days

        if len(hist) < days * 0.8:  # Need at least 80% of days
            return None

        start_price = hist['Close'].iloc[-days] if len(hist) >= days else hist['Close'].iloc[0]
        end_price = hist['Close'].iloc[-1]

        return ((end_price - start_price) / start_price) * 100
    except:
        return None
```

#### Task 2.3: Create `collectors/fundamentals.py` (using FMP API)

```python
"""
Fundamental Data Collector

Uses Financial Modeling Prep API (free tier: 250 calls/day)
to fetch earnings, revenue, and margin data.
"""

import os
import requests
from dataclasses import dataclass
from datetime import date
from typing import Optional, Dict, List

FMP_BASE_URL = "https://financialmodelingprep.com/api/v3"


@dataclass
class FundamentalData:
    ticker: str
    date: date

    # Earnings
    eps_quarterly: Optional[float]
    eps_growth_quarterly: Optional[float]  # YoY %
    eps_growth_annual: Optional[float]
    eps_acceleration: bool  # This Q growth > Last Q growth

    # Revenue
    revenue_quarterly: Optional[float]
    revenue_growth_quarterly: Optional[float]
    revenue_growth_annual: Optional[float]

    # Margins
    profit_margin: Optional[float]
    margin_expanding: bool

    # Quality score
    fundamental_score: int  # 0-100


def get_fundamentals(ticker: str) -> FundamentalData:
    """
    Fetch fundamental data from Financial Modeling Prep.

    Free tier allows 250 calls/day, so use wisely.
    """
    api_key = os.getenv("FMP_API_KEY")
    if not api_key:
        raise ValueError("FMP_API_KEY not set in environment")

    # Get income statement (quarterly)
    url = f"{FMP_BASE_URL}/income-statement/{ticker}?period=quarter&limit=8&apikey={api_key}"
    response = requests.get(url)

    if response.status_code != 200:
        raise ValueError(f"FMP API error: {response.status_code}")

    data = response.json()

    if not data or len(data) < 2:
        return _empty_fundamentals(ticker, "Insufficient data")

    # Current and year-ago quarters
    current = data[0]
    year_ago = data[4] if len(data) > 4 else None
    last_q = data[1] if len(data) > 1 else None

    # Calculate EPS growth
    eps_current = current.get('eps', 0)
    eps_year_ago = year_ago.get('eps', 0) if year_ago else 0
    eps_last_q = last_q.get('eps', 0) if last_q else 0

    eps_growth_q = _calc_growth(eps_current, eps_year_ago)

    # Calculate EPS acceleration (is this quarter's growth > last quarter's growth?)
    if last_q and len(data) > 5:
        last_q_year_ago = data[5]
        last_q_growth = _calc_growth(eps_last_q, last_q_year_ago.get('eps', 0))
        eps_acceleration = eps_growth_q is not None and last_q_growth is not None and eps_growth_q > last_q_growth
    else:
        eps_acceleration = False

    # Calculate revenue growth
    rev_current = current.get('revenue', 0)
    rev_year_ago = year_ago.get('revenue', 0) if year_ago else 0
    rev_growth_q = _calc_growth(rev_current, rev_year_ago)

    # Calculate margins
    profit_margin = (current.get('netIncome', 0) / rev_current * 100) if rev_current else None
    last_margin = (last_q.get('netIncome', 0) / last_q.get('revenue', 1) * 100) if last_q and last_q.get('revenue') else None
    margin_expanding = profit_margin is not None and last_margin is not None and profit_margin > last_margin

    # Calculate score
    score = _calculate_fundamental_score(eps_growth_q, rev_growth_q, eps_acceleration, margin_expanding)

    return FundamentalData(
        ticker=ticker,
        date=date.today(),
        eps_quarterly=eps_current,
        eps_growth_quarterly=eps_growth_q,
        eps_growth_annual=None,  # Would need annual data
        eps_acceleration=eps_acceleration,
        revenue_quarterly=rev_current,
        revenue_growth_quarterly=rev_growth_q,
        revenue_growth_annual=None,
        profit_margin=profit_margin,
        margin_expanding=margin_expanding,
        fundamental_score=score
    )


def _calc_growth(current: float, previous: float) -> Optional[float]:
    """Calculate growth percentage."""
    if previous == 0 or previous is None:
        return None
    return ((current - previous) / abs(previous)) * 100


def _calculate_fundamental_score(eps_growth, rev_growth, acceleration, margin_expanding) -> int:
    """Calculate fundamental quality score 0-100."""
    score = 0

    # EPS growth (up to 40 points)
    if eps_growth is not None:
        if eps_growth >= 50:
            score += 40
        elif eps_growth >= 25:
            score += 30
        elif eps_growth >= 15:
            score += 20
        elif eps_growth > 0:
            score += 10

    # Revenue growth (up to 30 points)
    if rev_growth is not None:
        if rev_growth >= 25:
            score += 30
        elif rev_growth >= 15:
            score += 20
        elif rev_growth >= 10:
            score += 15
        elif rev_growth > 0:
            score += 5

    # EPS acceleration (15 points)
    if acceleration:
        score += 15

    # Margin expansion (15 points)
    if margin_expanding:
        score += 15

    return min(score, 100)


def _empty_fundamentals(ticker: str, reason: str) -> FundamentalData:
    """Return empty fundamentals result."""
    return FundamentalData(
        ticker=ticker,
        date=date.today(),
        eps_quarterly=None,
        eps_growth_quarterly=None,
        eps_growth_annual=None,
        eps_acceleration=False,
        revenue_quarterly=None,
        revenue_growth_quarterly=None,
        revenue_growth_annual=None,
        profit_margin=None,
        margin_expanding=False,
        fundamental_score=0
    )
```

#### Task 2.4: Create `collectors/universe.py`

```python
"""
Stock Universe Management

Maintains the list of stocks to screen.
Filters by price, market cap, and volume.
"""

from typing import List, Dict
import yfinance as yf
import pandas as pd

# S&P 500 tickers (update periodically)
SP500_URL = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"


def get_sp500_tickers() -> List[str]:
    """Fetch current S&P 500 constituents."""
    try:
        tables = pd.read_html(SP500_URL)
        df = tables[0]
        return df['Symbol'].str.replace('.', '-').tolist()
    except Exception as e:
        print(f"Error fetching S&P 500: {e}")
        # Fallback to hardcoded list
        return _get_fallback_tickers()


def filter_universe(
    tickers: List[str],
    min_price: float = 10.0,
    min_market_cap: float = 500_000_000,
    min_volume: int = 500_000
) -> List[str]:
    """
    Filter tickers by quality criteria.

    Returns tickers that pass all filters.
    """
    valid = []

    for ticker in tickers:
        try:
            stock = yf.Ticker(ticker)
            info = stock.info

            # Check price
            price = info.get('regularMarketPrice') or info.get('currentPrice', 0)
            if price < min_price:
                continue

            # Check market cap
            market_cap = info.get('marketCap', 0)
            if market_cap < min_market_cap:
                continue

            # Check volume
            avg_volume = info.get('averageVolume', 0)
            if avg_volume < min_volume:
                continue

            valid.append(ticker)

        except Exception as e:
            continue  # Skip problematic tickers

    return valid


def _get_fallback_tickers() -> List[str]:
    """Hardcoded major tickers as fallback."""
    return [
        'AAPL', 'MSFT', 'GOOGL', 'AMZN', 'NVDA', 'META', 'TSLA', 'BRK-B',
        'JPM', 'V', 'UNH', 'MA', 'HD', 'PG', 'JNJ', 'MRK', 'ABBV', 'CVX',
        'LLY', 'PEP', 'KO', 'COST', 'AVGO', 'MCD', 'WMT', 'CSCO', 'TMO',
        'ACN', 'ABT', 'DHR', 'NKE', 'TXN', 'NEE', 'PM', 'UPS', 'RTX',
        # Add more as needed
    ]
```

---

### Phase 3: Entry Detection

**Goal**: Build VCP pattern detector and breakout confirmation.

#### Task 3.1: Create `signals/vcp_detector.py`

```python
"""
Volatility Contraction Pattern (VCP) Detector

Identifies stocks forming the VCP pattern:
- Multiple contractions in price range
- Each contraction shallower than the last
- Volume drying up during consolidation
"""

from dataclasses import dataclass
from datetime import date
from typing import List, Optional
import numpy as np
import yfinance as yf


@dataclass
class VCPPattern:
    ticker: str
    date: date
    is_valid: bool

    # Pattern characteristics
    num_contractions: int
    contractions: List[float]  # Depth of each contraction (%)
    pivot_price: float

    # Volume analysis
    volume_declining: bool
    volume_dry_up_ratio: float  # Current vol / avg vol

    # Quality score
    pattern_score: int  # 0-100

    # Context
    base_length_days: int
    notes: str


def detect_vcp(ticker: str, lookback_days: int = 90) -> VCPPattern:
    """
    Detect Volatility Contraction Pattern in price data.

    A valid VCP has:
    1. 2-5 contractions (pullbacks from local highs)
    2. Each contraction is shallower than the previous
    3. Volume is declining (drying up)
    4. Price is forming a tight pivot point
    """
    stock = yf.Ticker(ticker)
    hist = stock.history(period=f"{lookback_days + 20}d")

    if len(hist) < lookback_days:
        return _empty_vcp(ticker, "Insufficient data")

    # Use last N days
    hist = hist.tail(lookback_days)

    # Find local highs (potential contraction start points)
    highs = _find_local_highs(hist['High'].values)
    lows = _find_local_lows(hist['Low'].values)

    # Calculate contractions
    contractions = _calculate_contractions(hist, highs, lows)

    # Check if contractions are decreasing
    is_decreasing = _contractions_decreasing(contractions)

    # Analyze volume
    avg_vol = hist['Volume'].mean()
    recent_vol = hist['Volume'].tail(5).mean()
    vol_ratio = recent_vol / avg_vol if avg_vol > 0 else 1.0
    vol_declining = vol_ratio < 0.8  # Volume at least 20% below average

    # Calculate pivot price (resistance level)
    pivot = hist['High'].tail(20).max()

    # Determine validity
    num_contractions = len(contractions)
    is_valid = (
        2 <= num_contractions <= 5 and
        is_decreasing and
        vol_declining and
        max(contractions) <= 35 if contractions else False  # No contraction > 35%
    )

    # Score the pattern
    score = _calculate_vcp_score(contractions, vol_ratio, is_decreasing)

    return VCPPattern(
        ticker=ticker,
        date=date.today(),
        is_valid=is_valid,
        num_contractions=num_contractions,
        contractions=contractions,
        pivot_price=pivot,
        volume_declining=vol_declining,
        volume_dry_up_ratio=vol_ratio,
        pattern_score=score,
        base_length_days=lookback_days,
        notes=_generate_notes(is_valid, contractions, vol_declining)
    )


def _find_local_highs(prices: np.ndarray, window: int = 5) -> List[int]:
    """Find indices of local high points."""
    highs = []
    for i in range(window, len(prices) - window):
        if prices[i] == max(prices[i-window:i+window+1]):
            highs.append(i)
    return highs


def _find_local_lows(prices: np.ndarray, window: int = 5) -> List[int]:
    """Find indices of local low points."""
    lows = []
    for i in range(window, len(prices) - window):
        if prices[i] == min(prices[i-window:i+window+1]):
            lows.append(i)
    return lows


def _calculate_contractions(hist, highs, lows) -> List[float]:
    """Calculate the depth of each contraction."""
    # Implementation: measure pullback from each high to subsequent low
    contractions = []
    # ... detailed implementation
    return contractions


def _contractions_decreasing(contractions: List[float]) -> bool:
    """Check if each contraction is shallower than the previous."""
    if len(contractions) < 2:
        return False
    for i in range(1, len(contractions)):
        if contractions[i] >= contractions[i-1]:
            return False
    return True


def _calculate_vcp_score(contractions, vol_ratio, is_decreasing) -> int:
    """Calculate pattern quality score 0-100."""
    score = 0

    # Points for number of contractions (2-3 is ideal)
    if 2 <= len(contractions) <= 3:
        score += 30
    elif len(contractions) == 4:
        score += 20

    # Points for decreasing contractions
    if is_decreasing:
        score += 25

    # Points for volume dry-up
    if vol_ratio < 0.5:
        score += 25
    elif vol_ratio < 0.7:
        score += 15
    elif vol_ratio < 0.9:
        score += 5

    # Points for tight final contraction
    if contractions and contractions[-1] < 15:
        score += 20
    elif contractions and contractions[-1] < 20:
        score += 10

    return min(score, 100)


def _empty_vcp(ticker: str, reason: str) -> VCPPattern:
    """Return empty/invalid VCP result."""
    return VCPPattern(
        ticker=ticker,
        date=date.today(),
        is_valid=False,
        num_contractions=0,
        contractions=[],
        pivot_price=0.0,
        volume_declining=False,
        volume_dry_up_ratio=1.0,
        pattern_score=0,
        base_length_days=0,
        notes=reason
    )


def _generate_notes(is_valid, contractions, vol_declining) -> str:
    """Generate human-readable notes about the pattern."""
    if is_valid:
        return f"{len(contractions)} contractions, volume drying up"

    issues = []
    if not contractions or len(contractions) < 2:
        issues.append("insufficient contractions")
    if not vol_declining:
        issues.append("volume not declining")

    return "Invalid: " + ", ".join(issues)
```

#### Task 3.2: Create `signals/breakout.py`

```python
"""
Breakout Detection

Identifies when a stock breaks out above its pivot point
with volume confirmation.
"""

from dataclasses import dataclass
from datetime import date
from typing import Optional
import yfinance as yf


@dataclass
class BreakoutSignal:
    ticker: str
    date: date
    is_breakout: bool

    # Price action
    pivot_price: float
    current_price: float
    breakout_pct: float  # How far above pivot

    # Volume confirmation
    volume_today: int
    avg_volume: int
    volume_ratio: float
    volume_confirmed: bool

    # Entry parameters
    suggested_entry: float
    suggested_stop: float
    suggested_target: float
    risk_reward_ratio: float

    notes: str


def check_breakout(
    ticker: str,
    pivot_price: float,
    volume_multiplier: float = 1.5
) -> BreakoutSignal:
    """
    Check if stock is breaking out above pivot.

    Requirements for valid breakout:
    1. Price > pivot price
    2. Volume >= volume_multiplier * average volume
    3. Price not extended (< 5% above pivot ideally)
    """
    stock = yf.Ticker(ticker)
    hist = stock.history(period="30d")

    if len(hist) < 20:
        return _empty_breakout(ticker, pivot_price, "Insufficient data")

    # Current price and volume
    current_price = hist['Close'].iloc[-1]
    volume_today = int(hist['Volume'].iloc[-1])
    avg_volume = int(hist['Volume'].tail(20).mean())

    # Check breakout conditions
    is_above_pivot = current_price > pivot_price
    breakout_pct = ((current_price - pivot_price) / pivot_price) * 100

    volume_ratio = volume_today / avg_volume if avg_volume > 0 else 0
    volume_confirmed = volume_ratio >= volume_multiplier

    is_breakout = is_above_pivot and volume_confirmed and breakout_pct < 5

    # Calculate entry parameters
    entry = current_price
    stop = pivot_price * 0.93  # 7% below pivot
    target = entry * 1.20  # 20% profit target

    risk = entry - stop
    reward = target - entry
    rr_ratio = reward / risk if risk > 0 else 0

    return BreakoutSignal(
        ticker=ticker,
        date=date.today(),
        is_breakout=is_breakout,
        pivot_price=pivot_price,
        current_price=current_price,
        breakout_pct=breakout_pct,
        volume_today=volume_today,
        avg_volume=avg_volume,
        volume_ratio=volume_ratio,
        volume_confirmed=volume_confirmed,
        suggested_entry=round(entry, 2),
        suggested_stop=round(stop, 2),
        suggested_target=round(target, 2),
        risk_reward_ratio=round(rr_ratio, 2),
        notes=_generate_breakout_notes(is_above_pivot, volume_confirmed, breakout_pct)
    )


def _empty_breakout(ticker: str, pivot: float, reason: str) -> BreakoutSignal:
    """Return empty breakout signal."""
    return BreakoutSignal(
        ticker=ticker,
        date=date.today(),
        is_breakout=False,
        pivot_price=pivot,
        current_price=0,
        breakout_pct=0,
        volume_today=0,
        avg_volume=0,
        volume_ratio=0,
        volume_confirmed=False,
        suggested_entry=0,
        suggested_stop=0,
        suggested_target=0,
        risk_reward_ratio=0,
        notes=reason
    )


def _generate_breakout_notes(above_pivot: bool, vol_confirmed: bool, pct: float) -> str:
    """Generate notes about breakout quality."""
    if above_pivot and vol_confirmed and pct < 5:
        return f"Valid breakout +{pct:.1f}% with volume"

    issues = []
    if not above_pivot:
        issues.append("below pivot")
    if not vol_confirmed:
        issues.append("volume not confirmed")
    if pct >= 5:
        issues.append(f"extended {pct:.1f}%")

    return "No breakout: " + ", ".join(issues)
```

---

### Phase 4: Paper Trading Engine

**Goal**: Build the paper trading system to simulate trades.

#### Task 4.1: Create `utils/paper_trading.py`

```python
"""
Paper Trading Engine

Simulates trades with virtual money for validation.
Tracks positions, calculates P&L, manages stops/targets.
"""

from dataclasses import dataclass
from datetime import date
from typing import List, Optional, Dict
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from utils.db import get_db
from utils.config import config


@dataclass
class Position:
    id: int
    ticker: str
    entry_date: date
    entry_price: float
    shares: int
    position_value: float
    stop_price: float
    target_price: float
    current_stop: float
    highest_price: float
    status: str


@dataclass
class PortfolioStatus:
    cash: float
    positions_value: float
    total_value: float
    open_positions: List[Position]
    daily_pnl: float
    daily_pnl_pct: float
    total_pnl: float
    total_pnl_pct: float


class PaperTradingEngine:
    """
    Manages paper trading portfolio.
    """

    def __init__(self, starting_capital: float = None):
        self.starting_capital = starting_capital or config.V2_PORTFOLIO_SIZE
        self._ensure_initialized()

    def _ensure_initialized(self):
        """Ensure portfolio is initialized in database."""
        with get_db() as conn:
            cursor = conn.execute(
                "SELECT COUNT(*) FROM portfolio_snapshots"
            )
            if cursor.fetchone()[0] == 0:
                # Initialize with starting capital
                conn.execute("""
                    INSERT INTO portfolio_snapshots
                    (date, cash, positions_value, total_value, daily_pnl, daily_pnl_pct, open_positions)
                    VALUES (?, ?, 0, ?, 0, 0, 0)
                """, (date.today().isoformat(), self.starting_capital, self.starting_capital))

    def enter_trade(
        self,
        ticker: str,
        entry_price: float,
        shares: int,
        stop_price: float,
        target_price: float,
        notes: str = ""
    ) -> int:
        """
        Enter a new paper trade.

        Returns: trade_id
        """
        position_value = entry_price * shares

        with get_db() as conn:
            cursor = conn.execute("""
                INSERT INTO paper_trades_v2
                (ticker, entry_date, entry_price, shares, position_value,
                 stop_price, target_price, current_stop, highest_price, notes)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                ticker, date.today().isoformat(), entry_price, shares,
                position_value, stop_price, target_price, stop_price,
                entry_price, notes
            ))

            trade_id = cursor.lastrowid

            # Update cash
            self._update_cash(-position_value)

        return trade_id

    def exit_trade(
        self,
        trade_id: int,
        exit_price: float,
        reason: str = "MANUAL"
    ) -> Dict:
        """
        Exit an existing trade.

        Returns: dict with trade results
        """
        with get_db() as conn:
            # Get trade details
            cursor = conn.execute(
                "SELECT * FROM paper_trades_v2 WHERE id = ?", (trade_id,)
            )
            trade = cursor.fetchone()

            if not trade or trade['status'] != 'OPEN':
                raise ValueError(f"Trade {trade_id} not found or not open")

            # Calculate returns
            entry_price = trade['entry_price']
            shares = trade['shares']
            return_pct = ((exit_price - entry_price) / entry_price) * 100
            return_dollars = (exit_price - entry_price) * shares
            days_held = (date.today() - date.fromisoformat(trade['entry_date'])).days

            # Update trade
            conn.execute("""
                UPDATE paper_trades_v2
                SET exit_date = ?, exit_price = ?, exit_reason = ?,
                    return_pct = ?, return_dollars = ?, days_held = ?,
                    status = 'CLOSED'
                WHERE id = ?
            """, (
                date.today().isoformat(), exit_price, reason,
                return_pct, return_dollars, days_held, trade_id
            ))

            # Return cash
            exit_value = exit_price * shares
            self._update_cash(exit_value)

        return {
            'trade_id': trade_id,
            'ticker': trade['ticker'],
            'return_pct': round(return_pct, 2),
            'return_dollars': round(return_dollars, 2),
            'days_held': days_held,
            'reason': reason
        }

    def check_stops_and_targets(self, current_prices: Dict[str, float]) -> List[Dict]:
        """
        Check all open positions for stop/target hits.

        Returns: list of triggered exits
        """
        triggered = []

        with get_db() as conn:
            cursor = conn.execute(
                "SELECT * FROM paper_trades_v2 WHERE status = 'OPEN'"
            )
            positions = cursor.fetchall()

            for pos in positions:
                ticker = pos['ticker']
                if ticker not in current_prices:
                    continue

                price = current_prices[ticker]

                # Check stop
                if price <= pos['current_stop']:
                    result = self.exit_trade(pos['id'], price, 'STOP')
                    triggered.append(result)
                    continue

                # Check target
                if price >= pos['target_price']:
                    result = self.exit_trade(pos['id'], price, 'TARGET')
                    triggered.append(result)
                    continue

                # Update trailing stop if price made new high
                if price > pos['highest_price']:
                    new_stop = self._calculate_trailing_stop(
                        pos['entry_price'], price, pos['current_stop']
                    )
                    conn.execute("""
                        UPDATE paper_trades_v2
                        SET highest_price = ?, current_stop = ?
                        WHERE id = ?
                    """, (price, new_stop, pos['id']))

        return triggered

    def _calculate_trailing_stop(
        self,
        entry_price: float,
        current_price: float,
        current_stop: float
    ) -> float:
        """
        Calculate new trailing stop.

        Rules:
        - After +5%: Move to breakeven
        - After +10%: Trail at highest - 10%
        """
        gain_pct = ((current_price - entry_price) / entry_price) * 100

        if gain_pct >= 10:
            # Trail at 10% below highest
            new_stop = current_price * 0.90
        elif gain_pct >= 5:
            # Move to breakeven
            new_stop = entry_price
        else:
            new_stop = current_stop

        # Never lower the stop
        return max(new_stop, current_stop)

    def get_portfolio_status(self, current_prices: Dict[str, float]) -> PortfolioStatus:
        """Get current portfolio status."""
        with get_db() as conn:
            # Get cash
            cursor = conn.execute(
                "SELECT cash FROM portfolio_snapshots ORDER BY date DESC LIMIT 1"
            )
            cash = cursor.fetchone()['cash']

            # Get open positions
            cursor = conn.execute(
                "SELECT * FROM paper_trades_v2 WHERE status = 'OPEN'"
            )
            positions = []
            positions_value = 0

            for row in cursor.fetchall():
                ticker = row['ticker']
                current_price = current_prices.get(ticker, row['entry_price'])
                pos_value = current_price * row['shares']
                positions_value += pos_value

                positions.append(Position(
                    id=row['id'],
                    ticker=ticker,
                    entry_date=date.fromisoformat(row['entry_date']),
                    entry_price=row['entry_price'],
                    shares=row['shares'],
                    position_value=pos_value,
                    stop_price=row['stop_price'],
                    target_price=row['target_price'],
                    current_stop=row['current_stop'],
                    highest_price=row['highest_price'],
                    status=row['status']
                ))

            total_value = cash + positions_value
            total_pnl = total_value - self.starting_capital
            total_pnl_pct = (total_pnl / self.starting_capital) * 100

            return PortfolioStatus(
                cash=cash,
                positions_value=positions_value,
                total_value=total_value,
                open_positions=positions,
                daily_pnl=0,  # Calculate separately
                daily_pnl_pct=0,
                total_pnl=total_pnl,
                total_pnl_pct=total_pnl_pct
            )

    def _update_cash(self, amount: float):
        """Update cash balance."""
        with get_db() as conn:
            conn.execute("""
                UPDATE portfolio_snapshots
                SET cash = cash + ?
                WHERE date = (SELECT MAX(date) FROM portfolio_snapshots)
            """, (amount,))

    def calculate_position_size(
        self,
        entry_price: float,
        stop_price: float,
        portfolio_value: float = None
    ) -> int:
        """
        Calculate position size based on risk.

        Risk per trade = 2% of portfolio
        """
        if portfolio_value is None:
            portfolio_value = self.starting_capital

        risk_per_share = entry_price - stop_price
        max_risk = portfolio_value * config.V2_MAX_RISK_PER_TRADE

        shares = int(max_risk / risk_per_share) if risk_per_share > 0 else 0

        # Cap at max position %
        max_shares = int((portfolio_value * config.V2_MAX_POSITION_PCT) / entry_price)

        return min(shares, max_shares)
```

---

### Phase 5: Dashboard & Alerts

**Goal**: Update the dashboard for v2 and add alert system.

#### Task 5.1: Create new API endpoints in `app.py`

Add these routes:

```python
# ============================================================================
# V2 API ENDPOINTS
# ============================================================================

@app.route("/api/v2/portfolio")
def api_v2_portfolio():
    """Get V2 paper trading portfolio status."""
    from utils.paper_trading import PaperTradingEngine
    from collectors.market import get_current_prices

    engine = PaperTradingEngine()

    # Get current prices for open positions
    positions = engine.get_open_positions()
    tickers = [p.ticker for p in positions]
    prices = get_current_prices(tickers)

    status = engine.get_portfolio_status(prices)

    return jsonify({
        "cash": status.cash,
        "positions_value": status.positions_value,
        "total_value": status.total_value,
        "total_pnl": status.total_pnl,
        "total_pnl_pct": status.total_pnl_pct,
        "positions": [
            {
                "id": p.id,
                "ticker": p.ticker,
                "shares": p.shares,
                "entry_price": p.entry_price,
                "current_price": prices.get(p.ticker, p.entry_price),
                "stop": p.current_stop,
                "target": p.target_price,
                "pnl_pct": ((prices.get(p.ticker, p.entry_price) - p.entry_price) / p.entry_price) * 100
            }
            for p in status.open_positions
        ]
    })


@app.route("/api/v2/watchlist")
def api_v2_watchlist():
    """Get V2 watchlist - stocks ready for breakout."""
    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        SELECT * FROM watchlist_v2
        WHERE status = 'WATCHING'
        ORDER BY total_score DESC
    """)

    watchlist = [dict(row) for row in cur.fetchall()]
    conn.close()

    return jsonify({"watchlist": watchlist})


@app.route("/api/v2/screening")
def api_v2_screening():
    """Get today's screening results."""
    conn = get_db()
    cur = conn.cursor()

    today = date.today().isoformat()

    cur.execute("""
        SELECT t.*, f.fundamental_score, v.pattern_score
        FROM trend_template t
        LEFT JOIN fundamentals f ON t.ticker = f.ticker AND f.date = ?
        LEFT JOIN vcp_patterns v ON t.ticker = v.ticker AND v.date = ?
        WHERE t.date = ? AND t.template_compliant = 1
        ORDER BY t.rs_rating DESC
    """, (today, today, today))

    results = [dict(row) for row in cur.fetchall()]
    conn.close()

    return jsonify({"results": results, "date": today})


@app.route("/api/v2/enter-trade", methods=["POST"])
def api_v2_enter_trade():
    """Enter a new V2 paper trade."""
    from utils.paper_trading import PaperTradingEngine

    data = request.get_json()

    engine = PaperTradingEngine()

    try:
        trade_id = engine.enter_trade(
            ticker=data['ticker'],
            entry_price=data['price'],
            shares=data['shares'],
            stop_price=data['stop'],
            target_price=data['target'],
            notes=data.get('notes', '')
        )

        return jsonify({"success": True, "trade_id": trade_id})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})


@app.route("/api/v2/exit-trade", methods=["POST"])
def api_v2_exit_trade():
    """Exit a V2 paper trade."""
    from utils.paper_trading import PaperTradingEngine

    data = request.get_json()

    engine = PaperTradingEngine()

    try:
        result = engine.exit_trade(
            trade_id=data['trade_id'],
            exit_price=data['price'],
            reason=data.get('reason', 'MANUAL')
        )

        return jsonify({"success": True, **result})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})
```

#### Task 5.2: Create `output/alerts.py`

```python
"""
Alert System

Sends notifications for important events.
"""

from datetime import datetime
from typing import Optional
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from utils.db import get_db
from utils.config import config
from output.emailer import send_email


def send_alert(
    alert_type: str,
    ticker: str,
    message: str,
    send_email: bool = True
) -> int:
    """
    Send an alert and log it.

    Alert types:
    - BREAKOUT: New entry opportunity
    - STOP_HIT: Position stopped out
    - TARGET_HIT: Profit target reached
    - WATCHLIST_ADD: New stock added to watchlist
    - WEEKLY_SCAN: Weekly screening results

    Returns: alert_id
    """
    # Log to database
    with get_db() as conn:
        cursor = conn.execute("""
            INSERT INTO alerts_v2 (ticker, alert_type, message, delivered)
            VALUES (?, ?, ?, ?)
        """, (ticker, alert_type, message, False))

        alert_id = cursor.lastrowid

    # Send notification
    if send_email and config.ALERT_EMAIL:
        subject = f"[Stock Radar] {alert_type}: {ticker}"
        _send_email_alert(subject, message, alert_id)

    return alert_id


def _send_email_alert(subject: str, message: str, alert_id: int):
    """Send email and update delivery status."""
    try:
        send_email(
            to=config.EMAIL_TO,
            subject=subject,
            body=message
        )

        # Mark as delivered
        with get_db() as conn:
            conn.execute(
                "UPDATE alerts_v2 SET delivered = 1 WHERE id = ?",
                (alert_id,)
            )
    except Exception as e:
        print(f"Failed to send alert email: {e}")


def format_breakout_alert(ticker: str, pivot: float, price: float, volume_ratio: float) -> str:
    """Format a breakout alert message."""
    return f"""
BREAKOUT ALERT: {ticker}

Pivot Price: ${pivot:.2f}
Current Price: ${price:.2f} (+{((price-pivot)/pivot)*100:.1f}%)
Volume: {volume_ratio:.1f}x average

ACTION: Review for potential entry

---
Stock Radar V2
"""


def format_stop_hit_alert(ticker: str, entry: float, exit: float, return_pct: float) -> str:
    """Format a stop hit alert message."""
    return f"""
STOP HIT: {ticker}

Entry Price: ${entry:.2f}
Exit Price: ${exit:.2f}
Return: {return_pct:+.1f}%

Position closed automatically.

---
Stock Radar V2
"""


def format_target_hit_alert(ticker: str, entry: float, exit: float, return_pct: float) -> str:
    """Format a target hit alert message."""
    return f"""
TARGET HIT: {ticker}

Entry Price: ${entry:.2f}
Exit Price: ${exit:.2f}
Return: {return_pct:+.1f}%

Profit target reached! Position closed.

---
Stock Radar V2
"""
```

---

## CLI Commands to Add

Add these commands to `daily_run.py`:

```python
# V2 Commands

@cli.command("v2-init")
def v2_init():
    """Initialize V2 database tables and portfolio."""
    from utils.db import init_db
    init_db()

    from utils.paper_trading import PaperTradingEngine
    engine = PaperTradingEngine()

    click.echo("V2 initialized successfully!")
    click.echo(f"Starting capital: ${config.V2_PORTFOLIO_SIZE:,.2f}")


@cli.command("v2-scan")
@click.option("--limit", "-l", default=50, help="Number of stocks to scan")
def v2_scan(limit):
    """Run V2 screening: Trend Template + RS + VCP."""
    from collectors.universe import get_sp500_tickers, filter_universe
    from signals.trend_template import check_trend_template

    click.echo("Fetching universe...")
    tickers = get_sp500_tickers()[:limit]  # Limit for testing

    click.echo(f"Scanning {len(tickers)} stocks...")

    passing = []
    for ticker in tickers:
        try:
            result = check_trend_template(ticker)
            if result.passes_template:
                passing.append(result)
                click.echo(f"  ✓ {ticker} - RS: {result.rs_rating or 'N/A'}")
        except Exception as e:
            click.echo(f"  ✗ {ticker}: {e}")

    click.echo()
    click.echo(f"Found {len(passing)} stocks passing Trend Template")


@cli.command("v2-portfolio")
def v2_portfolio():
    """Show V2 paper trading portfolio status."""
    from utils.paper_trading import PaperTradingEngine
    from collectors.market import get_current_prices

    engine = PaperTradingEngine()

    # Get current prices
    positions = engine.get_open_positions() if hasattr(engine, 'get_open_positions') else []
    tickers = [p.ticker for p in positions] if positions else []
    prices = get_current_prices(tickers) if tickers else {}

    status = engine.get_portfolio_status(prices)

    click.echo("=" * 50)
    click.echo("V2 PAPER TRADING PORTFOLIO")
    click.echo("=" * 50)
    click.echo()
    click.echo(f"Cash:            ${status.cash:>12,.2f}")
    click.echo(f"Positions:       ${status.positions_value:>12,.2f}")
    click.echo(f"Total Value:     ${status.total_value:>12,.2f}")
    click.echo()
    click.echo(f"Total P&L:       ${status.total_pnl:>+12,.2f} ({status.total_pnl_pct:+.2f}%)")
    click.echo()

    if status.open_positions:
        click.echo("Open Positions:")
        click.echo("-" * 50)
        for pos in status.open_positions:
            current = prices.get(pos.ticker, pos.entry_price)
            pnl = ((current - pos.entry_price) / pos.entry_price) * 100
            click.echo(f"  {pos.ticker:<6} {pos.shares:>5} sh @ ${pos.entry_price:.2f}  "
                      f"Now: ${current:.2f}  P&L: {pnl:+.1f}%")
    else:
        click.echo("No open positions")


@cli.command("v2-enter")
@click.argument("ticker")
@click.option("--price", "-p", type=float, required=True, help="Entry price")
@click.option("--shares", "-s", type=int, help="Number of shares (auto-calculated if not provided)")
@click.option("--stop", type=float, help="Stop price (default: -7%)")
@click.option("--target", type=float, help="Target price (default: +20%)")
def v2_enter(ticker, price, shares, stop, target):
    """Enter a V2 paper trade."""
    from utils.paper_trading import PaperTradingEngine

    engine = PaperTradingEngine()

    # Calculate defaults
    if stop is None:
        stop = price * (1 - config.V2_DEFAULT_STOP_PCT)
    if target is None:
        target = price * (1 + config.V2_DEFAULT_TARGET_PCT)
    if shares is None:
        shares = engine.calculate_position_size(price, stop)

    trade_id = engine.enter_trade(
        ticker=ticker.upper(),
        entry_price=price,
        shares=shares,
        stop_price=stop,
        target_price=target
    )

    click.echo(f"Entered trade #{trade_id}:")
    click.echo(f"  {ticker.upper()} - {shares} shares @ ${price:.2f}")
    click.echo(f"  Stop: ${stop:.2f} | Target: ${target:.2f}")


@cli.command("v2-exit")
@click.argument("trade_id", type=int)
@click.option("--price", "-p", type=float, required=True, help="Exit price")
@click.option("--reason", "-r", default="MANUAL", help="Exit reason")
def v2_exit(trade_id, price, reason):
    """Exit a V2 paper trade."""
    from utils.paper_trading import PaperTradingEngine

    engine = PaperTradingEngine()

    result = engine.exit_trade(trade_id, price, reason)

    click.echo(f"Exited trade #{trade_id}:")
    click.echo(f"  {result['ticker']} @ ${price:.2f}")
    click.echo(f"  Return: {result['return_pct']:+.2f}% (${result['return_dollars']:+.2f})")
    click.echo(f"  Days held: {result['days_held']}")
```

---

## Testing Checklist

After each phase, verify:

### Phase 1
- [ ] Database migrations run without error
- [ ] New tables created
- [ ] Config values load correctly

### Phase 2
- [ ] Trend Template correctly identifies compliant stocks
- [ ] RS rating calculation returns valid percentiles
- [ ] Universe filtering removes penny stocks

### Phase 3
- [ ] VCP detector identifies valid patterns
- [ ] Breakout detection triggers on volume
- [ ] Earnings data prevents entries near earnings

### Phase 4
- [ ] Paper trades enter correctly
- [ ] Stops execute at correct prices
- [ ] Trailing stops update properly
- [ ] Portfolio value calculates correctly

### Phase 5
- [ ] Dashboard shows V2 portfolio
- [ ] Alerts send via email
- [ ] API endpoints return expected data

---

## Important Notes

1. **Keep V1 running** - Don't break existing functionality during development
2. **Test locally first** - Before deploying to GCP
3. **Paper trade only** - No real money until 30+ days of validation
4. **Log everything** - We need data to evaluate performance
5. **Ask questions** - If anything is unclear, ask the user

---

## User Preferences & Decisions

Based on conversation history:
- Prefers minimal daily attention (work + family)
- Wants automation over manual review
- Values statistical validation
- Currently using GCP e2-micro VM
- Email alerts are acceptable, SMS optional
- Starting paper trading capital: $50,000

### Confirmed Decisions (Jan 28, 2026)

1. **Fundamental Data API**: Using Financial Modeling Prep free tier (250 calls/day)
   - Sign up at: https://site.financialmodelingprep.com/developer/docs
   - Add `FMP_API_KEY` to `.env` file

2. **Paper Trading Capital**: $50,000 starting balance

3. **V1 System**: Shut down completely
   - Stop V1 cron jobs
   - Keep V1 database tables for reference but don't run V1 scoring
   - Start fresh with V2

4. **Existing Positions**: Ignore completely
   - Don't migrate GMGI, UPXI, VNRX to V2
   - User will handle closing those manually if desired
   - V2 starts with clean slate: $50,000 cash, no positions

---

## First Steps After Opening Claude Code

1. **Create a new branch for V2 development**
   ```bash
   cd /home/ned_lindau/stock-radar
   git checkout -b v2-momentum
   ```
   All V2 work should happen on this branch. Keep `main` intact as a fallback.

2. **Set up FMP API Key** (user may have already done this)
   ```bash
   # On GCP VM, add to .env file:
   echo "FMP_API_KEY=your_key_here" >> /home/ned_lindau/stock-radar/.env
   ```

3. **Stop V1 Cron Jobs** (user has already done this)
   ```bash
   # Edit crontab to comment out V1 jobs
   crontab -e
   # Comment out all stock-radar cron entries (add # at start of each line)
   ```

4. **Begin Phase 1 Implementation**
   - Update `utils/db.py` with new schema
   - Update `utils/config.py` with V2 settings
   - Run `python daily_run.py init` to create new tables
