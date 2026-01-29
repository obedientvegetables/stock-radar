"""
Relative Strength Rating Calculator

Calculates IBD-style RS rating by comparing stock performance
to all stocks in the universe.

RS Rating of 90 means the stock outperformed 90% of all stocks.
We want stocks with RS >= 70 (top 30% of market).
"""

import sys
from pathlib import Path
from datetime import date, timedelta
from typing import List, Dict, Optional, Tuple
from concurrent.futures import ThreadPoolExecutor, as_completed

import yfinance as yf
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent))
from utils.db import get_db
from utils.config import config


def calculate_rs_rating(
    ticker: str,
    universe: List[str],
    lookback_days: int = 252
) -> float:
    """
    Calculate relative strength rating (0-100).

    Compares the stock's 12-month performance to all stocks
    in the universe and returns the percentile ranking.

    Args:
        ticker: Stock to calculate RS for
        universe: List of comparison tickers
        lookback_days: Performance lookback period (default 252 = 1 year)

    Returns:
        RS rating from 0-100 (percentile ranking)
    """
    # Get performance for target stock
    target_perf = _get_performance(ticker, lookback_days)
    if target_perf is None:
        return 0.0

    # Get performance for all stocks in universe
    performances = []
    for t in universe:
        if t == ticker:
            continue
        perf = _get_performance(t, lookback_days)
        if perf is not None:
            performances.append(perf)

    if not performances:
        return 50.0  # Default if no comparison available

    # Calculate percentile
    below = sum(1 for p in performances if p < target_perf)
    percentile = (below / len(performances)) * 100

    return round(percentile, 1)


def calculate_rs_rating_fast(
    ticker: str,
    universe_performances: Dict[str, float]
) -> float:
    """
    Calculate RS rating using pre-computed universe performances.

    This is much faster when scanning multiple stocks since we
    only need to fetch universe performance data once.

    Args:
        ticker: Stock to calculate RS for
        universe_performances: Dict of {ticker: performance_pct}

    Returns:
        RS rating from 0-100
    """
    target_perf = universe_performances.get(ticker)
    if target_perf is None:
        return 0.0

    # Filter out the target ticker and None values
    other_perfs = [p for t, p in universe_performances.items() if t != ticker and p is not None]

    if not other_perfs:
        return 50.0

    below = sum(1 for p in other_perfs if p < target_perf)
    percentile = (below / len(other_perfs)) * 100

    return round(percentile, 1)


def get_universe_performances(
    tickers: List[str],
    lookback_days: int = 252,
    max_workers: int = 10
) -> Dict[str, float]:
    """
    Get performance for all tickers in universe (parallelized).

    Args:
        tickers: List of ticker symbols
        lookback_days: Performance lookback period
        max_workers: Number of parallel threads

    Returns:
        Dict of {ticker: performance_pct}
    """
    performances = {}

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_ticker = {
            executor.submit(_get_performance, ticker, lookback_days): ticker
            for ticker in tickers
        }

        for future in as_completed(future_to_ticker):
            ticker = future_to_ticker[future]
            try:
                perf = future.result()
                performances[ticker] = perf
            except Exception:
                performances[ticker] = None

    return performances


def _get_performance(ticker: str, days: int) -> Optional[float]:
    """
    Get percentage performance over specified days.

    Uses weighted calculation:
    - 40% weight on most recent quarter (63 days)
    - 20% weight on Q2
    - 20% weight on Q3
    - 20% weight on Q4

    This gives more weight to recent performance while still
    considering longer-term strength.
    """
    try:
        stock = yf.Ticker(ticker)
        hist = stock.history(period=f"{days + 30}d")  # Buffer for missing days

        if len(hist) < days * 0.8:  # Need at least 80% of days
            return None

        # Simple performance calculation (full period)
        start_price = hist['Close'].iloc[-days] if len(hist) >= days else hist['Close'].iloc[0]
        end_price = hist['Close'].iloc[-1]

        if start_price <= 0:
            return None

        total_return = ((end_price - start_price) / start_price) * 100

        # Calculate quarterly returns for weighted RS
        # This mimics IBD's approach more closely
        quarters = []
        for q in range(4):
            q_start = -days + (q * 63)
            q_end = q_start + 63

            if q_start < -len(hist):
                continue

            q_start_idx = max(q_start, -len(hist))
            q_end_idx = min(q_end, -1) if q_end < 0 else -1

            q_start_price = hist['Close'].iloc[q_start_idx]
            q_end_price = hist['Close'].iloc[q_end_idx]

            if q_start_price > 0:
                q_return = ((q_end_price - q_start_price) / q_start_price) * 100
                quarters.append(q_return)

        # If we have quarterly data, use weighted calculation
        if len(quarters) >= 4:
            weights = [0.4, 0.2, 0.2, 0.2]  # Most recent gets highest weight
            quarters.reverse()  # Most recent first
            weighted_return = sum(w * r for w, r in zip(weights, quarters[:4]))
            return weighted_return

        return total_return

    except Exception:
        return None


def calculate_all_rs_ratings(
    tickers: List[str],
    lookback_days: int = 252,
    verbose: bool = False
) -> Dict[str, float]:
    """
    Calculate RS ratings for all tickers in a universe.

    This is the most efficient way to calculate RS for multiple stocks
    since it only fetches performance data once.

    Args:
        tickers: List of ticker symbols
        lookback_days: Performance lookback period
        verbose: Print progress

    Returns:
        Dict of {ticker: rs_rating}
    """
    if verbose:
        print(f"Fetching performance data for {len(tickers)} stocks...")

    # Get all performances first
    performances = get_universe_performances(tickers, lookback_days)

    valid_perfs = {t: p for t, p in performances.items() if p is not None}
    if verbose:
        print(f"Got valid performance for {len(valid_perfs)}/{len(tickers)} stocks")

    # Calculate RS rating for each
    rs_ratings = {}
    for ticker in tickers:
        rs_ratings[ticker] = calculate_rs_rating_fast(ticker, valid_perfs)

    return rs_ratings


def update_rs_ratings_in_db(rs_ratings: Dict[str, float], target_date: Optional[date] = None) -> int:
    """
    Update RS ratings in trend_template table.

    Args:
        rs_ratings: Dict of {ticker: rs_rating}
        target_date: Date to update (defaults to today)

    Returns:
        Number of rows updated
    """
    if target_date is None:
        target_date = date.today()

    count = 0
    with get_db() as conn:
        for ticker, rs_rating in rs_ratings.items():
            cursor = conn.execute("""
                UPDATE trend_template
                SET rs_rating = ?
                WHERE ticker = ? AND date = ?
            """, (rs_rating, ticker, target_date.isoformat()))
            if cursor.rowcount > 0:
                count += 1

    return count


def get_top_rs_stocks(
    min_rs: int = None,
    limit: int = 50,
    target_date: Optional[date] = None
) -> List[Dict]:
    """
    Get stocks with highest RS ratings from database.

    Args:
        min_rs: Minimum RS rating (default from config)
        limit: Maximum number of results
        target_date: Date to query

    Returns:
        List of dicts with stock data sorted by RS rating
    """
    if min_rs is None:
        min_rs = config.RS_MIN_RATING
    if target_date is None:
        target_date = date.today()

    with get_db() as conn:
        cursor = conn.execute("""
            SELECT * FROM trend_template
            WHERE date = ? AND rs_rating >= ?
            ORDER BY rs_rating DESC
            LIMIT ?
        """, (target_date.isoformat(), min_rs, limit))

        return [dict(row) for row in cursor.fetchall()]


if __name__ == "__main__":
    # Test with a small universe
    test_universe = ['AAPL', 'MSFT', 'GOOGL', 'AMZN', 'NVDA', 'META', 'TSLA', 'AMD', 'NFLX', 'CRM']

    print("Testing Relative Strength Calculator")
    print("=" * 50)

    print("\nCalculating RS ratings for test universe...")
    rs_ratings = calculate_all_rs_ratings(test_universe, verbose=True)

    print("\nRS Ratings (sorted by strength):")
    sorted_rs = sorted(rs_ratings.items(), key=lambda x: x[1] or 0, reverse=True)
    for ticker, rs in sorted_rs:
        print(f"  {ticker}: RS {rs:.0f}")
