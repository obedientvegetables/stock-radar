"""
Stock Universe Management

Maintains the list of stocks to screen.
Filters by price, market cap, and volume.
"""

import sys
from pathlib import Path
from typing import List, Dict, Optional
from datetime import date

import pandas as pd
import yfinance as yf

sys.path.insert(0, str(Path(__file__).parent.parent))
from utils.config import config
from utils.db import get_db


# Wikipedia URL for S&P 500 constituents
SP500_URL = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"


def get_sp500_tickers() -> List[str]:
    """
    Fetch current S&P 500 constituents from Wikipedia.

    Returns list of ticker symbols with dots replaced by dashes
    (e.g., BRK.B -> BRK-B for yfinance compatibility).
    """
    try:
        tables = pd.read_html(SP500_URL)
        df = tables[0]
        # Replace dots with dashes for yfinance compatibility
        tickers = df['Symbol'].str.replace('.', '-', regex=False).tolist()
        return tickers
    except Exception as e:
        print(f"Error fetching S&P 500 from Wikipedia: {e}")
        return _get_fallback_tickers()


def filter_universe(
    tickers: List[str],
    min_price: float = None,
    min_market_cap: float = None,
    min_volume: int = None,
    verbose: bool = False
) -> List[Dict]:
    """
    Filter tickers by quality criteria.

    Args:
        tickers: List of ticker symbols to filter
        min_price: Minimum stock price (default from config)
        min_market_cap: Minimum market cap (default from config)
        min_volume: Minimum average volume (default from config)
        verbose: Print progress during filtering

    Returns:
        List of dicts with ticker info that passes all filters
    """
    min_price = min_price or config.MIN_STOCK_PRICE
    min_market_cap = min_market_cap or config.MIN_MARKET_CAP
    min_volume = min_volume or config.MIN_AVG_VOLUME

    valid = []

    for i, ticker in enumerate(tickers):
        if verbose and i % 10 == 0:
            print(f"  Checking {i+1}/{len(tickers)}...")

        try:
            stock = yf.Ticker(ticker)
            info = stock.info

            # Get price (try multiple fields)
            price = (
                info.get('regularMarketPrice') or
                info.get('currentPrice') or
                info.get('previousClose') or
                0
            )
            if price < min_price:
                continue

            # Get market cap
            market_cap = info.get('marketCap', 0) or 0
            if market_cap < min_market_cap:
                continue

            # Get average volume
            avg_volume = info.get('averageVolume', 0) or 0
            if avg_volume < min_volume:
                continue

            valid.append({
                'ticker': ticker,
                'company_name': info.get('shortName', ''),
                'sector': info.get('sector', ''),
                'industry': info.get('industry', ''),
                'price': price,
                'market_cap': market_cap,
                'avg_volume': avg_volume,
            })

        except Exception as e:
            if verbose:
                print(f"  Error checking {ticker}: {e}")
            continue

    return valid


def update_universe_db(stocks: List[Dict], source: str = 'sp500') -> int:
    """
    Update the stock_universe table with filtered stocks.

    Args:
        stocks: List of stock dicts from filter_universe()
        source: Source of the universe ('sp500', 'russell1000', etc.)

    Returns:
        Number of stocks inserted/updated
    """
    today = date.today().isoformat()
    count = 0

    with get_db() as conn:
        for stock in stocks:
            conn.execute("""
                INSERT INTO stock_universe
                (ticker, company_name, sector, industry, market_cap, avg_volume, price,
                 in_sp500, passes_liquidity, last_screened, added_date, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(ticker) DO UPDATE SET
                    company_name = excluded.company_name,
                    sector = excluded.sector,
                    industry = excluded.industry,
                    market_cap = excluded.market_cap,
                    avg_volume = excluded.avg_volume,
                    price = excluded.price,
                    in_sp500 = excluded.in_sp500,
                    passes_liquidity = 1,
                    last_screened = excluded.last_screened,
                    updated_at = CURRENT_TIMESTAMP
            """, (
                stock['ticker'],
                stock['company_name'],
                stock['sector'],
                stock['industry'],
                stock['market_cap'],
                stock['avg_volume'],
                stock['price'],
                source == 'sp500',
                today,
                today
            ))
            count += 1

    return count


def get_screened_universe(passes_liquidity: bool = True) -> List[str]:
    """
    Get tickers from database that pass liquidity filters.

    Returns:
        List of ticker symbols
    """
    with get_db() as conn:
        if passes_liquidity:
            cursor = conn.execute(
                "SELECT ticker FROM stock_universe WHERE passes_liquidity = 1 ORDER BY market_cap DESC"
            )
        else:
            cursor = conn.execute(
                "SELECT ticker FROM stock_universe ORDER BY market_cap DESC"
            )
        return [row['ticker'] for row in cursor.fetchall()]


def get_universe_stats() -> Dict:
    """Get statistics about the current universe."""
    with get_db() as conn:
        cursor = conn.execute("""
            SELECT
                COUNT(*) as total,
                SUM(CASE WHEN passes_liquidity = 1 THEN 1 ELSE 0 END) as passes_liquidity,
                SUM(CASE WHEN passes_trend_template = 1 THEN 1 ELSE 0 END) as passes_trend,
                SUM(CASE WHEN in_sp500 = 1 THEN 1 ELSE 0 END) as in_sp500,
                MAX(last_screened) as last_update
            FROM stock_universe
        """)
        row = cursor.fetchone()
        return {
            'total': row['total'] or 0,
            'passes_liquidity': row['passes_liquidity'] or 0,
            'passes_trend_template': row['passes_trend'] or 0,
            'in_sp500': row['in_sp500'] or 0,
            'last_update': row['last_update']
        }


def _get_fallback_tickers() -> List[str]:
    """Hardcoded major tickers as fallback if Wikipedia fails."""
    return [
        # Technology
        'AAPL', 'MSFT', 'GOOGL', 'GOOG', 'AMZN', 'NVDA', 'META', 'TSLA', 'AVGO', 'ORCL',
        'CRM', 'ADBE', 'AMD', 'CSCO', 'INTC', 'TXN', 'QCOM', 'INTU', 'IBM', 'NOW',
        'AMAT', 'MU', 'ADI', 'LRCX', 'SNPS', 'KLAC', 'CDNS', 'MRVL', 'FTNT', 'PANW',

        # Financials
        'BRK-B', 'JPM', 'V', 'MA', 'BAC', 'WFC', 'GS', 'MS', 'SPGI', 'BLK',
        'AXP', 'C', 'SCHW', 'CB', 'MMC', 'PGR', 'AON', 'ICE', 'CME', 'MCO',

        # Healthcare
        'UNH', 'JNJ', 'LLY', 'PFE', 'ABBV', 'MRK', 'TMO', 'ABT', 'DHR', 'BMY',
        'AMGN', 'GILD', 'VRTX', 'ISRG', 'MDT', 'SYK', 'REGN', 'ZTS', 'BSX', 'ELV',

        # Consumer
        'WMT', 'PG', 'KO', 'PEP', 'COST', 'HD', 'MCD', 'NKE', 'SBUX', 'TGT',
        'LOW', 'TJX', 'BKNG', 'MAR', 'CMG', 'YUM', 'ORLY', 'AZO', 'ROST', 'DG',

        # Industrials
        'GE', 'CAT', 'RTX', 'HON', 'UNP', 'BA', 'UPS', 'DE', 'LMT', 'ADP',
        'MMM', 'ITW', 'EMR', 'ETN', 'PH', 'CTAS', 'PCAR', 'CARR', 'GD', 'NSC',

        # Energy
        'XOM', 'CVX', 'COP', 'EOG', 'SLB', 'MPC', 'PSX', 'VLO', 'OXY', 'KMI',

        # Utilities & REITs
        'NEE', 'DUK', 'SO', 'D', 'AEP', 'SRE', 'EXC', 'PEG', 'ED', 'XEL',
        'AMT', 'PLD', 'CCI', 'EQIX', 'PSA', 'SPG', 'O', 'WELL', 'DLR', 'AVB',

        # Communications
        'DIS', 'CMCSA', 'NFLX', 'VZ', 'T', 'TMUS', 'CHTR', 'EA', 'TTWO', 'WBD',

        # Materials
        'LIN', 'APD', 'SHW', 'ECL', 'FCX', 'NEM', 'NUE', 'DOW', 'DD', 'PPG',
    ]


if __name__ == "__main__":
    # Test the module
    print("Fetching S&P 500 tickers...")
    tickers = get_sp500_tickers()
    print(f"Found {len(tickers)} tickers")

    print("\nFiltering by quality criteria...")
    print(f"  Min price: ${config.MIN_STOCK_PRICE}")
    print(f"  Min market cap: ${config.MIN_MARKET_CAP:,.0f}")
    print(f"  Min avg volume: {config.MIN_AVG_VOLUME:,}")

    # Test with first 10 tickers
    filtered = filter_universe(tickers[:10], verbose=True)
    print(f"\nFiltered to {len(filtered)} stocks (from first 10)")

    for stock in filtered[:5]:
        print(f"  {stock['ticker']}: ${stock['price']:.2f}, "
              f"MCap: ${stock['market_cap']/1e9:.1f}B, "
              f"Vol: {stock['avg_volume']:,}")
