"""
Breakout Detection

Identifies when a stock breaks out above its pivot point
with volume confirmation.

Key requirements for valid breakout:
1. Price crosses above pivot price
2. Volume >= 1.5x average (confirmation)
3. Price not extended (< 5% above pivot ideally)
4. Not near earnings
"""

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Optional, Dict, List, Tuple
import yfinance as yf
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from utils.db import get_db
from utils.config import config


@dataclass
class BreakoutSignal:
    """Result of breakout analysis."""
    ticker: str
    analysis_date: date
    is_breakout: bool
    
    # Price action
    pivot_price: float
    current_price: float
    breakout_pct: float  # How far above pivot
    
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
    position_size_shares: int  # Based on 2% risk
    
    # Risk factors
    is_extended: bool  # > 5% above pivot
    near_earnings: bool
    
    # Quality
    breakout_quality: str  # "A", "B", "C", "F"
    notes: str
    
    def to_dict(self) -> Dict:
        return {
            'ticker': self.ticker,
            'date': self.analysis_date.isoformat(),
            'is_breakout': self.is_breakout,
            'pivot_price': self.pivot_price,
            'current_price': self.current_price,
            'breakout_pct': self.breakout_pct,
            'volume_ratio': self.volume_ratio,
            'volume_confirmed': self.volume_confirmed,
            'suggested_entry': self.suggested_entry,
            'suggested_stop': self.suggested_stop,
            'suggested_target': self.suggested_target,
            'risk_reward_ratio': self.risk_reward_ratio,
            'breakout_quality': self.breakout_quality,
        }


def check_breakout(
    ticker: str,
    pivot_price: float,
    volume_multiplier: float = None,
    portfolio_value: float = None
) -> BreakoutSignal:
    """
    Check if stock is breaking out above pivot.
    
    Args:
        ticker: Stock symbol
        pivot_price: Resistance level to break
        volume_multiplier: Required volume vs average (default from config)
        portfolio_value: For position sizing (default from config)
    
    Returns:
        BreakoutSignal with analysis
    """
    if volume_multiplier is None:
        volume_multiplier = config.VOLUME_BREAKOUT_MULTIPLIER
    if portfolio_value is None:
        portfolio_value = config.V2_PORTFOLIO_SIZE
    
    try:
        stock = yf.Ticker(ticker)
        hist = stock.history(period="60d")
        
        if len(hist) < 20:
            return _empty_breakout(ticker, pivot_price, "Insufficient data")
        
        # Current price and volume
        current_price = float(hist['Close'].iloc[-1])
        volume_today = int(hist['Volume'].iloc[-1])
        avg_volume = int(hist['Volume'].tail(20).mean())
        
        # Check breakout conditions
        is_above_pivot = current_price > pivot_price
        breakout_pct = ((current_price - pivot_price) / pivot_price) * 100
        
        volume_ratio = volume_today / avg_volume if avg_volume > 0 else 0
        volume_confirmed = volume_ratio >= volume_multiplier
        
        # Check if extended (too far above pivot)
        is_extended = breakout_pct > 5
        
        # Check earnings proximity (simplified - would need real earnings data)
        near_earnings = False  # Will implement with earnings.py
        
        # Determine if valid breakout
        is_breakout = (
            is_above_pivot and
            volume_confirmed and
            not is_extended and
            not near_earnings
        )
        
        # Calculate entry parameters
        entry = current_price
        stop = entry * (1 - config.V2_DEFAULT_STOP_PCT)  # 7% below entry
        target = entry * (1 + config.V2_DEFAULT_TARGET_PCT)  # 20% above entry
        
        risk = entry - stop
        reward = target - entry
        rr_ratio = reward / risk if risk > 0 else 0
        
        # Position sizing (2% risk)
        max_risk = portfolio_value * config.V2_MAX_RISK_PER_TRADE
        position_shares = int(max_risk / risk) if risk > 0 else 0
        
        # Cap at max position size
        max_position = portfolio_value * config.V2_MAX_POSITION_PCT
        max_shares = int(max_position / entry) if entry > 0 else 0
        position_shares = min(position_shares, max_shares)
        
        # Quality grade
        quality = _grade_breakout(
            is_above_pivot, volume_confirmed, is_extended, 
            breakout_pct, volume_ratio, near_earnings
        )
        
        return BreakoutSignal(
            ticker=ticker,
            analysis_date=date.today(),
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
            position_size_shares=position_shares,
            is_extended=is_extended,
            near_earnings=near_earnings,
            breakout_quality=quality,
            notes=_generate_breakout_notes(
                is_above_pivot, volume_confirmed, is_extended, 
                breakout_pct, near_earnings
            ),
        )
        
    except Exception as e:
        return _empty_breakout(ticker, pivot_price, f"Error: {str(e)[:50]}")


def check_breakouts_batch(
    watchlist: List[Dict],
    verbose: bool = True
) -> List[BreakoutSignal]:
    """
    Check breakouts for a list of stocks with pivot prices.
    
    Args:
        watchlist: List of dicts with 'ticker' and 'pivot_price' keys
        verbose: Print progress
    
    Returns:
        List of BreakoutSignals that are valid breakouts
    """
    breakouts = []
    
    for i, item in enumerate(watchlist):
        ticker = item['ticker']
        pivot = item['pivot_price']
        
        if verbose and (i + 1) % 10 == 0:
            print(f"  Checking breakouts: {i + 1}/{len(watchlist)}...")
        
        signal = check_breakout(ticker, pivot)
        
        if signal.is_breakout:
            breakouts.append(signal)
    
    if verbose:
        print(f"\nBreakout check complete: {len(breakouts)} valid breakouts")
    
    return breakouts


def _grade_breakout(
    above_pivot: bool,
    volume_ok: bool,
    extended: bool,
    breakout_pct: float,
    volume_ratio: float,
    near_earnings: bool
) -> str:
    """
    Grade breakout quality A/B/C/F.
    
    A: Perfect setup - above pivot, strong volume, tight, no earnings
    B: Good setup - above pivot, decent volume, slightly extended
    C: Marginal - above pivot but weak volume or too extended
    F: No breakout
    """
    if not above_pivot:
        return "F"
    
    if near_earnings:
        return "F"
    
    score = 0
    
    # Volume confirmation
    if volume_ratio >= 2.0:
        score += 3
    elif volume_ratio >= 1.5:
        score += 2
    elif volume_ratio >= 1.0:
        score += 1
    
    # Extension
    if breakout_pct < 2:
        score += 3
    elif breakout_pct < 5:
        score += 2
    elif breakout_pct < 8:
        score += 1
    
    if score >= 5:
        return "A"
    elif score >= 3:
        return "B"
    elif score >= 1:
        return "C"
    else:
        return "F"


def _empty_breakout(ticker: str, pivot: float, reason: str) -> BreakoutSignal:
    """Return empty breakout signal."""
    return BreakoutSignal(
        ticker=ticker,
        analysis_date=date.today(),
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
        position_size_shares=0,
        is_extended=False,
        near_earnings=False,
        breakout_quality="F",
        notes=reason,
    )


def _generate_breakout_notes(
    above_pivot: bool,
    vol_confirmed: bool,
    extended: bool,
    breakout_pct: float,
    near_earnings: bool
) -> str:
    """Generate notes about breakout quality."""
    if above_pivot and vol_confirmed and not extended and not near_earnings:
        return f"Valid breakout +{breakout_pct:.1f}% with strong volume"
    
    issues = []
    if not above_pivot:
        issues.append("below pivot")
    if not vol_confirmed:
        issues.append("weak volume")
    if extended:
        issues.append(f"extended +{breakout_pct:.1f}%")
    if near_earnings:
        issues.append("near earnings")
    
    if above_pivot and issues:
        return f"Above pivot but: {', '.join(issues)}"
    
    return "No breakout: " + ", ".join(issues)


def get_intraday_breakout_check(ticker: str, pivot_price: float) -> Dict:
    """
    Quick intraday breakout check (for monitoring).
    
    Returns minimal info for quick checks during market hours.
    """
    try:
        stock = yf.Ticker(ticker)
        
        # Get today's data
        hist = stock.history(period="5d")
        if hist.empty:
            return {'error': 'No data'}
        
        current = float(hist['Close'].iloc[-1])
        volume = int(hist['Volume'].iloc[-1])
        avg_vol = int(hist['Volume'].iloc[:-1].mean())
        
        return {
            'ticker': ticker,
            'current_price': round(current, 2),
            'pivot_price': round(pivot_price, 2),
            'above_pivot': current > pivot_price,
            'pct_from_pivot': round((current - pivot_price) / pivot_price * 100, 2),
            'volume_ratio': round(volume / avg_vol, 2) if avg_vol > 0 else 0,
        }
    except Exception as e:
        return {'error': str(e)}


def format_breakout_report(signal: BreakoutSignal) -> str:
    """Format a readable report for a breakout signal."""
    status = f"🚀 BREAKOUT ({signal.breakout_quality})" if signal.is_breakout else "❌ NO BREAKOUT"
    
    lines = [
        f"\n{status} - {signal.ticker}",
        "=" * 50,
        f"",
        f"Price Action:",
        f"  Pivot Price: ${signal.pivot_price:.2f}",
        f"  Current Price: ${signal.current_price:.2f}",
        f"  Breakout: {signal.breakout_pct:+.2f}%",
        f"  Extended: {'⚠️ Yes' if signal.is_extended else '✅ No'}",
        f"",
        f"Volume:",
        f"  Today: {signal.volume_today:,}",
        f"  Average: {signal.avg_volume:,}",
        f"  Ratio: {signal.volume_ratio:.2f}x",
        f"  Confirmed: {'✅ Yes' if signal.volume_confirmed else '❌ No'}",
        f"",
    ]
    
    if signal.is_breakout:
        lines.extend([
            f"Trade Setup:",
            f"  Entry: ${signal.suggested_entry:.2f}",
            f"  Stop: ${signal.suggested_stop:.2f} ({(signal.suggested_stop - signal.suggested_entry) / signal.suggested_entry * 100:.1f}%)",
            f"  Target: ${signal.suggested_target:.2f} ({(signal.suggested_target - signal.suggested_entry) / signal.suggested_entry * 100:.1f}%)",
            f"  Risk/Reward: {signal.risk_reward_ratio:.1f}:1",
            f"  Position Size: {signal.position_size_shares} shares",
            f"",
        ])
    
    lines.append(f"Notes: {signal.notes}")
    
    return "\n".join(lines)


# Quick test
if __name__ == "__main__":
    print("Testing Breakout Detection")
    print("=" * 50)
    
    # Test with some stocks and arbitrary pivot prices
    test_cases = [
        ('AAPL', 180.0),
        ('NVDA', 130.0),
        ('MSFT', 400.0),
    ]
    
    for ticker, pivot in test_cases:
        signal = check_breakout(ticker, pivot)
        print(format_breakout_report(signal))
