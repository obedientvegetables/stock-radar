"""
Volatility Contraction Pattern (VCP) Detector

Identifies stocks forming the VCP pattern:
- Multiple contractions in price range
- Each contraction shallower than the last
- Volume drying up during consolidation
- Price forming a tight pivot point

Based on Mark Minervini's pattern recognition from "Trade Like a Stock Market Wizard"
"""

from dataclasses import dataclass
from datetime import date, timedelta
from typing import List, Optional, Dict, Tuple
import yfinance as yf
import pandas as pd
import numpy as np
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from utils.db import get_db
from utils.config import config


@dataclass
class Contraction:
    """A single contraction within a VCP pattern."""
    start_idx: int
    end_idx: int
    high_price: float
    low_price: float
    depth_pct: float  # Pullback depth as percentage


@dataclass
class VCPPattern:
    """Result of VCP pattern detection."""
    ticker: str
    analysis_date: date
    is_valid: bool
    
    # Pattern characteristics
    num_contractions: int
    contractions: List[float]  # Depth of each contraction (%)
    pivot_price: float
    current_price: float
    distance_to_pivot_pct: float
    
    # Volume analysis
    volume_declining: bool
    volume_ratio: float  # Recent vol / avg vol
    
    # Quality metrics
    pattern_score: int  # 0-100
    base_length_days: int
    
    # Context
    notes: str
    
    def to_dict(self) -> Dict:
        return {
            'ticker': self.ticker,
            'date': self.analysis_date.isoformat(),
            'num_contractions': self.num_contractions,
            'depth_contraction_1': self.contractions[0] if len(self.contractions) > 0 else None,
            'depth_contraction_2': self.contractions[1] if len(self.contractions) > 1 else None,
            'depth_contraction_3': self.contractions[2] if len(self.contractions) > 2 else None,
            'current_depth': self.contractions[-1] if self.contractions else None,
            'volume_dry_up': self.volume_declining,
            'volume_ratio': self.volume_ratio,
            'pivot_price': self.pivot_price,
            'pattern_valid': self.is_valid,
            'pattern_score': self.pattern_score,
            'base_length_days': self.base_length_days,
            'notes': self.notes,
        }


def detect_vcp(ticker: str, lookback_days: int = 90) -> VCPPattern:
    """
    Detect Volatility Contraction Pattern in price data.
    
    A valid VCP has:
    1. 2-5 contractions (pullbacks from local highs)
    2. Each contraction is shallower than the previous
    3. Volume is declining (drying up)
    4. Price is forming a tight pivot point
    
    Args:
        ticker: Stock symbol
        lookback_days: Days to analyze for pattern
    
    Returns:
        VCPPattern with detection results
    """
    try:
        stock = yf.Ticker(ticker)
        hist = stock.history(period=f"{lookback_days + 30}d")
        
        if len(hist) < lookback_days:
            return _empty_vcp(ticker, f"Insufficient data: only {len(hist)} days")
        
        # Use last N days
        hist = hist.tail(lookback_days).copy()
        hist.reset_index(drop=True, inplace=True)
        
        # Find the base period (consolidation after an advance)
        base_start, base_data = _find_base_period(hist)
        
        if base_data is None or len(base_data) < 20:
            return _empty_vcp(ticker, "No clear base pattern found")
        
        # Find contractions within the base
        contractions = _find_contractions(base_data)
        
        # Analyze volume
        avg_vol = hist['Volume'].mean()
        recent_vol = hist['Volume'].tail(10).mean()
        vol_ratio = recent_vol / avg_vol if avg_vol > 0 else 1.0
        vol_declining = vol_ratio < 0.8
        
        # Calculate pivot price (resistance level)
        pivot = float(base_data['High'].max())
        current_price = float(hist['Close'].iloc[-1])
        distance_to_pivot = ((pivot - current_price) / current_price) * 100
        
        # Check validity
        contraction_depths = [c.depth_pct for c in contractions]
        is_decreasing = _contractions_decreasing(contraction_depths)
        
        is_valid = (
            len(contractions) >= config.MIN_CONTRACTIONS and
            len(contractions) <= config.MAX_CONTRACTIONS and
            is_decreasing and
            vol_declining and
            (max(contraction_depths) <= config.MAX_BASE_DEPTH if contraction_depths else False) and
            distance_to_pivot < 10  # Within 10% of pivot
        )
        
        # Score the pattern
        score = _calculate_vcp_score(contraction_depths, vol_ratio, is_decreasing, distance_to_pivot)
        
        return VCPPattern(
            ticker=ticker,
            analysis_date=date.today(),
            is_valid=is_valid,
            num_contractions=len(contractions),
            contractions=contraction_depths,
            pivot_price=round(pivot, 2),
            current_price=round(current_price, 2),
            distance_to_pivot_pct=round(distance_to_pivot, 2),
            volume_declining=vol_declining,
            volume_ratio=round(vol_ratio, 2),
            pattern_score=score,
            base_length_days=len(base_data),
            notes=_generate_notes(is_valid, contraction_depths, vol_declining, distance_to_pivot),
        )
        
    except Exception as e:
        return _empty_vcp(ticker, f"Error: {str(e)[:50]}")


def _find_base_period(hist: pd.DataFrame) -> Tuple[int, Optional[pd.DataFrame]]:
    """
    Find the consolidation base period.
    
    Looks for a period where:
    - Price made a significant advance (20%+ gain)
    - Then started consolidating (sideways movement)
    """
    if len(hist) < 30:
        return 0, None
    
    # Find the highest point in the data
    high_idx = hist['High'].idxmax()
    
    # Base starts after the high point
    if high_idx < len(hist) - 20:
        base_start = high_idx
        return base_start, hist.iloc[base_start:].copy()
    
    # Alternative: look for consolidation in recent data
    # Find where volatility started decreasing
    rolling_range = (hist['High'] - hist['Low']) / hist['Close'] * 100
    
    # Find where range started tightening
    for i in range(20, len(hist) - 20):
        recent_range = rolling_range.iloc[i:].mean()
        prior_range = rolling_range.iloc[:i].mean()
        
        if recent_range < prior_range * 0.7:  # Range tightened by 30%+
            return i, hist.iloc[i:].copy()
    
    # Default: use last 60 days as potential base
    base_start = max(0, len(hist) - 60)
    return base_start, hist.iloc[base_start:].copy()


def _find_contractions(base_data: pd.DataFrame) -> List[Contraction]:
    """
    Find contractions (pullbacks) within the base.
    
    A contraction is a pullback from a local high to a local low.
    """
    if len(base_data) < 10:
        return []
    
    highs = base_data['High'].values
    lows = base_data['Low'].values
    
    # Find local highs and lows
    local_highs = _find_local_extremes(highs, is_high=True)
    local_lows = _find_local_extremes(lows, is_high=False)
    
    contractions = []
    
    # Match highs with subsequent lows
    for high_idx in local_highs:
        # Find next low after this high
        next_lows = [l for l in local_lows if l > high_idx]
        if not next_lows:
            continue
        
        low_idx = next_lows[0]
        high_price = highs[high_idx]
        low_price = lows[low_idx]
        
        # Calculate depth
        depth = ((high_price - low_price) / high_price) * 100
        
        if depth >= 3 and depth <= 50:  # Meaningful contraction
            contractions.append(Contraction(
                start_idx=high_idx,
                end_idx=low_idx,
                high_price=high_price,
                low_price=low_price,
                depth_pct=round(depth, 1),
            ))
    
    return contractions[:5]  # Max 5 contractions


def _find_local_extremes(prices: np.ndarray, is_high: bool, window: int = 5) -> List[int]:
    """Find indices of local high or low points."""
    extremes = []
    
    for i in range(window, len(prices) - window):
        if is_high:
            if prices[i] == max(prices[i-window:i+window+1]):
                extremes.append(i)
        else:
            if prices[i] == min(prices[i-window:i+window+1]):
                extremes.append(i)
    
    return extremes


def _contractions_decreasing(depths: List[float]) -> bool:
    """Check if each contraction is shallower than the previous."""
    if len(depths) < 2:
        return len(depths) == 1  # Single contraction is OK
    
    for i in range(1, len(depths)):
        if depths[i] >= depths[i-1]:
            return False
    return True


def _calculate_vcp_score(
    contractions: List[float],
    vol_ratio: float,
    is_decreasing: bool,
    distance_to_pivot: float
) -> int:
    """Calculate pattern quality score 0-100."""
    score = 0
    
    if not contractions:
        return 0
    
    # Points for number of contractions (2-3 is ideal: 30 pts)
    if 2 <= len(contractions) <= 3:
        score += 30
    elif len(contractions) == 4:
        score += 20
    elif len(contractions) >= 1:
        score += 10
    
    # Points for decreasing contractions (25 pts)
    if is_decreasing:
        score += 25
    
    # Points for volume dry-up (25 pts)
    if vol_ratio < 0.5:
        score += 25
    elif vol_ratio < 0.7:
        score += 15
    elif vol_ratio < 0.9:
        score += 5
    
    # Points for tight final contraction (10 pts)
    if contractions[-1] < 10:
        score += 10
    elif contractions[-1] < 15:
        score += 5
    
    # Points for being close to pivot (10 pts)
    if distance_to_pivot < 3:
        score += 10
    elif distance_to_pivot < 5:
        score += 5
    
    return min(score, 100)


def _empty_vcp(ticker: str, reason: str) -> VCPPattern:
    """Return empty/invalid VCP result."""
    return VCPPattern(
        ticker=ticker,
        analysis_date=date.today(),
        is_valid=False,
        num_contractions=0,
        contractions=[],
        pivot_price=0.0,
        current_price=0.0,
        distance_to_pivot_pct=0.0,
        volume_declining=False,
        volume_ratio=1.0,
        pattern_score=0,
        base_length_days=0,
        notes=reason,
    )


def _generate_notes(is_valid: bool, contractions: List[float], vol_declining: bool, distance: float) -> str:
    """Generate human-readable notes about the pattern."""
    if is_valid:
        return f"{len(contractions)} contractions ({', '.join(f'{c:.0f}%' for c in contractions)}), volume drying up, {distance:.1f}% from pivot"
    
    issues = []
    if len(contractions) < 2:
        issues.append(f"only {len(contractions)} contraction(s)")
    if not vol_declining:
        issues.append("volume not declining")
    if not _contractions_decreasing(contractions):
        issues.append("contractions not decreasing")
    if distance >= 10:
        issues.append(f"{distance:.1f}% from pivot")
    
    return "Invalid: " + ", ".join(issues) if issues else "Pattern incomplete"


def save_vcp_pattern(pattern: VCPPattern) -> None:
    """Save VCP pattern to database."""
    d = pattern.to_dict()
    
    with get_db() as conn:
        conn.execute("""
            INSERT OR REPLACE INTO vcp_patterns
            (ticker, date, num_contractions, depth_contraction_1, depth_contraction_2,
             depth_contraction_3, current_depth, volume_dry_up, volume_ratio,
             pivot_price, pattern_valid, pattern_score, base_length_days, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            d['ticker'], d['date'], d['num_contractions'],
            d['depth_contraction_1'], d['depth_contraction_2'], d['depth_contraction_3'],
            d['current_depth'], d['volume_dry_up'], d['volume_ratio'],
            d['pivot_price'], d['pattern_valid'], d['pattern_score'],
            d['base_length_days'], d['notes'],
        ))


def scan_for_vcp_patterns(
    tickers: List[str],
    save_to_db: bool = True,
    verbose: bool = True
) -> List[VCPPattern]:
    """
    Scan multiple stocks for VCP patterns.
    
    Returns list of valid patterns found.
    """
    valid_patterns = []
    
    for i, ticker in enumerate(tickers):
        if verbose and (i + 1) % 25 == 0:
            print(f"  VCP scan: {i + 1}/{len(tickers)}... ({len(valid_patterns)} found)")
        
        pattern = detect_vcp(ticker)
        
        if save_to_db:
            save_vcp_pattern(pattern)
        
        if pattern.is_valid:
            valid_patterns.append(pattern)
    
    if verbose:
        print(f"\nVCP scan complete: {len(valid_patterns)} valid patterns found")
    
    return valid_patterns


def format_vcp_report(pattern: VCPPattern) -> str:
    """Format a readable report for a VCP pattern."""
    status = "✅ VALID VCP" if pattern.is_valid else "❌ NO VCP"
    
    lines = [
        f"\n{status} - {pattern.ticker}",
        "=" * 50,
        f"Pattern Score: {pattern.pattern_score}/100",
        f"",
        f"Contractions: {pattern.num_contractions}",
    ]
    
    for i, depth in enumerate(pattern.contractions, 1):
        lines.append(f"  #{i}: {depth:.1f}% pullback")
    
    lines.extend([
        f"",
        f"Pivot Price: ${pattern.pivot_price:.2f}",
        f"Current Price: ${pattern.current_price:.2f}",
        f"Distance to Pivot: {pattern.distance_to_pivot_pct:.1f}%",
        f"",
        f"Volume Analysis:",
        f"  Volume Ratio: {pattern.volume_ratio:.2f}x average",
        f"  Volume Drying Up: {'✅ Yes' if pattern.volume_declining else '❌ No'}",
        f"",
        f"Base Length: {pattern.base_length_days} days",
        f"",
        f"Notes: {pattern.notes}",
    ])
    
    return "\n".join(lines)


# Quick test
if __name__ == "__main__":
    print("Testing VCP Pattern Detector")
    print("=" * 50)
    
    # Test with some stocks
    test_tickers = ['AAPL', 'MSFT', 'NVDA', 'META', 'GOOGL']
    
    for ticker in test_tickers:
        pattern = detect_vcp(ticker)
        if pattern.pattern_score > 30:
            print(format_vcp_report(pattern))
        else:
            print(f"{ticker}: Score {pattern.pattern_score}/100 - {pattern.notes}")
