"""
Earnings Calendar Integration

Fetches earnings dates to avoid trading near earnings announcements.

Rule: No new positions within 5 days of earnings.
"""

from datetime import date, datetime, timedelta
from typing import Optional, Dict, List, Tuple
import yfinance as yf
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from utils.config import config


def get_earnings_date(ticker: str) -> Optional[date]:
    """
    Get next earnings date for a stock.
    
    Args:
        ticker: Stock symbol
    
    Returns:
        Next earnings date or None if not available
    """
    try:
        stock = yf.Ticker(ticker)
        
        # Try to get earnings dates from yfinance
        calendar = stock.calendar
        
        if calendar is not None and not calendar.empty:
            # calendar is a DataFrame with earnings info
            if 'Earnings Date' in calendar.index:
                earnings_date = calendar.loc['Earnings Date']
                if isinstance(earnings_date, (list, tuple)) and len(earnings_date) > 0:
                    return _parse_date(earnings_date[0])
                elif earnings_date is not None:
                    return _parse_date(earnings_date)
        
        # Alternative: try earnings_dates attribute
        earnings_dates = getattr(stock, 'earnings_dates', None)
        if earnings_dates is not None and not earnings_dates.empty:
            # Get next future date
            today = datetime.now()
            future_dates = earnings_dates[earnings_dates.index > today]
            if not future_dates.empty:
                return future_dates.index[0].date()
        
        return None
        
    except Exception as e:
        return None


def _parse_date(value) -> Optional[date]:
    """Parse various date formats to date object."""
    if value is None:
        return None
    
    if isinstance(value, date):
        return value
    
    if isinstance(value, datetime):
        return value.date()
    
    if isinstance(value, str):
        try:
            return datetime.strptime(value, '%Y-%m-%d').date()
        except ValueError:
            try:
                return datetime.strptime(value, '%b %d, %Y').date()
            except ValueError:
                return None
    
    return None


def is_earnings_safe(ticker: str, days: int = None) -> Tuple[bool, Optional[date]]:
    """
    Check if we're far enough from earnings to trade.
    
    Args:
        ticker: Stock symbol
        days: Buffer days before earnings (default from config)
    
    Returns:
        Tuple of (is_safe, earnings_date)
        - is_safe: True if OK to trade, False if too close to earnings
        - earnings_date: Next earnings date (if known)
    """
    if days is None:
        days = config.EARNINGS_BUFFER_DAYS
    
    earnings_date = get_earnings_date(ticker)
    
    if earnings_date is None:
        # Unknown earnings date - assume safe but flag it
        return True, None
    
    today = date.today()
    days_until = (earnings_date - today).days
    
    # Safe if earnings is more than N days away
    # Also safe if earnings already passed (days_until negative)
    is_safe = days_until > days or days_until < -1
    
    return is_safe, earnings_date


def check_earnings_batch(tickers: List[str], days: int = None) -> Dict[str, Dict]:
    """
    Check earnings proximity for multiple stocks.
    
    Args:
        tickers: List of stock symbols
        days: Buffer days
    
    Returns:
        Dict mapping ticker -> {is_safe, earnings_date, days_until}
    """
    if days is None:
        days = config.EARNINGS_BUFFER_DAYS
    
    results = {}
    today = date.today()
    
    for ticker in tickers:
        is_safe, earnings_date = is_earnings_safe(ticker, days)
        
        if earnings_date:
            days_until = (earnings_date - today).days
        else:
            days_until = None
        
        results[ticker] = {
            'ticker': ticker,
            'is_safe': is_safe,
            'earnings_date': earnings_date.isoformat() if earnings_date else None,
            'days_until': days_until,
        }
    
    return results


def filter_by_earnings(tickers: List[str], days: int = None) -> Tuple[List[str], List[str]]:
    """
    Filter tickers by earnings proximity.
    
    Args:
        tickers: List of stock symbols
        days: Buffer days
    
    Returns:
        Tuple of (safe_tickers, unsafe_tickers)
    """
    if days is None:
        days = config.EARNINGS_BUFFER_DAYS
    
    safe = []
    unsafe = []
    
    for ticker in tickers:
        is_safe, _ = is_earnings_safe(ticker, days)
        if is_safe:
            safe.append(ticker)
        else:
            unsafe.append(ticker)
    
    return safe, unsafe


def get_upcoming_earnings(tickers: List[str], days_ahead: int = 14) -> List[Dict]:
    """
    Get stocks with earnings coming up in next N days.
    
    Args:
        tickers: List of stock symbols to check
        days_ahead: Look ahead window
    
    Returns:
        List of dicts with ticker and earnings info, sorted by date
    """
    today = date.today()
    cutoff = today + timedelta(days=days_ahead)
    
    upcoming = []
    
    for ticker in tickers:
        earnings_date = get_earnings_date(ticker)
        
        if earnings_date and today <= earnings_date <= cutoff:
            days_until = (earnings_date - today).days
            upcoming.append({
                'ticker': ticker,
                'earnings_date': earnings_date.isoformat(),
                'days_until': days_until,
            })
    
    # Sort by date
    upcoming.sort(key=lambda x: x['days_until'])
    
    return upcoming


def format_earnings_report(results: Dict[str, Dict]) -> str:
    """Format earnings check results as readable report."""
    lines = [
        "=" * 50,
        "EARNINGS PROXIMITY CHECK",
        "=" * 50,
        "",
    ]
    
    safe = [r for r in results.values() if r['is_safe']]
    unsafe = [r for r in results.values() if not r['is_safe']]
    
    if unsafe:
        lines.append("⚠️  AVOID - Earnings within 5 days:")
        lines.append("-" * 40)
        for r in unsafe:
            if r['days_until'] is not None:
                lines.append(f"  {r['ticker']:<6} - {r['days_until']} days ({r['earnings_date']})")
            else:
                lines.append(f"  {r['ticker']:<6} - earnings date unknown")
        lines.append("")
    
    if safe:
        lines.append("✅ SAFE to trade:")
        lines.append("-" * 40)
        for r in safe:
            if r['earnings_date']:
                lines.append(f"  {r['ticker']:<6} - {r['days_until']} days until earnings")
            else:
                lines.append(f"  {r['ticker']:<6} - earnings date unknown")
    
    return "\n".join(lines)


# Quick test
if __name__ == "__main__":
    print("Testing Earnings Calendar")
    print("=" * 50)
    
    test_tickers = ['AAPL', 'MSFT', 'NVDA', 'META', 'GOOGL', 'AMZN', 'TSLA']
    
    print("\nChecking earnings dates...")
    results = check_earnings_batch(test_tickers)
    
    print(format_earnings_report(results))
    
    print("\n\nUpcoming earnings in next 30 days:")
    upcoming = get_upcoming_earnings(test_tickers, days_ahead=30)
    for item in upcoming:
        print(f"  {item['ticker']}: {item['earnings_date']} ({item['days_until']} days)")
