"""
Options Flow Collector

Collects options volume and open interest data using yfinance.
Detects unusual options activity that may signal upcoming moves.

Key metrics:
- Call/Put volume vs 20-day average
- Put/Call ratio
- Near-term vs long-term expiration focus
"""

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Optional
import time

import yfinance as yf
import pandas as pd

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from utils.config import config
from utils.db import get_db


@dataclass
class OptionsSnapshot:
    """Options data for a single ticker on a single day."""
    ticker: str
    date: date
    call_volume: int
    put_volume: int
    call_oi: int  # open interest
    put_oi: int
    avg_call_volume_20d: float
    avg_put_volume_20d: float
    call_volume_ratio: float  # today vs 20d avg
    put_call_ratio: float
    unusual_calls: bool
    unusual_puts: bool
    near_term_call_volume: int  # expiring within 2 weeks
    near_term_put_volume: int


def get_options_data(ticker: str) -> Optional[OptionsSnapshot]:
    """
    Get current options data for a ticker.

    Args:
        ticker: Stock symbol

    Returns:
        OptionsSnapshot or None if data unavailable
    """
    try:
        stock = yf.Ticker(ticker)

        # Get available expiration dates
        expirations = stock.options
        if not expirations:
            return None

        today = date.today()
        two_weeks = today + timedelta(days=14)

        total_call_volume = 0
        total_put_volume = 0
        total_call_oi = 0
        total_put_oi = 0
        near_term_call_volume = 0
        near_term_put_volume = 0

        # Aggregate across expiration dates
        for exp_str in expirations[:8]:  # Limit to first 8 expirations for speed
            try:
                exp_date = datetime.strptime(exp_str, "%Y-%m-%d").date()
                opt_chain = stock.option_chain(exp_str)

                # Calls
                if not opt_chain.calls.empty:
                    call_vol = opt_chain.calls['volume'].fillna(0).sum()
                    call_oi = opt_chain.calls['openInterest'].fillna(0).sum()
                    total_call_volume += int(call_vol)
                    total_call_oi += int(call_oi)

                    if exp_date <= two_weeks:
                        near_term_call_volume += int(call_vol)

                # Puts
                if not opt_chain.puts.empty:
                    put_vol = opt_chain.puts['volume'].fillna(0).sum()
                    put_oi = opt_chain.puts['openInterest'].fillna(0).sum()
                    total_put_volume += int(put_vol)
                    total_put_oi += int(put_oi)

                    if exp_date <= two_weeks:
                        near_term_put_volume += int(put_vol)

            except Exception as e:
                # Skip problematic expiration dates
                continue

        if total_call_volume == 0 and total_put_volume == 0:
            return None

        # Get historical averages from database
        avg_call, avg_put = get_historical_averages(ticker, days=20)

        # Calculate ratios
        call_volume_ratio = total_call_volume / avg_call if avg_call > 0 else 0
        put_call_ratio = total_put_volume / total_call_volume if total_call_volume > 0 else 0

        # Flag unusual activity (>2x average)
        unusual_calls = call_volume_ratio >= 2.0
        unusual_puts = total_put_volume / avg_put >= 2.0 if avg_put > 0 else False

        return OptionsSnapshot(
            ticker=ticker,
            date=today,
            call_volume=total_call_volume,
            put_volume=total_put_volume,
            call_oi=total_call_oi,
            put_oi=total_put_oi,
            avg_call_volume_20d=avg_call,
            avg_put_volume_20d=avg_put,
            call_volume_ratio=call_volume_ratio,
            put_call_ratio=put_call_ratio,
            unusual_calls=unusual_calls,
            unusual_puts=unusual_puts,
            near_term_call_volume=near_term_call_volume,
            near_term_put_volume=near_term_put_volume,
        )

    except Exception as e:
        print(f"Error getting options for {ticker}: {e}")
        return None


def get_historical_averages(ticker: str, days: int = 20) -> tuple[float, float]:
    """
    Get average call/put volume from historical data.

    Returns:
        (avg_call_volume, avg_put_volume)
    """
    cutoff = (date.today() - timedelta(days=days)).isoformat()

    with get_db() as conn:
        cursor = conn.execute(
            """
            SELECT AVG(call_volume) as avg_call, AVG(put_volume) as avg_put
            FROM options_flow
            WHERE ticker = ? AND date >= ?
            """,
            (ticker.upper(), cutoff)
        )
        row = cursor.fetchone()

    if row and row['avg_call']:
        return float(row['avg_call']), float(row['avg_put'] or 0)

    # No historical data yet - return 0s (will build up over time)
    return 0.0, 0.0


def save_options_snapshot(snapshot: OptionsSnapshot) -> bool:
    """Save options snapshot to database."""
    try:
        with get_db() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO options_flow
                (ticker, date, call_volume, put_volume, call_oi, put_oi,
                 avg_call_volume_20d, avg_put_volume_20d, call_volume_ratio,
                 put_call_ratio, unusual_calls, unusual_puts)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    snapshot.ticker,
                    snapshot.date.isoformat(),
                    snapshot.call_volume,
                    snapshot.put_volume,
                    snapshot.call_oi,
                    snapshot.put_oi,
                    snapshot.avg_call_volume_20d,
                    snapshot.avg_put_volume_20d,
                    snapshot.call_volume_ratio,
                    snapshot.put_call_ratio,
                    snapshot.unusual_calls,
                    snapshot.unusual_puts,
                )
            )
        return True
    except Exception as e:
        print(f"Error saving options for {snapshot.ticker}: {e}")
        return False


def collect_options_data(tickers: list[str], delay: float = 0.5) -> dict:
    """
    Collect options data for a list of tickers.

    Args:
        tickers: List of stock symbols
        delay: Delay between requests (seconds)

    Returns:
        Dict with collection statistics
    """
    stats = {
        "tickers_requested": len(tickers),
        "tickers_collected": 0,
        "unusual_calls": 0,
        "unusual_puts": 0,
        "errors": [],
    }

    for i, ticker in enumerate(tickers):
        try:
            snapshot = get_options_data(ticker)

            if snapshot:
                if save_options_snapshot(snapshot):
                    stats["tickers_collected"] += 1

                    if snapshot.unusual_calls:
                        stats["unusual_calls"] += 1
                    if snapshot.unusual_puts:
                        stats["unusual_puts"] += 1

            # Progress indicator
            if (i + 1) % 10 == 0:
                print(f"  Processed {i + 1}/{len(tickers)} tickers...")

            # Rate limiting
            if delay > 0:
                time.sleep(delay)

        except Exception as e:
            stats["errors"].append(f"{ticker}: {str(e)}")

    return stats


def get_unusual_options(min_call_ratio: float = 2.0, limit: int = 20) -> list[dict]:
    """
    Get stocks with unusual options activity today.

    Args:
        min_call_ratio: Minimum call volume ratio to include
        limit: Maximum results

    Returns:
        List of options records with unusual activity
    """
    today = date.today().isoformat()

    with get_db() as conn:
        cursor = conn.execute(
            """
            SELECT ticker, call_volume, put_volume, call_volume_ratio,
                   put_call_ratio, unusual_calls, unusual_puts
            FROM options_flow
            WHERE date = ?
              AND (call_volume_ratio >= ? OR unusual_calls = 1)
            ORDER BY call_volume_ratio DESC
            LIMIT ?
            """,
            (today, min_call_ratio, limit)
        )
        return [dict(row) for row in cursor.fetchall()]


def get_default_watchlist() -> list[str]:
    """
    Get default watchlist for options scanning.

    Combines:
    - Stocks with recent insider buying
    - High-volume stocks
    """
    tickers = set()

    # Add stocks with recent insider buying
    with get_db() as conn:
        cutoff = (date.today() - timedelta(days=14)).isoformat()
        cursor = conn.execute(
            """
            SELECT DISTINCT ticker FROM insider_trades
            WHERE trade_type = 'P' AND trade_date >= ?
            """,
            (cutoff,)
        )
        for row in cursor.fetchall():
            tickers.add(row['ticker'])

    # Add some high-volume popular stocks as baseline
    popular = [
        'AAPL', 'MSFT', 'GOOGL', 'AMZN', 'META', 'NVDA', 'TSLA',
        'AMD', 'INTC', 'CRM', 'NFLX', 'DIS', 'BA', 'JPM', 'GS',
        'V', 'MA', 'PYPL', 'SQ', 'COIN', 'SPY', 'QQQ', 'IWM'
    ]
    tickers.update(popular)

    return sorted(list(tickers))


if __name__ == "__main__":
    print("Testing options data collection...")

    # Test single ticker
    print("\nTesting AAPL options:")
    snapshot = get_options_data("AAPL")
    if snapshot:
        print(f"  Call volume: {snapshot.call_volume:,}")
        print(f"  Put volume: {snapshot.put_volume:,}")
        print(f"  Call OI: {snapshot.call_oi:,}")
        print(f"  Put OI: {snapshot.put_oi:,}")
        print(f"  Call volume ratio: {snapshot.call_volume_ratio:.2f}x")
        print(f"  Put/Call ratio: {snapshot.put_call_ratio:.2f}")
        print(f"  Unusual calls: {snapshot.unusual_calls}")
        print(f"  Near-term call volume: {snapshot.near_term_call_volume:,}")
    else:
        print("  No data available")

    # Test collection on small list
    print("\nCollecting options for watchlist...")
    watchlist = get_default_watchlist()[:10]  # First 10 for testing
    print(f"Watchlist: {watchlist}")

    stats = collect_options_data(watchlist, delay=0.3)
    print(f"\nResults:")
    print(f"  Collected: {stats['tickers_collected']}/{stats['tickers_requested']}")
    print(f"  Unusual calls: {stats['unusual_calls']}")
    print(f"  Unusual puts: {stats['unusual_puts']}")
