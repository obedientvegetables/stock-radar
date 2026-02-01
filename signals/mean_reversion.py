"""
Mean Reversion Signal Detector

Identifies oversold stocks that are likely to bounce.
Works best in choppy/sideways markets - uncorrelated with momentum.

Entry criteria:
- RSI(14) < 30 (oversold)
- Price dropped 8%+ in 3 days
- No major news/earnings (avoid falling knives)
- Quality stock (market cap > $10B, profitable)

Exit criteria:
- RSI > 50 (normalized)
- 5% profit target
- 5% stop loss
- 5-day time limit
"""

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import List, Optional, Dict, Tuple
import numpy as np
import yfinance as yf
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from utils.db import get_db
from utils.config import config


@dataclass
class MeanReversionSignal:
    """Result of mean reversion analysis."""
    ticker: str
    date: date
    is_signal: bool
    
    # Price data
    current_price: float
    price_3d_ago: float
    drop_pct: float  # Negative = dropped
    
    # RSI data
    rsi_14: float
    rsi_oversold: bool  # RSI < 30
    
    # Quality filters
    market_cap: float
    is_profitable: bool
    passes_quality: bool
    
    # Earnings check
    earnings_safe: bool
    days_to_earnings: Optional[int]
    
    # Entry parameters
    suggested_entry: float
    suggested_stop: float  # 5% below entry
    suggested_target: float  # 5% above entry
    
    # Signal quality
    signal_score: int  # 0-100
    signal_grade: str  # A, B, C, F
    
    notes: str


# Configuration for mean reversion
MR_CONFIG = {
    'rsi_oversold': 30,
    'rsi_exit': 50,
    'min_drop_pct': 8,  # Minimum 8% drop in 3 days
    'min_market_cap': 10_000_000_000,  # $10B minimum
    'stop_loss_pct': 5,
    'profit_target_pct': 5,
    'max_hold_days': 5,
}


def calculate_rsi(prices: np.ndarray, period: int = 14) -> float:
    """Calculate RSI for the most recent price."""
    if len(prices) < period + 1:
        return 50.0  # Default to neutral
    
    deltas = np.diff(prices)
    gains = np.where(deltas > 0, deltas, 0)
    losses = np.where(deltas < 0, -deltas, 0)
    
    avg_gain = np.mean(gains[-period:])
    avg_loss = np.mean(losses[-period:])
    
    if avg_loss == 0:
        return 100.0
    
    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    
    return round(rsi, 1)


def check_mean_reversion(ticker: str) -> MeanReversionSignal:
    """
    Check if a stock is showing mean reversion buy signal.
    
    Looks for:
    1. RSI < 30 (oversold)
    2. Price dropped 8%+ in last 3 days
    3. Quality stock (large cap, profitable)
    4. Not near earnings
    """
    try:
        stock = yf.Ticker(ticker)
        hist = stock.history(period="30d")
        info = stock.info
        
        if len(hist) < 20:
            return _empty_signal(ticker, "Insufficient price data")
        
        # Current price and 3-day ago price
        current_price = hist['Close'].iloc[-1]
        price_3d_ago = hist['Close'].iloc[-4] if len(hist) >= 4 else current_price
        drop_pct = ((current_price - price_3d_ago) / price_3d_ago) * 100
        
        # Calculate RSI
        prices = hist['Close'].values
        rsi = calculate_rsi(prices)
        rsi_oversold = rsi < MR_CONFIG['rsi_oversold']
        
        # Quality filters
        market_cap = info.get('marketCap', 0) or 0
        is_profitable = (info.get('trailingEps', 0) or 0) > 0
        passes_quality = market_cap >= MR_CONFIG['min_market_cap'] and is_profitable
        
        # Check earnings
        earnings_safe, days_to_earnings = _check_earnings(stock)
        
        # Determine if signal
        drop_significant = drop_pct <= -MR_CONFIG['min_drop_pct']
        is_signal = rsi_oversold and drop_significant and passes_quality and earnings_safe
        
        # Calculate entry parameters
        entry = current_price
        stop = entry * (1 - MR_CONFIG['stop_loss_pct'] / 100)
        target = entry * (1 + MR_CONFIG['profit_target_pct'] / 100)
        
        # Score the signal
        score, grade = _score_signal(rsi, drop_pct, market_cap, is_profitable)
        
        return MeanReversionSignal(
            ticker=ticker,
            date=date.today(),
            is_signal=is_signal,
            current_price=round(current_price, 2),
            price_3d_ago=round(price_3d_ago, 2),
            drop_pct=round(drop_pct, 1),
            rsi_14=rsi,
            rsi_oversold=rsi_oversold,
            market_cap=market_cap,
            is_profitable=is_profitable,
            passes_quality=passes_quality,
            earnings_safe=earnings_safe,
            days_to_earnings=days_to_earnings,
            suggested_entry=round(entry, 2),
            suggested_stop=round(stop, 2),
            suggested_target=round(target, 2),
            signal_score=score,
            signal_grade=grade,
            notes=_generate_notes(rsi_oversold, drop_significant, passes_quality, earnings_safe)
        )
        
    except Exception as e:
        return _empty_signal(ticker, str(e)[:50])


def check_mean_reversion_exit(
    ticker: str, 
    entry_price: float, 
    entry_date: date
) -> Tuple[bool, str, float]:
    """
    Check if a mean reversion position should exit.
    
    Exit conditions:
    1. RSI > 50 (recovered)
    2. 5% profit target
    3. 5% stop loss
    4. 5-day time limit
    
    Returns: (should_exit, reason, current_price)
    """
    try:
        stock = yf.Ticker(ticker)
        hist = stock.history(period="10d")
        
        if len(hist) < 5:
            return False, "", 0
        
        current_price = hist['Close'].iloc[-1]
        prices = hist['Close'].values
        rsi = calculate_rsi(prices)
        
        # Calculate return
        return_pct = ((current_price - entry_price) / entry_price) * 100
        
        # Days held
        days_held = (date.today() - entry_date).days
        
        # Check exit conditions
        if return_pct <= -MR_CONFIG['stop_loss_pct']:
            return True, "STOP", current_price
        
        if return_pct >= MR_CONFIG['profit_target_pct']:
            return True, "TARGET", current_price
        
        if rsi >= MR_CONFIG['rsi_exit']:
            return True, "RSI_RECOVERED", current_price
        
        if days_held >= MR_CONFIG['max_hold_days']:
            return True, "TIME_LIMIT", current_price
        
        return False, "", current_price
        
    except Exception as e:
        return False, f"Error: {e}", 0


def _check_earnings(stock) -> Tuple[bool, Optional[int]]:
    """Check if stock is safe from imminent earnings."""
    try:
        calendar = stock.calendar
        if calendar is None or (hasattr(calendar, 'empty') and calendar.empty):
            return True, None
        
        if 'Earnings Date' in calendar.index:
            earnings_dates = calendar.loc['Earnings Date']
            if isinstance(earnings_dates, (list, np.ndarray)) and len(earnings_dates) > 0:
                next_earnings = earnings_dates[0]
                if hasattr(next_earnings, 'date'):
                    next_earnings = next_earnings.date()
                elif isinstance(next_earnings, str):
                    next_earnings = datetime.strptime(next_earnings, '%Y-%m-%d').date()
                
                days_until = (next_earnings - date.today()).days
                return days_until > 5, days_until
        
        return True, None
    except:
        return True, None


def _score_signal(rsi: float, drop_pct: float, market_cap: float, is_profitable: bool) -> Tuple[int, str]:
    """Score the quality of the mean reversion signal."""
    score = 0
    
    # RSI score (more oversold = better)
    if rsi < 20:
        score += 35
    elif rsi < 25:
        score += 30
    elif rsi < 30:
        score += 20
    
    # Drop magnitude (bigger drop = better bounce potential)
    if drop_pct <= -15:
        score += 30
    elif drop_pct <= -12:
        score += 25
    elif drop_pct <= -10:
        score += 20
    elif drop_pct <= -8:
        score += 15
    
    # Quality bonus
    if market_cap >= 50_000_000_000:  # $50B+
        score += 20
    elif market_cap >= 20_000_000_000:  # $20B+
        score += 15
    elif market_cap >= 10_000_000_000:  # $10B+
        score += 10
    
    if is_profitable:
        score += 15
    
    # Grade
    if score >= 80:
        grade = 'A'
    elif score >= 60:
        grade = 'B'
    elif score >= 40:
        grade = 'C'
    else:
        grade = 'F'
    
    return min(score, 100), grade


def _generate_notes(rsi_oversold: bool, drop_significant: bool, 
                    passes_quality: bool, earnings_safe: bool) -> str:
    """Generate human-readable notes."""
    if rsi_oversold and drop_significant and passes_quality and earnings_safe:
        return "Strong mean reversion setup"
    
    issues = []
    if not rsi_oversold:
        issues.append("RSI not oversold")
    if not drop_significant:
        issues.append("Drop < 8%")
    if not passes_quality:
        issues.append("Fails quality filter")
    if not earnings_safe:
        issues.append("Near earnings")
    
    return "No signal: " + ", ".join(issues)


def _empty_signal(ticker: str, reason: str) -> MeanReversionSignal:
    """Return empty signal for error cases."""
    return MeanReversionSignal(
        ticker=ticker,
        date=date.today(),
        is_signal=False,
        current_price=0,
        price_3d_ago=0,
        drop_pct=0,
        rsi_14=50,
        rsi_oversold=False,
        market_cap=0,
        is_profitable=False,
        passes_quality=False,
        earnings_safe=True,
        days_to_earnings=None,
        suggested_entry=0,
        suggested_stop=0,
        suggested_target=0,
        signal_score=0,
        signal_grade='F',
        notes=f"Error: {reason}"
    )


def scan_for_mean_reversion(tickers: List[str] = None, save_to_db: bool = True) -> List[MeanReversionSignal]:
    """
    Scan multiple tickers for mean reversion signals.
    
    Returns list of signals that passed criteria.
    """
    if tickers is None:
        tickers = get_large_cap_universe()
    
    signals = []
    
    for ticker in tickers:
        try:
            signal = check_mean_reversion(ticker)
            
            if signal.is_signal:
                signals.append(signal)
                print(f"  📉 {ticker}: RSI={signal.rsi_14}, Drop={signal.drop_pct}%, Grade={signal.signal_grade}")
                
                if save_to_db:
                    save_mean_reversion_signal(signal)
            else:
                print(f"  · {ticker}: RSI={signal.rsi_14}, Drop={signal.drop_pct}%")
        except Exception as e:
            print(f"  ✗ {ticker}: {e}")
    
    # Sort by score
    signals.sort(key=lambda x: x.signal_score, reverse=True)
    
    return signals


def save_mean_reversion_signal(signal: MeanReversionSignal):
    """Save mean reversion signal to database."""
    with get_db() as conn:
        conn.execute("""
            INSERT OR REPLACE INTO mean_reversion_signals
            (ticker, date, rsi_14, drop_pct, current_price, 
             suggested_entry, suggested_stop, suggested_target,
             signal_score, signal_grade, is_signal, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            signal.ticker, signal.date.isoformat(), signal.rsi_14,
            signal.drop_pct, signal.current_price,
            signal.suggested_entry, signal.suggested_stop, signal.suggested_target,
            signal.signal_score, signal.signal_grade, signal.is_signal, signal.notes
        ))


def get_active_mr_signals(min_grade: str = 'C') -> List[Dict]:
    """Get active mean reversion signals from database."""
    grade_order = {'A': 4, 'B': 3, 'C': 2, 'F': 1}
    min_grade_val = grade_order.get(min_grade, 2)
    
    with get_db() as conn:
        cursor = conn.execute("""
            SELECT * FROM mean_reversion_signals
            WHERE is_signal = 1
            AND date >= date('now', '-3 days')
            ORDER BY signal_score DESC
        """)
        
        signals = []
        for row in cursor.fetchall():
            row_grade_val = grade_order.get(row['signal_grade'], 0)
            if row_grade_val >= min_grade_val:
                signals.append(dict(row))
        
        return signals


def get_large_cap_universe() -> List[str]:
    """Get list of large cap quality stocks to scan for mean reversion."""
    # Top S&P 500 by market cap - these are stocks where dips are buying opportunities
    return [
        # Tech
        'AAPL', 'MSFT', 'GOOGL', 'AMZN', 'NVDA', 'META', 'TSLA', 'AVGO',
        'ORCL', 'CRM', 'AMD', 'INTC', 'IBM', 'QCOM', 'AMAT', 'ADI',
        # Finance
        'JPM', 'V', 'MA', 'BAC', 'WFC', 'GS', 'MS', 'BLK', 'AXP', 'C',
        # Healthcare
        'UNH', 'JNJ', 'PFE', 'ABBV', 'MRK', 'LLY', 'TMO', 'ABT', 'BMY', 'AMGN',
        # Consumer
        'PG', 'KO', 'PEP', 'WMT', 'COST', 'HD', 'MCD', 'NKE', 'DIS', 'SBUX',
        # Industrial
        'CAT', 'DE', 'HON', 'UPS', 'RTX', 'BA', 'GE', 'MMM', 'UNP', 'FDX',
        # Energy
        'XOM', 'CVX', 'COP', 'SLB', 'EOG',
        # Other
        'NFLX', 'CMCSA', 'T', 'VZ', 'LOW', 'TGT',
    ]


if __name__ == "__main__":
    print("=" * 60)
    print("MEAN REVERSION SCANNER")
    print(f"{date.today()}")
    print("=" * 60)
    print()
    
    tickers = get_large_cap_universe()
    print(f"Scanning {len(tickers)} large cap stocks for oversold bounces...")
    print()
    
    signals = scan_for_mean_reversion(tickers, save_to_db=False)
    
    print()
    print("=" * 60)
    print(f"Found {len(signals)} mean reversion signals")
    print("=" * 60)
    
    if signals:
        print()
        for s in signals[:5]:
            print(f"{s.ticker}")
            print(f"  RSI: {s.rsi_14} | Drop: {s.drop_pct}% | Grade: {s.signal_grade}")
            print(f"  Entry: ${s.suggested_entry} | Stop: ${s.suggested_stop} | Target: ${s.suggested_target}")
            print()
