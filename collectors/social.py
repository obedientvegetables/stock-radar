"""
Social Media Collector

Collects mention counts and sentiment from Adanos API and Stocktwits.
Focuses on VELOCITY (acceleration in mentions) as the key metric.

Sources:
- Adanos API: Pre-processed Reddit sentiment data (https://api.adanos.org/reddit/stocks/v1)
- Stocktwits: Free API tier (secondary/confirmation source)
"""

import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Optional

import requests

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from utils.config import config
from utils.db import get_db


@dataclass
class SocialSnapshot:
    """Social media metrics for a ticker on a single day."""
    ticker: str
    date: date
    reddit_mentions: int
    reddit_sentiment: float  # -1 to 1
    reddit_velocity: float  # % change from yesterday
    stocktwits_mentions: int
    stocktwits_sentiment: float
    stocktwits_velocity: float
    combined_velocity: float
    bullish_ratio: float


class AdanosAPIClient:
    """Client for the Adanos Reddit Stock Sentiment API."""

    def __init__(self, api_key: str = None):
        self.api_key = api_key or config.ADANOS_API_KEY
        self.base_url = config.ADANOS_API_BASE
        self.session = self._create_session()

    def _create_session(self) -> requests.Session:
        """Create a requests session with auth headers."""
        session = requests.Session()
        session.headers.update({
            "X-API-Key": self.api_key,
            "Accept": "application/json",
            "Content-Type": "application/json",
        })
        return session

    def _request(self, endpoint: str, params: dict = None, retries: int = 3) -> Optional[dict]:
        """Make an authenticated request to the API with retry logic."""
        url = f"{self.base_url}{endpoint}"

        for attempt in range(retries):
            try:
                response = self.session.get(url, params=params, timeout=30)
                response.raise_for_status()
                return response.json()
            except requests.exceptions.HTTPError as e:
                if response.status_code == 401:
                    print("Adanos API authentication failed - check your API key")
                    return None
                elif response.status_code == 429:
                    wait_time = 2 ** attempt * 10  # Exponential backoff: 10s, 20s, 40s
                    print(f"Rate limited - waiting {wait_time}s before retry ({attempt + 1}/{retries})")
                    time.sleep(wait_time)
                    continue
                else:
                    print(f"Adanos API error {response.status_code}: {e}")
                    return None
            except requests.exceptions.RequestException as e:
                print(f"Adanos API request failed: {e}")
                if attempt < retries - 1:
                    time.sleep(2 ** attempt)
                    continue
                return None

        print(f"Failed after {retries} retries: {endpoint}")
        return None

    def get_trending(self, period: str = "24h", limit: int = 100) -> Optional[list]:
        """Get trending stocks ranked by buzz score.

        Args:
            period: Time period - 1h, 6h, 24h, 7d
            limit: Number of results (max 100)

        Returns:
            List of stock data dicts with keys:
            - ticker, buzz_score, trend, mentions, sentiment_score
            - bullish_pct, bearish_pct, company_name, unique_posts, total_upvotes
        """
        data = self._request("/trending", {"period": period, "limit": limit})
        if data is None:
            return None
        # API returns array directly or wrapped in {"stocks": [...]}
        return data if isinstance(data, list) else data.get("stocks", [])

    def get_stock(self, ticker: str) -> Optional[dict]:
        """Get detailed sentiment data for a specific stock."""
        return self._request(f"/stock/{ticker.upper()}")

    def compare(self, tickers: list) -> Optional[list]:
        """Compare sentiment metrics for multiple tickers (up to 10)."""
        return self._request("/compare", {"tickers": ",".join(tickers[:10])})


def fetch_stocktwits_data(ticker: str) -> dict:
    """
    Fetch recent messages for a ticker from Stocktwits.

    Note: Stocktwits API may require authentication.
    If 403/429 errors occur, returns empty data gracefully.

    Args:
        ticker: Stock symbol

    Returns:
        Dict with messages and sentiment data
    """
    url = f"https://api.stocktwits.com/api/2/streams/symbol/{ticker}.json"

    try:
        headers = {"User-Agent": "StockRadar/1.0"}
        response = requests.get(url, headers=headers, timeout=30)

        if response.status_code in (403, 429):
            # API requires auth or rate limited - return empty gracefully
            return {"messages": [], "count": 0, "bullish_ratio": 0.5}

        if response.status_code == 404:
            return {"messages": [], "count": 0, "bullish_ratio": 0.5}

        response.raise_for_status()
        data = response.json()

        messages = []
        bullish_count = 0
        bearish_count = 0

        for msg in data.get("messages", []):
            sentiment = msg.get("entities", {}).get("sentiment", {})
            is_bullish = sentiment.get("basic") == "Bullish"
            is_bearish = sentiment.get("basic") == "Bearish"

            if is_bullish:
                bullish_count += 1
            elif is_bearish:
                bearish_count += 1

            messages.append({
                "body": msg.get("body", ""),
                "created_at": msg.get("created_at", ""),
                "bullish": is_bullish,
                "bearish": is_bearish,
            })

        total_sentiment = bullish_count + bearish_count
        bullish_ratio = bullish_count / total_sentiment if total_sentiment > 0 else 0.5

        return {
            "messages": messages,
            "count": len(messages),
            "bullish_count": bullish_count,
            "bearish_count": bearish_count,
            "bullish_ratio": bullish_ratio,
        }

    except Exception as e:
        # Silently return empty data - Stocktwits is optional
        return {"messages": [], "count": 0, "bullish_ratio": 0.5}


def collect_adanos_data(period: str = "24h") -> dict[str, dict]:
    """
    Collect ticker mentions from Adanos API.

    Args:
        period: Time period - 1h, 6h, 24h, 7d

    Returns:
        Dict mapping ticker to mention data
    """
    client = AdanosAPIClient()

    if not client.api_key:
        print("  Warning: ADANOS_API_KEY not set - skipping Adanos data")
        return {}

    trending = client.get_trending(period=period, limit=100)
    if trending is None:
        print("  Failed to fetch Adanos trending data")
        return {}

    ticker_data = {}
    for stock in trending:
        ticker = stock.get("ticker")
        if not ticker:
            continue

        # Map Adanos API response to our format
        # sentiment_score: -1 to 1
        sentiment = stock.get("sentiment_score", 0)
        mentions = stock.get("mentions", 0)
        buzz_score = stock.get("buzz_score", 0)
        bullish_pct = stock.get("bullish_pct", 50)
        bearish_pct = stock.get("bearish_pct", 50)
        trend = stock.get("trend", "stable")  # rising, falling, stable

        ticker_data[ticker] = {
            "mentions": mentions,
            "avg_sentiment": sentiment,
            "buzz_score": buzz_score,
            "bullish_pct": bullish_pct,
            "bearish_pct": bearish_pct,
            "trend": trend,
            "unique_posts": stock.get("unique_posts", 0),
            "total_upvotes": stock.get("total_upvotes", 0),
        }

    return ticker_data


def get_historical_mentions(ticker: str, days: int = 7) -> dict:
    """Get historical mention data for velocity calculation."""
    cutoff = (date.today() - timedelta(days=days)).isoformat()

    with get_db() as conn:
        cursor = conn.execute(
            """
            SELECT date, reddit_mentions, stocktwits_mentions
            FROM social_metrics
            WHERE ticker = ? AND date >= ?
            ORDER BY date DESC
            """,
            (ticker.upper(), cutoff)
        )
        rows = cursor.fetchall()

    if not rows:
        return {"has_history": False}

    yesterday = rows[0] if rows else None
    avg_mentions = sum(r["reddit_mentions"] + r["stocktwits_mentions"] for r in rows) / len(rows)

    return {
        "has_history": True,
        "yesterday_reddit": yesterday["reddit_mentions"] if yesterday else 0,
        "yesterday_stocktwits": yesterday["stocktwits_mentions"] if yesterday else 0,
        "avg_mentions": avg_mentions,
    }


def calculate_velocity(current: int, previous: int) -> float:
    """Calculate percentage change (velocity)."""
    if previous <= 0:
        return 0.0 if current == 0 else 100.0
    return ((current - previous) / previous) * 100


def save_social_snapshot(snapshot: SocialSnapshot) -> bool:
    """Save social snapshot to database."""
    try:
        with get_db() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO social_metrics
                (ticker, date, reddit_mentions, reddit_sentiment, reddit_velocity,
                 stocktwits_mentions, stocktwits_sentiment, stocktwits_velocity,
                 combined_velocity, bullish_ratio)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    snapshot.ticker,
                    snapshot.date.isoformat(),
                    snapshot.reddit_mentions,
                    snapshot.reddit_sentiment,
                    snapshot.reddit_velocity,
                    snapshot.stocktwits_mentions,
                    snapshot.stocktwits_sentiment,
                    snapshot.stocktwits_velocity,
                    snapshot.combined_velocity,
                    snapshot.bullish_ratio,
                )
            )
        return True
    except Exception as e:
        print(f"Error saving social data for {snapshot.ticker}: {e}")
        return False


def collect_social_data(tickers: list[str] = None, source: str = "all") -> dict:
    """
    Collect social media data for tickers.

    Args:
        tickers: List of tickers to collect (None = use Adanos trending)
        source: Data source - "adanos", "stocktwits", or "all"

    Returns:
        Dict with collection statistics
    """
    stats = {
        "tickers_collected": 0,
        "high_velocity": 0,
        "adanos_tickers": 0,
        "stocktwits_tickers": 0,
        "errors": [],
    }

    today = date.today()

    # Collect Adanos data (Reddit sentiment)
    adanos_data = {}
    if source in ("adanos", "all"):
        print("  Fetching Adanos API data...")
        adanos_data = collect_adanos_data(period="24h")
        stats["adanos_tickers"] = len(adanos_data)
        print(f"  Found {len(adanos_data)} tickers from Adanos API")

    # Determine which tickers to process
    if tickers:
        target_tickers = set(t.upper() for t in tickers)
    else:
        # Use Adanos trending tickers
        target_tickers = set(adanos_data.keys())

    if not target_tickers:
        print("  No tickers to process")
        return stats

    # Process each ticker
    for ticker in sorted(target_tickers):
        try:
            # Adanos/Reddit data
            adanos_info = adanos_data.get(ticker, {})
            reddit_mentions = adanos_info.get("mentions", 0)
            reddit_sentiment = adanos_info.get("avg_sentiment", 0)

            # Adanos provides bullish_pct (0-100), convert to ratio (0-1)
            adanos_bullish_ratio = adanos_info.get("bullish_pct", 50) / 100

            # Stocktwits data (secondary source)
            stocktwits_mentions = 0
            stocktwits_sentiment = 0
            stocktwits_bullish_ratio = 0.5

            if source in ("stocktwits", "all"):
                stocktwits_info = fetch_stocktwits_data(ticker)
                stocktwits_mentions = stocktwits_info.get("count", 0)
                stocktwits_sentiment = (stocktwits_info.get("bullish_ratio", 0.5) - 0.5) * 2  # Convert to -1 to 1
                stocktwits_bullish_ratio = stocktwits_info.get("bullish_ratio", 0.5)
                time.sleep(0.5)  # Rate limit Stocktwits
                if stocktwits_mentions > 0:
                    stats["stocktwits_tickers"] += 1

            # Calculate combined bullish ratio
            if reddit_mentions > 0 and stocktwits_mentions > 0:
                # Weight by mention count
                total = reddit_mentions + stocktwits_mentions
                bullish_ratio = (
                    (adanos_bullish_ratio * reddit_mentions + stocktwits_bullish_ratio * stocktwits_mentions)
                    / total
                )
            elif reddit_mentions > 0:
                bullish_ratio = adanos_bullish_ratio
            elif stocktwits_mentions > 0:
                bullish_ratio = stocktwits_bullish_ratio
            else:
                bullish_ratio = 0.5

            # Get historical data for velocity
            history = get_historical_mentions(ticker, days=7)

            # Calculate velocity
            reddit_velocity = calculate_velocity(
                reddit_mentions,
                history.get("yesterday_reddit", 0)
            )
            stocktwits_velocity = calculate_velocity(
                stocktwits_mentions,
                history.get("yesterday_stocktwits", 0)
            )

            # Combined velocity: weighted average if both have data
            if reddit_velocity > 0 and stocktwits_velocity > 0:
                combined_velocity = (reddit_velocity + stocktwits_velocity) / 2
            elif reddit_velocity > 0:
                combined_velocity = reddit_velocity
            elif stocktwits_velocity > 0:
                combined_velocity = stocktwits_velocity
            else:
                combined_velocity = 0

            snapshot = SocialSnapshot(
                ticker=ticker,
                date=today,
                reddit_mentions=reddit_mentions,
                reddit_sentiment=reddit_sentiment,
                reddit_velocity=reddit_velocity,
                stocktwits_mentions=stocktwits_mentions,
                stocktwits_sentiment=stocktwits_sentiment,
                stocktwits_velocity=stocktwits_velocity,
                combined_velocity=combined_velocity,
                bullish_ratio=bullish_ratio,
            )

            if save_social_snapshot(snapshot):
                stats["tickers_collected"] += 1
                if combined_velocity > 100:
                    stats["high_velocity"] += 1

        except Exception as e:
            stats["errors"].append(f"{ticker}: {str(e)}")

    return stats


def get_trending_tickers(min_mentions: int = 3, limit: int = 20) -> list[dict]:
    """Get tickers with high social activity today."""
    today = date.today().isoformat()

    with get_db() as conn:
        cursor = conn.execute(
            """
            SELECT ticker, reddit_mentions, stocktwits_mentions,
                   reddit_sentiment, combined_velocity, bullish_ratio
            FROM social_metrics
            WHERE date = ?
              AND (reddit_mentions >= ? OR stocktwits_mentions >= ?)
            ORDER BY (reddit_mentions + stocktwits_mentions) DESC
            LIMIT ?
            """,
            (today, min_mentions, min_mentions, limit)
        )
        return [dict(row) for row in cursor.fetchall()]


def get_adanos_trending(period: str = "24h", limit: int = 20) -> list[dict]:
    """Get trending tickers directly from Adanos API (for display purposes)."""
    client = AdanosAPIClient()

    if not client.api_key:
        return []

    trending = client.get_trending(period=period, limit=limit)
    if trending is None:
        return []

    return trending


if __name__ == "__main__":
    print("Testing social media collection...")
    print()

    # Test Adanos collection
    print("Collecting from Adanos API...")
    adanos_data = collect_adanos_data()

    print(f"Found {len(adanos_data)} tickers")
    if adanos_data:
        top_tickers = sorted(adanos_data.items(), key=lambda x: x[1]["mentions"], reverse=True)[:10]
        print("\nTop 10 mentioned tickers (Adanos):")
        for ticker, data in top_tickers:
            print(f"  {ticker}: {data['mentions']} mentions, sentiment: {data['avg_sentiment']:.2f}, buzz: {data['buzz_score']:.1f}")
    else:
        print("  No data - check ADANOS_API_KEY")

    # Test Stocktwits
    print("\nTesting Stocktwits for AAPL...")
    st_data = fetch_stocktwits_data("AAPL")
    print(f"  Messages: {st_data.get('count', 0)}")
    print(f"  Bullish ratio: {st_data.get('bullish_ratio', 0):.2f}")
