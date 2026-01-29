"""
Stock Radar Database Utilities

SQLite database connection and schema management.
"""

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Optional

from .config import config


@contextmanager
def get_db(db_path: Optional[Path] = None):
    """
    Context manager for database connections.

    Usage:
        with get_db() as conn:
            cursor = conn.execute("SELECT * FROM signals")
            rows = cursor.fetchall()
    """
    path = db_path or config.DB_PATH
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row  # Enable column access by name
    conn.execute("PRAGMA foreign_keys = ON")  # Enable foreign key support

    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db(db_path: Optional[Path] = None):
    """Initialize the database with the schema."""
    path = db_path or config.DB_PATH

    # Ensure data directory exists
    path.parent.mkdir(parents=True, exist_ok=True)

    with get_db(path) as conn:
        conn.executescript(SCHEMA)

    print(f"Database initialized at {path}")


# Database Schema
SCHEMA = """
-- Insider trading data from SEC EDGAR
CREATE TABLE IF NOT EXISTS insider_trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT NOT NULL,
    company_name TEXT,
    insider_name TEXT NOT NULL,
    insider_title TEXT,
    trade_type TEXT NOT NULL,  -- 'P' for purchase, 'S' for sale
    shares INTEGER,
    price_per_share REAL,
    total_value REAL,
    shares_owned_after INTEGER,
    trade_date DATE NOT NULL,
    filed_date DATE NOT NULL,
    form_type TEXT DEFAULT '4',
    source_url TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(ticker, insider_name, trade_date, shares, trade_type)
);

-- Daily aggregated insider activity per ticker
CREATE TABLE IF NOT EXISTS insider_daily (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT NOT NULL,
    date DATE NOT NULL,
    buy_transactions INTEGER DEFAULT 0,
    sell_transactions INTEGER DEFAULT 0,
    buy_value REAL DEFAULT 0,
    sell_value REAL DEFAULT 0,
    unique_buyers INTEGER DEFAULT 0,
    unique_sellers INTEGER DEFAULT 0,
    ceo_cfo_buying BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(ticker, date)
);

-- Options flow data
CREATE TABLE IF NOT EXISTS options_flow (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT NOT NULL,
    date DATE NOT NULL,
    call_volume INTEGER,
    put_volume INTEGER,
    call_oi INTEGER,  -- open interest
    put_oi INTEGER,
    avg_call_volume_20d REAL,
    avg_put_volume_20d REAL,
    call_volume_ratio REAL,  -- today vs 20d avg
    put_call_ratio REAL,
    unusual_calls BOOLEAN DEFAULT FALSE,
    unusual_puts BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(ticker, date)
);

-- Social media metrics
CREATE TABLE IF NOT EXISTS social_metrics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT NOT NULL,
    date DATE NOT NULL,
    reddit_mentions INTEGER DEFAULT 0,
    reddit_sentiment REAL,  -- -1 to 1
    reddit_velocity REAL,   -- % change from yesterday
    stocktwits_mentions INTEGER DEFAULT 0,
    stocktwits_sentiment REAL,
    stocktwits_velocity REAL,
    combined_velocity REAL,
    bullish_ratio REAL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(ticker, date)
);

-- Market data
CREATE TABLE IF NOT EXISTS market_data (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT NOT NULL,
    date DATE NOT NULL,
    open REAL,
    high REAL,
    low REAL,
    close REAL,
    volume INTEGER,
    avg_volume_20d REAL,
    ma_20 REAL,
    ma_50 REAL,
    rsi_14 REAL,
    atr_14 REAL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(ticker, date)
);

-- Combined signals and scores
CREATE TABLE IF NOT EXISTS signals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date DATE NOT NULL,
    ticker TEXT NOT NULL,

    -- Individual signal scores (0-100)
    insider_score INTEGER DEFAULT 0,
    options_score INTEGER DEFAULT 0,
    social_score INTEGER DEFAULT 0,
    technical_score INTEGER DEFAULT 0,

    -- Signal details (JSON for flexibility)
    insider_details TEXT,  -- JSON
    options_details TEXT,  -- JSON
    social_details TEXT,   -- JSON

    -- Combined score and action
    total_score INTEGER NOT NULL,
    tier TEXT,  -- 'A', 'B', 'C'
    action TEXT,  -- 'TRADE', 'WATCH', 'NONE'

    -- Trade parameters
    entry_price REAL,
    stop_price REAL,
    target_price REAL,
    position_size TEXT,  -- 'FULL', 'HALF', 'QUARTER'

    -- Context
    market_regime TEXT,
    notes TEXT,

    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(date, ticker)
);

-- Track outcomes
CREATE TABLE IF NOT EXISTS trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    signal_id INTEGER,  -- NULL allowed for manual trades without signals
    ticker TEXT NOT NULL,
    entry_date DATE NOT NULL,
    entry_price REAL NOT NULL,
    shares INTEGER,
    stop_price REAL,    -- Store stop/target directly for trades without signals
    target_price REAL,

    -- Exit info (filled when closed)
    exit_date DATE,
    exit_price REAL,
    exit_reason TEXT,  -- 'TARGET', 'STOP', 'TIME', 'MANUAL'

    -- Results
    return_pct REAL,
    return_dollars REAL,
    days_held INTEGER,

    -- Status
    status TEXT DEFAULT 'OPEN',  -- 'OPEN', 'CLOSED'
    notes TEXT,

    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (signal_id) REFERENCES signals(id)
);

-- Daily market context
CREATE TABLE IF NOT EXISTS market_context (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date DATE NOT NULL UNIQUE,
    vix REAL,
    spy_change REAL,
    fear_greed INTEGER,
    market_regime TEXT,  -- 'RISK_ON', 'RISK_OFF', 'NEUTRAL'
    notes TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- For validation: historical insider buying vs returns
CREATE TABLE IF NOT EXISTS validation_insider (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT NOT NULL,
    signal_date DATE NOT NULL,
    insider_buy_value REAL,
    num_buyers INTEGER,
    ceo_cfo_buy BOOLEAN,
    price_at_signal REAL,
    return_1d REAL,
    return_3d REAL,
    return_5d REAL,
    return_10d REAL,
    return_20d REAL,
    spy_return_1d REAL,
    spy_return_3d REAL,
    spy_return_5d REAL,
    spy_return_10d REAL,
    spy_return_20d REAL,
    excess_return_5d REAL,  -- stock return - SPY return
    excess_return_10d REAL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(ticker, signal_date)
);

-- Indexes for common queries
CREATE INDEX IF NOT EXISTS idx_insider_trades_ticker_date ON insider_trades(ticker, trade_date);
CREATE INDEX IF NOT EXISTS idx_insider_trades_filed ON insider_trades(filed_date);
CREATE INDEX IF NOT EXISTS idx_signals_date ON signals(date);
CREATE INDEX IF NOT EXISTS idx_signals_score ON signals(total_score DESC);
CREATE INDEX IF NOT EXISTS idx_trades_status ON trades(status);
CREATE INDEX IF NOT EXISTS idx_validation_date ON validation_insider(signal_date);
CREATE INDEX IF NOT EXISTS idx_market_data_ticker_date ON market_data(ticker, date);
CREATE INDEX IF NOT EXISTS idx_options_flow_ticker_date ON options_flow(ticker, date);
CREATE INDEX IF NOT EXISTS idx_social_metrics_ticker_date ON social_metrics(ticker, date);

-- =============================================================
-- V2 MOMENTUM TRADING SYSTEM TABLES
-- =============================================================

-- Trend Template compliance tracking (Minervini 8-point system)
CREATE TABLE IF NOT EXISTS trend_template (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT NOT NULL,
    date DATE NOT NULL,

    -- Moving averages
    price REAL,
    ma_50 REAL,
    ma_150 REAL,
    ma_200 REAL,

    -- 52-week range
    high_52w REAL,
    low_52w REAL,

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
    criteria_passed INTEGER,  -- Count of criteria passed (0-8)

    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(ticker, date)
);

-- Fundamental quality metrics
CREATE TABLE IF NOT EXISTS fundamentals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT NOT NULL,
    date DATE NOT NULL,

    -- Earnings
    eps_current_quarter REAL,
    eps_prior_year_quarter REAL,
    eps_growth_quarterly REAL,  -- YoY %
    eps_growth_annual REAL,     -- YoY %
    eps_acceleration BOOLEAN,   -- This Q > Last Q growth

    -- Revenue
    revenue_current_quarter REAL,
    revenue_prior_year_quarter REAL,
    revenue_growth_quarterly REAL,
    revenue_growth_annual REAL,

    -- Margins
    profit_margin REAL,
    profit_margin_prior REAL,
    margin_expanding BOOLEAN,

    -- Quality score (0-100)
    fundamental_score INTEGER,

    -- Data source metadata
    data_source TEXT,  -- 'FMP', 'ALPHAVANTAGE', 'YFINANCE'

    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(ticker, date)
);

-- VCP pattern detection
CREATE TABLE IF NOT EXISTS vcp_patterns (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT NOT NULL,
    date DATE NOT NULL,

    -- Base metrics
    base_start_date DATE,
    base_length_days INTEGER,

    -- Pattern metrics
    num_contractions INTEGER,
    depth_contraction_1 REAL,  -- % depth of first pullback
    depth_contraction_2 REAL,
    depth_contraction_3 REAL,
    depth_contraction_4 REAL,
    current_depth REAL,

    -- Volume analysis
    volume_dry_up BOOLEAN,  -- Volume declining during base
    volume_contraction_pct REAL,  -- % decline in volume

    -- Pivot point
    pivot_price REAL,
    pivot_high_date DATE,

    -- Pattern quality
    pattern_valid BOOLEAN,
    pattern_score INTEGER,  -- 0-100
    pattern_stage TEXT,  -- 'FORMING', 'READY', 'TRIGGERED', 'FAILED'

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
    max_buy_price REAL,  -- pivot + 5% max chase

    -- Scores
    trend_score INTEGER,
    fundamental_score INTEGER,
    pattern_score INTEGER,
    rs_rating REAL,
    total_score INTEGER,

    -- Status
    status TEXT DEFAULT 'WATCHING',  -- WATCHING, TRIGGERED, EXPIRED, STOPPED, FILLED
    triggered_date DATE,
    triggered_price REAL,
    triggered_volume REAL,

    -- Expiration
    expiration_date DATE,  -- Remove from watchlist after this date

    notes TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Alert log
CREATE TABLE IF NOT EXISTS alerts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT NOT NULL,
    alert_type TEXT NOT NULL,  -- BREAKOUT, STOP_HIT, TARGET_HIT, WATCHLIST_ADD, PATTERN_FORMING
    priority TEXT DEFAULT 'NORMAL',  -- LOW, NORMAL, HIGH, URGENT
    message TEXT,
    details TEXT,  -- JSON for additional context
    sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    delivered BOOLEAN DEFAULT FALSE,
    delivery_method TEXT,  -- EMAIL, SMS, BOTH
    acknowledged BOOLEAN DEFAULT FALSE,
    acknowledged_at TIMESTAMP
);

-- V2 Paper trades with enhanced tracking
CREATE TABLE IF NOT EXISTS paper_trades_v2 (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT NOT NULL,

    -- Entry details
    entry_date DATE NOT NULL,
    entry_price REAL NOT NULL,
    shares INTEGER NOT NULL,
    entry_value REAL NOT NULL,  -- shares * entry_price

    -- Stop management
    initial_stop REAL NOT NULL,
    current_stop REAL NOT NULL,
    stop_type TEXT DEFAULT 'FIXED',  -- FIXED, TRAILING, BREAKEVEN

    -- Target
    target_price REAL,
    target_pct REAL,

    -- Risk metrics at entry
    risk_per_share REAL,  -- entry_price - initial_stop
    risk_dollars REAL,  -- risk_per_share * shares
    risk_pct REAL,  -- risk_dollars / portfolio_value
    risk_reward_ratio REAL,  -- (target - entry) / (entry - stop)

    -- Position tracking
    highest_price REAL,  -- For trailing stop calculation
    lowest_price_since_entry REAL,
    days_held INTEGER DEFAULT 0,

    -- Exit details
    exit_date DATE,
    exit_price REAL,
    exit_value REAL,
    exit_reason TEXT,  -- TARGET, STOP, TRAILING_STOP, TIME, MANUAL, BREAKOUT_FAIL

    -- Results
    return_pct REAL,
    return_dollars REAL,
    r_multiple REAL,  -- return / initial_risk

    -- Status
    status TEXT DEFAULT 'OPEN',  -- OPEN, CLOSED

    -- Metadata
    signal_source TEXT,  -- V2_TREND, V2_VCP, V2_BREAKOUT
    notes TEXT,

    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Portfolio snapshots for equity curve tracking
CREATE TABLE IF NOT EXISTS portfolio_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date DATE NOT NULL UNIQUE,

    -- Cash and positions
    cash_balance REAL NOT NULL,
    positions_value REAL NOT NULL,  -- Sum of all open position values
    total_value REAL NOT NULL,  -- cash + positions

    -- Position counts
    open_positions INTEGER DEFAULT 0,

    -- Daily P&L
    daily_pnl REAL DEFAULT 0,
    daily_pnl_pct REAL DEFAULT 0,

    -- Cumulative stats
    total_return_pct REAL DEFAULT 0,
    max_drawdown_pct REAL DEFAULT 0,
    peak_value REAL,

    -- Benchmarks
    spy_close REAL,
    spy_return_pct REAL,  -- From start date

    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Stock universe management
CREATE TABLE IF NOT EXISTS stock_universe (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT NOT NULL UNIQUE,
    company_name TEXT,
    sector TEXT,
    industry TEXT,
    market_cap REAL,
    avg_volume REAL,
    price REAL,

    -- Index membership
    in_sp500 BOOLEAN DEFAULT FALSE,
    in_russell1000 BOOLEAN DEFAULT FALSE,

    -- Screening status
    passes_liquidity BOOLEAN DEFAULT FALSE,  -- Price >= $10, MarketCap >= $500M, Volume >= 500K
    passes_trend_template BOOLEAN DEFAULT FALSE,
    last_screened DATE,

    -- Metadata
    added_date DATE,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- V2 Indexes
CREATE INDEX IF NOT EXISTS idx_trend_template_ticker_date ON trend_template(ticker, date);
CREATE INDEX IF NOT EXISTS idx_trend_template_compliant ON trend_template(template_compliant, date);
CREATE INDEX IF NOT EXISTS idx_fundamentals_ticker_date ON fundamentals(ticker, date);
CREATE INDEX IF NOT EXISTS idx_vcp_patterns_ticker_date ON vcp_patterns(ticker, date);
CREATE INDEX IF NOT EXISTS idx_vcp_patterns_valid ON vcp_patterns(pattern_valid, date);
CREATE INDEX IF NOT EXISTS idx_watchlist_status ON watchlist(status);
CREATE INDEX IF NOT EXISTS idx_watchlist_ticker ON watchlist(ticker);
CREATE INDEX IF NOT EXISTS idx_alerts_ticker ON alerts(ticker);
CREATE INDEX IF NOT EXISTS idx_alerts_type ON alerts(alert_type);
CREATE INDEX IF NOT EXISTS idx_alerts_sent ON alerts(sent_at);
CREATE INDEX IF NOT EXISTS idx_paper_trades_v2_status ON paper_trades_v2(status);
CREATE INDEX IF NOT EXISTS idx_paper_trades_v2_ticker ON paper_trades_v2(ticker);
CREATE INDEX IF NOT EXISTS idx_portfolio_snapshots_date ON portfolio_snapshots(date);
CREATE INDEX IF NOT EXISTS idx_stock_universe_ticker ON stock_universe(ticker);
CREATE INDEX IF NOT EXISTS idx_stock_universe_passes ON stock_universe(passes_liquidity, passes_trend_template);
"""


def get_table_counts():
    """Get row counts for all tables (useful for status checks)."""
    # V1 tables
    v1_tables = [
        "insider_trades",
        "insider_daily",
        "options_flow",
        "social_metrics",
        "market_data",
        "signals",
        "trades",
        "market_context",
        "validation_insider",
    ]

    # V2 tables
    v2_tables = [
        "trend_template",
        "fundamentals",
        "vcp_patterns",
        "watchlist",
        "alerts",
        "paper_trades_v2",
        "portfolio_snapshots",
        "stock_universe",
    ]

    counts = {}
    with get_db() as conn:
        for table in v1_tables + v2_tables:
            try:
                cursor = conn.execute(f"SELECT COUNT(*) FROM {table}")
                counts[table] = cursor.fetchone()[0]
            except Exception:
                counts[table] = -1  # Table doesn't exist yet

    return counts


def get_v2_table_counts():
    """Get row counts for V2 tables only."""
    v2_tables = [
        "trend_template",
        "fundamentals",
        "vcp_patterns",
        "watchlist",
        "alerts",
        "paper_trades_v2",
        "portfolio_snapshots",
        "stock_universe",
    ]

    counts = {}
    with get_db() as conn:
        for table in v2_tables:
            try:
                cursor = conn.execute(f"SELECT COUNT(*) FROM {table}")
                counts[table] = cursor.fetchone()[0]
            except Exception:
                counts[table] = -1

    return counts


if __name__ == "__main__":
    # Initialize database when run directly
    init_db()
    print("\nTable counts:")
    for table, count in get_table_counts().items():
        print(f"  {table}: {count}")
