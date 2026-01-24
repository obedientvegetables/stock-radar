"""
Signal Combiner and Decision Logic

Combines insider, options, and social signals to make trade decisions.

DECISION RULES:
- TRADE: (insider >= 15 OR options >= 15) AND social >= 10
- WATCH: insider >= 10 OR options >= 10
- NONE: No primary signals

POSITION SIZING:
- total_score >= 60: FULL position
- total_score >= 45: HALF position
- total_score >= 30: QUARTER position
"""

import json
import logging
from dataclasses import dataclass
from datetime import date
from typing import Optional

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from utils.config import config
from utils.db import get_db
from signals.insider_signal import score_insider, InsiderSignal
from signals.options_signal import score_options, OptionsSignal
from signals.social_signal import score_social, SocialSignal
from signals.quality_filter import filter_universe

logger = logging.getLogger('stock_radar.combiner')


@dataclass
class CombinedSignal:
    """Combined signal with all scores and trade decision."""
    ticker: str
    date: date

    # Individual scores
    insider_score: int
    options_score: int
    social_score: int
    total_score: int

    # Individual signals (for details)
    insider_signal: InsiderSignal
    options_signal: OptionsSignal
    social_signal: SocialSignal

    # Decision
    action: str  # 'TRADE', 'WATCH', 'NONE'
    tier: str  # 'A', 'B', 'C'
    position_size: str  # 'FULL', 'HALF', 'QUARTER', 'NONE'

    # Trade parameters
    entry_price: Optional[float]
    stop_price: Optional[float]
    target_price: Optional[float]

    # Context
    notes: str


def combine_signals(
    ticker: str,
    target_date: Optional[date] = None,
    current_price: Optional[float] = None,
    atr: Optional[float] = None,
) -> CombinedSignal:
    """
    Combine all signal components and make a trade decision.

    Args:
        ticker: Stock symbol
        target_date: Date to score (default: today)
        current_price: Current stock price (for trade parameters)
        atr: Average True Range (for stop/target calculation)

    Returns:
        CombinedSignal with scores and decision
    """
    if target_date is None:
        target_date = date.today()

    # Get individual signals
    insider = score_insider(ticker)
    options = score_options(ticker, target_date)
    social = score_social(ticker, target_date)

    # Calculate total score
    total_score = insider.score + options.score + social.score

    # Determine action based on decision tree
    action = "NONE"
    tier = "C"
    notes_parts = []

    # Primary signal check
    has_primary_signal = insider.score >= config.INSIDER_MIN_SCORE or options.score >= config.OPTIONS_MIN_SCORE
    has_social_confirmation = social.score >= config.SOCIAL_MIN_SCORE

    if has_primary_signal and has_social_confirmation:
        action = "TRADE"
        tier = "A"
        if insider.score >= config.INSIDER_MIN_SCORE:
            notes_parts.append("Strong insider buying")
        if options.score >= config.OPTIONS_MIN_SCORE:
            notes_parts.append("Unusual options activity")
        notes_parts.append("Social confirmation")

    elif has_primary_signal:
        action = "WATCH"
        tier = "B"
        if insider.score >= config.INSIDER_MIN_SCORE:
            notes_parts.append("Insider buying (needs social confirmation)")
        if options.score >= config.OPTIONS_MIN_SCORE:
            notes_parts.append("Options activity (needs social confirmation)")

    elif insider.score >= 10 or options.score >= 10:
        action = "WATCH"
        tier = "C"
        notes_parts.append("Moderate signal - monitoring")

    # Determine position size based on total score
    if action == "TRADE":
        if total_score >= 60:
            position_size = "FULL"
        elif total_score >= 45:
            position_size = "HALF"
        else:
            position_size = "QUARTER"
    else:
        position_size = "NONE"

    # Calculate trade parameters if we have price data
    entry_price = current_price
    stop_price = None
    target_price = None

    if current_price and action == "TRADE":
        if atr and atr > 0:
            # Use ATR for stops and targets
            stop_price = round(current_price - (2 * atr), 2)
            target_price = round(current_price + (3 * atr), 2)
        else:
            # Default percentages
            stop_price = round(current_price * (1 - config.DEFAULT_STOP_PCT), 2)
            target_price = round(current_price * (1 + config.DEFAULT_TARGET_PCT), 2)

    return CombinedSignal(
        ticker=ticker,
        date=target_date,
        insider_score=insider.score,
        options_score=options.score,
        social_score=social.score,
        total_score=total_score,
        insider_signal=insider,
        options_signal=options,
        social_signal=social,
        action=action,
        tier=tier,
        position_size=position_size,
        entry_price=entry_price,
        stop_price=stop_price,
        target_price=target_price,
        notes="; ".join(notes_parts) if notes_parts else "No significant signals",
    )


def save_signal(signal: CombinedSignal) -> bool:
    """Save combined signal to database."""
    try:
        with get_db() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO signals
                (date, ticker, insider_score, options_score, social_score, total_score,
                 insider_details, options_details, social_details,
                 tier, action, entry_price, stop_price, target_price, position_size, notes)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    signal.date.isoformat(),
                    signal.ticker,
                    signal.insider_score,
                    signal.options_score,
                    signal.social_score,
                    signal.total_score,
                    json.dumps(signal.insider_signal.details),
                    json.dumps(signal.options_signal.details),
                    json.dumps(signal.social_signal.details),
                    signal.tier,
                    signal.action,
                    signal.entry_price,
                    signal.stop_price,
                    signal.target_price,
                    signal.position_size,
                    signal.notes,
                )
            )
        return True
    except Exception as e:
        print(f"Error saving signal for {signal.ticker}: {e}")
        return False


def select_stock_of_the_day(candidates: list[CombinedSignal]) -> tuple[Optional[CombinedSignal], str]:
    """
    Select Stock of the Day or return None if quality bar not met.

    Quality requirements:
    - Minimum total score (MIN_SOTD_SCORE, default 35)
    - At least MIN_ACTIVE_SIGNALS active signals (score > 0)
    - At least one strong insider or options signal (score >= MIN_INSIDER_OR_OPTIONS_SCORE)

    Args:
        candidates: List of CombinedSignal objects (already scored)

    Returns:
        Tuple of (selected_signal or None, reason_string)
    """
    if not candidates:
        return None, "No candidates passed quality filters"

    # Sort by total score descending
    sorted_candidates = sorted(candidates, key=lambda x: x.total_score, reverse=True)
    top_pick = sorted_candidates[0]

    # Check minimum score
    if top_pick.total_score < config.STOCK_OF_DAY_MIN_SCORE:
        return None, (
            f"Best score {top_pick.total_score} ({top_pick.ticker}) "
            f"below minimum {config.STOCK_OF_DAY_MIN_SCORE}"
        )

    # Count active signals (score > 0)
    active_signals = sum([
        1 if top_pick.insider_score > 0 else 0,
        1 if top_pick.options_score > 0 else 0,
        1 if top_pick.social_score > 0 else 0,
    ])

    if active_signals < config.MIN_ACTIVE_SIGNALS:
        return None, (
            f"{top_pick.ticker}: Only {active_signals} active signal(s), "
            f"need {config.MIN_ACTIVE_SIGNALS}"
        )

    # Check for at least one strong signal
    if (top_pick.insider_score < config.MIN_INSIDER_OR_OPTIONS_SCORE and
            top_pick.options_score < config.MIN_INSIDER_OR_OPTIONS_SCORE):
        return None, (
            f"{top_pick.ticker}: No strong insider ({top_pick.insider_score}) "
            f"or options ({top_pick.options_score}) signal "
            f"(need >= {config.MIN_INSIDER_OR_OPTIONS_SCORE})"
        )

    return top_pick, "Meets all quality criteria"


def log_daily_analysis(
    candidates: list[CombinedSignal],
    filtered_out: list[tuple[str, str]],
    final_pick: Optional[CombinedSignal],
    reason: str,
):
    """
    Log the full decision process for debugging.

    Args:
        candidates: Stocks that passed quality filter and were scored
        filtered_out: List of (ticker, reason) tuples for rejected stocks
        final_pick: The selected SOTD signal, or None
        reason: Reason for the final decision
    """
    logger.info(f"=== SOTD Analysis for {date.today()} ===")
    logger.info(f"Stocks filtered out by quality gate: {len(filtered_out)}")
    for stock, filter_reason in filtered_out[:10]:
        logger.info(f"  REJECTED {stock}: {filter_reason}")
    if len(filtered_out) > 10:
        logger.info(f"  ... and {len(filtered_out) - 10} more")

    logger.info(f"Candidates that passed filters: {len(candidates)}")
    sorted_candidates = sorted(candidates, key=lambda c: c.total_score, reverse=True)
    for c in sorted_candidates[:5]:
        logger.info(
            f"  {c.ticker}: Score {c.total_score} "
            f"(insider={c.insider_score}, "
            f"options={c.options_score}, "
            f"social={c.social_score})"
        )

    if final_pick:
        logger.info(f"SELECTED: {final_pick.ticker} - {reason}")
    else:
        logger.info(f"NO TRADE: {reason}")


def get_scoring_universe() -> list[str]:
    """
    Get the universe of tickers to score.

    Includes:
    - Stocks with recent insider buying
    - Stocks with unusual options activity today
    - Stocks trending on social media
    """
    tickers = set()
    today = date.today().isoformat()
    cutoff_14d = (date.today() - __import__("datetime").timedelta(days=14)).isoformat()

    with get_db() as conn:
        # Insider buying in last 14 days
        cursor = conn.execute(
            "SELECT DISTINCT ticker FROM insider_trades WHERE trade_type = 'P' AND trade_date >= ?",
            (cutoff_14d,)
        )
        for row in cursor.fetchall():
            tickers.add(row["ticker"])

        # Unusual options today
        cursor = conn.execute(
            "SELECT DISTINCT ticker FROM options_flow WHERE date = ? AND call_volume_ratio >= 1.5",
            (today,)
        )
        for row in cursor.fetchall():
            tickers.add(row["ticker"])

        # Social mentions today
        cursor = conn.execute(
            "SELECT DISTINCT ticker FROM social_metrics WHERE date = ? AND reddit_mentions >= 2",
            (today,)
        )
        for row in cursor.fetchall():
            tickers.add(row["ticker"])

    return sorted(list(tickers))


def run_daily_scoring(target_date: Optional[date] = None) -> list[CombinedSignal]:
    """
    Run the daily scoring pipeline with quality filtering.

    Steps:
    1. Get scoring universe (tickers with any signal activity)
    2. Apply quality filter (price, market cap, volume gates)
    3. Score remaining tickers
    4. Select Stock of the Day (or NO_TRADE)
    5. Log the full decision process

    Args:
        target_date: Date to score (default: today)

    Returns:
        List of signals sorted by total_score descending
    """
    if target_date is None:
        target_date = date.today()

    # Get universe
    universe = get_scoring_universe()
    logger.info(f"Scoring universe: {len(universe)} tickers")
    print(f"Found {len(universe)} tickers in scoring universe")

    # Apply quality filter
    print("Applying quality filters...")
    passed_tickers, filtered_out = filter_universe(universe)
    print(f"  Passed quality filter: {len(passed_tickers)}")
    print(f"  Rejected by quality filter: {len(filtered_out)}")

    if filtered_out:
        for ticker, reason in filtered_out[:5]:
            print(f"    REJECTED {ticker}: {reason}")
        if len(filtered_out) > 5:
            print(f"    ... and {len(filtered_out) - 5} more")

    if not passed_tickers:
        print("No tickers passed quality filters.")
        log_daily_analysis([], filtered_out, None, "No candidates passed quality filters")
        return []

    # Score remaining tickers
    print(f"Scoring {len(passed_tickers)} tickers...")
    signals = []

    for ticker in passed_tickers:
        try:
            signal = combine_signals(ticker, target_date)
            if save_signal(signal):
                signals.append(signal)
        except Exception as e:
            logger.error(f"Error scoring {ticker}: {e}")
            print(f"Error scoring {ticker}: {e}")

    # Sort by total score descending
    signals.sort(key=lambda s: s.total_score, reverse=True)

    # Select Stock of the Day
    sotd_pick, sotd_reason = select_stock_of_the_day(signals)

    # Save SOTD decision to database
    _save_sotd_decision(target_date, sotd_pick, sotd_reason, signals, filtered_out)

    # Log the full decision process
    log_daily_analysis(signals, filtered_out, sotd_pick, sotd_reason)

    if sotd_pick:
        print(f"\n  STOCK OF THE DAY: {sotd_pick.ticker} (Score: {sotd_pick.total_score})")
    else:
        print(f"\n  NO TRADE TODAY: {sotd_reason}")

    return signals


def _save_sotd_decision(
    target_date: date,
    pick: Optional[CombinedSignal],
    reason: str,
    candidates: list[CombinedSignal],
    filtered_out: list[tuple[str, str]],
):
    """Save the SOTD decision to the database for the dashboard to read."""
    try:
        decision = {
            "date": target_date.isoformat(),
            "has_pick": pick is not None,
            "ticker": pick.ticker if pick else None,
            "score": pick.total_score if pick else None,
            "reason": reason,
            "candidates_count": len(candidates),
            "filtered_out_count": len(filtered_out),
            "top_candidates": [
                {
                    "ticker": c.ticker,
                    "total_score": c.total_score,
                    "insider_score": c.insider_score,
                    "options_score": c.options_score,
                    "social_score": c.social_score,
                }
                for c in sorted(candidates, key=lambda x: x.total_score, reverse=True)[:5]
            ],
            "rejected_samples": [
                {"ticker": t, "reason": r}
                for t, r in filtered_out[:10]
            ],
        }

        with get_db() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS sotd_decisions (
                    date TEXT PRIMARY KEY,
                    decision_json TEXT NOT NULL
                )
                """
            )
            conn.execute(
                "INSERT OR REPLACE INTO sotd_decisions (date, decision_json) VALUES (?, ?)",
                (target_date.isoformat(), json.dumps(decision))
            )
    except Exception as e:
        logger.error(f"Error saving SOTD decision: {e}")


def get_top_signals(
    target_date: Optional[date] = None,
    action_filter: Optional[str] = None,
    limit: int = 10
) -> list[dict]:
    """
    Get top signals from database.

    Args:
        target_date: Date to get signals for (default: today)
        action_filter: Filter by action ('TRADE', 'WATCH', None for all)
        limit: Maximum results

    Returns:
        List of signal dicts
    """
    if target_date is None:
        target_date = date.today()

    with get_db() as conn:
        if action_filter:
            cursor = conn.execute(
                """
                SELECT * FROM signals
                WHERE date = ? AND action = ?
                ORDER BY total_score DESC
                LIMIT ?
                """,
                (target_date.isoformat(), action_filter, limit)
            )
        else:
            cursor = conn.execute(
                """
                SELECT * FROM signals
                WHERE date = ?
                ORDER BY total_score DESC
                LIMIT ?
                """,
                (target_date.isoformat(), limit)
            )

        return [dict(row) for row in cursor.fetchall()]


def format_combined_signal(signal: CombinedSignal) -> str:
    """Format a combined signal for display."""
    lines = [
        f"{signal.ticker} - Total Score: {signal.total_score}/{config.TOTAL_MAX_SCORE}",
        "=" * 50,
        f"Action: {signal.action} | Tier: {signal.tier} | Size: {signal.position_size}",
        "",
        "Component Scores:",
        f"  Insider:  {signal.insider_score:>2}/{config.INSIDER_MAX_SCORE} {'*' if signal.insider_score >= config.INSIDER_MIN_SCORE else ''}",
        f"  Options:  {signal.options_score:>2}/{config.OPTIONS_MAX_SCORE} {'*' if signal.options_score >= config.OPTIONS_MIN_SCORE else ''}",
        f"  Social:   {signal.social_score:>2}/{config.SOCIAL_MAX_SCORE} {'*' if signal.social_score >= config.SOCIAL_MIN_SCORE else ''}",
    ]

    if signal.entry_price:
        lines.extend([
            "",
            "Trade Setup:",
            f"  Entry:  ${signal.entry_price:.2f}",
            f"  Stop:   ${signal.stop_price:.2f}" if signal.stop_price else "  Stop:   N/A",
            f"  Target: ${signal.target_price:.2f}" if signal.target_price else "  Target: N/A",
        ])

    lines.extend([
        "",
        f"Notes: {signal.notes}",
    ])

    return "\n".join(lines)


if __name__ == "__main__":
    print("Testing signal combiner...")
    print()

    # Test combining signals for a few tickers
    for ticker in ["AAPL", "NVDA", "NYC"]:
        signal = combine_signals(ticker, current_price=100.0)
        print(format_combined_signal(signal))
        print()
