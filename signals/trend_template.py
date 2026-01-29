"""
Minervini Trend Template Scanner

Checks stocks against the 8-point Trend Template criteria.
ALL criteria must pass for a stock to be considered in a confirmed uptrend.

The 8 Criteria:
1. Price > 50-day MA
2. Price > 150-day MA
3. Price > 200-day MA
4. 50-day MA > 150-day MA
5. 150-day MA > 200-day MA
6. 200-day MA trending up (at least 1 month)
7. Price within 25% of 52-week high
8. Price at least 30% above 52-week low
"""

import sys
from pathlib import Path
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Optional, List

import yfinance as yf
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent))
from utils.db import get_db


@dataclass
class TrendTemplateResult:
    """Result of Trend Template analysis for a single stock."""
    ticker: str
    check_date: date
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

    # Overall result
    passes_template: bool
    criteria_passed: int  # Count out of 8

    # Additional context
    rs_rating: Optional[float] = None
    distance_from_high_pct: Optional[float] = None
    distance_from_low_pct: Optional[float] = None

    def get_criteria_summary(self) -> str:
        """Get a string summary of which criteria passed/failed."""
        criteria = [
            ('Price > MA50', self.c1_price_above_ma50),
            ('Price > MA150', self.c2_price_above_ma150),
            ('Price > MA200', self.c3_price_above_ma200),
            ('MA50 > MA150', self.c4_ma50_above_ma150),
            ('MA150 > MA200', self.c5_ma150_above_ma200),
            ('MA200 trending up', self.c6_ma200_trending_up),
            ('Within 25% of high', self.c7_within_25pct_of_high),
            ('30%+ above low', self.c8_above_30pct_from_low),
        ]
        passed = [name for name, result in criteria if result]
        failed = [name for name, result in criteria if not result]

        summary = f"Passed ({len(passed)}/8): {', '.join(passed) if passed else 'None'}"
        if failed:
            summary += f"\nFailed: {', '.join(failed)}"
        return summary


def check_trend_template(ticker: str, target_date: Optional[date] = None) -> TrendTemplateResult:
    """
    Check if a stock passes the Minervini Trend Template.

    Args:
        ticker: Stock ticker symbol
        target_date: Date to check (defaults to today)

    Returns:
        TrendTemplateResult with all criteria results

    Raises:
        ValueError: If insufficient historical data
    """
    if target_date is None:
        target_date = date.today()

    # Fetch historical data - need 252 trading days for 52-week + buffer for MAs
    stock = yf.Ticker(ticker)
    hist = stock.history(period="15mo")  # ~315 trading days

    if len(hist) < 200:
        raise ValueError(f"Insufficient data for {ticker}: only {len(hist)} days available, need 200+")

    # Current price and moving averages
    current_price = float(hist['Close'].iloc[-1])
    ma_50 = float(hist['Close'].rolling(50).mean().iloc[-1])
    ma_150 = float(hist['Close'].rolling(150).mean().iloc[-1])
    ma_200 = float(hist['Close'].rolling(200).mean().iloc[-1])

    # 200-day MA from 30 days ago (to check if trending up)
    ma_200_series = hist['Close'].rolling(200).mean()
    if len(ma_200_series) >= 230:
        ma_200_30d_ago = float(ma_200_series.iloc[-30])
    else:
        # Not enough data for 30-day lookback, use earliest available
        ma_200_30d_ago = float(ma_200_series.dropna().iloc[0])

    # 52-week high and low (using last 252 trading days)
    lookback_days = min(252, len(hist))
    high_52w = float(hist['High'].tail(lookback_days).max())
    low_52w = float(hist['Low'].tail(lookback_days).min())

    # Calculate each criterion
    c1 = current_price > ma_50
    c2 = current_price > ma_150
    c3 = current_price > ma_200
    c4 = ma_50 > ma_150
    c5 = ma_150 > ma_200
    c6 = ma_200 > ma_200_30d_ago  # Trending up over last month
    c7 = current_price >= high_52w * 0.75  # Within 25% of 52-week high
    c8 = current_price >= low_52w * 1.30  # At least 30% above 52-week low

    criteria = [c1, c2, c3, c4, c5, c6, c7, c8]
    passes_all = all(criteria)
    num_passed = sum(criteria)

    # Calculate distance metrics
    distance_from_high = ((high_52w - current_price) / high_52w) * 100 if high_52w > 0 else 0
    distance_from_low = ((current_price - low_52w) / low_52w) * 100 if low_52w > 0 else 0

    return TrendTemplateResult(
        ticker=ticker,
        check_date=target_date,
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
        passes_template=passes_all,
        criteria_passed=num_passed,
        distance_from_high_pct=round(distance_from_high, 2),
        distance_from_low_pct=round(distance_from_low, 2)
    )


def scan_universe(tickers: List[str], verbose: bool = False) -> List[TrendTemplateResult]:
    """
    Scan multiple tickers for Trend Template compliance.

    Args:
        tickers: List of ticker symbols
        verbose: Print progress

    Returns:
        List of TrendTemplateResult for all stocks (passing and failing)
    """
    results = []

    for i, ticker in enumerate(tickers):
        if verbose and i % 10 == 0:
            print(f"  Scanning {i+1}/{len(tickers)}...")

        try:
            result = check_trend_template(ticker)
            results.append(result)

            if verbose and result.passes_template:
                print(f"    ✓ {ticker} passes ({result.criteria_passed}/8)")

        except Exception as e:
            if verbose:
                print(f"    ✗ {ticker}: {e}")

    return results


def save_results_to_db(results: List[TrendTemplateResult]) -> int:
    """
    Save Trend Template results to database.

    Args:
        results: List of TrendTemplateResult objects

    Returns:
        Number of rows inserted/updated
    """
    count = 0

    with get_db() as conn:
        for r in results:
            conn.execute("""
                INSERT INTO trend_template
                (ticker, date, price, ma_50, ma_150, ma_200, high_52w, low_52w,
                 price_above_ma50, price_above_ma150, price_above_ma200,
                 ma50_above_ma150, ma150_above_ma200, ma200_trending_up,
                 price_within_25pct_of_high, price_above_30pct_from_low,
                 rs_rating, template_compliant, criteria_passed)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(ticker, date) DO UPDATE SET
                    price = excluded.price,
                    ma_50 = excluded.ma_50,
                    ma_150 = excluded.ma_150,
                    ma_200 = excluded.ma_200,
                    high_52w = excluded.high_52w,
                    low_52w = excluded.low_52w,
                    price_above_ma50 = excluded.price_above_ma50,
                    price_above_ma150 = excluded.price_above_ma150,
                    price_above_ma200 = excluded.price_above_ma200,
                    ma50_above_ma150 = excluded.ma50_above_ma150,
                    ma150_above_ma200 = excluded.ma150_above_ma200,
                    ma200_trending_up = excluded.ma200_trending_up,
                    price_within_25pct_of_high = excluded.price_within_25pct_of_high,
                    price_above_30pct_from_low = excluded.price_above_30pct_from_low,
                    rs_rating = excluded.rs_rating,
                    template_compliant = excluded.template_compliant,
                    criteria_passed = excluded.criteria_passed
            """, (
                r.ticker,
                r.check_date.isoformat(),
                r.price,
                r.ma_50,
                r.ma_150,
                r.ma_200,
                r.high_52w,
                r.low_52w,
                r.c1_price_above_ma50,
                r.c2_price_above_ma150,
                r.c3_price_above_ma200,
                r.c4_ma50_above_ma150,
                r.c5_ma150_above_ma200,
                r.c6_ma200_trending_up,
                r.c7_within_25pct_of_high,
                r.c8_above_30pct_from_low,
                r.rs_rating,
                r.passes_template,
                r.criteria_passed
            ))
            count += 1

    return count


def get_compliant_stocks(target_date: Optional[date] = None) -> List[dict]:
    """
    Get stocks that pass the Trend Template from database.

    Args:
        target_date: Date to query (defaults to today)

    Returns:
        List of dicts with compliant stock data
    """
    if target_date is None:
        target_date = date.today()

    with get_db() as conn:
        cursor = conn.execute("""
            SELECT * FROM trend_template
            WHERE date = ? AND template_compliant = 1
            ORDER BY rs_rating DESC NULLS LAST, criteria_passed DESC
        """, (target_date.isoformat(),))

        return [dict(row) for row in cursor.fetchall()]


if __name__ == "__main__":
    # Test with a few tickers
    test_tickers = ['AAPL', 'MSFT', 'NVDA', 'AMD', 'TSLA']

    print("Testing Trend Template Scanner")
    print("=" * 50)

    for ticker in test_tickers:
        try:
            result = check_trend_template(ticker)
            status = "✓ PASSES" if result.passes_template else "✗ FAILS"
            print(f"\n{ticker}: {status} ({result.criteria_passed}/8)")
            print(f"  Price: ${result.price:.2f}")
            print(f"  MA50: ${result.ma_50:.2f}, MA150: ${result.ma_150:.2f}, MA200: ${result.ma_200:.2f}")
            print(f"  52W High: ${result.high_52w:.2f} ({result.distance_from_high_pct:.1f}% away)")
            print(f"  52W Low: ${result.low_52w:.2f} ({result.distance_from_low_pct:.1f}% above)")
            if not result.passes_template:
                print(f"  {result.get_criteria_summary()}")
        except Exception as e:
            print(f"\n{ticker}: ERROR - {e}")
