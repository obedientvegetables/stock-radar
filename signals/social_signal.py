"""
Social Media Signal Scorer

Scores stocks based on social media velocity and sentiment.
This is a CONFIRMATION signal, not primary.

SCORING RUBRIC (0-20 points max):
- Velocity > 100% (mentions doubled): +6 points
- Velocity > 200% (mentions tripled): +10 points
- Sentiment > 0.3 (positive): +4 points
- Bullish ratio > 65%: +3 points
- Cross-platform confirmation: +3 points
"""

import json
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Optional

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from utils.config import config
from utils.db import get_db


@dataclass
class SocialSignal:
    """Result of social signal scoring for a ticker."""
    ticker: str
    score: int  # 0-20
    reddit_mentions: int
    stocktwits_mentions: int
    combined_velocity: float
    avg_sentiment: float
    bullish_ratio: float
    cross_platform: bool
    details: dict

    def to_db_row(self) -> dict:
        """Convert to database row format."""
        return {
            "social_score": self.score,
            "social_details": json.dumps(self.details),
        }

    @property
    def is_strong(self) -> bool:
        """Check if this is a strong signal (meets minimum threshold)."""
        return self.score >= config.SOCIAL_MIN_SCORE


def get_social_activity(ticker: str, target_date: Optional[date] = None) -> dict:
    """
    Get social media activity for a ticker.

    Args:
        ticker: Stock symbol
        target_date: Date to check (default: today)

    Returns:
        Dict with social activity
    """
    if target_date is None:
        target_date = date.today()

    with get_db() as conn:
        cursor = conn.execute(
            """
            SELECT reddit_mentions, reddit_sentiment, reddit_velocity,
                   stocktwits_mentions, stocktwits_sentiment, stocktwits_velocity,
                   combined_velocity, bullish_ratio
            FROM social_metrics
            WHERE ticker = ? AND date = ?
            """,
            (ticker.upper(), target_date.isoformat())
        )
        row = cursor.fetchone()

    if not row:
        return {
            "has_data": False,
            "reddit_mentions": 0,
            "stocktwits_mentions": 0,
            "combined_velocity": 0,
            "avg_sentiment": 0,
            "bullish_ratio": 0.5,
        }

    # Calculate average sentiment
    reddit_sent = row["reddit_sentiment"] or 0
    stocktwits_sent = row["stocktwits_sentiment"] or 0

    if row["reddit_mentions"] > 0 and row["stocktwits_mentions"] > 0:
        avg_sentiment = (reddit_sent + stocktwits_sent) / 2
    elif row["reddit_mentions"] > 0:
        avg_sentiment = reddit_sent
    elif row["stocktwits_mentions"] > 0:
        avg_sentiment = stocktwits_sent
    else:
        avg_sentiment = 0

    return {
        "has_data": True,
        "reddit_mentions": row["reddit_mentions"],
        "reddit_sentiment": reddit_sent,
        "reddit_velocity": row["reddit_velocity"] or 0,
        "stocktwits_mentions": row["stocktwits_mentions"],
        "stocktwits_sentiment": stocktwits_sent,
        "stocktwits_velocity": row["stocktwits_velocity"] or 0,
        "combined_velocity": row["combined_velocity"] or 0,
        "avg_sentiment": avg_sentiment,
        "bullish_ratio": row["bullish_ratio"] or 0.5,
    }


def score_social(ticker: str, target_date: Optional[date] = None) -> SocialSignal:
    """
    Score a stock based on social media activity.

    SCORING RUBRIC (0-20 points max):
    - Velocity > 100%: +6 points
    - Velocity > 200%: +10 points (replaces +6)
    - Sentiment > 0.3: +4 points
    - Bullish ratio > 65%: +3 points
    - Cross-platform (both Reddit & Stocktwits): +3 points

    Args:
        ticker: Stock symbol
        target_date: Date to score (default: today)

    Returns:
        SocialSignal with score and details
    """
    activity = get_social_activity(ticker, target_date)

    # No data = no signal
    if not activity["has_data"]:
        return SocialSignal(
            ticker=ticker,
            score=0,
            reddit_mentions=0,
            stocktwits_mentions=0,
            combined_velocity=0,
            avg_sentiment=0,
            bullish_ratio=0.5,
            cross_platform=False,
            details={"reason": "No social data available"},
        )

    score = 0
    score_breakdown = []

    velocity = activity["combined_velocity"]
    sentiment = activity["avg_sentiment"]
    bullish = activity["bullish_ratio"]
    reddit = activity["reddit_mentions"]
    stocktwits = activity["stocktwits_mentions"]

    # Velocity scoring
    if velocity >= 200:
        score += 10
        score_breakdown.append(f"+10: Velocity {velocity:.0f}% (>200%)")
    elif velocity >= 100:
        score += 6
        score_breakdown.append(f"+6: Velocity {velocity:.0f}% (>100%)")

    # Sentiment scoring
    if sentiment > 0.3:
        score += 4
        score_breakdown.append(f"+4: Positive sentiment ({sentiment:.2f})")

    # Bullish ratio scoring
    if bullish > 0.65:
        score += 3
        score_breakdown.append(f"+3: High bullish ratio ({bullish:.0%})")

    # Cross-platform confirmation
    cross_platform = reddit > 0 and stocktwits > 0
    if cross_platform:
        score += 3
        score_breakdown.append("+3: Cross-platform confirmation")

    # Cap at max score
    score = min(score, config.SOCIAL_MAX_SCORE)

    return SocialSignal(
        ticker=ticker,
        score=score,
        reddit_mentions=reddit,
        stocktwits_mentions=stocktwits,
        combined_velocity=velocity,
        avg_sentiment=sentiment,
        bullish_ratio=bullish,
        cross_platform=cross_platform,
        details={
            "date": (target_date or date.today()).isoformat(),
            "score_breakdown": score_breakdown,
            "reddit_velocity": activity.get("reddit_velocity", 0),
            "stocktwits_velocity": activity.get("stocktwits_velocity", 0),
        },
    )


def get_top_social_stocks(min_score: int = 6, limit: int = 20) -> list[SocialSignal]:
    """
    Get stocks with highest social scores today.

    Args:
        min_score: Minimum score to include
        limit: Maximum results

    Returns:
        List of SocialSignal sorted by score descending
    """
    today = date.today().isoformat()

    with get_db() as conn:
        cursor = conn.execute(
            """
            SELECT ticker FROM social_metrics
            WHERE date = ?
              AND (reddit_mentions > 0 OR stocktwits_mentions > 0)
            ORDER BY (reddit_mentions + stocktwits_mentions) DESC
            LIMIT ?
            """,
            (today, limit * 2)
        )
        tickers = [row["ticker"] for row in cursor.fetchall()]

    # Score each ticker
    signals = []
    for ticker in tickers:
        signal = score_social(ticker)
        if signal.score >= min_score:
            signals.append(signal)

    # Sort by score descending
    signals.sort(key=lambda s: s.score, reverse=True)

    return signals[:limit]


def format_signal_report(signal: SocialSignal) -> str:
    """Format a social signal for display."""
    lines = [
        f"{signal.ticker} - Social Score: {signal.score}/{config.SOCIAL_MAX_SCORE}",
        "-" * 40,
    ]

    if signal.score == 0:
        lines.append("  No significant social activity")
        return "\n".join(lines)

    lines.append(f"  Reddit mentions: {signal.reddit_mentions}")
    lines.append(f"  Stocktwits mentions: {signal.stocktwits_mentions}")
    lines.append(f"  Combined velocity: {signal.combined_velocity:.0f}%")
    lines.append(f"  Avg sentiment: {signal.avg_sentiment:.2f}")
    lines.append(f"  Bullish ratio: {signal.bullish_ratio:.0%}")
    lines.append(f"  Cross-platform: {'Yes' if signal.cross_platform else 'No'}")

    if signal.details.get("score_breakdown"):
        lines.append("")
        lines.append("  Score breakdown:")
        for item in signal.details["score_breakdown"]:
            lines.append(f"    {item}")

    return "\n".join(lines)


if __name__ == "__main__":
    print("Testing social signal scoring...")
    print()

    # Test scoring for a ticker
    for ticker in ["AAPL", "NVDA", "TSLA", "GME"]:
        signal = score_social(ticker)
        print(format_signal_report(signal))
        print()
