"""
Fundamental Data Collector

Uses Financial Modeling Prep API (free tier: 250 calls/day)
to fetch earnings, revenue, and margin data.

Sign up at: https://site.financialmodelingprep.com/developer/docs
"""

import os
import requests
import time
from dataclasses import dataclass
from datetime import date
from typing import Optional, Dict, List
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from utils.db import get_db
from utils.config import config

FMP_BASE_URL = "https://financialmodelingprep.com/api/v3"


@dataclass
class FundamentalData:
    """Fundamental data for a single stock."""
    ticker: str
    analysis_date: date
    
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
    
    def to_dict(self) -> Dict:
        return {
            'ticker': self.ticker,
            'date': self.analysis_date.isoformat(),
            'eps_quarterly': self.eps_quarterly,
            'eps_growth_quarterly': self.eps_growth_quarterly,
            'eps_growth_annual': self.eps_growth_annual,
            'eps_acceleration': self.eps_acceleration,
            'revenue_quarterly': self.revenue_quarterly,
            'revenue_growth_quarterly': self.revenue_growth_quarterly,
            'revenue_growth_annual': self.revenue_growth_annual,
            'profit_margin': self.profit_margin,
            'margin_expanding': self.margin_expanding,
            'fundamental_score': self.fundamental_score,
        }


def get_fundamentals(ticker: str) -> FundamentalData:
    """
    Fetch fundamental data from Financial Modeling Prep.
    
    Free tier allows 250 calls/day, so use wisely.
    
    Args:
        ticker: Stock symbol
    
    Returns:
        FundamentalData with earnings, revenue, and margins
    """
    api_key = config.FMP_API_KEY
    if not api_key:
        # Return empty data if no API key
        return _empty_fundamentals(ticker, "FMP_API_KEY not configured")
    
    try:
        # Get income statement (quarterly)
        url = f"{FMP_BASE_URL}/income-statement/{ticker}?period=quarter&limit=8&apikey={api_key}"
        response = requests.get(url, timeout=10)
        
        if response.status_code == 401:
            return _empty_fundamentals(ticker, "Invalid FMP API key")
        
        if response.status_code != 200:
            return _empty_fundamentals(ticker, f"FMP API error: {response.status_code}")
        
        data = response.json()
        
        if not data or len(data) < 2:
            return _empty_fundamentals(ticker, "Insufficient quarterly data")
        
        # Parse the data
        return _parse_income_statement(ticker, data)
        
    except requests.RequestException as e:
        return _empty_fundamentals(ticker, f"Request error: {str(e)[:50]}")
    except Exception as e:
        return _empty_fundamentals(ticker, f"Error: {str(e)[:50]}")


def _parse_income_statement(ticker: str, data: List[Dict]) -> FundamentalData:
    """Parse FMP income statement data into FundamentalData."""
    
    # Quarters: data[0] = most recent, data[4] = year ago
    current = data[0]
    year_ago = data[4] if len(data) > 4 else None
    last_q = data[1] if len(data) > 1 else None
    two_q_ago = data[2] if len(data) > 2 else None
    
    # EPS values
    eps_current = current.get('eps') or current.get('epsdiluted', 0)
    eps_year_ago = (year_ago.get('eps') or year_ago.get('epsdiluted', 0)) if year_ago else 0
    eps_last_q = (last_q.get('eps') or last_q.get('epsdiluted', 0)) if last_q else 0
    
    # EPS growth (YoY)
    eps_growth_q = _calc_growth(eps_current, eps_year_ago)
    
    # EPS acceleration (is this quarter's growth > last quarter's growth?)
    eps_acceleration = False
    if last_q and len(data) > 5:
        last_q_year_ago = data[5]
        eps_last_q_ya = last_q_year_ago.get('eps') or last_q_year_ago.get('epsdiluted', 0)
        last_q_growth = _calc_growth(eps_last_q, eps_last_q_ya)
        if eps_growth_q is not None and last_q_growth is not None:
            eps_acceleration = eps_growth_q > last_q_growth
    
    # Revenue values
    rev_current = current.get('revenue', 0)
    rev_year_ago = year_ago.get('revenue', 0) if year_ago else 0
    rev_growth_q = _calc_growth(rev_current, rev_year_ago)
    
    # Margins
    net_income = current.get('netIncome', 0)
    profit_margin = (net_income / rev_current * 100) if rev_current else None
    
    # Margin expansion
    margin_expanding = False
    if last_q and profit_margin is not None:
        last_rev = last_q.get('revenue', 1)
        last_ni = last_q.get('netIncome', 0)
        last_margin = (last_ni / last_rev * 100) if last_rev else None
        if last_margin is not None:
            margin_expanding = profit_margin > last_margin
    
    # Calculate fundamental score
    score = _calculate_fundamental_score(eps_growth_q, rev_growth_q, eps_acceleration, margin_expanding)
    
    return FundamentalData(
        ticker=ticker,
        analysis_date=date.today(),
        eps_quarterly=eps_current,
        eps_growth_quarterly=round(eps_growth_q, 2) if eps_growth_q else None,
        eps_growth_annual=None,  # Would need annual data
        eps_acceleration=eps_acceleration,
        revenue_quarterly=rev_current,
        revenue_growth_quarterly=round(rev_growth_q, 2) if rev_growth_q else None,
        revenue_growth_annual=None,
        profit_margin=round(profit_margin, 2) if profit_margin else None,
        margin_expanding=margin_expanding,
        fundamental_score=score,
    )


def _calc_growth(current: float, previous: float) -> Optional[float]:
    """Calculate growth percentage."""
    if previous == 0 or previous is None:
        return None
    return ((current - previous) / abs(previous)) * 100


def _calculate_fundamental_score(eps_growth, rev_growth, acceleration, margin_expanding) -> int:
    """
    Calculate fundamental quality score 0-100.
    
    Scoring breakdown:
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
        elif eps_growth >= 15:
            score += 20
        elif eps_growth > 0:
            score += 10
        # Negative EPS growth = 0 points
    
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
    """Return empty fundamentals result when data unavailable."""
    return FundamentalData(
        ticker=ticker,
        analysis_date=date.today(),
        eps_quarterly=None,
        eps_growth_quarterly=None,
        eps_growth_annual=None,
        eps_acceleration=False,
        revenue_quarterly=None,
        revenue_growth_quarterly=None,
        revenue_growth_annual=None,
        profit_margin=None,
        margin_expanding=False,
        fundamental_score=0,
    )


def collect_fundamentals_batch(
    tickers: List[str],
    save_to_db: bool = True,
    verbose: bool = True
) -> List[FundamentalData]:
    """
    Collect fundamental data for multiple stocks.
    
    Note: Free FMP tier is 250 calls/day, so use wisely!
    
    Args:
        tickers: List of stock symbols
        save_to_db: Save to database
        verbose: Print progress
    
    Returns:
        List of FundamentalData objects
    """
    results = []
    
    if not config.FMP_API_KEY:
        if verbose:
            print("⚠️  FMP_API_KEY not configured - skipping fundamental collection")
            print("   Set FMP_API_KEY in .env to enable this feature")
        return results
    
    for i, ticker in enumerate(tickers):
        if verbose and (i + 1) % 25 == 0:
            print(f"  Collecting fundamentals: {i + 1}/{len(tickers)}...")
        
        data = get_fundamentals(ticker)
        results.append(data)
        
        if save_to_db and data.fundamental_score > 0:
            save_fundamentals(data)
        
        # Rate limit (FMP free tier)
        time.sleep(0.25)
    
    if verbose:
        scored = [r for r in results if r.fundamental_score > 0]
        print(f"\nFundamentals collected: {len(scored)}/{len(tickers)} with valid data")
        
        # Show top scores
        top = sorted(scored, key=lambda x: x.fundamental_score, reverse=True)[:5]
        if top:
            print("\nTop 5 by Fundamental Score:")
            for r in top:
                print(f"  {r.ticker}: {r.fundamental_score} (EPS: {r.eps_growth_quarterly or 'N/A'}%, Rev: {r.revenue_growth_quarterly or 'N/A'}%)")
    
    return results


def save_fundamentals(data: FundamentalData) -> None:
    """Save fundamental data to database."""
    with get_db() as conn:
        conn.execute("""
            INSERT OR REPLACE INTO fundamentals
            (ticker, date, eps_quarterly, eps_growth_quarterly, eps_growth_annual,
             eps_acceleration, revenue_quarterly, revenue_growth_quarterly, revenue_growth_annual,
             profit_margin, margin_expanding, fundamental_score)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            data.ticker,
            data.analysis_date.isoformat(),
            data.eps_quarterly,
            data.eps_growth_quarterly,
            data.eps_growth_annual,
            data.eps_acceleration,
            data.revenue_quarterly,
            data.revenue_growth_quarterly,
            data.revenue_growth_annual,
            data.profit_margin,
            data.margin_expanding,
            data.fundamental_score,
        ))


def get_fundamentals_from_db(ticker: str, target_date: Optional[date] = None) -> Optional[Dict]:
    """Get fundamental data from database."""
    if target_date is None:
        target_date = date.today()
    
    with get_db() as conn:
        cursor = conn.execute("""
            SELECT * FROM fundamentals
            WHERE ticker = ? AND date = ?
        """, (ticker, target_date.isoformat()))
        
        row = cursor.fetchone()
        return dict(row) if row else None


def format_fundamentals_report(data: FundamentalData) -> str:
    """Format a readable report for fundamental data."""
    lines = [
        f"\n📊 {data.ticker} - Fundamental Analysis",
        f"{'=' * 50}",
        f"",
        f"Earnings:",
        f"  Quarterly EPS: ${data.eps_quarterly:.2f}" if data.eps_quarterly else "  Quarterly EPS: N/A",
        f"  EPS Growth (YoY): {data.eps_growth_quarterly:+.1f}%" if data.eps_growth_quarterly else "  EPS Growth: N/A",
        f"  EPS Accelerating: {'✅ Yes' if data.eps_acceleration else '❌ No'}",
        f"",
        f"Revenue:",
        f"  Quarterly Revenue: ${data.revenue_quarterly/1e9:.2f}B" if data.revenue_quarterly else "  Quarterly Revenue: N/A",
        f"  Revenue Growth (YoY): {data.revenue_growth_quarterly:+.1f}%" if data.revenue_growth_quarterly else "  Revenue Growth: N/A",
        f"",
        f"Margins:",
        f"  Profit Margin: {data.profit_margin:.1f}%" if data.profit_margin else "  Profit Margin: N/A",
        f"  Margin Expanding: {'✅ Yes' if data.margin_expanding else '❌ No'}",
        f"",
        f"Fundamental Score: {data.fundamental_score}/100",
    ]
    
    return "\n".join(lines)


# Quick test
if __name__ == "__main__":
    print("Testing Fundamentals Collector")
    print("=" * 50)
    
    if not config.FMP_API_KEY:
        print("⚠️  FMP_API_KEY not set in environment")
        print("   Set it in .env to test fundamental data collection")
        print("   Sign up at: https://site.financialmodelingprep.com/developer/docs")
    else:
        # Test with a few stocks
        test_tickers = ['AAPL', 'NVDA', 'TSLA']
        
        for ticker in test_tickers:
            data = get_fundamentals(ticker)
            print(format_fundamentals_report(data))
            time.sleep(0.5)
