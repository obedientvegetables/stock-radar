"""
Minervini Trend Template Scanner

Checks stocks against the 8-point Trend Template criteria.
ALL criteria must pass for a stock to be considered in Stage 2 uptrend.

Based on Mark Minervini's SEPA methodology from "Trade Like a Stock Market Wizard"
"""

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Optional, List, Dict
import yfinance as yf
import pandas as pd
import numpy as np
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from utils.db import get_db
from utils.config import config


@dataclass
class TrendTemplateResult:
    """Result of trend template analysis for a single stock."""
    ticker: str
    analysis_date: date
    price: float
    
    # Moving averages
    ma_50: float
    ma_150: float
    ma_200: float
    
    # 52-week range
    high_52w: float
    low_52w: float
    
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
    
    def to_dict(self) -> Dict:
        """Convert to dictionary for database storage."""
        return {
            'ticker': self.ticker,
            'date': self.analysis_date.isoformat(),
            'price': self.price,
            'ma_50': self.ma_50,
            'ma_150': self.ma_150,
            'ma_200': self.ma_200,
            'high_52w': self.high_52w,
            'low_52w': self.low_52w,
            'price_above_ma50': self.c1_price_above_ma50,
            'price_above_ma150': self.c2_price_above_ma150,
            'price_above_ma200': self.c3_price_above_ma200,
            'ma50_above_ma150': self.c4_ma50_above_ma150,
            'ma150_above_ma200': self.c5_ma150_above_ma200,
            'ma200_trending_up': self.c6_ma200_trending_up,
            'price_within_25pct_of_high': self.c7_within_25pct_of_high,
            'price_above_30pct_from_low': self.c8_above_30pct_from_low,
            'rs_rating': self.rs_rating,
            'template_compliant': self.passes_template,
            'criteria_passed': self.criteria_passed,
        }


def check_trend_template(ticker: str, target_date: Optional[date] = None) -> TrendTemplateResult:
    """
    Check if a stock passes Minervini's 8-point Trend Template.
    
    The 8 criteria (ALL must pass for Stage 2 uptrend):
    1. Price > 50-day MA
    2. Price > 150-day MA
    3. Price > 200-day MA
    4. 50-day MA > 150-day MA
    5. 150-day MA > 200-day MA
    6. 200-day MA trending up (at least 1 month)
    7. Price within 25% of 52-week high
    8. Price at least 30% above 52-week low
    
    Args:
        ticker: Stock symbol
        target_date: Date to analyze (default: today)
    
    Returns:
        TrendTemplateResult with pass/fail for each criterion
    """
    if target_date is None:
        target_date = date.today()
    
    # Fetch historical data
    # Need ~315 days for 252 trading days (52-week) + 200-day MA calculation buffer
    stock = yf.Ticker(ticker)
    hist = stock.history(period="15mo")
    
    if len(hist) < 200:
        raise ValueError(f"Insufficient data for {ticker}: only {len(hist)} days available, need 200+")
    
    # Get current price and calculate MAs
    current_price = float(hist['Close'].iloc[-1])
    
    # Moving averages
    ma_50 = float(hist['Close'].rolling(50).mean().iloc[-1])
    ma_150 = float(hist['Close'].rolling(150).mean().iloc[-1])
    ma_200 = float(hist['Close'].rolling(200).mean().iloc[-1])
    
    # 200-day MA from 30 days ago (to check if trending up)
    if len(hist) >= 230:
        ma_200_30d_ago = float(hist['Close'].rolling(200).mean().iloc[-30])
    else:
        ma_200_30d_ago = ma_200  # Fallback if not enough data
    
    # 52-week high and low (use last 252 trading days)
    lookback = min(252, len(hist))
    high_52w = float(hist['High'].tail(lookback).max())
    low_52w = float(hist['Low'].tail(lookback).min())
    
    # Calculate criteria
    c1 = current_price > ma_50
    c2 = current_price > ma_150
    c3 = current_price > ma_200
    c4 = ma_50 > ma_150
    c5 = ma_150 > ma_200
    c6 = ma_200 > ma_200_30d_ago  # Trending up over last month
    c7 = current_price >= high_52w * 0.75  # Within 25% of 52-week high
    c8 = current_price >= low_52w * 1.30  # At least 30% above 52-week low
    
    criteria = [c1, c2, c3, c4, c5, c6, c7, c8]
    
    # Calculate distances
    distance_from_high = ((high_52w - current_price) / high_52w) * 100
    distance_from_low = ((current_price - low_52w) / low_52w) * 100
    
    return TrendTemplateResult(
        ticker=ticker,
        analysis_date=target_date,
        price=round(current_price, 2),
        ma_50=round(ma_50, 2),
        ma_150=round(ma_150, 2),
        ma_200=round(ma_200, 2),
        high_52w=round(high_52w, 2),
        low_52w=round(low_52w, 2),
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
        distance_from_high_pct=round(distance_from_high, 2),
        distance_from_low_pct=round(distance_from_low, 2),
    )


def scan_universe(
    tickers: List[str],
    verbose: bool = True,
    save_to_db: bool = True
) -> List[TrendTemplateResult]:
    """
    Scan multiple stocks for trend template compliance.
    
    Args:
        tickers: List of stock symbols to scan
        verbose: Print progress
        save_to_db: Save results to database
    
    Returns:
        List of TrendTemplateResult for stocks that pass
    """
    passing = []
    failed = []
    errors = []
    
    for i, ticker in enumerate(tickers):
        if verbose and (i + 1) % 25 == 0:
            print(f"  Scanning: {i + 1}/{len(tickers)}... ({len(passing)} passing)")
        
        try:
            result = check_trend_template(ticker)
            
            if save_to_db:
                save_trend_template_result(result)
            
            if result.passes_template:
                passing.append(result)
            else:
                failed.append(result)
                
        except Exception as e:
            errors.append((ticker, str(e)))
            continue
    
    if verbose:
        print(f"\nScan complete:")
        print(f"  Passing: {len(passing)}")
        print(f"  Failed: {len(failed)}")
        print(f"  Errors: {len(errors)}")
    
    return passing


def save_trend_template_result(result: TrendTemplateResult) -> None:
    """Save trend template result to database."""
    with get_db() as conn:
        conn.execute("""
            INSERT OR REPLACE INTO trend_template
            (ticker, date, price, ma_50, ma_150, ma_200, high_52w, low_52w,
             price_above_ma50, price_above_ma150, price_above_ma200,
             ma50_above_ma150, ma150_above_ma200, ma200_trending_up,
             price_within_25pct_of_high, price_above_30pct_from_low,
             rs_rating, template_compliant, criteria_passed)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            result.ticker,
            result.analysis_date.isoformat(),
            result.price,
            result.ma_50,
            result.ma_150,
            result.ma_200,
            result.high_52w,
            result.low_52w,
            result.c1_price_above_ma50,
            result.c2_price_above_ma150,
            result.c3_price_above_ma200,
            result.c4_ma50_above_ma150,
            result.c5_ma150_above_ma200,
            result.c6_ma200_trending_up,
            result.c7_within_25pct_of_high,
            result.c8_above_30pct_from_low,
            result.rs_rating,
            result.passes_template,
            result.criteria_passed,
        ))


def get_compliant_stocks(target_date: Optional[date] = None) -> List[Dict]:
    """Get all stocks passing trend template from database."""
    if target_date is None:
        target_date = date.today()
    
    with get_db() as conn:
        cursor = conn.execute("""
            SELECT * FROM trend_template
            WHERE date = ? AND template_compliant = 1
            ORDER BY rs_rating DESC NULLS LAST, criteria_passed DESC
        """, (target_date.isoformat(),))
        
        rows = cursor.fetchall()
        return [dict(row) for row in rows]


def format_template_report(result: TrendTemplateResult) -> str:
    """Format a readable report for a trend template result."""
    check = "✅" if result.passes_template else "❌"
    
    lines = [
        f"\n{check} {result.ticker} - Trend Template Analysis",
        f"{'=' * 50}",
        f"Price: ${result.price:.2f}",
        f"",
        f"Moving Averages:",
        f"  50-day:  ${result.ma_50:.2f}",
        f"  150-day: ${result.ma_150:.2f}",
        f"  200-day: ${result.ma_200:.2f}",
        f"",
        f"52-Week Range: ${result.low_52w:.2f} - ${result.high_52w:.2f}",
        f"  Distance from high: {result.distance_from_high_pct:.1f}%",
        f"  Above 52-week low: {result.distance_from_low_pct:.1f}%",
        f"",
        f"Criteria ({result.criteria_passed}/8 passing):",
        f"  {'✅' if result.c1_price_above_ma50 else '❌'} 1. Price > 50-day MA",
        f"  {'✅' if result.c2_price_above_ma150 else '❌'} 2. Price > 150-day MA",
        f"  {'✅' if result.c3_price_above_ma200 else '❌'} 3. Price > 200-day MA",
        f"  {'✅' if result.c4_ma50_above_ma150 else '❌'} 4. 50-day MA > 150-day MA",
        f"  {'✅' if result.c5_ma150_above_ma200 else '❌'} 5. 150-day MA > 200-day MA",
        f"  {'✅' if result.c6_ma200_trending_up else '❌'} 6. 200-day MA trending up",
        f"  {'✅' if result.c7_within_25pct_of_high else '❌'} 7. Within 25% of 52-week high",
        f"  {'✅' if result.c8_above_30pct_from_low else '❌'} 8. 30%+ above 52-week low",
    ]
    
    if result.rs_rating is not None:
        lines.append(f"\nRelative Strength Rating: {result.rs_rating:.1f}")
    
    return "\n".join(lines)


# Quick test
if __name__ == "__main__":
    # Test with a few well-known stocks
    test_tickers = ['AAPL', 'MSFT', 'NVDA', 'META', 'TSLA']
    
    print("Testing Trend Template Scanner")
    print("=" * 50)
    
    for ticker in test_tickers:
        try:
            result = check_trend_template(ticker)
            status = "✅ PASSES" if result.passes_template else f"❌ FAILS ({result.criteria_passed}/8)"
            print(f"{ticker}: {status}")
            
            if result.passes_template:
                print(format_template_report(result))
        except Exception as e:
            print(f"{ticker}: ERROR - {e}")
