"""
Breakout Detection

Identifies when a stock breaks out above its pivot point
with volume confirmation.

Valid breakout requirements:
1. Price crosses above pivot
2. Volume >= 1.5x average (confirmation)
3. Not too extended (< 5% above pivot ideally)
4. No earnings within 5 days
"""

import sys
from pathlib import Path
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Optional

import yfinance as yf

sys.path.insert(0, str(Path(__file__).parent.parent))
from utils.config import config
from utils.db import get_db


@dataclass
class BreakoutSignal:
    """Result of breakout detection for a single stock."""
    ticker: str
    check_date: date
    is_breakout: bool

    # Price action
    pivot_price: float
    current_price: float
    breakout_pct: float  # How far above pivot (%)

    # Volume confirmation
    volume_today: int
    avg_volume: int
    volume_ratio: float
    volume_confirmed: bool

    # Entry parameters
    suggested_entry: float
    suggested_stop: float
    suggested_target: float
    risk_reward_ratio: float

    # Position sizing
    shares_for_risk: int  # Based on 2% risk
    position_value: float

    # Status
    notes: str


def check_breakout(
    ticker: str,
    pivot_price: float,
    portfolio_value: float = None,
    volume_multiplier: float = None
) -> BreakoutSignal:
    """
    Check if stock is breaking out above pivot.

    Args:
        ticker: Stock ticker symbol
        pivot_price: Resistance level to break
        portfolio_value: For position sizing (defaults to config)
        volume_multiplier: Required volume multiple (defaults to config)

    Returns:
        BreakoutSignal with analysis and trade parameters
    """
    if volume_multiplier is None:
        volume_multiplier = config.BREAKOUT_VOLUME_MULTIPLIER
    if portfolio_value is None:
        portfolio_value = config.V2_PAPER_PORTFOLIO_SIZE

    stock = yf.Ticker(ticker)
    hist = stock.history(period="30d")

    if len(hist) < 20:
        return _empty_breakout(ticker, pivot_price, "Insufficient data")

    # Current price and volume
    current_price = float(hist['Close'].iloc[-1])
    volume_today = int(hist['Volume'].iloc[-1])
    avg_volume = int(hist['Volume'].tail(20).mean())

    # Check breakout conditions
    is_above_pivot = current_price > pivot_price
    breakout_pct = ((current_price - pivot_price) / pivot_price) * 100 if pivot_price > 0 else 0

    volume_ratio = volume_today / avg_volume if avg_volume > 0 else 0
    volume_confirmed = volume_ratio >= volume_multiplier

    # Valid breakout: above pivot, volume confirmed, not too extended
    max_chase = config.MAX_CHASE_PCT * 100  # Convert to percentage
    is_breakout = is_above_pivot and volume_confirmed and breakout_pct < max_chase

    # Calculate entry parameters
    entry = current_price
    stop = pivot_price * (1 - config.V2_DEFAULT_STOP_PCT)  # 7% below pivot
    target = entry * (1 + config.V2_DEFAULT_TARGET_PCT)  # 20% profit target

    # Risk/reward calculation
    risk_per_share = entry - stop
    reward_per_share = target - entry
    rr_ratio = reward_per_share / risk_per_share if risk_per_share > 0 else 0

    # Position sizing based on risk
    max_risk_dollars = portfolio_value * config.V2_MAX_RISK_PER_TRADE
    shares = int(max_risk_dollars / risk_per_share) if risk_per_share > 0 else 0

    # Cap at max position percentage
    max_shares = int((portfolio_value * config.V2_MAX_POSITION_PCT) / entry) if entry > 0 else 0
    shares = min(shares, max_shares)

    position_value = shares * entry

    return BreakoutSignal(
        ticker=ticker,
        check_date=date.today(),
        is_breakout=is_breakout,
        pivot_price=round(pivot_price, 2),
        current_price=round(current_price, 2),
        breakout_pct=round(breakout_pct, 2),
        volume_today=volume_today,
        avg_volume=avg_volume,
        volume_ratio=round(volume_ratio, 2),
        volume_confirmed=volume_confirmed,
        suggested_entry=round(entry, 2),
        suggested_stop=round(stop, 2),
        suggested_target=round(target, 2),
        risk_reward_ratio=round(rr_ratio, 2),
        shares_for_risk=shares,
        position_value=round(position_value, 2),
        notes=_generate_breakout_notes(is_above_pivot, volume_confirmed, breakout_pct, max_chase)
    )


def check_watchlist_for_breakouts(portfolio_value: float = None) -> list:
    """
    Check all stocks on watchlist for breakouts.

    Returns list of BreakoutSignal for stocks that triggered.
    """
    if portfolio_value is None:
        portfolio_value = config.V2_PAPER_PORTFOLIO_SIZE

    breakouts = []

    with get_db() as conn:
        cursor = conn.execute("""
            SELECT ticker, pivot_price FROM watchlist
            WHERE status = 'WATCHING'
        """)

        for row in cursor.fetchall():
            ticker = row['ticker']
            pivot = row['pivot_price']

            try:
                signal = check_breakout(ticker, pivot, portfolio_value)
                if signal.is_breakout:
                    breakouts.append(signal)

                    # Update watchlist status
                    conn.execute("""
                        UPDATE watchlist
                        SET status = 'TRIGGERED',
                            triggered_date = ?,
                            triggered_price = ?,
                            triggered_volume = ?
                        WHERE ticker = ? AND status = 'WATCHING'
                    """, (
                        date.today().isoformat(),
                        signal.current_price,
                        signal.volume_today,
                        ticker
                    ))

            except Exception as e:
                print(f"Error checking {ticker}: {e}")

    return breakouts


def is_earnings_safe(ticker: str, buffer_days: int = None) -> tuple:
    """
    Check if we're far enough from earnings to trade.

    Args:
        ticker: Stock ticker symbol
        buffer_days: Days to stay away from earnings (defaults to config)

    Returns:
        Tuple of (is_safe: bool, next_earnings_date: Optional[date], days_until: Optional[int])
    """
    if buffer_days is None:
        buffer_days = config.EARNINGS_BUFFER_DAYS

    try:
        stock = yf.Ticker(ticker)
        calendar = stock.calendar

        if calendar is None or calendar.empty:
            return True, None, None

        # Try to get earnings date from calendar
        earnings_date = None
        if 'Earnings Date' in calendar.index:
            earnings_date = calendar.loc['Earnings Date']
            if hasattr(earnings_date, 'iloc'):
                earnings_date = earnings_date.iloc[0]

        if earnings_date is None:
            return True, None, None

        # Convert to date if needed
        if hasattr(earnings_date, 'date'):
            earnings_date = earnings_date.date()

        # Calculate days until earnings
        days_until = (earnings_date - date.today()).days

        is_safe = days_until > buffer_days or days_until < -2  # Past earnings by 2+ days is fine

        return is_safe, earnings_date, days_until

    except Exception as e:
        # If we can't get earnings data, assume it's safe
        return True, None, None


def get_max_buy_price(pivot_price: float) -> float:
    """
    Calculate maximum price we should pay (don't chase extended breakouts).

    Args:
        pivot_price: The pivot/resistance level

    Returns:
        Maximum buy price (pivot + max chase %)
    """
    return round(pivot_price * (1 + config.MAX_CHASE_PCT), 2)


def _generate_breakout_notes(
    above_pivot: bool,
    vol_confirmed: bool,
    breakout_pct: float,
    max_chase: float
) -> str:
    """Generate notes about breakout quality."""
    if above_pivot and vol_confirmed and breakout_pct < max_chase:
        return f"Valid breakout +{breakout_pct:.1f}% with {vol_confirmed}x volume"

    issues = []
    if not above_pivot:
        issues.append("below pivot")
    if not vol_confirmed:
        issues.append("volume not confirmed")
    if breakout_pct >= max_chase:
        issues.append(f"too extended (+{breakout_pct:.1f}%)")

    return "No breakout: " + ", ".join(issues) if issues else "Watching"


def _empty_breakout(ticker: str, pivot: float, reason: str) -> BreakoutSignal:
    """Return empty breakout signal."""
    return BreakoutSignal(
        ticker=ticker,
        check_date=date.today(),
        is_breakout=False,
        pivot_price=pivot,
        current_price=0,
        breakout_pct=0,
        volume_today=0,
        avg_volume=0,
        volume_ratio=0,
        volume_confirmed=False,
        suggested_entry=0,
        suggested_stop=0,
        suggested_target=0,
        risk_reward_ratio=0,
        shares_for_risk=0,
        position_value=0,
        notes=reason
    )


def add_to_watchlist(
    ticker: str,
    pivot_price: float,
    trend_score: int = 0,
    fundamental_score: int = 0,
    pattern_score: int = 0,
    rs_rating: float = 0,
    notes: str = ""
) -> int:
    """
    Add a stock to the breakout watchlist.

    Args:
        ticker: Stock symbol
        pivot_price: Breakout level to watch
        trend_score: Trend template score
        fundamental_score: Fundamentals score
        pattern_score: VCP pattern score
        rs_rating: Relative strength rating
        notes: Optional notes

    Returns:
        Watchlist entry ID
    """
    stop_price = pivot_price * (1 - config.V2_DEFAULT_STOP_PCT)
    target_price = pivot_price * (1 + config.V2_DEFAULT_TARGET_PCT)
    max_buy_price = get_max_buy_price(pivot_price)
    total_score = trend_score + fundamental_score + pattern_score + int(rs_rating)
    expiration_date = date.today() + timedelta(days=config.WATCHLIST_EXPIRY_DAYS)

    with get_db() as conn:
        cursor = conn.execute("""
            INSERT INTO watchlist
            (ticker, added_date, pivot_price, stop_price, target_price, max_buy_price,
             trend_score, fundamental_score, pattern_score, rs_rating, total_score,
             status, expiration_date, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'WATCHING', ?, ?)
        """, (
            ticker,
            date.today().isoformat(),
            pivot_price,
            stop_price,
            target_price,
            max_buy_price,
            trend_score,
            fundamental_score,
            pattern_score,
            rs_rating,
            total_score,
            expiration_date.isoformat(),
            notes
        ))
        return cursor.lastrowid


def get_watchlist(status: str = 'WATCHING') -> list:
    """
    Get current watchlist entries.

    Args:
        status: Filter by status (WATCHING, TRIGGERED, EXPIRED, etc.)

    Returns:
        List of watchlist entries as dicts
    """
    with get_db() as conn:
        cursor = conn.execute("""
            SELECT * FROM watchlist
            WHERE status = ?
            ORDER BY total_score DESC
        """, (status,))
        return [dict(row) for row in cursor.fetchall()]


def expire_old_watchlist_entries() -> int:
    """
    Mark watchlist entries as expired if past expiration date.

    Returns:
        Number of entries expired
    """
    with get_db() as conn:
        cursor = conn.execute("""
            UPDATE watchlist
            SET status = 'EXPIRED'
            WHERE status = 'WATCHING' AND expiration_date < ?
        """, (date.today().isoformat(),))
        return cursor.rowcount


if __name__ == "__main__":
    # Test with sample data
    print("Testing Breakout Detection")
    print("=" * 50)

    # Test breakout check
    test_cases = [
        ('NVDA', 140.0),  # Example pivot
        ('AAPL', 190.0),
        ('MSFT', 420.0),
    ]

    for ticker, pivot in test_cases:
        try:
            signal = check_breakout(ticker, pivot)
            status = "✓ BREAKOUT" if signal.is_breakout else "✗ No breakout"
            print(f"\n{ticker} (Pivot: ${pivot}):")
            print(f"  Status: {status}")
            print(f"  Current: ${signal.current_price:.2f} ({signal.breakout_pct:+.1f}%)")
            print(f"  Volume: {signal.volume_ratio:.1f}x avg ({'confirmed' if signal.volume_confirmed else 'not confirmed'})")
            if signal.is_breakout:
                print(f"  Entry: ${signal.suggested_entry:.2f}")
                print(f"  Stop: ${signal.suggested_stop:.2f}")
                print(f"  Target: ${signal.suggested_target:.2f}")
                print(f"  R:R = {signal.risk_reward_ratio:.1f}")
                print(f"  Shares: {signal.shares_for_risk} (${signal.position_value:,.0f})")
            print(f"  Notes: {signal.notes}")

            # Check earnings
            is_safe, earnings_date, days_until = is_earnings_safe(ticker)
            if earnings_date:
                safety = "SAFE" if is_safe else "AVOID"
                print(f"  Earnings: {earnings_date} ({days_until} days) - {safety}")

        except Exception as e:
            print(f"\n{ticker}: ERROR - {e}")
