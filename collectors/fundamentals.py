"""
Fundamental Data Collector

Uses Financial Modeling Prep API (free tier: 250 calls/day)
to fetch earnings, revenue, and margin data.

Calculates:
- EPS growth (quarterly and annual YoY)
- Revenue growth (quarterly and annual YoY)
- EPS acceleration (this Q growth > last Q growth)
- Margin expansion

Alternative fallback: yfinance (limited fundamental data)
"""

import os
import sys
from pathlib import Path
from dataclasses import dataclass
from datetime import date
from typing import Optional, Dict, List
import requests

import yfinance as yf

sys.path.insert(0, str(Path(__file__).parent.parent))
from utils.config import config
from utils.db import get_db


@dataclass
class FundamentalData:
    """Fundamental metrics for a stock."""
    ticker: str
    check_date: date

    # Earnings
    eps_current_quarter: Optional[float]
    eps_prior_year_quarter: Optional[float]
    eps_growth_quarterly: Optional[float]  # YoY %
    eps_growth_annual: Optional[float]
    eps_acceleration: bool  # This Q growth > Last Q growth

    # Revenue
    revenue_current_quarter: Optional[float]
    revenue_prior_year_quarter: Optional[float]
    revenue_growth_quarterly: Optional[float]
    revenue_growth_annual: Optional[float]

    # Margins
    profit_margin: Optional[float]
    profit_margin_prior: Optional[float]
    margin_expanding: bool

    # Quality score
    fundamental_score: int  # 0-100

    # Data source
    data_source: str  # 'FMP', 'YFINANCE', 'NONE'


def get_fundamentals(ticker: str) -> FundamentalData:
    """
    Fetch fundamental data for a stock.

    Tries FMP API first (if key available), falls back to yfinance.

    Args:
        ticker: Stock ticker symbol

    Returns:
        FundamentalData object with metrics and score
    """
    # Try FMP first if API key is available
    if config.FMP_API_KEY:
        try:
            return _get_fundamentals_fmp(ticker)
        except Exception as e:
            print(f"FMP failed for {ticker}: {e}, trying yfinance...")

    # Fallback to yfinance
    try:
        return _get_fundamentals_yfinance(ticker)
    except Exception as e:
        print(f"yfinance failed for {ticker}: {e}")
        return _empty_fundamentals(ticker, "NONE")


def _get_fundamentals_fmp(ticker: str) -> FundamentalData:
    """
    Fetch fundamentals from Financial Modeling Prep API.

    Free tier: 250 API calls/day
    """
    api_key = config.FMP_API_KEY
    base_url = config.FMP_API_BASE

    # Get quarterly income statements (need 8 quarters for YoY comparison)
    url = f"{base_url}/income-statement/{ticker}?period=quarter&limit=8&apikey={api_key}"
    response = requests.get(url, timeout=10)

    if response.status_code != 200:
        raise ValueError(f"FMP API error: {response.status_code}")

    data = response.json()

    if not data or len(data) < 2:
        return _empty_fundamentals(ticker, "FMP")

    # Current quarter and year-ago quarter
    current = data[0]
    year_ago = data[4] if len(data) > 4 else None
    last_q = data[1] if len(data) > 1 else None
    last_q_year_ago = data[5] if len(data) > 5 else None

    # EPS calculations
    eps_current = current.get('eps') or current.get('epsdiluted', 0)
    eps_year_ago = year_ago.get('eps') or year_ago.get('epsdiluted', 0) if year_ago else 0
    eps_last_q = last_q.get('eps') or last_q.get('epsdiluted', 0) if last_q else 0
    eps_last_q_ya = last_q_year_ago.get('eps') or last_q_year_ago.get('epsdiluted', 0) if last_q_year_ago else 0

    eps_growth_q = _calc_growth(eps_current, eps_year_ago)

    # EPS acceleration: is this quarter's YoY growth > last quarter's YoY growth?
    last_q_growth = _calc_growth(eps_last_q, eps_last_q_ya)
    eps_acceleration = (
        eps_growth_q is not None and
        last_q_growth is not None and
        eps_growth_q > last_q_growth
    )

    # Revenue calculations
    rev_current = current.get('revenue', 0)
    rev_year_ago = year_ago.get('revenue', 0) if year_ago else 0
    rev_growth_q = _calc_growth(rev_current, rev_year_ago)

    # Margin calculations
    net_income = current.get('netIncome', 0)
    last_net_income = last_q.get('netIncome', 0) if last_q else 0
    last_revenue = last_q.get('revenue', 1) if last_q else 1

    profit_margin = (net_income / rev_current * 100) if rev_current else None
    profit_margin_prior = (last_net_income / last_revenue * 100) if last_revenue else None
    margin_expanding = (
        profit_margin is not None and
        profit_margin_prior is not None and
        profit_margin > profit_margin_prior
    )

    # Calculate quality score
    score = _calculate_fundamental_score(eps_growth_q, rev_growth_q, eps_acceleration, margin_expanding)

    return FundamentalData(
        ticker=ticker,
        check_date=date.today(),
        eps_current_quarter=eps_current,
        eps_prior_year_quarter=eps_year_ago,
        eps_growth_quarterly=eps_growth_q,
        eps_growth_annual=None,  # Would need annual statements
        eps_acceleration=eps_acceleration,
        revenue_current_quarter=rev_current,
        revenue_prior_year_quarter=rev_year_ago,
        revenue_growth_quarterly=rev_growth_q,
        revenue_growth_annual=None,
        profit_margin=round(profit_margin, 2) if profit_margin else None,
        profit_margin_prior=round(profit_margin_prior, 2) if profit_margin_prior else None,
        margin_expanding=margin_expanding,
        fundamental_score=score,
        data_source='FMP'
    )


def _get_fundamentals_yfinance(ticker: str) -> FundamentalData:
    """
    Fetch fundamentals from yfinance (fallback).

    Limited data available but works without API key.
    """
    stock = yf.Ticker(ticker)
    info = stock.info

    # Try to get quarterly financials
    try:
        quarterly_financials = stock.quarterly_financials
        quarterly_income = stock.quarterly_income_stmt
    except Exception:
        quarterly_financials = None
        quarterly_income = None

    # EPS from info
    eps_trailing = info.get('trailingEps')
    eps_forward = info.get('forwardEps')

    # Revenue growth
    revenue_growth = info.get('revenueGrowth')
    if revenue_growth:
        revenue_growth = revenue_growth * 100  # Convert to percentage

    # Earnings growth
    earnings_growth = info.get('earningsGrowth') or info.get('earningsQuarterlyGrowth')
    if earnings_growth:
        earnings_growth = earnings_growth * 100

    # Profit margin
    profit_margin = info.get('profitMargins')
    if profit_margin:
        profit_margin = profit_margin * 100

    # Calculate score (limited data available)
    score = _calculate_fundamental_score(
        earnings_growth,
        revenue_growth,
        False,  # Can't determine acceleration from yfinance
        False   # Can't determine margin expansion easily
    )

    return FundamentalData(
        ticker=ticker,
        check_date=date.today(),
        eps_current_quarter=eps_trailing,
        eps_prior_year_quarter=None,
        eps_growth_quarterly=earnings_growth,
        eps_growth_annual=earnings_growth,
        eps_acceleration=False,
        revenue_current_quarter=info.get('totalRevenue'),
        revenue_prior_year_quarter=None,
        revenue_growth_quarterly=revenue_growth,
        revenue_growth_annual=revenue_growth,
        profit_margin=round(profit_margin, 2) if profit_margin else None,
        profit_margin_prior=None,
        margin_expanding=False,
        fundamental_score=score,
        data_source='YFINANCE'
    )


def _calc_growth(current: float, previous: float) -> Optional[float]:
    """Calculate growth percentage."""
    if previous == 0 or previous is None or current is None:
        return None
    return round(((current - previous) / abs(previous)) * 100, 2)


def _calculate_fundamental_score(
    eps_growth: Optional[float],
    rev_growth: Optional[float],
    acceleration: bool,
    margin_expanding: bool
) -> int:
    """
    Calculate fundamental quality score 0-100.

    Scoring rubric:
    - EPS growth: up to 40 points
    - Revenue growth: up to 30 points
    - EPS acceleration: 15 points
    - Margin expansion: 15 points
    """
    score = 0

    # EPS growth (up to 40 points)
    if eps_growth is not None:
        if eps_growth >= 50:
            score += 40
        elif eps_growth >= 25:
            score += 30
        elif eps_growth >= 15:  # Our minimum threshold
            score += 20
        elif eps_growth > 0:
            score += 10

    # Revenue growth (up to 30 points)
    if rev_growth is not None:
        if rev_growth >= 25:
            score += 30
        elif rev_growth >= 15:
            score += 20
        elif rev_growth >= 10:  # Our minimum threshold
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


def _empty_fundamentals(ticker: str, source: str) -> FundamentalData:
    """Return empty fundamentals result."""
    return FundamentalData(
        ticker=ticker,
        check_date=date.today(),
        eps_current_quarter=None,
        eps_prior_year_quarter=None,
        eps_growth_quarterly=None,
        eps_growth_annual=None,
        eps_acceleration=False,
        revenue_current_quarter=None,
        revenue_prior_year_quarter=None,
        revenue_growth_quarterly=None,
        revenue_growth_annual=None,
        profit_margin=None,
        profit_margin_prior=None,
        margin_expanding=False,
        fundamental_score=0,
        data_source=source
    )


def save_fundamentals_to_db(data: FundamentalData) -> bool:
    """
    Save fundamental data to database.

    Returns True if successful.
    """
    with get_db() as conn:
        conn.execute("""
            INSERT INTO fundamentals
            (ticker, date, eps_current_quarter, eps_prior_year_quarter,
             eps_growth_quarterly, eps_growth_annual, eps_acceleration,
             revenue_current_quarter, revenue_prior_year_quarter,
             revenue_growth_quarterly, revenue_growth_annual,
             profit_margin, profit_margin_prior, margin_expanding,
             fundamental_score, data_source)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(ticker, date) DO UPDATE SET
                eps_current_quarter = excluded.eps_current_quarter,
                eps_prior_year_quarter = excluded.eps_prior_year_quarter,
                eps_growth_quarterly = excluded.eps_growth_quarterly,
                eps_growth_annual = excluded.eps_growth_annual,
                eps_acceleration = excluded.eps_acceleration,
                revenue_current_quarter = excluded.revenue_current_quarter,
                revenue_prior_year_quarter = excluded.revenue_prior_year_quarter,
                revenue_growth_quarterly = excluded.revenue_growth_quarterly,
                revenue_growth_annual = excluded.revenue_growth_annual,
                profit_margin = excluded.profit_margin,
                profit_margin_prior = excluded.profit_margin_prior,
                margin_expanding = excluded.margin_expanding,
                fundamental_score = excluded.fundamental_score,
                data_source = excluded.data_source
        """, (
            data.ticker,
            data.check_date.isoformat(),
            data.eps_current_quarter,
            data.eps_prior_year_quarter,
            data.eps_growth_quarterly,
            data.eps_growth_annual,
            data.eps_acceleration,
            data.revenue_current_quarter,
            data.revenue_prior_year_quarter,
            data.revenue_growth_quarterly,
            data.revenue_growth_annual,
            data.profit_margin,
            data.profit_margin_prior,
            data.margin_expanding,
            data.fundamental_score,
            data.data_source
        ))

    return True


def collect_fundamentals_batch(tickers: List[str], verbose: bool = False) -> List[FundamentalData]:
    """
    Collect fundamentals for multiple tickers.

    Note: Be mindful of FMP API rate limits (250/day on free tier).

    Args:
        tickers: List of ticker symbols
        verbose: Print progress

    Returns:
        List of FundamentalData objects
    """
    results = []

    for i, ticker in enumerate(tickers):
        if verbose and i % 10 == 0:
            print(f"  Fetching fundamentals {i+1}/{len(tickers)}...")

        try:
            data = get_fundamentals(ticker)
            results.append(data)
            save_fundamentals_to_db(data)

            if verbose and data.fundamental_score >= 50:
                print(f"    ✓ {ticker}: Score {data.fundamental_score}, "
                      f"EPS +{data.eps_growth_quarterly or 0:.0f}%, "
                      f"Rev +{data.revenue_growth_quarterly or 0:.0f}%")

        except Exception as e:
            if verbose:
                print(f"    ✗ {ticker}: {e}")

    return results


if __name__ == "__main__":
    # Test with a few tickers
    test_tickers = ['AAPL', 'NVDA', 'MSFT', 'AMD', 'TSLA']

    print("Testing Fundamentals Collector")
    print("=" * 50)

    if config.FMP_API_KEY:
        print(f"Using FMP API (key configured)")
    else:
        print("FMP API key not set, using yfinance fallback")

    for ticker in test_tickers:
        try:
            data = get_fundamentals(ticker)
            print(f"\n{ticker} (via {data.data_source}):")
            print(f"  Score: {data.fundamental_score}/100")
            print(f"  EPS Growth (Q): {data.eps_growth_quarterly or 'N/A'}%")
            print(f"  Revenue Growth (Q): {data.revenue_growth_quarterly or 'N/A'}%")
            print(f"  EPS Acceleration: {'Yes' if data.eps_acceleration else 'No'}")
            print(f"  Margin Expanding: {'Yes' if data.margin_expanding else 'No'}")
            print(f"  Profit Margin: {data.profit_margin or 'N/A'}%")
        except Exception as e:
            print(f"\n{ticker}: ERROR - {e}")
