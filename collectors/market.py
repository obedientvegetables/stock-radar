"""
Market Data Collector

Collects price data and calculates technical indicators using yfinance.
Used for:
- Current price for trade entry
- ATR for stop/target calculation
- Historical prices for validation

"""

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Optional
import time

import yfinance as yf
import pandas as pd

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from utils.db import get_db


@dataclass
class MarketSnapshot:
    """Market data for a single ticker."""
    ticker: str
    date: date
    open: float
    high: float
    low: float
    close: float
    volume: int
    atr_14: Optional[float]  # 14-day Average True Range
    sma_20: Optional[float]  # 20-day Simple Moving Average
    sma_50: Optional[float]  # 50-day Simple Moving Average
    rsi_14: Optional[float]  # 14-day RSI
    relative_volume: Optional[float]  # Today's volume vs 20-day avg


def calculate_atr(df: pd.DataFrame, period: int = 14) -> Optional[float]:
    """
    Calculate Average True Range.

    Args:
        df: DataFrame with high, low, close columns
        period: ATR period (default 14)

    Returns:
        ATR value or None if insufficient data
    """
    if len(df) < period + 1:
        return None

    df = df.copy()
    df['prev_close'] = df['Close'].shift(1)
    df['tr1'] = df['High'] - df['Low']
    df['tr2'] = abs(df['High'] - df['prev_close'])
    df['tr3'] = abs(df['Low'] - df['prev_close'])
    df['true_range'] = df[['tr1', 'tr2', 'tr3']].max(axis=1)

    atr = df['true_range'].iloc[-period:].mean()
    return round(atr, 4)


def calculate_rsi(df: pd.DataFrame, period: int = 14) -> Optional[float]:
    """
    Calculate Relative Strength Index.

    Args:
        df: DataFrame with close prices
        period: RSI period (default 14)

    Returns:
        RSI value (0-100) or None if insufficient data
    """
    if len(df) < period + 1:
        return None

    df = df.copy()
    delta = df['Close'].diff()

    gain = delta.where(delta > 0, 0)
    loss = (-delta).where(delta < 0, 0)

    avg_gain = gain.iloc[-period:].mean()
    avg_loss = loss.iloc[-period:].mean()

    if avg_loss == 0:
        return 100.0

    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))

    return round(rsi, 2)


def get_market_data(ticker: str, days: int = 60) -> Optional[MarketSnapshot]:
    """
    Get current market data for a ticker.

    Args:
        ticker: Stock symbol
        days: Days of history for indicator calculation

    Returns:
        MarketSnapshot or None if data unavailable
    """
    try:
        stock = yf.Ticker(ticker)

        # Get historical data
        end_date = datetime.now()
        start_date = end_date - timedelta(days=days + 10)  # Extra buffer for weekends

        df = stock.history(start=start_date, end=end_date)

        if df.empty or len(df) < 5:
            return None

        # Get today's data
        today_data = df.iloc[-1]
        today = df.index[-1].date()

        # Calculate indicators
        atr_14 = calculate_atr(df, period=14)
        rsi_14 = calculate_rsi(df, period=14)

        # Simple moving averages
        sma_20 = round(df['Close'].iloc[-20:].mean(), 2) if len(df) >= 20 else None
        sma_50 = round(df['Close'].iloc[-50:].mean(), 2) if len(df) >= 50 else None

        # Relative volume
        avg_volume_20d = df['Volume'].iloc[-21:-1].mean() if len(df) >= 21 else None
        today_volume = int(today_data['Volume'])
        relative_volume = round(today_volume / avg_volume_20d, 2) if avg_volume_20d and avg_volume_20d > 0 else None

        return MarketSnapshot(
            ticker=ticker.upper(),
            date=today,
            open=round(float(today_data['Open']), 2),
            high=round(float(today_data['High']), 2),
            low=round(float(today_data['Low']), 2),
            close=round(float(today_data['Close']), 2),
            volume=today_volume,
            atr_14=atr_14,
            sma_20=sma_20,
            sma_50=sma_50,
            rsi_14=rsi_14,
            relative_volume=relative_volume,
        )

    except Exception as e:
        print(f"Error getting market data for {ticker}: {e}")
        return None


def get_current_price(ticker: str) -> Optional[float]:
    """
    Get current/latest price for a ticker.

    Args:
        ticker: Stock symbol

    Returns:
        Current price or None
    """
    try:
        stock = yf.Ticker(ticker)
        info = stock.info

        # Try multiple price fields
        price = info.get('regularMarketPrice') or info.get('currentPrice') or info.get('previousClose')

        if price:
            return round(float(price), 2)

        # Fallback: get from history
        hist = stock.history(period='1d')
        if not hist.empty:
            return round(float(hist['Close'].iloc[-1]), 2)

        return None

    except Exception as e:
        print(f"Error getting price for {ticker}: {e}")
        return None


def save_market_data(snapshot: MarketSnapshot) -> bool:
    """Save market data to database."""
    try:
        with get_db() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO market_data
                (ticker, date, open, high, low, close, volume, atr_14, sma_20, sma_50)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    snapshot.ticker,
                    snapshot.date.isoformat(),
                    snapshot.open,
                    snapshot.high,
                    snapshot.low,
                    snapshot.close,
                    snapshot.volume,
                    snapshot.atr_14,
                    snapshot.sma_20,
                    snapshot.sma_50,
                )
            )
        return True
    except Exception as e:
        print(f"Error saving market data for {snapshot.ticker}: {e}")
        return False


def collect_market_data(tickers: list[str], delay: float = 0.2) -> dict:
    """
    Collect market data for a list of tickers.

    Args:
        tickers: List of stock symbols
        delay: Delay between requests

    Returns:
        Dict with collection statistics
    """
    stats = {
        "tickers_requested": len(tickers),
        "tickers_collected": 0,
        "errors": [],
    }

    for i, ticker in enumerate(tickers):
        try:
            snapshot = get_market_data(ticker)

            if snapshot:
                if save_market_data(snapshot):
                    stats["tickers_collected"] += 1

            # Progress indicator
            if (i + 1) % 20 == 0:
                print(f"  Processed {i + 1}/{len(tickers)} tickers...")

            # Rate limiting
            if delay > 0:
                time.sleep(delay)

        except Exception as e:
            stats["errors"].append(f"{ticker}: {str(e)}")

    return stats


def get_price_history(ticker: str, days: int = 30) -> list[dict]:
    """
    Get price history from database.

    Args:
        ticker: Stock symbol
        days: Number of days

    Returns:
        List of price records
    """
    cutoff = (date.today() - timedelta(days=days)).isoformat()

    with get_db() as conn:
        cursor = conn.execute(
            """
            SELECT date, open, high, low, close, volume, atr_14
            FROM market_data
            WHERE ticker = ? AND date >= ?
            ORDER BY date DESC
            """,
            (ticker.upper(), cutoff)
        )
        return [dict(row) for row in cursor.fetchall()]


def get_returns_after_date(ticker: str, signal_date: date, periods: list[int] = [1, 3, 5, 10, 20]) -> dict:
    """
    Calculate returns for specified periods after a signal date.
    Used for validation.

    Args:
        ticker: Stock symbol
        signal_date: Date of the signal
        periods: Days after signal to calculate returns

    Returns:
        Dict with returns for each period
    """
    try:
        stock = yf.Ticker(ticker)

        start = signal_date - timedelta(days=5)  # Buffer
        end = signal_date + timedelta(days=max(periods) + 5)

        df = stock.history(start=start, end=end)

        if df.empty:
            return {}

        # Find the signal date price (or next trading day)
        df.index = df.index.date

        # Get entry price (close on signal date or next available)
        entry_price = None
        for offset in range(5):
            check_date = signal_date + timedelta(days=offset)
            if check_date in df.index:
                entry_price = df.loc[check_date, 'Close']
                break

        if entry_price is None:
            return {}

        returns = {}
        for period in periods:
            target_date = signal_date + timedelta(days=period)

            # Find closest available date
            for offset in range(5):
                check_date = target_date + timedelta(days=offset)
                if check_date in df.index:
                    exit_price = df.loc[check_date, 'Close']
                    returns[f"{period}d"] = round((exit_price / entry_price - 1) * 100, 2)
                    break

        return returns

    except Exception as e:
        print(f"Error calculating returns for {ticker}: {e}")
        return {}


if __name__ == "__main__":
    print("Testing market data collection...")

    # Test single ticker
    print("\nTesting AAPL market data:")
    snapshot = get_market_data("AAPL")
    if snapshot:
        print(f"  Date: {snapshot.date}")
        print(f"  Close: ${snapshot.close}")
        print(f"  Volume: {snapshot.volume:,}")
        print(f"  ATR(14): ${snapshot.atr_14}" if snapshot.atr_14 else "  ATR(14): N/A")
        print(f"  RSI(14): {snapshot.rsi_14}" if snapshot.rsi_14 else "  RSI(14): N/A")
        print(f"  SMA(20): ${snapshot.sma_20}" if snapshot.sma_20 else "  SMA(20): N/A")
        print(f"  Rel Volume: {snapshot.relative_volume}x" if snapshot.relative_volume else "  Rel Volume: N/A")
    else:
        print("  No data available")

    # Test quick price lookup
    print("\nTesting quick price lookup:")
    for ticker in ["AAPL", "MSFT", "NVDA"]:
        price = get_current_price(ticker)
        print(f"  {ticker}: ${price}" if price else f"  {ticker}: N/A")

    # Test collection
    print("\nCollecting market data for test list...")
    test_tickers = ["AAPL", "MSFT", "GOOGL", "AMZN", "NVDA"]
    stats = collect_market_data(test_tickers, delay=0.2)
    print(f"  Collected: {stats['tickers_collected']}/{stats['tickers_requested']}")
