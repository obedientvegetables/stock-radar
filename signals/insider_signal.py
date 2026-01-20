"""
Insider Trading Signal Scorer

Scores stocks based on insider buying activity from SEC Form 4 filings.

================================================================================
VALIDATION RESULTS (January 2026)
================================================================================
Sample: 1,040 insider buying events over 6 months
Key finding: Insider TITLE is more predictive than buy SIZE

OVERALL PERFORMANCE:
- 5-day excess return: +2.9%, win rate 62.2%, p=0.000
- 10-day excess return: +3.5%, win rate 63.7%, p=0.000

BY INSIDER TYPE:
- CEO/CFO: +4.97% excess return, 67% win rate (STRONGEST SIGNAL)
- Other insiders: +2.07% excess return, 60.3% win rate

BY BUY SIZE:
- All size buckets showed similar 2.4% - 3.6% excess returns
- Buy size matters less than insider title
- Large buys (>$1M) had 66.2% win rate vs ~60% for smaller

IMPLICATION: A $200k CEO purchase is a stronger signal than a $2M director purchase.
Weights were adjusted to reflect this: title bonuses increased, size bonuses decreased.
================================================================================

SCORING RUBRIC (0-30 points max):
- Any insider buy in 14 days: +5 points (baseline signal)
- Each additional unique buyer: +4 points (max +8 for 3+ buyers)
- CEO or CFO buying: +12 points (strongest signal - validated)
- Other C-suite (COO, President, CTO): +6 points
- Director buying: +0 bonus (baseline only - weakest signal)
- Buy value > $500k: +2 points (reduced - size matters less)
- Buy value > $1M: +2 more points (reduced - size matters less)
"""

import json
from dataclasses import dataclass, asdict
from datetime import date, timedelta
from typing import Optional

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from utils.config import config
from utils.db import get_db


def classify_insider_title(title: str) -> str:
    """
    Classify an insider title into categories based on validation findings.

    Categories (in order of signal strength based on validation):
    - "CEO/CFO": Chief Executive or Financial officers (+4.97% excess return)
    - "C-Suite": Other C-level executives (COO, CTO, President)
    - "Director": Board directors (weakest signal, +2.07% excess return)
    - "Other": VP, officers, 10% owners, etc.

    Returns the category string.
    """
    if not title:
        return "Other"

    title_upper = title.upper()

    # CEO/CFO detection - strongest signal
    # Handle patterns like "CEO", "Chief Executive", "Principal Executive Officer"
    if any(pattern in title_upper for pattern in [
        "CEO", "CHIEF EXECUTIVE", "PRINCIPAL EXECUTIVE"
    ]):
        return "CEO/CFO"

    if any(pattern in title_upper for pattern in [
        "CFO", "CHIEF FINANCIAL", "PRINCIPAL FINANCIAL"
    ]):
        return "CEO/CFO"

    # Director detection - check BEFORE C-suite to avoid "DIRECTOR" matching "CTO"
    # "Director" without CEO/CFO titles (already caught above)
    if "DIRECTOR" in title_upper:
        return "Director"

    # Other C-suite detection - strong signal
    # COO, CTO, President (but NOT Vice President)
    if any(pattern in title_upper for pattern in [
        "COO", "CHIEF OPERATING",
        "CTO", "CHIEF TECHNOLOGY",
        "CMO", "CHIEF MARKETING",
        "CIO", "CHIEF INFORMATION",
        "CHIEF LEGAL", "GENERAL COUNSEL"
    ]):
        return "C-Suite"

    # President check - but NOT Vice President
    if "PRESIDENT" in title_upper and "VICE" not in title_upper:
        return "C-Suite"

    # Everything else: VPs, officers, 10% owners, etc.
    return "Other"


@dataclass
class InsiderSignal:
    """Result of insider signal scoring for a ticker."""
    ticker: str
    score: int  # 0-30
    num_buyers: int
    total_value: float
    ceo_cfo_buying: bool
    csuite_buying: bool  # COO, President, CTO (non-CEO/CFO C-suite)
    largest_buy: float
    largest_buyer: str
    largest_buyer_title: str
    largest_buyer_type: str  # "CEO/CFO", "C-Suite", "Director", "Other"
    details: dict

    def to_db_row(self) -> dict:
        """Convert to database row format."""
        return {
            "insider_score": self.score,
            "insider_details": json.dumps(self.details),
        }

    @property
    def is_strong(self) -> bool:
        """Check if this is a strong signal (meets minimum threshold)."""
        return self.score >= config.INSIDER_MIN_SCORE


def get_insider_activity(ticker: str, lookback_days: int = 14) -> dict:
    """
    Get insider buying activity for a ticker.

    Args:
        ticker: Stock symbol
        lookback_days: Number of days to look back

    Returns:
        Dict with activity summary
    """
    cutoff = (date.today() - timedelta(days=lookback_days)).isoformat()

    with get_db() as conn:
        # Get individual trades
        cursor = conn.execute(
            """
            SELECT
                insider_name,
                insider_title,
                trade_type,
                shares,
                price_per_share,
                total_value,
                trade_date
            FROM insider_trades
            WHERE ticker = ?
              AND trade_date >= ?
              AND trade_type = 'P'
            ORDER BY total_value DESC
            """,
            (ticker.upper(), cutoff)
        )
        trades = [dict(row) for row in cursor.fetchall()]

    if not trades:
        return {
            "has_buying": False,
            "trades": [],
            "unique_buyers": 0,
            "total_value": 0,
            "ceo_cfo_buying": False,
            "csuite_buying": False,
            "largest_buy": 0,
            "largest_buyer": "",
            "largest_buyer_title": "",
            "largest_buyer_type": "",
        }

    # Calculate metrics
    unique_buyers = set()
    ceo_cfo_buying = False
    csuite_buying = False
    total_value = 0

    for trade in trades:
        unique_buyers.add(trade["insider_name"])
        total_value += trade["total_value"]

        # Classify the insider's title
        title_type = classify_insider_title(trade["insider_title"])
        if title_type == "CEO/CFO":
            ceo_cfo_buying = True
        elif title_type == "C-Suite":
            csuite_buying = True

    largest = trades[0] if trades else {}
    largest_type = classify_insider_title(largest.get("insider_title", ""))

    return {
        "has_buying": True,
        "trades": trades,
        "unique_buyers": len(unique_buyers),
        "buyer_names": list(unique_buyers),
        "total_value": total_value,
        "ceo_cfo_buying": ceo_cfo_buying,
        "csuite_buying": csuite_buying,
        "largest_buy": largest.get("total_value", 0),
        "largest_buyer": largest.get("insider_name", ""),
        "largest_buyer_title": largest.get("insider_title", ""),
        "largest_buyer_type": largest_type,
    }


def score_insider(ticker: str, lookback_days: int = None) -> InsiderSignal:
    """
    Score a stock based on insider buying activity.

    SCORING RUBRIC (0-30 points max) - Updated based on validation:
    - Any insider buy in lookback period: +5 points (baseline)
    - Each additional unique buyer: +4 points (max +8 for 3+ buyers)
    - CEO or CFO buying: +12 points (strongest signal - 67% win rate)
    - Other C-suite (COO, President, CTO): +6 points
    - Director buying: +0 bonus (weakest signal, baseline only)
    - Buy value > $500k: +2 points (reduced - size matters less than title)
    - Buy value > $1M: +2 more points (reduced - size matters less than title)

    Validation showed insider TITLE is more predictive than buy SIZE:
    - CEO/CFO: +4.97% excess return, 67% win rate
    - Others: +2.07% excess return, 60% win rate

    Args:
        ticker: Stock symbol
        lookback_days: Days to look back (default from config)

    Returns:
        InsiderSignal with score and details
    """
    if lookback_days is None:
        lookback_days = config.INSIDER_LOOKBACK_DAYS

    activity = get_insider_activity(ticker, lookback_days)

    # No buying = no signal
    if not activity["has_buying"]:
        return InsiderSignal(
            ticker=ticker,
            score=0,
            num_buyers=0,
            total_value=0,
            ceo_cfo_buying=False,
            csuite_buying=False,
            largest_buy=0,
            largest_buyer="",
            largest_buyer_title="",
            largest_buyer_type="",
            details={"reason": "No insider buying in lookback period"},
        )

    score = 0
    score_breakdown = []

    # Base score: any buying (+5)
    score += 5
    score_breakdown.append("+5: Insider buying detected")

    # Multiple buyers bonus: +4 per extra buyer, max +8 (for 3+ buyers)
    extra_buyers = min(activity["unique_buyers"] - 1, 2)  # Max 2 extra buyers for bonus
    if extra_buyers > 0:
        buyer_bonus = extra_buyers * 4
        score += buyer_bonus
        score_breakdown.append(f"+{buyer_bonus}: {activity['unique_buyers']} unique buyers (clusters are strong)")

    # Title-based bonuses (most important factor per validation)
    if activity["ceo_cfo_buying"]:
        # CEO/CFO: +12 points - strongest signal (+4.97% excess return, 67% win rate)
        score += 12
        score_breakdown.append("+12: CEO/CFO buying (strongest signal)")
    elif activity["csuite_buying"]:
        # Other C-suite: +6 points - strong signal
        score += 6
        score_breakdown.append("+6: C-Suite buying (COO/President/CTO)")
    # Directors get +0 bonus (weakest signal per validation)

    # Value bonuses - reduced weight since title matters more than size
    if activity["total_value"] > 1_000_000:
        score += 4  # +2 for >$500k, +2 more for >$1M
        score_breakdown.append(f"+4: Buy value ${activity['total_value']:,.0f} (>$1M)")
    elif activity["total_value"] > 500_000:
        score += 2
        score_breakdown.append(f"+2: Buy value ${activity['total_value']:,.0f} (>$500k)")

    # Cap at max score
    score = min(score, config.INSIDER_MAX_SCORE)

    return InsiderSignal(
        ticker=ticker,
        score=score,
        num_buyers=activity["unique_buyers"],
        total_value=activity["total_value"],
        ceo_cfo_buying=activity["ceo_cfo_buying"],
        csuite_buying=activity["csuite_buying"],
        largest_buy=activity["largest_buy"],
        largest_buyer=activity["largest_buyer"],
        largest_buyer_title=activity["largest_buyer_title"],
        largest_buyer_type=activity["largest_buyer_type"],
        details={
            "lookback_days": lookback_days,
            "score_breakdown": score_breakdown,
            "buyer_names": activity.get("buyer_names", []),
            "trade_count": len(activity["trades"]),
        },
    )


def get_top_insider_stocks(min_score: int = 10, limit: int = 20) -> list[InsiderSignal]:
    """
    Get stocks with the highest insider buying scores.

    Args:
        min_score: Minimum score to include
        limit: Maximum number of stocks to return

    Returns:
        List of InsiderSignal objects sorted by score descending
    """
    # Get all tickers with recent buying
    cutoff = (date.today() - timedelta(days=config.INSIDER_LOOKBACK_DAYS)).isoformat()

    with get_db() as conn:
        cursor = conn.execute(
            """
            SELECT DISTINCT ticker
            FROM insider_trades
            WHERE trade_type = 'P'
              AND trade_date >= ?
            """,
            (cutoff,)
        )
        tickers = [row["ticker"] for row in cursor.fetchall()]

    # Score each ticker
    signals = []
    for ticker in tickers:
        signal = score_insider(ticker)
        if signal.score >= min_score:
            signals.append(signal)

    # Sort by score descending
    signals.sort(key=lambda s: s.score, reverse=True)

    return signals[:limit]


def format_signal_report(signal: InsiderSignal) -> str:
    """Format an insider signal for display."""
    lines = [
        f"{signal.ticker} - Insider Score: {signal.score}/{config.INSIDER_MAX_SCORE}",
        "-" * 40,
    ]

    if signal.score == 0:
        lines.append("  No insider buying activity")
        return "\n".join(lines)

    # Highlight insider type prominently - this is the most important info
    if signal.ceo_cfo_buying:
        lines.append("  *** CEO/CFO BUYING *** (strongest signal)")
    elif signal.csuite_buying:
        lines.append("  ** C-Suite buying ** (COO/President/CTO)")
    else:
        lines.append("  Insider type: Director/Other")

    lines.append(f"  Unique buyers: {signal.num_buyers}")
    lines.append(f"  Total buy value: ${signal.total_value:,.0f}")

    if signal.largest_buyer:
        # Show the type classification for the largest buyer
        type_label = f" [{signal.largest_buyer_type}]" if signal.largest_buyer_type else ""
        lines.append(f"  Largest buy: ${signal.largest_buy:,.0f}")
        lines.append(f"    by {signal.largest_buyer}")
        lines.append(f"    Title: {signal.largest_buyer_title}{type_label}")

    lines.append("")
    lines.append("  Score breakdown:")
    for item in signal.details.get("score_breakdown", []):
        lines.append(f"    {item}")

    return "\n".join(lines)


if __name__ == "__main__":
    # Test scoring
    print("Top stocks by insider buying score:")
    print("=" * 50)

    signals = get_top_insider_stocks(min_score=5, limit=10)

    if not signals:
        print("No insider buying found. Run the collector first:")
        print("  python3 -m collectors.insider")
    else:
        for signal in signals:
            print()
            print(format_signal_report(signal))
