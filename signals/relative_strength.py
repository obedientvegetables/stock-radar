"""
Relative Strength Rating Calculator

Calculates IBD-style RS rating by comparing stock performance
to all stocks in the universe.

RS Rating of 90 means the stock outperformed 90% of stocks over
the past 12 months.
"""

from dataclasses import dataclass
from datetime import date, timedelta
from typing import List, Dict, Optional, Tuple
import yfinance as yf
import pandas as pd
import numpy as np
import time
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from utils.db import get_db


@dataclass
class RSRating:
    """Relative strength rating result."""
    ticker: str
    date: date
    rating: float  # 0-100 percentile
    performance_1m: Optional[float]  # % change
    performance_3m: Optional[float]
    performance_6m: Optional[float]
    performance_12m: Optional[float]
    weighted_performance: Optional[float]  # IBD-style weighted
    
    def to_dict(self) -> Dict:
        return {
            'ticker': self.ticker,
            'date': self.date.isoformat(),
            'rating': self.rating,
            'performance_1m': self.performance_1m,
            'performance_3m': self.performance_3m,
            'performance_6m': self.performance_6m,
            'performance_12m': self.performance_12m,
            'weighted_performance': self.weighted_performance,
        }


def calculate_rs_rating(
    ticker: str,
    universe: List[str],
    target_date: Optional[date] = None
) -> RSRating:
    """
    Calculate relative strength rating (0-100).
    
    Uses IBD-style weighted performance:
    - 40% weight to most recent quarter
    - 20% weight each to previous 3 quarters
    
    This emphasizes recent performance while still considering longer-term trends.
    
    Args:
        ticker: Stock to rate
        universe: List of stocks to compare against
        target_date: Date for analysis (default: today)
    
    Returns:
        RSRating with percentile ranking
    """
    if target_date is None:
        target_date = date.today()
    
    # Get performance for target stock
    target_perf = _get_stock_performance(ticker, target_date)
    if target_perf is None:
        return RSRating(
            ticker=ticker,
            date=target_date,
            rating=0.0,
            performance_1m=None,
            performance_3m=None,
            performance_6m=None,
            performance_12m=None,
            weighted_performance=None,
        )
    
    # Get performance for all stocks in universe
    performances = []
    for t in universe:
        if t == ticker:
            continue
        perf = _get_stock_performance(t, target_date)
        if perf is not None and perf['weighted'] is not None:
            performances.append(perf['weighted'])
        time.sleep(0.05)  # Rate limit
    
    if not performances:
        return RSRating(
            ticker=ticker,
            date=target_date,
            rating=50.0,  # Default if no comparison available
            **target_perf,
        )
    
    # Calculate percentile
    target_weighted = target_perf['weighted']
    if target_weighted is None:
        percentile = 50.0
    else:
        below = sum(1 for p in performances if p < target_weighted)
        percentile = (below / len(performances)) * 100
    
    return RSRating(
        ticker=ticker,
        date=target_date,
        rating=round(percentile, 1),
        performance_1m=target_perf.get('1m'),
        performance_3m=target_perf.get('3m'),
        performance_6m=target_perf.get('6m'),
        performance_12m=target_perf.get('12m'),
        weighted_performance=target_weighted,
    )


def calculate_rs_ratings_batch(
    tickers: List[str],
    target_date: Optional[date] = None,
    verbose: bool = True
) -> Dict[str, float]:
    """
    Calculate RS ratings for multiple stocks efficiently.
    
    Instead of comparing each stock to the full universe (O(n²)),
    we fetch all performance data first, then rank.
    
    Args:
        tickers: List of stocks to rate
        target_date: Date for analysis
        verbose: Print progress
    
    Returns:
        Dict mapping ticker -> RS rating
    """
    if target_date is None:
        target_date = date.today()
    
    if verbose:
        print(f"Calculating RS ratings for {len(tickers)} stocks...")
    
    # Fetch all performance data
    performances = {}
    for i, ticker in enumerate(tickers):
        if verbose and (i + 1) % 50 == 0:
            print(f"  Fetching: {i + 1}/{len(tickers)}...")
        
        perf = _get_stock_performance(ticker, target_date)
        if perf is not None and perf['weighted'] is not None:
            performances[ticker] = perf['weighted']
        
        time.sleep(0.05)  # Rate limit
    
    if not performances:
        return {t: 50.0 for t in tickers}
    
    # Rank all stocks by weighted performance
    sorted_tickers = sorted(performances.keys(), key=lambda t: performances[t])
    n = len(sorted_tickers)
    
    # Calculate percentile for each
    ratings = {}
    for i, ticker in enumerate(sorted_tickers):
        # Percentile = position / total * 100
        ratings[ticker] = round((i / n) * 100, 1)
    
    # Add 0 for stocks we couldn't calculate
    for ticker in tickers:
        if ticker not in ratings:
            ratings[ticker] = 0.0
    
    if verbose:
        top_5 = sorted(ratings.items(), key=lambda x: x[1], reverse=True)[:5]
        print(f"\nTop 5 by RS Rating:")
        for t, r in top_5:
            print(f"  {t}: {r:.1f}")
    
    return ratings


def _get_stock_performance(ticker: str, target_date: date) -> Optional[Dict]:
    """
    Get performance metrics for a stock.
    
    Returns dict with:
    - 1m, 3m, 6m, 12m: % returns for each period
    - weighted: IBD-style weighted performance
    """
    try:
        stock = yf.Ticker(ticker)
        
        # Get 15 months of history to ensure we have enough data
        hist = stock.history(period="15mo")
        
        if len(hist) < 60:  # Need at least ~3 months
            return None
        
        current_price = hist['Close'].iloc[-1]
        
        # Calculate returns for different periods
        returns = {}
        
        # 1 month (~21 trading days)
        if len(hist) >= 21:
            price_1m = hist['Close'].iloc[-21]
            returns['1m'] = ((current_price - price_1m) / price_1m) * 100
        else:
            returns['1m'] = None
        
        # 3 months (~63 trading days)
        if len(hist) >= 63:
            price_3m = hist['Close'].iloc[-63]
            returns['3m'] = ((current_price - price_3m) / price_3m) * 100
        else:
            returns['3m'] = None
        
        # 6 months (~126 trading days)
        if len(hist) >= 126:
            price_6m = hist['Close'].iloc[-126]
            returns['6m'] = ((current_price - price_6m) / price_6m) * 100
        else:
            returns['6m'] = None
        
        # 12 months (~252 trading days)
        if len(hist) >= 252:
            price_12m = hist['Close'].iloc[-252]
            returns['12m'] = ((current_price - price_12m) / price_12m) * 100
        else:
            returns['12m'] = None
        
        # Calculate IBD-style weighted performance
        # 40% most recent quarter, 20% each for previous quarters
        weighted = _calculate_weighted_performance(returns)
        returns['weighted'] = weighted
        
        return returns
        
    except Exception as e:
        return None


def _calculate_weighted_performance(returns: Dict) -> Optional[float]:
    """
    Calculate IBD-style weighted relative strength.
    
    Weights:
    - 40%: Most recent quarter (3m return - 6m return at 3m ago)
    - 20%: Q-1 (quarter before)
    - 20%: Q-2 
    - 20%: Q-3
    
    Simplified version: Weight 12m performance with recency bias
    - 40%: 3-month performance
    - 20%: 6-month performance  
    - 20%: 9-month (interpolated)
    - 20%: 12-month performance
    """
    if returns.get('3m') is None:
        return None
    
    # If we have full 12m data
    if returns.get('12m') is not None:
        # Simple weighted average emphasizing recent performance
        # 40% to most recent quarter, rest spread across older periods
        r3m = returns.get('3m', 0) or 0
        r6m = returns.get('6m', 0) or 0
        r12m = returns.get('12m', 0) or 0
        
        # Approximate quarterly returns
        q1 = r3m  # Most recent quarter
        q2 = r6m - r3m if r6m else 0  # Second quarter
        q3_q4 = r12m - r6m if (r12m and r6m) else 0  # Older quarters combined
        
        weighted = (q1 * 0.4) + (q2 * 0.2) + (q3_q4 * 0.2) + (r12m * 0.2)
        return round(weighted, 2)
    
    # Fallback: just use what we have
    r3m = returns.get('3m') or 0
    r6m = returns.get('6m') or r3m
    
    return round((r3m * 0.6) + (r6m * 0.4), 2)


def update_rs_ratings_in_db(ratings: Dict[str, float], target_date: Optional[date] = None) -> int:
    """
    Update RS ratings in the trend_template table.
    
    Args:
        ratings: Dict mapping ticker -> RS rating
        target_date: Date to update
    
    Returns:
        Number of rows updated
    """
    if target_date is None:
        target_date = date.today()
    
    updated = 0
    with get_db() as conn:
        for ticker, rating in ratings.items():
            cursor = conn.execute("""
                UPDATE trend_template
                SET rs_rating = ?
                WHERE ticker = ? AND date = ?
            """, (rating, ticker, target_date.isoformat()))
            updated += cursor.rowcount
    
    return updated


# Quick test
if __name__ == "__main__":
    # Test with a few stocks
    test_tickers = ['AAPL', 'MSFT', 'NVDA', 'META', 'TSLA', 'GOOGL', 'AMZN', 'AMD', 'NFLX', 'CRM']
    
    print("Testing Relative Strength Calculator")
    print("=" * 50)
    
    # Test batch calculation
    ratings = calculate_rs_ratings_batch(test_tickers, verbose=True)
    
    print("\n\nAll ratings:")
    for ticker, rating in sorted(ratings.items(), key=lambda x: x[1], reverse=True):
        print(f"  {ticker}: RS {rating:.1f}")
