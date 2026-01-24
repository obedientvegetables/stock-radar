"""
Stock Quality Filter

Applies hard filters to reject stocks before scoring.
This prevents penny stocks, illiquid stocks, and micro-caps from entering the system.

QUALITY GATES:
- Minimum price: $5.00 (no penny stocks)
- Minimum market cap: $500M (no micro-caps)
- Minimum average daily volume: 500K shares (no illiquid stocks)
"""

import logging
from typing import Optional

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

try:
    import yfinance as yf
except ImportError:
    yf = None

from utils.config import config

logger = logging.getLogger('stock_radar.quality_filter')


def passes_quality_filter(ticker: str) -> tuple[bool, str]:
    """
    Check if stock meets minimum quality requirements.

    Uses yfinance to fetch current price, market cap, and average volume.
    Returns (passes, reason) tuple.

    Args:
        ticker: Stock symbol

    Returns:
        Tuple of (passes: bool, reason: str)
    """
    try:
        if yf is None:
            return False, "yfinance not installed"
        stock = yf.Ticker(ticker)
        info = stock.info

        if not info or info.get('regularMarketPrice') is None and info.get('currentPrice') is None:
            return False, f"Could not fetch data for {ticker}"

        price = info.get('currentPrice') or info.get('regularMarketPrice', 0)
        market_cap = info.get('marketCap', 0)
        avg_volume = info.get('averageVolume', 0)

        if price < config.MIN_STOCK_PRICE:
            return False, f"Price ${price:.2f} below ${config.MIN_STOCK_PRICE:.2f} minimum"

        if market_cap < config.MIN_MARKET_CAP:
            cap_display = market_cap / 1e6 if market_cap else 0
            return False, f"Market cap ${cap_display:.0f}M below ${config.MIN_MARKET_CAP / 1e6:.0f}M minimum"

        if avg_volume < config.MIN_AVG_VOLUME:
            return False, f"Average volume {avg_volume:,} below {config.MIN_AVG_VOLUME:,} minimum"

        return True, "Passes quality filter"

    except Exception as e:
        return False, f"Could not verify {ticker}: {e}"


def filter_universe(tickers: list[str]) -> tuple[list[str], list[tuple[str, str]]]:
    """
    Filter a list of tickers through quality gates.

    Args:
        tickers: List of ticker symbols to filter

    Returns:
        Tuple of (passed_tickers, rejected_list) where rejected_list
        is a list of (ticker, reason) tuples.
    """
    passed = []
    rejected = []

    for ticker in tickers:
        passes, reason = passes_quality_filter(ticker)
        if passes:
            passed.append(ticker)
            logger.debug(f"PASSED {ticker}: {reason}")
        else:
            rejected.append((ticker, reason))
            logger.info(f"REJECTED {ticker}: {reason}")

    logger.info(
        f"Quality filter: {len(passed)} passed, {len(rejected)} rejected "
        f"out of {len(tickers)} total"
    )

    return passed, rejected
