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
"""


def get_table_counts():
    """Get row counts for all tables (useful for status checks)."""
    tables = [
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

    counts = {}
    with get_db() as conn:
        for table in tables:
            cursor = conn.execute(f"SELECT COUNT(*) FROM {table}")
            counts[table] = cursor.fetchone()[0]

    return counts


if __name__ == "__main__":
    # Initialize database when run directly
    init_db()
    print("\nTable counts:")
    for table, count in get_table_counts().items():
        print(f"  {table}: {count}")
