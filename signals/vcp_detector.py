"""
Volatility Contraction Pattern (VCP) Detector

Identifies stocks forming the VCP pattern (Mark Minervini's setup):
- Multiple contractions in price range
- Each contraction shallower than the last
- Volume drying up during consolidation
- Price near a clear pivot point

A valid VCP has:
1. 2-5 contractions (pullbacks from local highs)
2. Each contraction is shallower than the previous (tightening)
3. Volume is declining (drying up)
4. Base length between 3-10 weeks
5. Maximum base depth <= 35%
"""

import sys
from pathlib import Path
from dataclasses import dataclass
from datetime import date
from typing import List, Optional, Tuple

import numpy as np
import pandas as pd
import yfinance as yf

sys.path.insert(0, str(Path(__file__).parent.parent))
from utils.config import config
from utils.db import get_db


@dataclass
class VCPPattern:
    """Result of VCP pattern detection for a single stock."""
    ticker: str
    check_date: date
    is_valid: bool

    # Base characteristics
    base_start_date: Optional[date]
    base_length_days: int

    # Pattern characteristics
    num_contractions: int
    contractions: List[float]  # Depth of each contraction (%)
    pivot_price: float

    # Volume analysis
    volume_declining: bool
    volume_dry_up_ratio: float  # Current vol / avg vol (lower is better)

    # Quality score
    pattern_score: int  # 0-100
    pattern_stage: str  # FORMING, READY, TRIGGERED, FAILED

    # Context
    notes: str


def detect_vcp(ticker: str, lookback_days: int = 90) -> VCPPattern:
    """
    Detect Volatility Contraction Pattern in price data.

    Args:
        ticker: Stock ticker symbol
        lookback_days: Days of history to analyze

    Returns:
        VCPPattern with analysis results
    """
    stock = yf.Ticker(ticker)
    hist = stock.history(period=f"{lookback_days + 20}d")

    if len(hist) < lookback_days:
        return _empty_vcp(ticker, "Insufficient data")

    # Use last N days
    hist = hist.tail(lookback_days).copy()
    hist.reset_index(inplace=True)

    prices_high = hist['High'].values
    prices_low = hist['Low'].values
    prices_close = hist['Close'].values
    volumes = hist['Volume'].values

    # Find local highs and lows (potential contraction points)
    highs_idx = _find_local_extremes(prices_high, window=5, find_max=True)
    lows_idx = _find_local_extremes(prices_low, window=5, find_max=False)

    # Calculate contractions
    contractions = _calculate_contractions(prices_high, prices_low, highs_idx, lows_idx)

    # Check if contractions are decreasing (tightening)
    is_tightening = _contractions_decreasing(contractions)

    # Find base start (first significant high before contractions)
    if highs_idx:
        base_start_idx = highs_idx[0]
        base_start_date = hist['Date'].iloc[base_start_idx].date() if hasattr(hist['Date'].iloc[base_start_idx], 'date') else None
        base_length = lookback_days - base_start_idx
    else:
        base_start_date = None
        base_start_idx = 0
        base_length = lookback_days

    # Calculate pivot price (resistance level - highest high in recent history)
    pivot = float(prices_high[-20:].max())

    # Analyze volume - check if drying up
    avg_vol = float(volumes.mean())
    recent_vol = float(volumes[-10:].mean())  # Last 10 days
    vol_ratio = recent_vol / avg_vol if avg_vol > 0 else 1.0
    vol_declining = vol_ratio < config.VOLUME_DRY_UP_THRESHOLD

    # Calculate max base depth
    if len(prices_high) > 0:
        base_high = float(prices_high[base_start_idx:].max())
        base_low = float(prices_low[base_start_idx:].min())
        max_depth = ((base_high - base_low) / base_high) * 100 if base_high > 0 else 100
    else:
        max_depth = 100

    # Current price position
    current_price = float(prices_close[-1])
    current_depth = ((pivot - current_price) / pivot) * 100 if pivot > 0 else 0

    # Determine validity
    num_contractions = len(contractions)
    is_valid = (
        config.MIN_CONTRACTIONS <= num_contractions <= config.MAX_CONTRACTIONS and
        is_tightening and
        vol_declining and
        max_depth <= config.MAX_BASE_DEPTH and
        config.MIN_BASE_LENGTH <= base_length <= config.MAX_BASE_LENGTH
    )

    # Determine pattern stage
    if not is_valid:
        stage = 'FAILED'
    elif current_depth < 3:  # Within 3% of pivot
        stage = 'READY'
    else:
        stage = 'FORMING'

    # Score the pattern
    score = _calculate_vcp_score(contractions, vol_ratio, is_tightening, max_depth, current_depth)

    return VCPPattern(
        ticker=ticker,
        check_date=date.today(),
        is_valid=is_valid,
        base_start_date=base_start_date,
        base_length_days=base_length,
        num_contractions=num_contractions,
        contractions=contractions,
        pivot_price=round(pivot, 2),
        volume_declining=vol_declining,
        volume_dry_up_ratio=round(vol_ratio, 2),
        pattern_score=score,
        pattern_stage=stage,
        notes=_generate_notes(is_valid, contractions, vol_declining, is_tightening, max_depth, base_length)
    )


def _find_local_extremes(prices: np.ndarray, window: int = 5, find_max: bool = True) -> List[int]:
    """
    Find indices of local highs or lows.

    Args:
        prices: Array of prices
        window: Window size for local extreme detection
        find_max: True for highs, False for lows

    Returns:
        List of indices where local extremes occur
    """
    extremes = []

    for i in range(window, len(prices) - window):
        window_start = max(0, i - window)
        window_end = min(len(prices), i + window + 1)
        window_slice = prices[window_start:window_end]

        if find_max:
            if prices[i] == window_slice.max():
                extremes.append(i)
        else:
            if prices[i] == window_slice.min():
                extremes.append(i)

    return extremes


def _calculate_contractions(
    highs: np.ndarray,
    lows: np.ndarray,
    high_indices: List[int],
    low_indices: List[int]
) -> List[float]:
    """
    Calculate the depth of each contraction (pullback from high to low).

    A contraction is measured as the % decline from a local high to the
    subsequent local low before price moves back up.
    """
    contractions = []

    # Match each high with the next low
    for high_idx in high_indices:
        # Find the next low after this high
        subsequent_lows = [l for l in low_indices if l > high_idx]
        if not subsequent_lows:
            continue

        low_idx = subsequent_lows[0]
        high_price = highs[high_idx]
        low_price = lows[low_idx]

        if high_price > 0:
            depth = ((high_price - low_price) / high_price) * 100
            # Only count meaningful contractions (> 5%)
            if depth > 5:
                contractions.append(round(depth, 1))

    return contractions


def _contractions_decreasing(contractions: List[float]) -> bool:
    """
    Check if contractions are getting tighter (each shallower than previous).

    Allows for some tolerance - at least 2/3 should be decreasing.
    """
    if len(contractions) < 2:
        return False

    decreasing_count = 0
    for i in range(1, len(contractions)):
        if contractions[i] < contractions[i-1]:
            decreasing_count += 1

    # At least 60% should be decreasing
    return decreasing_count >= len(contractions) * 0.6 - 0.5


def _calculate_vcp_score(
    contractions: List[float],
    vol_ratio: float,
    is_tightening: bool,
    max_depth: float,
    current_depth: float
) -> int:
    """
    Calculate pattern quality score 0-100.

    Scoring:
    - Number of contractions (2-3 ideal): 25 pts
    - Tightening contractions: 25 pts
    - Volume dry-up: 25 pts
    - Tight final position (close to pivot): 25 pts
    """
    score = 0

    # Points for number of contractions (2-3 is ideal)
    if 2 <= len(contractions) <= 3:
        score += 25
    elif len(contractions) == 4:
        score += 20
    elif len(contractions) == 5:
        score += 15
    elif len(contractions) == 1:
        score += 5

    # Points for tightening contractions
    if is_tightening:
        score += 25

    # Points for volume dry-up (lower ratio = better)
    if vol_ratio < 0.4:
        score += 25
    elif vol_ratio < 0.5:
        score += 20
    elif vol_ratio < 0.6:
        score += 15
    elif vol_ratio < 0.8:
        score += 10

    # Points for being close to pivot (tight)
    if current_depth < 3:
        score += 25
    elif current_depth < 5:
        score += 20
    elif current_depth < 10:
        score += 15
    elif current_depth < 15:
        score += 10

    return min(score, 100)


def _generate_notes(
    is_valid: bool,
    contractions: List[float],
    vol_declining: bool,
    is_tightening: bool,
    max_depth: float,
    base_length: int
) -> str:
    """Generate human-readable notes about the pattern."""
    if is_valid:
        tight_str = f"{contractions[-1]:.0f}%" if contractions else "N/A"
        return f"{len(contractions)} contractions, tightening to {tight_str}, volume drying up"

    issues = []
    if len(contractions) < config.MIN_CONTRACTIONS:
        issues.append(f"only {len(contractions)} contractions (need {config.MIN_CONTRACTIONS}+)")
    if len(contractions) > config.MAX_CONTRACTIONS:
        issues.append(f"too many contractions ({len(contractions)})")
    if not is_tightening:
        issues.append("not tightening")
    if not vol_declining:
        issues.append("volume not drying up")
    if max_depth > config.MAX_BASE_DEPTH:
        issues.append(f"base too deep ({max_depth:.0f}%)")
    if base_length < config.MIN_BASE_LENGTH:
        issues.append(f"base too short ({base_length}d)")
    if base_length > config.MAX_BASE_LENGTH:
        issues.append(f"base too long ({base_length}d)")

    return "Invalid: " + ", ".join(issues) if issues else "Unknown issue"


def _empty_vcp(ticker: str, reason: str) -> VCPPattern:
    """Return empty/invalid VCP result."""
    return VCPPattern(
        ticker=ticker,
        check_date=date.today(),
        is_valid=False,
        base_start_date=None,
        base_length_days=0,
        num_contractions=0,
        contractions=[],
        pivot_price=0.0,
        volume_declining=False,
        volume_dry_up_ratio=1.0,
        pattern_score=0,
        pattern_stage='FAILED',
        notes=reason
    )


def save_vcp_to_db(vcp: VCPPattern) -> bool:
    """Save VCP pattern result to database."""
    with get_db() as conn:
        # Get contraction depths for columns
        c1 = vcp.contractions[0] if len(vcp.contractions) > 0 else None
        c2 = vcp.contractions[1] if len(vcp.contractions) > 1 else None
        c3 = vcp.contractions[2] if len(vcp.contractions) > 2 else None
        c4 = vcp.contractions[3] if len(vcp.contractions) > 3 else None
        current = vcp.contractions[-1] if vcp.contractions else None

        conn.execute("""
            INSERT INTO vcp_patterns
            (ticker, date, base_start_date, base_length_days, num_contractions,
             depth_contraction_1, depth_contraction_2, depth_contraction_3, depth_contraction_4,
             current_depth, volume_dry_up, volume_contraction_pct, pivot_price, pivot_high_date,
             pattern_valid, pattern_score, pattern_stage)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(ticker, date) DO UPDATE SET
                base_start_date = excluded.base_start_date,
                base_length_days = excluded.base_length_days,
                num_contractions = excluded.num_contractions,
                depth_contraction_1 = excluded.depth_contraction_1,
                depth_contraction_2 = excluded.depth_contraction_2,
                depth_contraction_3 = excluded.depth_contraction_3,
                depth_contraction_4 = excluded.depth_contraction_4,
                current_depth = excluded.current_depth,
                volume_dry_up = excluded.volume_dry_up,
                volume_contraction_pct = excluded.volume_contraction_pct,
                pivot_price = excluded.pivot_price,
                pattern_valid = excluded.pattern_valid,
                pattern_score = excluded.pattern_score,
                pattern_stage = excluded.pattern_stage
        """, (
            vcp.ticker,
            vcp.check_date.isoformat(),
            vcp.base_start_date.isoformat() if vcp.base_start_date else None,
            vcp.base_length_days,
            vcp.num_contractions,
            c1, c2, c3, c4, current,
            vcp.volume_declining,
            vcp.volume_dry_up_ratio,
            vcp.pivot_price,
            None,  # pivot_high_date - could calculate later
            vcp.is_valid,
            vcp.pattern_score,
            vcp.pattern_stage
        ))

    return True


def scan_for_vcp_patterns(tickers: List[str], verbose: bool = False) -> List[VCPPattern]:
    """
    Scan multiple tickers for VCP patterns.

    Args:
        tickers: List of ticker symbols
        verbose: Print progress

    Returns:
        List of VCPPattern results
    """
    results = []

    for i, ticker in enumerate(tickers):
        if verbose and i % 10 == 0:
            print(f"  Scanning VCP {i+1}/{len(tickers)}...")

        try:
            vcp = detect_vcp(ticker)
            results.append(vcp)
            save_vcp_to_db(vcp)

            if verbose and vcp.is_valid:
                print(f"    ✓ {ticker}: {vcp.pattern_stage}, Score {vcp.pattern_score}, "
                      f"Pivot ${vcp.pivot_price:.2f}")

        except Exception as e:
            if verbose:
                print(f"    ✗ {ticker}: {e}")

    return results


if __name__ == "__main__":
    # Test with a few tickers
    test_tickers = ['AAPL', 'NVDA', 'MSFT', 'AMD', 'TSLA']

    print("Testing VCP Detector")
    print("=" * 50)

    for ticker in test_tickers:
        try:
            vcp = detect_vcp(ticker)
            status = f"✓ {vcp.pattern_stage}" if vcp.is_valid else "✗ Invalid"
            print(f"\n{ticker}: {status}")
            print(f"  Score: {vcp.pattern_score}/100")
            print(f"  Contractions: {vcp.num_contractions} ({vcp.contractions})")
            print(f"  Pivot: ${vcp.pivot_price:.2f}")
            print(f"  Volume ratio: {vcp.volume_dry_up_ratio:.2f}x avg")
            print(f"  Base length: {vcp.base_length_days} days")
            print(f"  Notes: {vcp.notes}")
        except Exception as e:
            print(f"\n{ticker}: ERROR - {e}")
