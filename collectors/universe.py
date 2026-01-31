"""
Stock Universe Management

Maintains the list of stocks to screen for V2.
Filters by price, market cap, and volume.
"""

import time
from typing import List, Dict, Optional, Tuple
from datetime import date
import yfinance as yf
import pandas as pd

# S&P 500 tickers from Wikipedia
SP500_URL = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"


def get_sp500_tickers() -> List[str]:
    """Fetch current S&P 500 constituents from Wikipedia."""
    try:
        tables = pd.read_html(SP500_URL)
        df = tables[0]
        # Handle tickers with dots (e.g., BRK.B -> BRK-B for yfinance)
        tickers = df['Symbol'].str.replace('.', '-', regex=False).tolist()
        return tickers
    except Exception as e:
        print(f"Error fetching S&P 500 list: {e}")
        return _get_fallback_tickers()


def get_nasdaq100_tickers() -> List[str]:
    """Get NASDAQ-100 components."""
    # These rarely change, so hardcoded is fine
    return [
        'AAPL', 'MSFT', 'AMZN', 'NVDA', 'META', 'GOOGL', 'GOOG', 'TSLA', 'AVGO', 'COST',
        'ASML', 'PEP', 'AZN', 'CSCO', 'ADBE', 'NFLX', 'AMD', 'TMUS', 'LIN', 'TXN',
        'QCOM', 'INTU', 'CMCSA', 'AMGN', 'PDD', 'HON', 'AMAT', 'ISRG', 'BKNG', 'VRTX',
        'SBUX', 'ADP', 'LRCX', 'GILD', 'MU', 'ADI', 'MDLZ', 'PANW', 'REGN', 'KLAC',
        'SNPS', 'CDNS', 'MELI', 'PYPL', 'MAR', 'ABNB', 'CSX', 'ORLY', 'CTAS', 'NXPI',
        'CRWD', 'MRVL', 'PCAR', 'WDAY', 'MNST', 'ROP', 'FTNT', 'ADSK', 'DXCM', 'CPRT',
        'PAYX', 'MCHP', 'ROST', 'ODFL', 'AEP', 'KDP', 'KHC', 'FAST', 'IDXX', 'LULU',
        'EXC', 'CTSH', 'VRSK', 'CHTR', 'EA', 'GEHC', 'CSGP', 'BKR', 'FANG', 'XEL',
        'DDOG', 'CCEP', 'TTD', 'ANSS', 'CDW', 'ON', 'ZS', 'BIIB', 'GFS', 'TEAM',
        'ILMN', 'WBD', 'MDB', 'SPLK', 'SIRI', 'ALGN', 'ENPH', 'DLTR', 'LCID', 'RIVN',
    ]


def get_combined_universe() -> List[str]:
    """Get combined S&P 500 + NASDAQ-100 universe (deduplicated)."""
    sp500 = set(get_sp500_tickers())
    nasdaq100 = set(get_nasdaq100_tickers())
    combined = sp500.union(nasdaq100)
    return sorted(list(combined))


def filter_universe(
    tickers: List[str],
    min_price: float = 10.0,
    min_market_cap: float = 500_000_000,
    min_volume: int = 500_000,
    verbose: bool = True
) -> Tuple[List[str], Dict[str, str]]:
    """
    Filter tickers by quality criteria.
    
    Args:
        tickers: List of ticker symbols
        min_price: Minimum stock price
        min_market_cap: Minimum market cap in dollars
        min_volume: Minimum average daily volume
        verbose: Print progress
    
    Returns:
        Tuple of (valid_tickers, rejected_reasons)
    """
    valid = []
    rejected = {}
    
    for i, ticker in enumerate(tickers):
        if verbose and (i + 1) % 50 == 0:
            print(f"  Filtering: {i + 1}/{len(tickers)}...")
        
        try:
            stock = yf.Ticker(ticker)
            info = stock.info
            
            # Check price
            price = info.get('regularMarketPrice') or info.get('currentPrice') or info.get('previousClose', 0)
            if price < min_price:
                rejected[ticker] = f"Price ${price:.2f} < ${min_price}"
                continue
            
            # Check market cap
            market_cap = info.get('marketCap', 0)
            if market_cap < min_market_cap:
                rejected[ticker] = f"Market cap ${market_cap/1e9:.1f}B < ${min_market_cap/1e9:.1f}B"
                continue
            
            # Check volume
            avg_volume = info.get('averageVolume', 0)
            if avg_volume < min_volume:
                rejected[ticker] = f"Volume {avg_volume:,} < {min_volume:,}"
                continue
            
            valid.append(ticker)
            
            # Rate limit to avoid API issues
            time.sleep(0.1)
            
        except Exception as e:
            rejected[ticker] = f"Error: {str(e)[:50]}"
            continue
    
    return valid, rejected


def get_stock_info(ticker: str) -> Optional[Dict]:
    """Get basic info for a single stock."""
    try:
        stock = yf.Ticker(ticker)
        info = stock.info
        
        return {
            'ticker': ticker,
            'name': info.get('shortName', ''),
            'sector': info.get('sector', ''),
            'industry': info.get('industry', ''),
            'price': info.get('regularMarketPrice') or info.get('currentPrice', 0),
            'market_cap': info.get('marketCap', 0),
            'avg_volume': info.get('averageVolume', 0),
            'pe_ratio': info.get('trailingPE'),
            'forward_pe': info.get('forwardPE'),
            'beta': info.get('beta'),
        }
    except Exception as e:
        print(f"Error getting info for {ticker}: {e}")
        return None


def _get_fallback_tickers() -> List[str]:
    """Hardcoded major tickers as fallback if web scraping fails."""
    return [
        # Mega caps
        'AAPL', 'MSFT', 'GOOGL', 'AMZN', 'NVDA', 'META', 'TSLA', 'BRK-B',
        # Financials
        'JPM', 'V', 'MA', 'BAC', 'WFC', 'GS', 'MS', 'AXP',
        # Healthcare
        'UNH', 'JNJ', 'LLY', 'PFE', 'MRK', 'ABBV', 'TMO', 'ABT',
        # Consumer
        'PG', 'KO', 'PEP', 'COST', 'WMT', 'HD', 'MCD', 'NKE',
        # Tech
        'AVGO', 'CSCO', 'ORCL', 'CRM', 'ACN', 'ADBE', 'AMD', 'INTC',
        # Industrial
        'CAT', 'UPS', 'RTX', 'HON', 'BA', 'GE', 'MMM', 'DE',
        # Energy
        'XOM', 'CVX', 'COP', 'SLB', 'EOG', 'OXY', 'PSX', 'VLO',
        # Comm Services
        'DIS', 'NFLX', 'CMCSA', 'VZ', 'T', 'TMUS', 'CHTR',
        # Other
        'NEE', 'SO', 'DUK', 'PM', 'MO', 'LMT', 'NOC', 'GD',
    ]


# Quick test
if __name__ == "__main__":
    print("Fetching S&P 500 tickers...")
    sp500 = get_sp500_tickers()
    print(f"Found {len(sp500)} S&P 500 stocks")
    print(f"First 10: {sp500[:10]}")
    
    print("\nTesting filter on first 20 stocks...")
    valid, rejected = filter_universe(sp500[:20], verbose=True)
    print(f"\nValid: {len(valid)}")
    print(f"Rejected: {len(rejected)}")
    for ticker, reason in list(rejected.items())[:5]:
        print(f"  {ticker}: {reason}")
