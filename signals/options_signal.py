"""
Options Flow Signal Scorer

Scores stocks based on unusual options activity.

SCORING RUBRIC (0-25 points max):
- Call volume 2-3x average: +8 points
- Call volume 3-5x average: +12 points
- Call volume >5x average: +18 points
- Low put/call ratio (<0.5): +4 points
- Near-term expiration focus: +3 points
"""

import json
import logging
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Optional

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from utils.config import config
from utils.db import get_db

logger = logging.getLogger('stock_radar.options')


@dataclass
class OptionsSignal:
    """Result of options signal scoring for a ticker."""
    ticker: str
    score: int  # 0-25
    call_volume: int
    put_volume: int
    call_volume_ratio: float
    put_call_ratio: float
    unusual_calls: bool
    near_term_focus: bool
    details: dict

    def to_db_row(self) -> dict:
        """Convert to database row format."""
        return {
            "options_score": self.score,
            "options_details": json.dumps(self.details),
        }

    @property
    def is_strong(self) -> bool:
        """Check if this is a strong signal (meets minimum threshold)."""
        return self.score >= config.OPTIONS_MIN_SCORE


def get_options_activity(ticker: str, target_date: Optional[date] = None) -> dict:
    """
    Get options activity for a ticker.

    Args:
        ticker: Stock symbol
        target_date: Date to check (default: today)

    Returns:
        Dict with options activity
    """
    if target_date is None:
        target_date = date.today()

    with get_db() as conn:
        cursor = conn.execute(
            """
            SELECT call_volume, put_volume, call_oi, put_oi,
                   avg_call_volume_20d, avg_put_volume_20d,
                   call_volume_ratio, put_call_ratio,
                   unusual_calls, unusual_puts
            FROM options_flow
            WHERE ticker = ? AND date = ?
            """,
            (ticker.upper(), target_date.isoformat())
        )
        row = cursor.fetchone()

    if not row:
        return {
            "has_data": False,
            "call_volume": 0,
            "put_volume": 0,
            "call_volume_ratio": 0,
            "put_call_ratio": 0,
            "unusual_calls": False,
            "unusual_puts": False,
        }

    return {
        "has_data": True,
        "call_volume": row["call_volume"],
        "put_volume": row["put_volume"],
        "call_oi": row["call_oi"],
        "put_oi": row["put_oi"],
        "avg_call_volume_20d": row["avg_call_volume_20d"],
        "avg_put_volume_20d": row["avg_put_volume_20d"],
        "call_volume_ratio": row["call_volume_ratio"],
        "put_call_ratio": row["put_call_ratio"],
        "unusual_calls": bool(row["unusual_calls"]),
        "unusual_puts": bool(row["unusual_puts"]),
    }


def score_options(ticker: str, target_date: Optional[date] = None) -> OptionsSignal:
    """
    Score a stock based on options activity.

    SCORING RUBRIC (0-25 points max):
    - Call volume 2-3x average: +8 points
    - Call volume 3-5x average: +12 points
    - Call volume >5x average: +18 points
    - Low put/call ratio (<0.5): +4 points
    - Near-term expiration focus: +3 points (not yet implemented)

    Args:
        ticker: Stock symbol
        target_date: Date to score (default: today)

    Returns:
        OptionsSignal with score and details
    """
    activity = get_options_activity(ticker, target_date)

    # No data = no signal
    if not activity["has_data"]:
        return OptionsSignal(
            ticker=ticker,
            score=0,
            call_volume=0,
            put_volume=0,
            call_volume_ratio=0,
            put_call_ratio=0,
            unusual_calls=False,
            near_term_focus=False,
            details={"reason": "No options data available"},
        )

    # Liquidity gate: check if options are liquid enough to trust
    avg_daily_volume = activity.get("avg_call_volume_20d", 0) + activity.get("avg_put_volume_20d", 0)
    total_open_interest = activity.get("call_oi", 0) + activity.get("put_oi", 0)

    if avg_daily_volume < config.MIN_OPTIONS_AVG_VOLUME:
        logger.info(
            f"{ticker}: Options too illiquid (avg volume {avg_daily_volume} "
            f"< {config.MIN_OPTIONS_AVG_VOLUME} minimum)"
        )
        return OptionsSignal(
            ticker=ticker,
            score=0,
            call_volume=activity["call_volume"],
            put_volume=activity["put_volume"],
            call_volume_ratio=activity["call_volume_ratio"],
            put_call_ratio=activity["put_call_ratio"],
            unusual_calls=activity["unusual_calls"],
            near_term_focus=False,
            details={"reason": f"Options too illiquid (avg volume {avg_daily_volume} < {config.MIN_OPTIONS_AVG_VOLUME})"},
        )

    if total_open_interest < config.MIN_OPEN_INTEREST:
        logger.info(
            f"{ticker}: Insufficient open interest ({total_open_interest} "
            f"< {config.MIN_OPEN_INTEREST} minimum)"
        )
        return OptionsSignal(
            ticker=ticker,
            score=0,
            call_volume=activity["call_volume"],
            put_volume=activity["put_volume"],
            call_volume_ratio=activity["call_volume_ratio"],
            put_call_ratio=activity["put_call_ratio"],
            unusual_calls=activity["unusual_calls"],
            near_term_focus=False,
            details={"reason": f"Insufficient open interest ({total_open_interest} < {config.MIN_OPEN_INTEREST})"},
        )

    score = 0
    score_breakdown = []
    call_ratio = activity["call_volume_ratio"]
    pc_ratio = activity["put_call_ratio"]

    # Call volume ratio scoring
    if call_ratio >= 5.0:
        score += 18
        score_breakdown.append(f"+18: Call volume {call_ratio:.1f}x average (>5x)")
    elif call_ratio >= 3.0:
        score += 12
        score_breakdown.append(f"+12: Call volume {call_ratio:.1f}x average (3-5x)")
    elif call_ratio >= 2.0:
        score += 8
        score_breakdown.append(f"+8: Call volume {call_ratio:.1f}x average (2-3x)")

    # Low put/call ratio (bullish)
    if pc_ratio < 0.5 and activity["call_volume"] > 0:
        score += 4
        score_breakdown.append(f"+4: Low put/call ratio ({pc_ratio:.2f})")

    # Near-term focus bonus (would need additional data tracking)
    # For now, just add if unusual calls detected
    near_term_focus = False
    if activity["unusual_calls"] and call_ratio >= 2.0:
        score += 3
        score_breakdown.append("+3: Unusual call activity")
        near_term_focus = True

    # Cap at max score
    score = min(score, config.OPTIONS_MAX_SCORE)

    return OptionsSignal(
        ticker=ticker,
        score=score,
        call_volume=activity["call_volume"],
        put_volume=activity["put_volume"],
        call_volume_ratio=call_ratio,
        put_call_ratio=pc_ratio,
        unusual_calls=activity["unusual_calls"],
        near_term_focus=near_term_focus,
        details={
            "date": (target_date or date.today()).isoformat(),
            "score_breakdown": score_breakdown,
            "avg_call_volume": activity.get("avg_call_volume_20d", 0),
        },
    )


def get_top_options_stocks(min_score: int = 8, limit: int = 20) -> list[OptionsSignal]:
    """
    Get stocks with highest options scores today.

    Args:
        min_score: Minimum score to include
        limit: Maximum results

    Returns:
        List of OptionsSignal sorted by score descending
    """
    today = date.today().isoformat()

    with get_db() as conn:
        cursor = conn.execute(
            """
            SELECT ticker FROM options_flow
            WHERE date = ?
              AND call_volume_ratio >= 1.5
            ORDER BY call_volume_ratio DESC
            LIMIT ?
            """,
            (today, limit * 2)  # Get more than needed, will filter by score
        )
        tickers = [row["ticker"] for row in cursor.fetchall()]

    # Score each ticker
    signals = []
    for ticker in tickers:
        signal = score_options(ticker)
        if signal.score >= min_score:
            signals.append(signal)

    # Sort by score descending
    signals.sort(key=lambda s: s.score, reverse=True)

    return signals[:limit]


def format_signal_report(signal: OptionsSignal) -> str:
    """Format an options signal for display."""
    lines = [
        f"{signal.ticker} - Options Score: {signal.score}/{config.OPTIONS_MAX_SCORE}",
        "-" * 40,
    ]

    if signal.score == 0:
        lines.append("  No significant options activity")
        return "\n".join(lines)

    lines.append(f"  Call volume: {signal.call_volume:,}")
    lines.append(f"  Put volume: {signal.put_volume:,}")
    lines.append(f"  Call ratio: {signal.call_volume_ratio:.1f}x average")
    lines.append(f"  Put/Call: {signal.put_call_ratio:.2f}")
    lines.append(f"  Unusual calls: {'Yes' if signal.unusual_calls else 'No'}")

    if signal.details.get("score_breakdown"):
        lines.append("")
        lines.append("  Score breakdown:")
        for item in signal.details["score_breakdown"]:
            lines.append(f"    {item}")

    return "\n".join(lines)


if __name__ == "__main__":
    print("Testing options signal scoring...")
    print()

    # Test scoring for a ticker
    for ticker in ["AAPL", "NVDA", "TSLA"]:
        signal = score_options(ticker)
        print(format_signal_report(signal))
        print()
