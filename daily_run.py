#!/usr/bin/env python3
"""
Stock Radar - Daily CLI Entry Point

Main command-line interface for running the stock radar system.
"""

import click
from datetime import date, datetime, timedelta
from pathlib import Path

# Add project root to path for imports
import sys
sys.path.insert(0, str(Path(__file__).parent))

from utils.config import config, setup_logging
from utils.db import get_db, get_table_counts, init_db

# Initialize logging
setup_logging()
from collectors.insider import collect_insider_data, get_recent_purchases
from collectors.options import collect_options_data, get_default_watchlist, get_unusual_options
from collectors.social import collect_social_data, get_trending_tickers
from collectors.market import collect_market_data, get_market_data, get_current_price
from signals.insider_signal import score_insider, get_top_insider_stocks, format_signal_report as format_insider_report
from signals.options_signal import score_options, get_top_options_stocks, format_signal_report as format_options_report
from signals.social_signal import score_social, get_top_social_stocks, format_signal_report as format_social_report
from signals.combiner import (
    combine_signals, run_daily_scoring, get_top_signals, format_combined_signal, get_scoring_universe
)
from output.formatter import format_daily_email, preview_email
from output.emailer import send_daily_email, test_email_connection, send_test_email


@click.group()
def cli():
    """Stock Radar - Daily stock signal generator."""
    pass


@cli.command()
def status():
    """Show system status and database health."""
    click.echo("=" * 50)
    click.echo("STOCK RADAR STATUS")
    click.echo("=" * 50)
    click.echo()

    # Check configuration
    click.echo("Configuration:")
    issues = config.validate()
    if issues:
        for issue in issues:
            click.echo(f"  ⚠️  {issue}")
    else:
        click.echo("  ✅ All required config present")
    click.echo()

    # Check database
    click.echo("Database:")
    if config.DB_PATH.exists():
        click.echo(f"  ✅ Database exists at {config.DB_PATH}")
        counts = get_table_counts()
        click.echo("  Table counts:")
        for table, count in counts.items():
            click.echo(f"    {table}: {count}")
    else:
        click.echo(f"  ❌ Database not found at {config.DB_PATH}")
        click.echo("  Run: python3 -m utils.db")
    click.echo()

    # Check directories
    click.echo("Directories:")
    click.echo(f"  Data: {config.DATA_DIR} {'✅' if config.DATA_DIR.exists() else '❌'}")
    click.echo(f"  Logs: {config.LOGS_DIR} {'✅' if config.LOGS_DIR.exists() else '❌'}")
    click.echo()


@cli.command()
def health():
    """Show system health and recent activity."""
    from datetime import datetime, timedelta
    from utils.trading_calendar import is_trading_day, next_trading_day, previous_trading_day

    click.echo("=" * 50)
    click.echo("STOCK RADAR HEALTH CHECK")
    click.echo("=" * 50)
    click.echo()

    today = date.today()
    now = datetime.now()

    # Trading calendar status
    click.echo("Trading Calendar:")
    click.echo(f"  Today ({today}): {'Trading day' if is_trading_day(today) else 'Market closed'}")
    click.echo(f"  Next trading day: {next_trading_day(today)}")
    click.echo(f"  Previous trading day: {previous_trading_day(today)}")
    click.echo()

    # Check database
    if not config.DB_PATH.exists():
        click.echo("Database: NOT FOUND")
        click.echo("  Run: python3 daily_run.py init")
        return

    click.echo("Recent Activity:")
    with get_db() as conn:
        # Last insider collection
        cursor = conn.execute(
            "SELECT MAX(filed_date) as last_date, COUNT(*) as count FROM insider_trades WHERE filed_date >= date('now', '-7 days')"
        )
        insider = cursor.fetchone()
        if insider and insider['last_date']:
            click.echo(f"  Last insider data: {insider['last_date']} ({insider['count']} trades in last 7 days)")
        else:
            click.echo("  Last insider data: No recent data")

        # Last options collection
        cursor = conn.execute(
            "SELECT MAX(date) as last_date, COUNT(*) as count FROM options_flow WHERE date >= date('now', '-7 days')"
        )
        options = cursor.fetchone()
        if options and options['last_date']:
            click.echo(f"  Last options data: {options['last_date']} ({options['count']} records in last 7 days)")
        else:
            click.echo("  Last options data: No recent data")

        # Last social collection
        cursor = conn.execute(
            "SELECT MAX(date) as last_date, COUNT(*) as count FROM social_metrics WHERE date >= date('now', '-7 days')"
        )
        social = cursor.fetchone()
        if social and social['last_date']:
            click.echo(f"  Last social data: {social['last_date']} ({social['count']} records in last 7 days)")
        else:
            click.echo("  Last social data: No recent data")

        # Last signal generation
        cursor = conn.execute(
            "SELECT MAX(date) as last_date, COUNT(*) as today_count FROM signals WHERE date = date('now')"
        )
        signals = cursor.fetchone()
        cursor = conn.execute(
            "SELECT date, COUNT(*) as count FROM signals WHERE date >= date('now', '-7 days') GROUP BY date ORDER BY date DESC LIMIT 5"
        )
        recent_signals = cursor.fetchall()

        click.echo()
        click.echo("Signal Generation:")
        if recent_signals:
            for row in recent_signals:
                click.echo(f"  {row['date']}: {row['count']} signals")
        else:
            click.echo("  No signals in last 7 days")

        # Today's signals summary
        cursor = conn.execute(
            "SELECT action, COUNT(*) as count FROM signals WHERE date = date('now') GROUP BY action"
        )
        today_actions = cursor.fetchall()
        if today_actions:
            click.echo()
            click.echo("Today's Signals:")
            for row in today_actions:
                click.echo(f"  {row['action']}: {row['count']}")

    # Check cron log for errors
    click.echo()
    click.echo("Recent Errors:")
    cron_log = config.LOGS_DIR / "cron.log"
    if cron_log.exists():
        try:
            with open(cron_log, 'r') as f:
                lines = f.readlines()
                # Look for ERROR in last 100 lines
                recent_lines = lines[-100:] if len(lines) > 100 else lines
                errors = [l.strip() for l in recent_lines if 'ERROR' in l.upper()]
                if errors:
                    for err in errors[-5:]:  # Show last 5 errors
                        click.echo(f"  {err[:80]}")
                else:
                    click.echo("  No errors in recent log")
        except Exception as e:
            click.echo(f"  Could not read log: {e}")
    else:
        click.echo("  No cron log found (scripts not yet run)")

    # Overall health assessment
    click.echo()
    click.echo("-" * 50)

    issues = []
    if not insider or not insider['last_date']:
        issues.append("No recent insider data")
    if not options or not options['last_date']:
        issues.append("No recent options data")
    if not social or not social['last_date']:
        issues.append("No recent social data")
    if not recent_signals:
        issues.append("No signals generated recently")

    if issues:
        click.echo("Issues Found:")
        for issue in issues:
            click.echo(f"  - {issue}")
        click.echo()
        click.echo("Run 'python3 daily_run.py evening' to collect data and generate signals")
    else:
        click.echo("System healthy - all data sources active")


@cli.command()
def init():
    """Initialize or reset the database."""
    if config.DB_PATH.exists():
        if not click.confirm("Database exists. Re-initialize? (This won't delete data)"):
            return
    init_db()
    click.echo("Database initialized.")


@cli.command()
@click.option("--date", "-d", "target_date", default=None,
              help="Date to score (YYYY-MM-DD), defaults to today")
def score(target_date):
    """Run daily scoring pipeline."""
    if target_date:
        try:
            scoring_date = datetime.strptime(target_date, "%Y-%m-%d").date()
        except ValueError:
            click.echo("Invalid date format. Use YYYY-MM-DD")
            return
    else:
        scoring_date = date.today()

    click.echo(f"Scoring stocks for {scoring_date}...")
    click.echo()

    # Get universe of tickers to score
    universe = get_scoring_universe()
    click.echo(f"Found {len(universe)} tickers in scoring universe")

    if not universe:
        click.echo("No tickers to score. Run data collection first:")
        click.echo("  python3 daily_run.py insider-collect")
        click.echo("  python3 daily_run.py options-collect")
        click.echo("  python3 daily_run.py social-collect")
        return

    # Run scoring
    signals = run_daily_scoring(scoring_date)

    # Show results summary
    trade_signals = [s for s in signals if s.action == "TRADE"]
    watch_signals = [s for s in signals if s.action == "WATCH"]

    click.echo()
    click.echo("=" * 50)
    click.echo("SCORING COMPLETE")
    click.echo("=" * 50)
    click.echo(f"  Total scored: {len(signals)}")
    click.echo(f"  TRADE signals: {len(trade_signals)}")
    click.echo(f"  WATCH signals: {len(watch_signals)}")
    click.echo()

    if trade_signals:
        click.echo("Top TRADE signals:")
        for sig in trade_signals[:5]:
            click.echo(f"  {sig.ticker:<6} Score: {sig.total_score:>2} | I:{sig.insider_score:>2} O:{sig.options_score:>2} S:{sig.social_score:>2}")
    click.echo()
    click.echo("Run 'python3 daily_run.py top' for detailed view")


@cli.command()
@click.option("--action", "-a", type=click.Choice(["TRADE", "WATCH", "ALL"]), default="ALL",
              help="Filter by action type")
@click.option("--limit", "-l", default=10, help="Number of signals to show")
def top(action, limit):
    """Show today's top signals."""
    today = date.today()

    action_filter = action if action != "ALL" else None
    signals = get_top_signals(target_date=today, action_filter=action_filter, limit=limit)

    if not signals:
        click.echo(f"No signals found for {today}")
        click.echo("Run: python3 daily_run.py score")
        return

    click.echo(f"Top signals for {today}" + (f" (action={action})" if action != "ALL" else "") + ":")
    click.echo("-" * 70)
    click.echo(f"{'Ticker':<8} {'Score':>6} {'Action':<8} {'Tier':>4} {'Size':<8} {'I':>4} {'O':>4} {'S':>4}")
    click.echo("-" * 70)

    for sig in signals:
        click.echo(
            f"{sig['ticker']:<8} {sig['total_score']:>6} {sig['action']:<8} "
            f"{sig['tier'] or '-':>4} {sig['position_size'] or '-':<8} "
            f"{sig['insider_score']:>4} {sig['options_score']:>4} {sig['social_score']:>4}"
        )

    click.echo()
    click.echo("Use 'python3 daily_run.py explain <TICKER>' for details")


@cli.command()
@click.argument("ticker")
@click.option("--live", is_flag=True, help="Calculate live signal (don't use cached)")
def explain(ticker, live):
    """Show signal breakdown for a specific ticker."""
    today = date.today()
    ticker = ticker.upper()

    if live:
        # Get current price and ATR for live calculation
        price = get_current_price(ticker)
        market = get_market_data(ticker)
        atr = market.atr_14 if market else None

        signal = combine_signals(ticker, today, current_price=price, atr=atr)

        click.echo()
        click.echo(format_combined_signal(signal))
        return

    # Use cached signal from database
    with get_db() as conn:
        cursor = conn.execute(
            """
            SELECT *
            FROM signals
            WHERE date = ? AND ticker = ?
            """,
            (today.isoformat(), ticker)
        )
        signal = cursor.fetchone()

    if not signal:
        click.echo(f"No cached signal found for {ticker} on {today}")
        click.echo("Use --live flag to calculate now, or run 'python3 daily_run.py score'")
        return

    click.echo(f"\n{ticker} Signal Breakdown ({today})")
    click.echo("=" * 50)
    click.echo(f"Total Score: {signal['total_score']}/{config.TOTAL_MAX_SCORE}")
    click.echo(f"Action: {signal['action']}")
    click.echo(f"Tier: {signal['tier'] or 'N/A'}")
    click.echo()
    click.echo("Component Scores:")
    click.echo(f"  Insider:  {signal['insider_score']:>2}/{config.INSIDER_MAX_SCORE} {'*' if signal['insider_score'] >= config.INSIDER_MIN_SCORE else ''}")
    click.echo(f"  Options:  {signal['options_score']:>2}/{config.OPTIONS_MAX_SCORE} {'*' if signal['options_score'] >= config.OPTIONS_MIN_SCORE else ''}")
    click.echo(f"  Social:   {signal['social_score']:>2}/{config.SOCIAL_MAX_SCORE} {'*' if signal['social_score'] >= config.SOCIAL_MIN_SCORE else ''}")
    click.echo()

    if signal['entry_price']:
        click.echo("Trade Setup:")
        click.echo(f"  Entry:  ${signal['entry_price']:.2f}")
        click.echo(f"  Stop:   ${signal['stop_price']:.2f}" if signal['stop_price'] else "  Stop:   N/A")
        click.echo(f"  Target: ${signal['target_price']:.2f}" if signal['target_price'] else "  Target: N/A")
        click.echo(f"  Size:   {signal['position_size']}")

    if signal['notes']:
        click.echo()
        click.echo(f"Notes: {signal['notes']}")


@cli.command()
@click.option("--preview", is_flag=True, help="Preview email without sending")
@click.option("--test", is_flag=True, help="Send test email to verify configuration")
@click.option("--date", "-d", "target_date", default=None,
              help="Date to generate email for (YYYY-MM-DD)")
def email(preview, test, target_date):
    """Generate and send daily email."""
    if target_date:
        try:
            email_date = datetime.strptime(target_date, "%Y-%m-%d").date()
        except ValueError:
            click.echo("Invalid date format. Use YYYY-MM-DD")
            return
    else:
        email_date = date.today()

    if test:
        click.echo("Testing email configuration...")
        result = test_email_connection()
        if result['success']:
            click.echo(f"  Connection: OK")
            click.echo("Sending test email...")
            result = send_test_email()
            click.echo(f"  {result['message']}")
        else:
            click.echo(f"  {result['message']}")
        return

    if preview:
        click.echo(preview_email(email_date))
        return

    # Send the daily email
    click.echo(f"Generating email for {email_date}...")
    result = send_daily_email(email_date)

    if result['success']:
        click.echo(f"  {result['message']}")
    else:
        click.echo(f"  Error: {result['message']}")
        click.echo()
        click.echo("Configure email in .env:")
        click.echo("  EMAIL_SMTP_SERVER=smtp.gmail.com")
        click.echo("  EMAIL_SMTP_PORT=587")
        click.echo("  EMAIL_USERNAME=your-email@gmail.com")
        click.echo("  EMAIL_PASSWORD=your-app-password")
        click.echo("  EMAIL_TO=recipient@example.com")


@cli.command()
@click.option("--count", "-c", default=100, help="Number of filings to fetch")
def morning(count):
    """Run morning data collection (insider filings)."""
    click.echo(f"Morning collection - {date.today()}")
    click.echo()

    stats = collect_insider_data(count=count, purchases_only=True)

    click.echo("Collection Results:")
    click.echo(f"  Filings fetched: {stats['filings_fetched']}")
    click.echo(f"  Filings parsed:  {stats['filings_parsed']}")
    click.echo(f"  Purchases found: {stats['purchases_found']}")
    click.echo(f"  New trades saved: {stats['trades_saved']}")

    if stats["errors"]:
        click.echo(f"  Errors: {len(stats['errors'])}")


@cli.command()
@click.option("--skip-collect", is_flag=True, help="Skip data collection (use existing data)")
def evening(skip_collect):
    """Run evening pipeline (collect -> score -> email)."""
    click.echo(f"Evening pipeline - {date.today()}")
    click.echo("=" * 50)
    click.echo()

    if not skip_collect:
        # Step 1: Collect insider data
        click.echo("Step 1/4: Collecting insider data...")
        insider_stats = collect_insider_data(count=100, purchases_only=True)
        click.echo(f"  Purchases found: {insider_stats['purchases_found']}")
        click.echo()

        # Step 2: Collect options data
        click.echo("Step 2/4: Collecting options data...")
        options_tickers = get_default_watchlist()
        options_stats = collect_options_data(options_tickers, delay=0.3)
        click.echo(f"  Tickers collected: {options_stats['tickers_collected']}")
        click.echo(f"  Unusual calls: {options_stats['unusual_calls']}")
        click.echo()

        # Step 3: Collect social data (via Adanos API + Stocktwits)
        click.echo("Step 3/4: Collecting social data...")
        social_stats = collect_social_data()
        click.echo(f"  Tickers collected: {social_stats['tickers_collected']}")
        click.echo(f"  High velocity: {social_stats['high_velocity']}")
        click.echo()
    else:
        click.echo("Skipping data collection (using existing data)")
        click.echo()

    # Step 4: Run scoring
    click.echo("Step 4/4: Running signal scoring...")
    signals = run_daily_scoring()

    trade_signals = [s for s in signals if s.action == "TRADE"]
    watch_signals = [s for s in signals if s.action == "WATCH"]

    click.echo()
    click.echo("=" * 50)
    click.echo("EVENING PIPELINE COMPLETE")
    click.echo("=" * 50)
    click.echo(f"  Total scored: {len(signals)}")
    click.echo(f"  TRADE signals: {len(trade_signals)}")
    click.echo(f"  WATCH signals: {len(watch_signals)}")
    click.echo()

    if trade_signals:
        click.echo("TRADE SIGNALS:")
        click.echo("-" * 50)
        for sig in trade_signals[:5]:
            click.echo(f"  {sig.ticker:<6} Score: {sig.total_score:>2}/{config.TOTAL_MAX_SCORE} - {sig.notes}")
        click.echo()

    click.echo("Run 'python3 daily_run.py top' for full list")
    click.echo("Run 'python3 daily_run.py email --preview' to preview email")


@cli.command()
def full():
    """Run complete pipeline (for catch-up days)."""
    click.echo(f"Full pipeline - {date.today()}")
    click.echo()
    click.echo("⚠️  Full pipeline not yet implemented")


# Paper Trading Commands
@cli.command()
@click.argument("ticker")
@click.argument("price", type=float)
@click.option("--size", "-s", type=click.Choice(["FULL", "HALF", "QUARTER"]), default="HALF",
              help="Position size (default: HALF)")
@click.option("--notes", "-n", default=None, help="Trade notes/reason")
def enter(ticker, price, size, notes):
    """Log a paper trade entry.

    Example: python3 daily_run.py enter NVDA 142.30 --size HALF --notes "CEO buying"
    """
    ticker = ticker.upper()
    today = date.today()

    # Calculate position size
    portfolio = config.PAPER_PORTFOLIO_SIZE
    size_pct = {"FULL": 0.10, "HALF": 0.05, "QUARTER": 0.025}[size]
    position_value = portfolio * size_pct
    shares = int(position_value / price)

    if shares < 1:
        click.echo(f"Error: Price ${price:.2f} too high for {size} position (${position_value:.2f})")
        return

    actual_value = shares * price

    # Look for today's signal for this ticker
    signal_id = None
    stop_price = None
    target_price = None

    with get_db() as conn:
        cursor = conn.execute(
            "SELECT id, stop_price, target_price FROM signals WHERE date = ? AND ticker = ?",
            (today.isoformat(), ticker)
        )
        signal = cursor.fetchone()

        if signal:
            signal_id = signal['id']
            stop_price = signal['stop_price']
            target_price = signal['target_price']

    # Default stop/target if no signal found
    if stop_price is None:
        stop_price = price * (1 - config.DEFAULT_STOP_PCT)
    if target_price is None:
        target_price = price * (1 + config.DEFAULT_TARGET_PCT)

    # Check for existing open position
    with get_db() as conn:
        cursor = conn.execute(
            "SELECT id FROM trades WHERE ticker = ? AND status = 'OPEN'",
            (ticker,)
        )
        existing = cursor.fetchone()

        if existing:
            click.echo(f"Error: Already have an open position in {ticker}")
            click.echo("Use 'python3 daily_run.py exit' to close it first")
            return

        # Insert the trade
        cursor = conn.execute(
            """
            INSERT INTO trades (signal_id, ticker, entry_date, entry_price, shares, stop_price, target_price, status, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?, 'OPEN', ?)
            """,
            (signal_id, ticker, today.isoformat(), price, shares, stop_price, target_price, notes)
        )

    # Show confirmation
    click.echo()
    click.echo("✓ Paper trade entered")
    click.echo(f"  Ticker: {ticker}")
    click.echo(f"  Entry: ${price:.2f}")
    click.echo(f"  Shares: {shares} ({size} position, ${actual_value:.2f})")
    click.echo(f"  Stop: ${stop_price:.2f} ({100*(stop_price/price - 1):+.1f}%)")
    click.echo(f"  Target: ${target_price:.2f} ({100*(target_price/price - 1):+.1f}%)")
    if notes:
        click.echo(f"  Notes: {notes}")
    if not signal_id:
        click.echo()
        click.echo("  Note: No signal found for today - using default stop/target")


@cli.command("exit")
@click.argument("ticker")
@click.argument("price", type=float)
@click.option("--reason", "-r", type=click.Choice(["TARGET", "STOP", "TIME", "MANUAL"]),
              default="MANUAL", help="Exit reason (default: MANUAL)")
@click.option("--notes", "-n", default=None, help="Exit notes")
def exit_trade(ticker, price, reason, notes):
    """Close an open paper trade.

    Example: python3 daily_run.py exit NVDA 156.50 --reason TARGET
    """
    ticker = ticker.upper()
    today = date.today()

    with get_db() as conn:
        # Find the open position
        cursor = conn.execute(
            """
            SELECT id, entry_date, entry_price, shares, notes as entry_notes
            FROM trades
            WHERE ticker = ? AND status = 'OPEN'
            """,
            (ticker,)
        )
        trade = cursor.fetchone()

        if not trade:
            click.echo(f"Error: No open position found for {ticker}")
            click.echo("Use 'python3 daily_run.py positions' to see open positions")
            return

        # Calculate returns
        entry_price = trade['entry_price']
        shares = trade['shares']
        entry_date = datetime.strptime(trade['entry_date'], "%Y-%m-%d").date()

        return_pct = ((price - entry_price) / entry_price) * 100
        return_dollars = (price - entry_price) * shares
        days_held = (today - entry_date).days

        # Combine notes
        all_notes = trade['entry_notes'] or ""
        if notes:
            all_notes = f"{all_notes}; Exit: {notes}" if all_notes else notes

        # Update the trade
        conn.execute(
            """
            UPDATE trades
            SET exit_date = ?, exit_price = ?, exit_reason = ?,
                return_pct = ?, return_dollars = ?, days_held = ?,
                status = 'CLOSED', notes = ?
            WHERE id = ?
            """,
            (today.isoformat(), price, reason, return_pct, return_dollars,
             days_held, all_notes, trade['id'])
        )

    # Show confirmation
    result_icon = "✅" if return_pct > 0 else "❌"
    click.echo()
    click.echo(f"{result_icon} Trade closed")
    click.echo(f"  Ticker: {ticker}")
    click.echo(f"  Entry: ${entry_price:.2f} → Exit: ${price:.2f}")
    click.echo(f"  Return: {return_pct:+.1f}% (${return_dollars:+.2f})")
    click.echo(f"  Days held: {days_held}")
    click.echo(f"  Reason: {reason}")


@cli.command()
def positions():
    """Show open paper trading positions with live prices."""
    with get_db() as conn:
        cursor = conn.execute(
            """
            SELECT t.id, t.ticker, t.entry_date, t.entry_price, t.shares, t.notes,
                   t.stop_price, t.target_price,
                   s.total_score
            FROM trades t
            LEFT JOIN signals s ON t.signal_id = s.id
            WHERE t.status = 'OPEN'
            ORDER BY t.entry_date DESC
            """
        )
        open_trades = cursor.fetchall()

    if not open_trades:
        click.echo("No open positions.")
        click.echo()
        click.echo("Use 'python3 daily_run.py enter TICKER PRICE' to log a paper trade.")
        return

    click.echo()
    click.echo(f"Open Positions ({len(open_trades)})")
    click.echo("─" * 60)

    total_unrealized = 0
    total_invested = 0
    today = date.today()

    for trade in open_trades:
        ticker = trade['ticker']
        entry_price = trade['entry_price']
        shares = trade['shares']
        entry_date = datetime.strptime(trade['entry_date'], "%Y-%m-%d").date()
        days_held = (today - entry_date).days

        # Get current price
        try:
            current_price = get_current_price(ticker)
        except Exception:
            current_price = None

        if current_price:
            change_pct = ((current_price - entry_price) / entry_price) * 100
            unrealized = (current_price - entry_price) * shares
            total_unrealized += unrealized
            price_str = f"${current_price:.2f}"
            change_str = f"{change_pct:+.1f}%"
        else:
            price_str = "N/A"
            change_str = ""
            unrealized = 0

        total_invested += entry_price * shares

        # Stop and target stored directly on trade
        stop = trade['stop_price'] if trade['stop_price'] else entry_price * (1 - config.DEFAULT_STOP_PCT)
        target = trade['target_price'] if trade['target_price'] else entry_price * (1 + config.DEFAULT_TARGET_PCT)

        click.echo(f"{ticker:<6} Entry: ${entry_price:.2f}  Now: {price_str}  {change_str}  ({days_held}d)")
        click.echo(f"       Stop: ${stop:.2f}   Target: ${target:.2f}   Shares: {shares}")
        if trade['notes']:
            click.echo(f"       Notes: {trade['notes']}")
        click.echo()

    click.echo("─" * 60)
    if total_unrealized >= 0:
        click.echo(f"Total unrealized: +${total_unrealized:.2f}")
    else:
        click.echo(f"Total unrealized: -${abs(total_unrealized):.2f}")
    click.echo(f"Total invested: ${total_invested:.2f}")


@cli.command()
@click.option("--days", "-d", default=30, help="Days of history to show")
def history(days):
    """Show closed paper trade history with stats."""
    cutoff_date = (date.today() - timedelta(days=days)).isoformat()

    with get_db() as conn:
        cursor = conn.execute(
            """
            SELECT ticker, entry_date, entry_price, exit_date, exit_price,
                   exit_reason, return_pct, return_dollars, days_held, shares
            FROM trades
            WHERE status = 'CLOSED' AND exit_date >= ?
            ORDER BY exit_date DESC
            """,
            (cutoff_date,)
        )
        closed_trades = cursor.fetchall()

    if not closed_trades:
        click.echo(f"No closed trades in the last {days} days.")
        return

    click.echo()
    click.echo(f"Closed Trades (last {days} days)")
    click.echo("─" * 70)

    wins = 0
    losses = 0
    total_return_dollars = 0
    total_return_pct = 0
    win_returns = []
    loss_returns = []

    for trade in closed_trades:
        pct = trade['return_pct'] or 0
        dollars = trade['return_dollars'] or 0
        total_return_dollars += dollars
        total_return_pct += pct

        if pct > 0:
            wins += 1
            win_returns.append(pct)
        else:
            losses += 1
            loss_returns.append(pct)

        result = "✅" if pct > 0 else "❌"
        click.echo(
            f"{result} {trade['ticker']:<6} "
            f"${trade['entry_price']:.2f} → ${trade['exit_price']:.2f}  "
            f"{pct:+.1f}% (${dollars:+.2f})  {trade['days_held']}d  {trade['exit_reason']}"
        )

    # Stats summary
    total_trades = len(closed_trades)
    win_rate = (wins / total_trades * 100) if total_trades > 0 else 0
    avg_win = sum(win_returns) / len(win_returns) if win_returns else 0
    avg_loss = sum(loss_returns) / len(loss_returns) if loss_returns else 0

    # Expectancy = (Win% * Avg Win) + (Loss% * Avg Loss)
    expectancy = (win_rate/100 * avg_win) + ((100-win_rate)/100 * avg_loss)

    click.echo()
    click.echo("─" * 70)
    click.echo("SUMMARY")
    click.echo("─" * 70)
    click.echo(f"  Total trades: {total_trades}")
    click.echo(f"  Winners: {wins} ({win_rate:.0f}%)")
    click.echo(f"  Losers: {losses}")
    click.echo(f"  Avg win: {avg_win:+.1f}%")
    click.echo(f"  Avg loss: {avg_loss:+.1f}%")
    click.echo(f"  Expectancy: {expectancy:+.2f}%")
    click.echo()
    click.echo(f"  Total return: ${total_return_dollars:+.2f}")
    click.echo(f"  Portfolio impact: {total_return_dollars/config.PAPER_PORTFOLIO_SIZE*100:+.2f}%")


@cli.command()
def performance():
    """Show comprehensive paper trading performance report."""
    today = date.today()

    with get_db() as conn:
        # Get all trades
        cursor = conn.execute(
            """
            SELECT t.*, s.total_score, s.insider_score, s.options_score, s.social_score,
                   s.insider_details
            FROM trades t
            LEFT JOIN signals s ON t.signal_id = s.id
            ORDER BY t.entry_date
            """
        )
        all_trades = cursor.fetchall()

    if not all_trades:
        click.echo()
        click.echo("Paper Trading Performance")
        click.echo("═" * 60)
        click.echo()
        click.echo("No trades yet.")
        click.echo()
        click.echo("To start paper trading:")
        click.echo("  1. Run 'python3 daily_run.py evening' to generate signals")
        click.echo("  2. Run 'python3 daily_run.py top' to see today's signals")
        click.echo("  3. Run 'python3 daily_run.py enter TICKER PRICE' to log a trade")
        click.echo()
        return

    open_trades = [t for t in all_trades if t['status'] == 'OPEN']
    closed_trades = [t for t in all_trades if t['status'] == 'CLOSED']

    # Find date range
    first_trade = datetime.strptime(all_trades[0]['entry_date'], "%Y-%m-%d").date()
    days_trading = (today - first_trade).days + 1

    click.echo()
    click.echo("Paper Trading Performance")
    click.echo("═" * 60)
    click.echo(f"Period: {first_trade.strftime('%b %d')} - {today.strftime('%b %d, %Y')} ({days_trading} days)")
    click.echo()

    # Closed trades stats
    if closed_trades:
        wins = [t for t in closed_trades if (t['return_pct'] or 0) > 0]
        losses = [t for t in closed_trades if (t['return_pct'] or 0) <= 0]
        total_return = sum(t['return_dollars'] or 0 for t in closed_trades)
        win_rate = len(wins) / len(closed_trades) * 100

        avg_win = sum(t['return_pct'] for t in wins) / len(wins) if wins else 0
        avg_loss = sum(t['return_pct'] for t in losses) / len(losses) if losses else 0
        expectancy = (win_rate/100 * avg_win) + ((100-win_rate)/100 * avg_loss)

        click.echo("CLOSED TRADES")
        click.echo("─" * 40)
        click.echo(f"  Total: {len(closed_trades)}")
        click.echo(f"  Winners: {len(wins)} ({win_rate:.0f}%)")
        click.echo(f"  Losers: {len(losses)}")
        click.echo(f"  Avg win: {avg_win:+.1f}%")
        click.echo(f"  Avg loss: {avg_loss:+.1f}%")
        click.echo(f"  Expectancy: {expectancy:+.2f}% per trade")
        click.echo(f"  Total return: ${total_return:+.2f} ({total_return/config.PAPER_PORTFOLIO_SIZE*100:+.2f}% of portfolio)")
        click.echo()

        # Breakdown by score
        click.echo("BY SIGNAL SCORE")
        click.echo("─" * 40)
        high_score = [t for t in closed_trades if t['total_score'] and t['total_score'] >= 50]
        med_score = [t for t in closed_trades if t['total_score'] and 35 <= t['total_score'] < 50]
        low_score = [t for t in closed_trades if t['total_score'] and t['total_score'] < 35]
        no_signal = [t for t in closed_trades if not t['total_score']]

        for label, trades in [("High (50+)", high_score), ("Medium (35-49)", med_score),
                               ("Low (<35)", low_score), ("No signal", no_signal)]:
            if trades:
                w = len([t for t in trades if (t['return_pct'] or 0) > 0])
                avg = sum(t['return_pct'] or 0 for t in trades) / len(trades)
                click.echo(f"  {label}: {len(trades)} trades, {w}/{len(trades)} wins, {avg:+.1f}% avg")

        click.echo()

        # Breakdown by insider type (parse insider_details JSON)
        import json
        ceo_cfo_trades = []
        other_insider_trades = []

        for t in closed_trades:
            if t['insider_details']:
                try:
                    details = json.loads(t['insider_details'])
                    if details.get('ceo_cfo_buying'):
                        ceo_cfo_trades.append(t)
                    elif details.get('unique_buyers', 0) > 0:
                        other_insider_trades.append(t)
                except (json.JSONDecodeError, TypeError):
                    pass

        if ceo_cfo_trades or other_insider_trades:
            click.echo("BY INSIDER TYPE")
            click.echo("─" * 40)
            if ceo_cfo_trades:
                w = len([t for t in ceo_cfo_trades if (t['return_pct'] or 0) > 0])
                avg = sum(t['return_pct'] or 0 for t in ceo_cfo_trades) / len(ceo_cfo_trades)
                click.echo(f"  CEO/CFO buying: {len(ceo_cfo_trades)} trades, {w}/{len(ceo_cfo_trades)} wins, {avg:+.1f}% avg")
            if other_insider_trades:
                w = len([t for t in other_insider_trades if (t['return_pct'] or 0) > 0])
                avg = sum(t['return_pct'] or 0 for t in other_insider_trades) / len(other_insider_trades)
                click.echo(f"  Other insider: {len(other_insider_trades)} trades, {w}/{len(other_insider_trades)} wins, {avg:+.1f}% avg")
            click.echo()

    else:
        click.echo("CLOSED TRADES")
        click.echo("─" * 40)
        click.echo("  None yet")
        click.echo()

    # Open positions
    click.echo("OPEN POSITIONS")
    click.echo("─" * 40)
    if open_trades:
        total_unrealized = 0
        for t in open_trades:
            try:
                current = get_current_price(t['ticker'])
                pnl = (current - t['entry_price']) * t['shares']
                total_unrealized += pnl
                pct = ((current - t['entry_price']) / t['entry_price']) * 100
                click.echo(f"  {t['ticker']}: ${t['entry_price']:.2f} → ${current:.2f} ({pct:+.1f}%)")
            except Exception:
                click.echo(f"  {t['ticker']}: ${t['entry_price']:.2f} → N/A")
        click.echo(f"  Total unrealized: ${total_unrealized:+.2f}")
    else:
        click.echo("  None")
    click.echo()

    # Status assessment
    click.echo("─" * 60)
    total_closed = len(closed_trades)
    if total_closed < 10:
        click.echo(f"Status: Too early to judge (need 10+ trades, have {total_closed})")
    elif total_closed < 20:
        click.echo(f"Status: Early results ({total_closed} trades) - continue monitoring")
    else:
        if closed_trades:
            win_rate = len([t for t in closed_trades if (t['return_pct'] or 0) > 0]) / len(closed_trades) * 100
            if win_rate >= 55 and expectancy > 0:
                click.echo(f"Status: System appears profitable ({win_rate:.0f}% win rate, {expectancy:+.2f}% expectancy)")
            elif expectancy > 0:
                click.echo(f"Status: Profitable but watch win rate ({win_rate:.0f}%)")
            else:
                click.echo(f"Status: Review strategy - negative expectancy ({expectancy:+.2f}%)")
    click.echo("═" * 60)


# Insider-specific commands
@cli.command("insider-collect")
@click.option("--count", "-c", default=100, help="Number of filings to fetch")
def insider_collect(count):
    """Fetch latest insider trading data from SEC EDGAR."""
    click.echo(f"Collecting insider data ({count} filings)...")
    click.echo()

    stats = collect_insider_data(count=count, purchases_only=True)

    click.echo("Results:")
    click.echo(f"  Filings fetched: {stats['filings_fetched']}")
    click.echo(f"  Filings parsed:  {stats['filings_parsed']}")
    click.echo(f"  Purchases found: {stats['purchases_found']}")
    click.echo(f"  New trades saved: {stats['trades_saved']}")

    if stats["errors"]:
        click.echo(f"  Errors: {len(stats['errors'])}")


@cli.command("insider-top")
@click.option("--min-score", "-m", default=5, help="Minimum score to show")
@click.option("--limit", "-l", default=10, help="Number of stocks to show")
def insider_top(min_score, limit):
    """Show stocks with highest insider buying scores."""
    signals = get_top_insider_stocks(min_score=min_score, limit=limit)

    if not signals:
        click.echo("No insider buying found meeting criteria.")
        click.echo("Run: python3 daily_run.py insider-collect")
        return

    click.echo(f"Top {len(signals)} stocks by insider buying score:")
    click.echo("=" * 60)

    for signal in signals:
        click.echo()
        click.echo(format_insider_report(signal))


@cli.command("insider-score")
@click.argument("ticker")
def insider_score_cmd(ticker):
    """Show insider buying score for a specific ticker."""
    signal = score_insider(ticker.upper())
    click.echo()
    click.echo(format_insider_report(signal))


@cli.command("insider-recent")
@click.option("--days", "-d", default=7, help="Days to look back")
@click.option("--min-value", "-v", default=100000, help="Minimum transaction value")
@click.option("--limit", "-l", default=20, help="Number of purchases to show")
def insider_recent(days, min_value, limit):
    """Show recent insider purchases."""
    purchases = get_recent_purchases(days=days, min_value=min_value)[:limit]

    if not purchases:
        click.echo(f"No insider purchases found in last {days} days with value >= ${min_value:,}")
        click.echo("Run: python3 daily_run.py insider-collect")
        return

    click.echo(f"Recent insider purchases (last {days} days, >= ${min_value:,}):")
    click.echo("-" * 80)
    click.echo(f"{'Ticker':<6} {'Date':<12} {'Insider':<25} {'Title':<15} {'Value':>12}")
    click.echo("-" * 80)

    for p in purchases:
        insider = p['insider_name'][:24] if p['insider_name'] else ""
        title = (p['insider_title'] or "")[:14]
        click.echo(
            f"{p['ticker']:<6} {p['trade_date']:<12} {insider:<25} {title:<15} ${p['total_value']:>10,.0f}"
        )


# Options-specific commands
@cli.command("options-collect")
@click.option("--tickers", "-t", default=None, help="Comma-separated tickers (default: watchlist)")
def options_collect(tickers):
    """Collect options data for watchlist or specific tickers."""
    if tickers:
        ticker_list = [t.strip().upper() for t in tickers.split(",")]
    else:
        ticker_list = get_default_watchlist()

    click.echo(f"Collecting options data for {len(ticker_list)} tickers...")
    click.echo()

    stats = collect_options_data(ticker_list, delay=0.3)

    click.echo("Results:")
    click.echo(f"  Tickers collected: {stats['tickers_collected']}/{stats['tickers_requested']}")
    click.echo(f"  Unusual calls: {stats['unusual_calls']}")
    click.echo(f"  Unusual puts: {stats['unusual_puts']}")

    if stats["errors"]:
        click.echo(f"  Errors: {len(stats['errors'])}")


@cli.command("options-top")
@click.option("--min-score", "-m", default=8, help="Minimum score to show")
@click.option("--limit", "-l", default=10, help="Number of stocks to show")
def options_top(min_score, limit):
    """Show stocks with highest options activity scores."""
    signals = get_top_options_stocks(min_score=min_score, limit=limit)

    if not signals:
        click.echo("No significant options activity found.")
        click.echo("Run: python3 daily_run.py options-collect")
        return

    click.echo(f"Top {len(signals)} stocks by options score:")
    click.echo("=" * 60)

    for signal in signals:
        click.echo()
        click.echo(format_options_report(signal))


@cli.command("options-score")
@click.argument("ticker")
def options_score_cmd(ticker):
    """Show options activity score for a specific ticker."""
    signal = score_options(ticker.upper())
    click.echo()
    click.echo(format_options_report(signal))


@cli.command("options-unusual")
@click.option("--min-ratio", "-r", default=2.0, help="Minimum call volume ratio")
@click.option("--limit", "-l", default=20, help="Number of stocks to show")
def options_unusual(min_ratio, limit):
    """Show stocks with unusual options activity today."""
    unusual = get_unusual_options(min_call_ratio=min_ratio, limit=limit)

    if not unusual:
        click.echo("No unusual options activity found today.")
        click.echo("Run: python3 daily_run.py options-collect")
        return

    click.echo(f"Unusual options activity (call volume >= {min_ratio}x average):")
    click.echo("-" * 70)
    click.echo(f"{'Ticker':<8} {'Call Vol':>12} {'Put Vol':>12} {'Ratio':>8} {'P/C':>8}")
    click.echo("-" * 70)

    for o in unusual:
        click.echo(
            f"{o['ticker']:<8} {o['call_volume']:>12,} {o['put_volume']:>12,} "
            f"{o['call_volume_ratio']:>7.1f}x {o['put_call_ratio']:>7.2f}"
        )


# Social-specific commands
@cli.command("social-collect")
@click.option("--tickers", "-t", default=None, help="Comma-separated tickers (default: use Adanos trending)")
@click.option("--source", "-s", type=click.Choice(["adanos", "stocktwits", "all"]), default="all",
              help="Data source: adanos (Reddit via API), stocktwits, or all (default)")
def social_collect(tickers, source):
    """Collect social media data from Adanos API and Stocktwits."""
    if tickers:
        ticker_list = [t.strip().upper() for t in tickers.split(",")]
    else:
        ticker_list = None  # Will use Adanos trending tickers

    click.echo(f"Collecting social media data (source: {source})...")
    click.echo()

    stats = collect_social_data(ticker_list, source=source)

    click.echo()
    click.echo("Results:")
    click.echo(f"  Tickers collected: {stats['tickers_collected']}")
    click.echo(f"  From Adanos API: {stats.get('adanos_tickers', 0)}")
    click.echo(f"  With Stocktwits data: {stats.get('stocktwits_tickers', 0)}")
    click.echo(f"  High velocity: {stats['high_velocity']}")

    if stats["errors"]:
        click.echo(f"  Errors: {len(stats['errors'])}")


@cli.command("social-top")
@click.option("--min-score", "-m", default=6, help="Minimum score to show")
@click.option("--limit", "-l", default=10, help="Number of stocks to show")
def social_top(min_score, limit):
    """Show stocks with highest social activity scores."""
    signals = get_top_social_stocks(min_score=min_score, limit=limit)

    if not signals:
        click.echo("No significant social activity found.")
        click.echo("Run: python3 daily_run.py social-collect")
        return

    click.echo(f"Top {len(signals)} stocks by social score:")
    click.echo("=" * 60)

    for signal in signals:
        click.echo()
        click.echo(format_social_report(signal))


@cli.command("social-score")
@click.argument("ticker")
def social_score_cmd(ticker):
    """Show social activity score for a specific ticker."""
    signal = score_social(ticker.upper())
    click.echo()
    click.echo(format_social_report(signal))


@cli.command("social-trending")
@click.option("--min-mentions", "-m", default=3, help="Minimum mentions to show")
@click.option("--limit", "-l", default=20, help="Number of stocks to show")
def social_trending(min_mentions, limit):
    """Show trending stocks on social media today."""
    trending = get_trending_tickers(min_mentions=min_mentions, limit=limit)

    if not trending:
        click.echo("No trending stocks found today.")
        click.echo("Run: python3 daily_run.py social-collect")
        return

    click.echo(f"Trending stocks (min {min_mentions} mentions):")
    click.echo("-" * 75)
    click.echo(f"{'Ticker':<8} {'Adanos':>8} {'Stocktwits':>10} {'Velocity':>10} {'Sentiment':>10} {'Bullish':>8}")
    click.echo("-" * 75)

    for t in trending:
        bullish_pct = t['bullish_ratio'] * 100 if t['bullish_ratio'] else 50
        click.echo(
            f"{t['ticker']:<8} {t['reddit_mentions']:>8} {t['stocktwits_mentions']:>10} "
            f"{t['combined_velocity']:>9.0f}% {t['reddit_sentiment']:>10.2f} {bullish_pct:>7.0f}%"
        )


# Validation commands
@cli.command("validate")
def validate_cmd():
    """Run insider buying validation analysis."""
    from validate_insider import run_validation

    result = run_validation()

    click.echo()
    click.echo("-" * 60)
    if result.get("proceed") is True:
        click.echo("RECOMMENDATION: Proceed with development")
    elif result.get("proceed") is False:
        click.echo("RECOMMENDATION: Stop and reconsider approach")
    else:
        click.echo("RECOMMENDATION: Collect more data first")


@cli.command("validate-backfill")
@click.option("--months", "-m", default=6, help="Months of history to fetch")
def validate_backfill(months):
    """Backfill historical insider data for validation."""
    from validate_insider import run_validation_backfill

    click.echo(f"Backfilling {months} months of insider data...")
    click.echo("This may take a while (respecting SEC rate limits)...")
    click.echo()

    stats = run_validation_backfill(months)

    click.echo()
    click.echo("Backfill complete!")
    click.echo(f"  Days processed: {stats['days_processed']}")
    click.echo(f"  Purchases found: {stats['purchases_found']}")
    click.echo(f"  Trades saved: {stats['trades_saved']}")
    click.echo()
    click.echo("Next: Run 'python3 daily_run.py validate-calculate' to calculate returns")


@cli.command("validate-calculate")
def validate_calculate():
    """Calculate returns for insider buying events."""
    from validate_insider import run_validation_calculate

    click.echo("Calculating returns for insider events...")
    click.echo("This requires fetching historical price data...")
    click.echo()

    events = run_validation_calculate()

    click.echo()
    click.echo(f"Processed {len(events)} events")
    click.echo()
    click.echo("Next: Run 'python3 daily_run.py validate' to see the analysis")


@cli.command("validate-report")
def validate_report():
    """Show the latest validation report."""
    from validate_insider import load_validation_events, analyze_returns, format_validation_report

    events = load_validation_events(min_value=50000)

    if len(events) < 50:
        click.echo(f"Only {len(events)} validated events found.")
        click.echo("Run 'python3 daily_run.py validate-calculate' first.")
        return

    results = analyze_returns(events)
    report = format_validation_report(results)
    click.echo(report)


if __name__ == "__main__":
    cli()
