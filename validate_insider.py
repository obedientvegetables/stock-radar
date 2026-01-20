#!/usr/bin/env python3
"""
Stock Radar - Insider Trading Validation

Phase 1.5: Validate that insider buying predicts returns BEFORE building more.

This script:
1. Backfills historical insider buying events from SEC EDGAR
2. Calculates subsequent stock returns at various intervals
3. Compares to SPY benchmark
4. Runs statistical analysis to determine if insider buying has predictive value
5. Generates GO/NO-GO recommendation

DECISION CRITERIA:
- If average 5-day excess return > 0.5% with p < 0.10: PROCEED
- If average 10-day excess return > 1.0% with p < 0.10: PROCEED
- If win rate (5-day) > 53% with p < 0.10: PROCEED
- If CEO/CFO buys show > 1% excess return: PROCEED
- Otherwise: STOP and reconsider approach
"""

import json
import time
import statistics
from dataclasses import dataclass, asdict
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional
import math

import sys
sys.path.insert(0, str(Path(__file__).parent))

import yfinance as yf
import requests
from scipy import stats as scipy_stats

from utils.db import get_db
from utils.config import config


# Time periods for return calculation
RETURN_PERIODS = [1, 3, 5, 10, 20]

# Minimum events for meaningful statistics
MIN_EVENTS_FOR_ANALYSIS = 50
MIN_EVENTS_PER_SEGMENT = 15


@dataclass
class ValidationEvent:
    """A single insider buying event with calculated returns."""
    ticker: str
    signal_date: date
    insider_buy_value: float
    num_buyers: int
    ceo_cfo_buy: bool
    insider_type: str  # 'CEO/CFO', 'Other Officer', 'Director', '10% Owner'
    price_at_signal: float

    # Stock returns
    return_1d: Optional[float] = None
    return_3d: Optional[float] = None
    return_5d: Optional[float] = None
    return_10d: Optional[float] = None
    return_20d: Optional[float] = None

    # SPY benchmark returns
    spy_return_1d: Optional[float] = None
    spy_return_3d: Optional[float] = None
    spy_return_5d: Optional[float] = None
    spy_return_10d: Optional[float] = None
    spy_return_20d: Optional[float] = None

    # Excess returns (stock - SPY)
    excess_return_1d: Optional[float] = None
    excess_return_3d: Optional[float] = None
    excess_return_5d: Optional[float] = None
    excess_return_10d: Optional[float] = None
    excess_return_20d: Optional[float] = None


@dataclass
class ValidationResults:
    """Aggregated validation results."""
    total_events: int
    date_range_start: date
    date_range_end: date

    # Average returns by period
    avg_returns: dict  # period -> avg return
    avg_spy_returns: dict
    avg_excess_returns: dict

    # Win rates (beat SPY)
    win_rates: dict  # period -> win rate

    # Statistical significance
    p_values: dict  # period -> p-value
    t_stats: dict   # period -> t-statistic

    # Segmentation results
    by_insider_type: dict
    by_buy_size: dict

    # Recommendation
    recommendation: str  # 'PROCEED', 'STOP', 'NEED_MORE_DATA'
    rationale: list[str]


def fetch_historical_form4_filings(start_date: date, end_date: date, max_per_day: int = 50) -> list[dict]:
    """
    Fetch historical Form 4 filings from SEC EDGAR full-text search.

    Args:
        start_date: Start of date range
        end_date: End of date range
        max_per_day: Maximum filings to process per day (rate limiting)

    Returns:
        List of filing metadata dicts
    """
    from collectors.insider import _sec_request

    all_filings = []

    # EDGAR full-text search endpoint
    search_url = "https://efts.sec.gov/LATEST/search-index"

    current_date = start_date
    while current_date <= end_date:
        date_str = current_date.strftime("%Y-%m-%d")

        try:
            # Search for Form 4 filings on this date
            params = {
                "q": '"form 4"',
                "dateRange": "custom",
                "startdt": date_str,
                "enddt": date_str,
                "forms": "4",
            }

            response = _sec_request(f"{search_url}?q=%22form%204%22&dateRange=custom&startdt={date_str}&enddt={date_str}&forms=4")

            if response.status_code == 200:
                data = response.json()
                hits = data.get("hits", {}).get("hits", [])

                for hit in hits[:max_per_day]:
                    source = hit.get("_source", {})
                    filings_info = source.get("filings", {})

                    filing = {
                        "cik": source.get("ciks", [""])[0] if source.get("ciks") else "",
                        "company": source.get("display_names", [""])[0] if source.get("display_names") else "",
                        "filed_date": date_str,
                        "file_num": filings_info.get("file_num", ""),
                        "accession": filings_info.get("accession_number", ""),
                    }

                    if filing["cik"] and filing["accession"]:
                        # Build filing URL
                        accession_formatted = filing["accession"].replace("-", "")
                        filing["link"] = f"https://www.sec.gov/Archives/edgar/data/{filing['cik']}/{accession_formatted}/"
                        all_filings.append(filing)

        except Exception as e:
            print(f"  Error fetching filings for {date_str}: {e}")

        current_date += timedelta(days=1)

        # Progress
        if (current_date - start_date).days % 30 == 0:
            print(f"  Scanned through {current_date}... ({len(all_filings)} filings found)")

        # Small delay to be respectful
        time.sleep(0.2)

    return all_filings


def backfill_historical_insider_data(months_back: int = 6, use_existing: bool = True) -> dict:
    """
    Backfill historical insider buying data for validation.

    This uses a different approach than the RSS feed - it iterates through
    SEC EDGAR daily index files to get historical Form 4 filings.

    Args:
        months_back: How many months of history to fetch
        use_existing: If True, skip tickers/dates already in database

    Returns:
        Dict with backfill statistics
    """
    from collectors.insider import parse_form4_xml, get_form4_xml_url, save_trades, _sec_request

    stats = {
        "days_processed": 0,
        "filings_found": 0,
        "filings_parsed": 0,
        "purchases_found": 0,
        "trades_saved": 0,
        "errors": [],
    }

    end_date = date.today() - timedelta(days=1)  # Start from yesterday
    start_date = end_date - timedelta(days=months_back * 30)

    print(f"Backfilling insider data from {start_date} to {end_date}")
    print(f"This may take a while...")
    print()

    # Use SEC EDGAR daily index files
    # Format: https://www.sec.gov/Archives/edgar/daily-index/YYYY/QTR#/form.idx
    current_date = start_date

    while current_date <= end_date:
        year = current_date.year
        quarter = (current_date.month - 1) // 3 + 1

        # Daily index URL
        idx_url = f"https://www.sec.gov/Archives/edgar/daily-index/{year}/QTR{quarter}/form.{current_date.strftime('%Y%m%d')}.idx"

        try:
            response = _sec_request(idx_url)

            if response.status_code == 200:
                stats["days_processed"] += 1

                # Parse the index file
                lines = response.text.split('\n')

                for line in lines:
                    # Form 4 lines look like:
                    # 4         Company Name           CIK     Date       edgar/data/CIK/accession.txt
                    if line.startswith('4 ') or line.startswith('4\t'):
                        parts = line.split()
                        if len(parts) >= 5:
                            try:
                                # Extract the filing path
                                file_path = parts[-1]
                                if 'edgar/data/' in file_path:
                                    # Convert .txt path to index URL
                                    # Path format: edgar/data/CIK/ACCESSION-WITH-DASHES.txt
                                    # URL format: https://www.sec.gov/Archives/edgar/data/CIK/ACCESSION-NO-DASHES/
                                    path_parts = file_path.split('/')
                                    cik = path_parts[2]
                                    accession_with_dashes = path_parts[3].replace('.txt', '')
                                    accession_no_dashes = accession_with_dashes.replace('-', '')
                                    filing_url = f"https://www.sec.gov/Archives/edgar/data/{cik}/{accession_no_dashes}/"
                                    stats["filings_found"] += 1

                                    # Get and parse the XML
                                    xml_url = get_form4_xml_url(filing_url)
                                    if xml_url:
                                        trades = parse_form4_xml(xml_url)
                                        stats["filings_parsed"] += 1

                                        purchases = [t for t in trades if t.trade_type == 'P']
                                        stats["purchases_found"] += len(purchases)

                                        if purchases:
                                            saved = save_trades(purchases)
                                            stats["trades_saved"] += saved

                                        # Rate limit: max ~3 filings per second
                                        time.sleep(0.35)

                            except Exception as e:
                                stats["errors"].append(f"Parse error: {str(e)[:50]}")

        except requests.exceptions.HTTPError as e:
            if e.response.status_code != 404:
                stats["errors"].append(f"{current_date}: {str(e)[:50]}")

        except Exception as e:
            stats["errors"].append(f"{current_date}: {str(e)[:50]}")

        # Progress
        days_done = (current_date - start_date).days
        if days_done > 0 and days_done % 7 == 0:
            print(f"  Week {days_done // 7}: {stats['purchases_found']} purchases found, {stats['trades_saved']} saved")

        current_date += timedelta(days=1)

    return stats


def calculate_returns_for_ticker(ticker: str, signal_date: date, periods: list[int] = RETURN_PERIODS) -> dict:
    """
    Calculate stock returns for various periods after the signal date.

    Args:
        ticker: Stock symbol
        signal_date: Date of the insider buying event
        periods: List of day periods to calculate returns for

    Returns:
        Dict with returns for each period, or empty dict if data unavailable
    """
    try:
        stock = yf.Ticker(ticker)

        # Fetch data from signal_date to signal_date + max_period + buffer
        start = signal_date - timedelta(days=5)  # Buffer for finding entry price
        end = signal_date + timedelta(days=max(periods) + 10)

        df = stock.history(start=start, end=end)

        if df.empty or len(df) < 2:
            return {}

        # Normalize index to date only
        df.index = df.index.date

        # Find entry price (close on signal date or next trading day)
        entry_price = None
        entry_date = None
        for offset in range(5):
            check_date = signal_date + timedelta(days=offset)
            if check_date in df.index:
                entry_price = float(df.loc[check_date, 'Close'])
                entry_date = check_date
                break

        if entry_price is None or entry_price <= 0:
            return {}

        returns = {"price_at_signal": entry_price}

        for period in periods:
            # Find exit price (close on signal_date + period or nearest trading day)
            for offset in range(5):
                check_date = entry_date + timedelta(days=period + offset)
                if check_date in df.index:
                    exit_price = float(df.loc[check_date, 'Close'])
                    ret = (exit_price / entry_price - 1) * 100
                    returns[f"return_{period}d"] = round(ret, 4)
                    break

        return returns

    except Exception as e:
        return {}


def calculate_all_returns(events: list[dict], progress_interval: int = 50) -> list[ValidationEvent]:
    """
    Calculate returns for all insider buying events.

    Args:
        events: List of insider buying events from database
        progress_interval: Print progress every N events

    Returns:
        List of ValidationEvent objects with returns calculated
    """
    validation_events = []

    # Pre-fetch SPY returns for all dates
    print("  Fetching SPY benchmark data...")
    spy_returns_cache = {}

    # Get unique signal dates
    signal_dates = list(set(e['signal_date'] for e in events))

    for i, date_str in enumerate(signal_dates):
        if isinstance(date_str, str):
            sig_date = datetime.strptime(date_str, "%Y-%m-%d").date()
        else:
            sig_date = date_str

        spy_ret = calculate_returns_for_ticker("SPY", sig_date)
        if spy_ret:
            spy_returns_cache[date_str] = spy_ret

        if (i + 1) % 100 == 0:
            print(f"    SPY data: {i + 1}/{len(signal_dates)}")

        time.sleep(0.1)  # Rate limiting

    print(f"  Cached SPY returns for {len(spy_returns_cache)} dates")
    print()
    print("  Calculating stock returns...")

    for i, event in enumerate(events):
        if isinstance(event['signal_date'], str):
            sig_date = datetime.strptime(event['signal_date'], "%Y-%m-%d").date()
        else:
            sig_date = event['signal_date']

        # Determine insider type
        if event.get('ceo_cfo_buy'):
            insider_type = "CEO/CFO"
        elif event.get('insider_title'):
            title = event['insider_title'].upper() if event['insider_title'] else ""
            if 'CEO' in title or 'CFO' in title or 'CHIEF' in title:
                insider_type = "CEO/CFO"
            elif 'OFFICER' in title or 'VP' in title or 'PRESIDENT' in title:
                insider_type = "Other Officer"
            elif 'DIRECTOR' in title:
                insider_type = "Director"
            elif '10%' in title or 'OWNER' in title:
                insider_type = "10% Owner"
            else:
                insider_type = "Other"
        else:
            insider_type = "Unknown"

        # Get stock returns
        stock_returns = calculate_returns_for_ticker(event['ticker'], sig_date)

        if not stock_returns or 'price_at_signal' not in stock_returns:
            continue

        # Get SPY returns
        spy_returns = spy_returns_cache.get(event['signal_date'], {})

        # Create validation event
        ve = ValidationEvent(
            ticker=event['ticker'],
            signal_date=sig_date,
            insider_buy_value=event.get('buy_value', 0),
            num_buyers=event.get('num_buyers', 1),
            ceo_cfo_buy=bool(event.get('ceo_cfo_buy')),
            insider_type=insider_type,
            price_at_signal=stock_returns['price_at_signal'],
        )

        # Set returns
        for period in RETURN_PERIODS:
            stock_ret = stock_returns.get(f"return_{period}d")
            spy_ret = spy_returns.get(f"return_{period}d")

            setattr(ve, f"return_{period}d", stock_ret)
            setattr(ve, f"spy_return_{period}d", spy_ret)

            if stock_ret is not None and spy_ret is not None:
                setattr(ve, f"excess_return_{period}d", round(stock_ret - spy_ret, 4))

        validation_events.append(ve)

        if (i + 1) % progress_interval == 0:
            print(f"    Processed {i + 1}/{len(events)} events...")

        time.sleep(0.15)  # Rate limiting

    return validation_events


def save_validation_events(events: list[ValidationEvent]) -> int:
    """Save validation events to database."""
    saved = 0

    with get_db() as conn:
        for event in events:
            try:
                conn.execute(
                    """
                    INSERT OR REPLACE INTO validation_insider
                    (ticker, signal_date, insider_buy_value, num_buyers, ceo_cfo_buy,
                     price_at_signal, return_1d, return_3d, return_5d, return_10d, return_20d,
                     spy_return_1d, spy_return_3d, spy_return_5d, spy_return_10d, spy_return_20d,
                     excess_return_5d, excess_return_10d)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        event.ticker,
                        event.signal_date.isoformat(),
                        event.insider_buy_value,
                        event.num_buyers,
                        event.ceo_cfo_buy,
                        event.price_at_signal,
                        event.return_1d,
                        event.return_3d,
                        event.return_5d,
                        event.return_10d,
                        event.return_20d,
                        event.spy_return_1d,
                        event.spy_return_3d,
                        event.spy_return_5d,
                        event.spy_return_10d,
                        event.spy_return_20d,
                        event.excess_return_5d,
                        event.excess_return_10d,
                    )
                )
                saved += 1
            except Exception as e:
                print(f"Error saving {event.ticker} {event.signal_date}: {e}")

    return saved


def load_validation_events(min_value: float = 50000) -> list[ValidationEvent]:
    """Load validation events from database."""
    events = []

    with get_db() as conn:
        cursor = conn.execute(
            """
            SELECT * FROM validation_insider
            WHERE insider_buy_value >= ?
              AND return_5d IS NOT NULL
              AND spy_return_5d IS NOT NULL
            ORDER BY signal_date
            """,
            (min_value,)
        )

        for row in cursor.fetchall():
            event = ValidationEvent(
                ticker=row['ticker'],
                signal_date=datetime.strptime(row['signal_date'], "%Y-%m-%d").date(),
                insider_buy_value=row['insider_buy_value'],
                num_buyers=row['num_buyers'],
                ceo_cfo_buy=bool(row['ceo_cfo_buy']),
                insider_type="CEO/CFO" if row['ceo_cfo_buy'] else "Other",
                price_at_signal=row['price_at_signal'],
                return_1d=row['return_1d'],
                return_3d=row['return_3d'],
                return_5d=row['return_5d'],
                return_10d=row['return_10d'],
                return_20d=row['return_20d'],
                spy_return_1d=row['spy_return_1d'],
                spy_return_3d=row['spy_return_3d'],
                spy_return_5d=row['spy_return_5d'],
                spy_return_10d=row['spy_return_10d'],
                spy_return_20d=row['spy_return_20d'],
            )

            # Calculate excess returns
            for period in RETURN_PERIODS:
                stock_ret = getattr(event, f"return_{period}d")
                spy_ret = getattr(event, f"spy_return_{period}d")
                if stock_ret is not None and spy_ret is not None:
                    setattr(event, f"excess_return_{period}d", round(stock_ret - spy_ret, 4))

            events.append(event)

    return events


def analyze_returns(events: list[ValidationEvent]) -> ValidationResults:
    """
    Perform statistical analysis on validation events.

    Args:
        events: List of ValidationEvent objects

    Returns:
        ValidationResults with aggregated statistics
    """
    if not events:
        return ValidationResults(
            total_events=0,
            date_range_start=date.today(),
            date_range_end=date.today(),
            avg_returns={},
            avg_spy_returns={},
            avg_excess_returns={},
            win_rates={},
            p_values={},
            t_stats={},
            by_insider_type={},
            by_buy_size={},
            recommendation="NEED_MORE_DATA",
            rationale=["No events to analyze"],
        )

    # Get date range
    dates = [e.signal_date for e in events]
    date_start = min(dates)
    date_end = max(dates)

    # Calculate metrics for each period
    avg_returns = {}
    avg_spy_returns = {}
    avg_excess_returns = {}
    win_rates = {}
    p_values = {}
    t_stats = {}

    for period in RETURN_PERIODS:
        stock_rets = [getattr(e, f"return_{period}d") for e in events if getattr(e, f"return_{period}d") is not None]
        spy_rets = [getattr(e, f"spy_return_{period}d") for e in events if getattr(e, f"spy_return_{period}d") is not None]
        excess_rets = [getattr(e, f"excess_return_{period}d") for e in events if getattr(e, f"excess_return_{period}d") is not None]

        if stock_rets:
            avg_returns[period] = round(statistics.mean(stock_rets), 3)
        if spy_rets:
            avg_spy_returns[period] = round(statistics.mean(spy_rets), 3)

        if excess_rets and len(excess_rets) >= 10:
            avg_excess_returns[period] = round(statistics.mean(excess_rets), 3)

            # Win rate (beat SPY)
            wins = sum(1 for r in excess_rets if r > 0)
            win_rates[period] = round(wins / len(excess_rets) * 100, 1)

            # T-test: is excess return significantly different from 0?
            t_stat, p_val = scipy_stats.ttest_1samp(excess_rets, 0)
            t_stats[period] = round(t_stat, 3)
            p_values[period] = round(p_val, 4)

    # Segmentation by insider type
    by_insider_type = analyze_by_segment(events, "insider_type")

    # Segmentation by buy size
    def get_size_bucket(value):
        if value < 100000:
            return "<$100k"
        elif value < 500000:
            return "$100k-$500k"
        elif value < 1000000:
            return "$500k-$1M"
        else:
            return ">$1M"

    for e in events:
        e.size_bucket = get_size_bucket(e.insider_buy_value)

    by_buy_size = analyze_by_segment(events, "size_bucket")

    # Generate recommendation
    recommendation, rationale = generate_recommendation(
        events, avg_excess_returns, win_rates, p_values, by_insider_type
    )

    return ValidationResults(
        total_events=len(events),
        date_range_start=date_start,
        date_range_end=date_end,
        avg_returns=avg_returns,
        avg_spy_returns=avg_spy_returns,
        avg_excess_returns=avg_excess_returns,
        win_rates=win_rates,
        p_values=p_values,
        t_stats=t_stats,
        by_insider_type=by_insider_type,
        by_buy_size=by_buy_size,
        recommendation=recommendation,
        rationale=rationale,
    )


def analyze_by_segment(events: list[ValidationEvent], segment_attr: str) -> dict:
    """Analyze returns by a segment attribute."""
    segments = {}

    # Group events by segment
    grouped = {}
    for e in events:
        key = getattr(e, segment_attr, "Unknown")
        if key not in grouped:
            grouped[key] = []
        grouped[key].append(e)

    for segment_name, segment_events in grouped.items():
        if len(segment_events) < MIN_EVENTS_PER_SEGMENT:
            continue

        # Get 5-day excess returns
        excess_5d = [e.excess_return_5d for e in segment_events if e.excess_return_5d is not None]

        if not excess_5d:
            continue

        avg_excess = round(statistics.mean(excess_5d), 3)
        wins = sum(1 for r in excess_5d if r > 0)
        win_rate = round(wins / len(excess_5d) * 100, 1)

        # T-test
        if len(excess_5d) >= 10:
            t_stat, p_val = scipy_stats.ttest_1samp(excess_5d, 0)
        else:
            t_stat, p_val = 0, 1.0

        segments[segment_name] = {
            "n": len(segment_events),
            "avg_excess_5d": avg_excess,
            "win_rate": win_rate,
            "p_value": round(p_val, 4),
            "t_stat": round(t_stat, 3),
        }

    return segments


def generate_recommendation(
    events: list[ValidationEvent],
    avg_excess_returns: dict,
    win_rates: dict,
    p_values: dict,
    by_insider_type: dict
) -> tuple[str, list[str]]:
    """
    Generate GO/NO-GO recommendation based on analysis.

    Returns:
        Tuple of (recommendation, list of rationale points)
    """
    rationale = []
    should_proceed = False

    if len(events) < MIN_EVENTS_FOR_ANALYSIS:
        return "NEED_MORE_DATA", [
            f"Only {len(events)} events available, need at least {MIN_EVENTS_FOR_ANALYSIS}",
            "Run more data collection before validation",
        ]

    # Check 5-day excess return
    excess_5d = avg_excess_returns.get(5, 0)
    p_5d = p_values.get(5, 1.0)
    win_5d = win_rates.get(5, 50)

    if excess_5d > 0.5 and p_5d < 0.10:
        should_proceed = True
        rationale.append(f"5-day excess return +{excess_5d:.2f}% is significant (p={p_5d:.3f})")

    # Check 10-day excess return
    excess_10d = avg_excess_returns.get(10, 0)
    p_10d = p_values.get(10, 1.0)

    if excess_10d > 1.0 and p_10d < 0.10:
        should_proceed = True
        rationale.append(f"10-day excess return +{excess_10d:.2f}% is significant (p={p_10d:.3f})")

    # Check win rate
    if win_5d > 53 and p_5d < 0.10:
        should_proceed = True
        rationale.append(f"5-day win rate {win_5d:.1f}% beats SPY consistently")

    # Check CEO/CFO segment
    ceo_cfo = by_insider_type.get("CEO/CFO", {})
    if ceo_cfo.get("avg_excess_5d", 0) > 1.0:
        should_proceed = True
        p_ceo = ceo_cfo.get("p_value", 1.0)
        rationale.append(f"CEO/CFO buying shows +{ceo_cfo['avg_excess_5d']:.2f}% excess return (p={p_ceo:.3f})")

    # Check for negative results
    if excess_5d <= 0:
        rationale.append(f"WARNING: 5-day excess return is {excess_5d:.2f}% (negative or zero)")
    if p_5d > 0.20 and p_10d > 0.20:
        rationale.append(f"WARNING: No statistical significance at any time horizon")

    if should_proceed:
        recommendation = "PROCEED"
    elif excess_5d < 0 or (p_5d > 0.30 and p_10d > 0.30):
        recommendation = "STOP"
        rationale.append("Insider buying does not appear to predict returns")
    else:
        recommendation = "UNCERTAIN"
        rationale.append("Results are inconclusive - more data may help")

    return recommendation, rationale


def format_validation_report(results: ValidationResults) -> str:
    """Format validation results as a text report."""
    lines = []

    lines.append("=" * 70)
    lines.append("STOCK RADAR - INSIDER BUYING VALIDATION REPORT")
    lines.append("=" * 70)
    lines.append(f"Data: {results.total_events} insider buy events from {results.date_range_start} to {results.date_range_end}")
    lines.append("")

    # Overall results table
    lines.append("OVERALL RESULTS")
    lines.append("-" * 70)
    lines.append(f"{'Metric':<22} {'1-Day':>8} {'3-Day':>8} {'5-Day':>8} {'10-Day':>8} {'20-Day':>8}")
    lines.append("-" * 70)

    # Average stock return
    row = "Avg Stock Return"
    for period in RETURN_PERIODS:
        val = results.avg_returns.get(period)
        row += f" {val:+7.1f}%" if val is not None else "     N/A"
    lines.append(row)

    # Average SPY return
    row = "Avg SPY Return"
    for period in RETURN_PERIODS:
        val = results.avg_spy_returns.get(period)
        row += f" {val:+7.1f}%" if val is not None else "     N/A"
    lines.append(row)

    # Average excess return
    row = "Avg EXCESS Return"
    for period in RETURN_PERIODS:
        val = results.avg_excess_returns.get(period)
        row += f" {val:+7.1f}%" if val is not None else "     N/A"
    lines.append(row)

    # Win rate
    row = "Win Rate vs SPY"
    for period in RETURN_PERIODS:
        val = results.win_rates.get(period)
        row += f"   {val:5.1f}%" if val is not None else "     N/A"
    lines.append(row)

    # P-value
    row = "P-Value"
    for period in RETURN_PERIODS:
        val = results.p_values.get(period)
        sig = "*" if val is not None and val < 0.10 else ""
        row += f"   {val:5.3f}{sig}" if val is not None else "     N/A"
    lines.append(row)

    lines.append("-" * 70)
    lines.append("* = statistically significant at p < 0.10")
    lines.append("")

    # By insider type
    if results.by_insider_type:
        lines.append("BY INSIDER TYPE")
        lines.append("-" * 70)
        lines.append(f"{'Type':<20} {'N':>6} {'5-Day Excess':>14} {'Win Rate':>10} {'P-Value':>10}")
        lines.append("-" * 70)

        for itype, data in sorted(results.by_insider_type.items(), key=lambda x: x[1].get('avg_excess_5d', 0), reverse=True):
            sig = "*" if data['p_value'] < 0.10 else ""
            lines.append(
                f"{itype:<20} {data['n']:>6} {data['avg_excess_5d']:>+13.2f}% {data['win_rate']:>9.1f}% {data['p_value']:>9.3f}{sig}"
            )
        lines.append("-" * 70)
        lines.append("")

    # By buy size
    if results.by_buy_size:
        lines.append("BY BUY SIZE")
        lines.append("-" * 70)
        lines.append(f"{'Size Bucket':<20} {'N':>6} {'5-Day Excess':>14} {'Win Rate':>10} {'P-Value':>10}")
        lines.append("-" * 70)

        # Sort by size bucket
        size_order = ["<$100k", "$100k-$500k", "$500k-$1M", ">$1M"]
        for size in size_order:
            if size in results.by_buy_size:
                data = results.by_buy_size[size]
                sig = "*" if data['p_value'] < 0.10 else ""
                lines.append(
                    f"{size:<20} {data['n']:>6} {data['avg_excess_5d']:>+13.2f}% {data['win_rate']:>9.1f}% {data['p_value']:>9.3f}{sig}"
                )
        lines.append("-" * 70)
        lines.append("")

    # Recommendation
    lines.append("=" * 70)
    if results.recommendation == "PROCEED":
        lines.append("RECOMMENDATION: PROCEED")
    elif results.recommendation == "STOP":
        lines.append("RECOMMENDATION: STOP AND RECONSIDER")
    elif results.recommendation == "NEED_MORE_DATA":
        lines.append("RECOMMENDATION: COLLECT MORE DATA")
    else:
        lines.append("RECOMMENDATION: UNCERTAIN")

    lines.append("")
    lines.append("Rationale:")
    for point in results.rationale:
        lines.append(f"  - {point}")
    lines.append("=" * 70)

    return "\n".join(lines)


def save_report(report: str, results: ValidationResults):
    """Save validation report to file."""
    output_dir = Path(__file__).parent / "output"
    output_dir.mkdir(exist_ok=True)

    # Save text report
    report_path = output_dir / f"validation_report_{date.today().isoformat()}.txt"
    with open(report_path, 'w') as f:
        f.write(report)

    # Save results as JSON
    json_path = output_dir / f"validation_results_{date.today().isoformat()}.json"
    results_dict = {
        "total_events": results.total_events,
        "date_range_start": results.date_range_start.isoformat(),
        "date_range_end": results.date_range_end.isoformat(),
        "avg_returns": results.avg_returns,
        "avg_spy_returns": results.avg_spy_returns,
        "avg_excess_returns": results.avg_excess_returns,
        "win_rates": results.win_rates,
        "p_values": results.p_values,
        "t_stats": results.t_stats,
        "by_insider_type": results.by_insider_type,
        "by_buy_size": results.by_buy_size,
        "recommendation": results.recommendation,
        "rationale": results.rationale,
    }
    with open(json_path, 'w') as f:
        json.dump(results_dict, f, indent=2)

    print(f"Report saved to {report_path}")
    print(f"Results saved to {json_path}")


def create_visualizations(events: list[ValidationEvent], results: ValidationResults):
    """
    Create visualization charts for the validation results.
    Saves charts to output/ directory.
    """
    try:
        import matplotlib.pyplot as plt
        import matplotlib
        matplotlib.use('Agg')  # Non-interactive backend
    except ImportError:
        print("matplotlib not available, skipping visualizations")
        return

    output_dir = Path(__file__).parent / "output"
    output_dir.mkdir(exist_ok=True)

    # 1. Histogram of 5-day excess returns
    fig, ax = plt.subplots(figsize=(10, 6))
    excess_5d = [e.excess_return_5d for e in events if e.excess_return_5d is not None]

    if excess_5d:
        ax.hist(excess_5d, bins=30, edgecolor='black', alpha=0.7, color='steelblue')
        ax.axvline(x=0, color='red', linestyle='--', linewidth=2, label='Break Even')
        avg = statistics.mean(excess_5d)
        ax.axvline(x=avg, color='green', linestyle='-', linewidth=2, label=f'Mean: {avg:.2f}%')
        ax.set_xlabel('5-Day Excess Return (%)', fontsize=12)
        ax.set_ylabel('Frequency', fontsize=12)
        ax.set_title('Distribution of 5-Day Excess Returns After Insider Buying', fontsize=14)
        ax.legend()
        ax.grid(True, alpha=0.3)
        plt.tight_layout()
        plt.savefig(output_dir / 'validation_histogram_5d.png', dpi=150)
        plt.close()
        print(f"  Saved: validation_histogram_5d.png")

    # 2. Cumulative returns chart
    fig, ax = plt.subplots(figsize=(12, 6))

    # Sort events by date
    sorted_events = sorted([e for e in events if e.excess_return_5d is not None], key=lambda x: x.signal_date)

    if sorted_events:
        cumulative_return = 0
        cumulative_returns = []
        dates = []

        for e in sorted_events:
            cumulative_return += e.excess_return_5d
            cumulative_returns.append(cumulative_return)
            dates.append(e.signal_date)

        ax.plot(dates, cumulative_returns, linewidth=2, color='steelblue')
        ax.axhline(y=0, color='red', linestyle='--', alpha=0.5)
        ax.fill_between(dates, 0, cumulative_returns, alpha=0.3,
                        where=[r >= 0 for r in cumulative_returns], color='green')
        ax.fill_between(dates, 0, cumulative_returns, alpha=0.3,
                        where=[r < 0 for r in cumulative_returns], color='red')
        ax.set_xlabel('Date', fontsize=12)
        ax.set_ylabel('Cumulative Excess Return (%)', fontsize=12)
        ax.set_title('Cumulative 5-Day Excess Returns Over Time', fontsize=14)
        ax.grid(True, alpha=0.3)
        plt.xticks(rotation=45)
        plt.tight_layout()
        plt.savefig(output_dir / 'validation_cumulative.png', dpi=150)
        plt.close()
        print(f"  Saved: validation_cumulative.png")

    # 3. Returns by insider type (bar chart)
    if results.by_insider_type:
        fig, ax = plt.subplots(figsize=(10, 6))

        types = list(results.by_insider_type.keys())
        excess_returns = [results.by_insider_type[t]['avg_excess_5d'] for t in types]
        win_rates = [results.by_insider_type[t]['win_rate'] for t in types]
        counts = [results.by_insider_type[t]['n'] for t in types]

        x = range(len(types))
        width = 0.35

        bars1 = ax.bar([i - width/2 for i in x], excess_returns, width, label='Avg Excess Return (%)', color='steelblue')
        ax2 = ax.twinx()
        bars2 = ax2.bar([i + width/2 for i in x], win_rates, width, label='Win Rate (%)', color='orange', alpha=0.7)

        ax.set_xlabel('Insider Type', fontsize=12)
        ax.set_ylabel('Avg 5-Day Excess Return (%)', fontsize=12, color='steelblue')
        ax2.set_ylabel('Win Rate (%)', fontsize=12, color='orange')
        ax.set_title('Returns by Insider Type', fontsize=14)
        ax.set_xticks(x)
        ax.set_xticklabels([f"{t}\n(n={c})" for t, c in zip(types, counts)])
        ax.axhline(y=0, color='red', linestyle='--', alpha=0.5)
        ax2.axhline(y=50, color='gray', linestyle=':', alpha=0.5)

        # Combined legend
        lines1, labels1 = ax.get_legend_handles_labels()
        lines2, labels2 = ax2.get_legend_handles_labels()
        ax.legend(lines1 + lines2, labels1 + labels2, loc='upper right')

        plt.tight_layout()
        plt.savefig(output_dir / 'validation_by_insider_type.png', dpi=150)
        plt.close()
        print(f"  Saved: validation_by_insider_type.png")

    # 4. Returns by buy size (bar chart)
    if results.by_buy_size:
        fig, ax = plt.subplots(figsize=(10, 6))

        size_order = ["<$100k", "$100k-$500k", "$500k-$1M", ">$1M"]
        sizes = [s for s in size_order if s in results.by_buy_size]
        excess_returns = [results.by_buy_size[s]['avg_excess_5d'] for s in sizes]
        counts = [results.by_buy_size[s]['n'] for s in sizes]

        colors = ['#ff6b6b' if r < 0 else '#51cf66' for r in excess_returns]
        bars = ax.bar(sizes, excess_returns, color=colors, edgecolor='black')

        ax.axhline(y=0, color='black', linestyle='-', linewidth=1)
        ax.set_xlabel('Buy Size', fontsize=12)
        ax.set_ylabel('Avg 5-Day Excess Return (%)', fontsize=12)
        ax.set_title('Returns by Insider Buy Size', fontsize=14)

        # Add count labels
        for bar, count in zip(bars, counts):
            height = bar.get_height()
            ax.annotate(f'n={count}',
                        xy=(bar.get_x() + bar.get_width() / 2, height),
                        xytext=(0, 3 if height >= 0 else -15),
                        textcoords="offset points",
                        ha='center', va='bottom' if height >= 0 else 'top')

        ax.grid(True, alpha=0.3, axis='y')
        plt.tight_layout()
        plt.savefig(output_dir / 'validation_by_buy_size.png', dpi=150)
        plt.close()
        print(f"  Saved: validation_by_buy_size.png")

    # 5. Returns by time horizon (line chart)
    fig, ax = plt.subplots(figsize=(10, 6))

    periods = RETURN_PERIODS
    avg_stock = [results.avg_returns.get(p, 0) for p in periods]
    avg_spy = [results.avg_spy_returns.get(p, 0) for p in periods]
    avg_excess = [results.avg_excess_returns.get(p, 0) for p in periods]

    ax.plot(periods, avg_stock, marker='o', linewidth=2, label='Stock Return', color='steelblue')
    ax.plot(periods, avg_spy, marker='s', linewidth=2, label='SPY Return', color='gray')
    ax.plot(periods, avg_excess, marker='^', linewidth=2, label='Excess Return', color='green')

    ax.axhline(y=0, color='red', linestyle='--', alpha=0.5)
    ax.set_xlabel('Days After Signal', fontsize=12)
    ax.set_ylabel('Average Return (%)', fontsize=12)
    ax.set_title('Returns by Time Horizon', fontsize=14)
    ax.legend()
    ax.grid(True, alpha=0.3)
    ax.set_xticks(periods)
    plt.tight_layout()
    plt.savefig(output_dir / 'validation_by_horizon.png', dpi=150)
    plt.close()
    print(f"  Saved: validation_by_horizon.png")

    print(f"\nAll visualizations saved to {output_dir}/")


def run_validation_backfill(months_back: int = 6):
    """
    Step 1: Backfill historical insider data.
    """
    print("=" * 60)
    print("STEP 1: BACKFILL HISTORICAL INSIDER DATA")
    print("=" * 60)
    print()

    stats = backfill_historical_insider_data(months_back=months_back)

    print()
    print("Backfill Results:")
    print(f"  Days processed: {stats['days_processed']}")
    print(f"  Filings found: {stats['filings_found']}")
    print(f"  Filings parsed: {stats['filings_parsed']}")
    print(f"  Purchases found: {stats['purchases_found']}")
    print(f"  Trades saved: {stats['trades_saved']}")

    if stats['errors']:
        print(f"  Errors: {len(stats['errors'])}")

    return stats


def run_validation_calculate():
    """
    Step 2: Calculate returns for insider buying events.
    """
    print("=" * 60)
    print("STEP 2: CALCULATE RETURNS FOR INSIDER EVENTS")
    print("=" * 60)
    print()

    # Load insider events from database
    events = load_insider_events(min_value=50000, days_back=365)
    print(f"Found {len(events)} insider buying events")

    if len(events) < 30:
        print()
        print("Not enough data. Run validation-backfill first to collect historical data.")
        return []

    print()
    print("Calculating returns (this may take a while)...")

    # Calculate returns
    validation_events = calculate_all_returns(events)

    print()
    print(f"Successfully calculated returns for {len(validation_events)} events")

    # Save to database
    saved = save_validation_events(validation_events)
    print(f"Saved {saved} events to validation_insider table")

    return validation_events


def run_validation_analysis():
    """
    Step 3: Run statistical analysis and generate report.
    """
    print("=" * 60)
    print("STEP 3: STATISTICAL ANALYSIS")
    print("=" * 60)
    print()

    # Load validation events
    events = load_validation_events(min_value=50000)
    print(f"Loaded {len(events)} validated events")

    if len(events) < MIN_EVENTS_FOR_ANALYSIS:
        print()
        print(f"Need at least {MIN_EVENTS_FOR_ANALYSIS} events for meaningful analysis.")
        print(f"Currently have {len(events)} events.")
        print()
        print("Run validation-calculate to process more events.")
        return None

    # Run analysis
    print()
    print("Running statistical analysis...")
    results = analyze_returns(events)

    # Format and print report
    report = format_validation_report(results)
    print()
    print(report)

    # Save report
    save_report(report, results)

    # Create visualizations
    print()
    print("Creating visualizations...")
    create_visualizations(events, results)

    return results


def load_insider_events(min_value: float = 50000, days_back: int = 365):
    """
    Load insider buying events from the database for validation.
    Groups by ticker and date to get aggregate buy value.
    """
    cutoff = (date.today() - timedelta(days=days_back)).isoformat()

    with get_db() as conn:
        cursor = conn.execute(
            """
            SELECT
                ticker,
                trade_date as signal_date,
                SUM(total_value) as buy_value,
                COUNT(DISTINCT insider_name) as num_buyers,
                MAX(CASE WHEN insider_title LIKE '%CEO%' OR insider_title LIKE '%CFO%'
                         OR insider_title LIKE '%Chief Executive%' OR insider_title LIKE '%Chief Financial%'
                    THEN 1 ELSE 0 END) as ceo_cfo_buy,
                GROUP_CONCAT(DISTINCT insider_title) as insider_title
            FROM insider_trades
            WHERE trade_type = 'P'
              AND trade_date >= ?
              AND total_value >= ?
            GROUP BY ticker, trade_date
            HAVING SUM(total_value) >= ?
            ORDER BY trade_date
            """,
            (cutoff, min_value / 10, min_value)  # Lower per-trade min, aggregate min
        )
        return [dict(row) for row in cursor.fetchall()]


def run_validation():
    """
    Main validation entry point - run full analysis.
    """
    print("=" * 60)
    print("INSIDER BUYING VALIDATION")
    print("=" * 60)
    print()

    # Check if we have validation data
    events = load_validation_events(min_value=50000)

    if len(events) < MIN_EVENTS_FOR_ANALYSIS:
        # Check if we have raw insider data
        raw_events = load_insider_events(min_value=50000, days_back=365)

        if len(raw_events) < 30:
            print(f"Insufficient insider data: {len(raw_events)} events")
            print()
            print("Options:")
            print("  1. Run 'python3 daily_run.py validate-backfill' to fetch historical data")
            print("  2. Run 'python3 daily_run.py insider-collect' daily to accumulate data")
            print()
            print(f"Need at least {MIN_EVENTS_FOR_ANALYSIS} events for validation.")
            return {"status": "insufficient_data", "proceed": None}

        print(f"Have {len(raw_events)} raw events but only {len(events)} with returns calculated")
        print()
        print("Run 'python3 daily_run.py validate-calculate' to calculate returns")
        return {"status": "needs_calculation", "proceed": None}

    # Run analysis
    results = run_validation_analysis()

    if results is None:
        return {"status": "error", "proceed": None}

    return {
        "status": "complete",
        "proceed": results.recommendation == "PROCEED",
        "recommendation": results.recommendation,
        "results": results,
    }


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1:
        cmd = sys.argv[1]
        if cmd == "backfill":
            months = int(sys.argv[2]) if len(sys.argv) > 2 else 6
            run_validation_backfill(months)
        elif cmd == "calculate":
            run_validation_calculate()
        elif cmd == "analyze":
            run_validation_analysis()
        else:
            print(f"Unknown command: {cmd}")
            print("Usage: python validate_insider.py [backfill|calculate|analyze]")
    else:
        result = run_validation()
        print()
        print("-" * 60)
        if result.get("proceed") is True:
            print("RECOMMENDATION: Proceed with development")
        elif result.get("proceed") is False:
            print("RECOMMENDATION: Stop and reconsider approach")
        else:
            print("RECOMMENDATION: Collect more data first")
