"""
Email Content Formatter

Formats daily signals into clean email content.
Generates both plain text and HTML versions.
"""

from datetime import date, datetime, timedelta
from typing import Optional

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from utils.config import config
from utils.db import get_db
from signals.combiner import get_top_signals
from collectors.market import get_current_price


def get_open_positions():
    """Get all open paper trading positions."""
    with get_db() as conn:
        cursor = conn.execute(
            """
            SELECT t.ticker, t.entry_date, t.entry_price, t.shares, t.notes,
                   t.stop_price, t.target_price
            FROM trades t
            WHERE t.status = 'OPEN'
            ORDER BY t.entry_date DESC
            """
        )
        return cursor.fetchall()


def get_recent_closed_trades(days: int = 7):
    """Get recently closed paper trades."""
    cutoff = (date.today() - timedelta(days=days)).isoformat()
    with get_db() as conn:
        cursor = conn.execute(
            """
            SELECT ticker, entry_date, entry_price, exit_date, exit_price,
                   exit_reason, return_pct, return_dollars, days_held
            FROM trades
            WHERE status = 'CLOSED' AND exit_date >= ?
            ORDER BY exit_date DESC
            """,
            (cutoff,)
        )
        return cursor.fetchall()


def get_trading_stats():
    """Get overall paper trading statistics."""
    with get_db() as conn:
        cursor = conn.execute(
            """
            SELECT COUNT(*) as total,
                   SUM(CASE WHEN return_pct > 0 THEN 1 ELSE 0 END) as wins,
                   SUM(return_dollars) as total_return
            FROM trades
            WHERE status = 'CLOSED'
            """
        )
        row = cursor.fetchone()
        if row and row['total'] > 0:
            return {
                'total': row['total'],
                'wins': row['wins'] or 0,
                'win_rate': (row['wins'] or 0) / row['total'] * 100,
                'total_return': row['total_return'] or 0,
            }
        return None


def format_daily_email(target_date: Optional[date] = None) -> dict:
    """
    Format the daily signal email.

    Args:
        target_date: Date to generate email for (default: today)

    Returns:
        Dict with 'subject', 'text', 'html' keys
    """
    if target_date is None:
        target_date = date.today()

    # Get signals
    all_signals = get_top_signals(target_date=target_date, action_filter=None, limit=50)
    trade_signals = [s for s in all_signals if s['action'] == 'TRADE']
    watch_signals = [s for s in all_signals if s['action'] == 'WATCH']

    # Build subject
    if trade_signals:
        top_tickers = ", ".join([s['ticker'] for s in trade_signals[:3]])
        subject = f"Stock Radar {target_date.strftime('%m/%d')}: {len(trade_signals)} TRADE - {top_tickers}"
    elif watch_signals:
        subject = f"Stock Radar {target_date.strftime('%m/%d')}: {len(watch_signals)} WATCH signals"
    else:
        subject = f"Stock Radar {target_date.strftime('%m/%d')}: No signals today"

    # Build text content
    text = format_text_email(target_date, trade_signals, watch_signals)

    # Build HTML content
    html = format_html_email(target_date, trade_signals, watch_signals)

    return {
        'subject': subject,
        'text': text,
        'html': html,
    }


def format_text_email(target_date: date, trade_signals: list, watch_signals: list) -> str:
    """Format plain text email content."""
    lines = [
        f"STOCK RADAR - {target_date.strftime('%A, %B %d, %Y')}",
        "=" * 50,
        "",
    ]

    # Get paper trading data
    open_positions = get_open_positions()
    recent_trades = get_recent_closed_trades(days=7)
    stats = get_trading_stats()

    # Summary
    lines.extend([
        "SUMMARY",
        "-" * 30,
        f"TRADE signals: {len(trade_signals)}",
        f"WATCH signals: {len(watch_signals)}",
    ])

    if stats:
        lines.append(f"Running win rate: {stats['win_rate']:.0f}% ({stats['wins']}/{stats['total']} trades)")

    lines.append("")

    # Trade signals
    if trade_signals:
        lines.extend([
            "TRADE SIGNALS (Action Required)",
            "=" * 50,
            "",
        ])

        for sig in trade_signals:
            lines.extend(format_signal_text(sig))
            lines.append("")

    # Watch signals
    if watch_signals:
        lines.extend([
            "WATCH LIST (Monitoring)",
            "=" * 50,
            "",
        ])

        for sig in watch_signals[:10]:  # Limit watch to 10
            lines.extend(format_signal_text(sig, brief=True))
            lines.append("")

    # Open positions section
    if open_positions:
        lines.extend([
            "OPEN POSITIONS",
            "=" * 50,
            "",
        ])
        total_unrealized = 0
        for pos in open_positions:
            try:
                current = get_current_price(pos['ticker'])
                pct = ((current - pos['entry_price']) / pos['entry_price']) * 100
                unrealized = (current - pos['entry_price']) * pos['shares']
                total_unrealized += unrealized
                lines.append(f"  {pos['ticker']}: ${pos['entry_price']:.2f} -> ${current:.2f} ({pct:+.1f}%)")
            except Exception:
                lines.append(f"  {pos['ticker']}: ${pos['entry_price']:.2f} (price unavailable)")
        lines.extend([
            "",
            f"  Total unrealized: ${total_unrealized:+.2f}",
            "",
        ])

    # Recent closed trades
    if recent_trades:
        lines.extend([
            "RECENT TRADES (Last 7 Days)",
            "=" * 50,
            "",
        ])
        for trade in recent_trades[:5]:  # Limit to 5
            result = "WIN" if (trade['return_pct'] or 0) > 0 else "LOSS"
            lines.append(
                f"  {result} {trade['ticker']}: {trade['return_pct']:+.1f}% (${trade['return_dollars']:+.2f}) - {trade['exit_reason']}"
            )
        lines.append("")

    # Footer
    lines.extend([
        "-" * 50,
        "Decision Rules:",
        f"  TRADE: (Insider >= {config.INSIDER_MIN_SCORE} OR Options >= {config.OPTIONS_MIN_SCORE}) AND Social >= {config.SOCIAL_MIN_SCORE}",
        f"  WATCH: Insider >= 10 OR Options >= 10",
        "",
        "Position Sizing:",
        "  FULL:    Total >= 60",
        "  HALF:    Total >= 45",
        "  QUARTER: Total >= 30",
        "",
        "Generated by Stock Radar",
    ])

    return "\n".join(lines)


def format_signal_text(sig: dict, brief: bool = False) -> list[str]:
    """Format a single signal for text email."""
    lines = [
        f"{sig['ticker']} - Score: {sig['total_score']}/{config.TOTAL_MAX_SCORE}",
        f"  Action: {sig['action']} | Tier: {sig['tier']} | Size: {sig['position_size'] or 'N/A'}",
    ]

    if not brief:
        lines.extend([
            f"  Insider:  {sig['insider_score']:>2}/{config.INSIDER_MAX_SCORE}  Options: {sig['options_score']:>2}/{config.OPTIONS_MAX_SCORE}  Social: {sig['social_score']:>2}/{config.SOCIAL_MAX_SCORE}",
        ])

        if sig.get('entry_price'):
            lines.extend([
                f"  Entry: ${sig['entry_price']:.2f}  Stop: ${sig.get('stop_price', 0):.2f}  Target: ${sig.get('target_price', 0):.2f}",
            ])

        if sig.get('notes'):
            lines.append(f"  Notes: {sig['notes']}")

    return lines


def format_html_email(target_date: date, trade_signals: list, watch_signals: list) -> str:
    """Format HTML email content."""
    html = f"""<!DOCTYPE html>
<html>
<head>
    <style>
        body {{ font-family: Arial, sans-serif; max-width: 700px; margin: 0 auto; padding: 20px; background: #f5f5f5; }}
        .container {{ background: white; padding: 20px; border-radius: 8px; }}
        h1 {{ color: #333; font-size: 24px; margin-bottom: 5px; }}
        h2 {{ color: #666; font-size: 18px; margin-top: 20px; border-bottom: 2px solid #ddd; padding-bottom: 5px; }}
        .summary {{ background: #f0f7ff; padding: 15px; border-radius: 5px; margin: 10px 0; }}
        .signal {{ background: #fafafa; padding: 15px; margin: 10px 0; border-left: 4px solid #ccc; border-radius: 4px; }}
        .signal.trade {{ border-left-color: #28a745; }}
        .signal.watch {{ border-left-color: #ffc107; }}
        .ticker {{ font-size: 20px; font-weight: bold; color: #333; }}
        .score {{ font-size: 18px; color: #666; }}
        .action {{ display: inline-block; padding: 3px 10px; border-radius: 3px; font-weight: bold; }}
        .action.trade {{ background: #28a745; color: white; }}
        .action.watch {{ background: #ffc107; color: #333; }}
        .scores {{ color: #666; margin: 5px 0; }}
        .trade-params {{ background: #e8f5e9; padding: 10px; border-radius: 4px; margin-top: 10px; }}
        .notes {{ color: #555; font-style: italic; margin-top: 5px; }}
        .footer {{ color: #999; font-size: 12px; margin-top: 30px; text-align: center; }}
    </style>
</head>
<body>
    <div class="container">
        <h1>Stock Radar</h1>
        <div style="color: #666;">{target_date.strftime('%A, %B %d, %Y')}</div>

        <div class="summary">
            <strong>Today's Summary:</strong><br>
            TRADE signals: <strong>{len(trade_signals)}</strong><br>
            WATCH signals: <strong>{len(watch_signals)}</strong>
        </div>
"""

    # Trade signals
    if trade_signals:
        html += """
        <h2>TRADE Signals</h2>
"""
        for sig in trade_signals:
            html += format_signal_html(sig, signal_type='trade')

    # Watch signals
    if watch_signals:
        html += """
        <h2>Watch List</h2>
"""
        for sig in watch_signals[:10]:
            html += format_signal_html(sig, signal_type='watch', brief=True)

    # No signals
    if not trade_signals and not watch_signals:
        html += """
        <div class="signal">
            <p>No significant signals detected today.</p>
            <p>The system scans for convergence of insider buying, unusual options activity, and social momentum.</p>
        </div>
"""

    # Paper trading positions and stats
    open_positions = get_open_positions()
    recent_trades = get_recent_closed_trades(days=7)
    stats = get_trading_stats()

    # Open positions section
    if open_positions:
        html += """
        <h2>Open Positions</h2>
        <table style="width: 100%; border-collapse: collapse; margin: 10px 0;">
            <tr style="background: #f5f5f5; border-bottom: 1px solid #ddd;">
                <th style="padding: 8px; text-align: left;">Ticker</th>
                <th style="padding: 8px; text-align: right;">Entry</th>
                <th style="padding: 8px; text-align: right;">Current</th>
                <th style="padding: 8px; text-align: right;">P&L</th>
            </tr>
"""
        total_unrealized = 0
        for pos in open_positions:
            try:
                current = get_current_price(pos['ticker'])
                pct = ((current - pos['entry_price']) / pos['entry_price']) * 100
                unrealized = (current - pos['entry_price']) * pos['shares']
                total_unrealized += unrealized
                color = "#28a745" if pct > 0 else "#dc3545"
                html += f"""
            <tr style="border-bottom: 1px solid #eee;">
                <td style="padding: 8px;"><strong>{pos['ticker']}</strong></td>
                <td style="padding: 8px; text-align: right;">${pos['entry_price']:.2f}</td>
                <td style="padding: 8px; text-align: right;">${current:.2f}</td>
                <td style="padding: 8px; text-align: right; color: {color};">{pct:+.1f}%</td>
            </tr>
"""
            except Exception:
                html += f"""
            <tr style="border-bottom: 1px solid #eee;">
                <td style="padding: 8px;"><strong>{pos['ticker']}</strong></td>
                <td style="padding: 8px; text-align: right;">${pos['entry_price']:.2f}</td>
                <td style="padding: 8px; text-align: right;">N/A</td>
                <td style="padding: 8px; text-align: right;">-</td>
            </tr>
"""
        color = "#28a745" if total_unrealized >= 0 else "#dc3545"
        html += f"""
        </table>
        <p style="margin-top: 5px;"><strong>Total unrealized:</strong> <span style="color: {color};">${total_unrealized:+.2f}</span></p>
"""

    # Recent trades section
    if recent_trades:
        html += """
        <h2>Recent Trades (Last 7 Days)</h2>
        <table style="width: 100%; border-collapse: collapse; margin: 10px 0;">
            <tr style="background: #f5f5f5; border-bottom: 1px solid #ddd;">
                <th style="padding: 8px; text-align: left;">Ticker</th>
                <th style="padding: 8px; text-align: right;">Return</th>
                <th style="padding: 8px; text-align: left;">Reason</th>
            </tr>
"""
        for trade in recent_trades[:5]:
            pct = trade['return_pct'] or 0
            color = "#28a745" if pct > 0 else "#dc3545"
            icon = "✓" if pct > 0 else "✗"
            html += f"""
            <tr style="border-bottom: 1px solid #eee;">
                <td style="padding: 8px;"><strong>{trade['ticker']}</strong></td>
                <td style="padding: 8px; text-align: right; color: {color};">{icon} {pct:+.1f}%</td>
                <td style="padding: 8px;">{trade['exit_reason']}</td>
            </tr>
"""
        html += """
        </table>
"""

    # Win rate footer
    if stats:
        html += f"""
        <div style="background: #f0f7ff; padding: 10px; border-radius: 5px; margin-top: 15px;">
            <strong>Paper Trading Stats:</strong> {stats['wins']}/{stats['total']} wins ({stats['win_rate']:.0f}%) | Total: ${stats['total_return']:+.2f}
        </div>
"""

    # Footer
    html += f"""
        <div class="footer">
            <p>Decision Rules: TRADE when primary signal (Insider >= {config.INSIDER_MIN_SCORE} OR Options >= {config.OPTIONS_MIN_SCORE}) + Social >= {config.SOCIAL_MIN_SCORE}</p>
            <p>Generated by Stock Radar</p>
        </div>
    </div>
</body>
</html>
"""

    return html


def format_signal_html(sig: dict, signal_type: str = 'trade', brief: bool = False) -> str:
    """Format a single signal for HTML email."""
    html = f"""
        <div class="signal {signal_type}">
            <span class="ticker">{sig['ticker']}</span>
            <span class="score">Score: {sig['total_score']}/{config.TOTAL_MAX_SCORE}</span>
            <span class="action {signal_type}">{sig['action']}</span>
            <span style="margin-left: 10px;">Tier: {sig['tier']} | Size: {sig['position_size'] or 'N/A'}</span>
            <div class="scores">
                Insider: {sig['insider_score']}/{config.INSIDER_MAX_SCORE} |
                Options: {sig['options_score']}/{config.OPTIONS_MAX_SCORE} |
                Social: {sig['social_score']}/{config.SOCIAL_MAX_SCORE}
            </div>
"""

    if not brief and sig.get('entry_price'):
        html += f"""
            <div class="trade-params">
                Entry: ${sig['entry_price']:.2f} |
                Stop: ${sig.get('stop_price', 0):.2f} |
                Target: ${sig.get('target_price', 0):.2f}
            </div>
"""

    if sig.get('notes'):
        html += f"""
            <div class="notes">{sig['notes']}</div>
"""

    html += """
        </div>
"""

    return html


def preview_email(target_date: Optional[date] = None) -> str:
    """
    Generate a preview of the email content.

    Args:
        target_date: Date to generate preview for

    Returns:
        Formatted text preview
    """
    email = format_daily_email(target_date)

    preview = [
        "=" * 60,
        "EMAIL PREVIEW",
        "=" * 60,
        "",
        f"Subject: {email['subject']}",
        "",
        "-" * 60,
        "TEXT VERSION",
        "-" * 60,
        email['text'],
        "",
        "-" * 60,
        f"HTML VERSION: {len(email['html'])} characters",
        "-" * 60,
    ]

    return "\n".join(preview)


if __name__ == "__main__":
    print("Testing email formatter...")
    print()
    print(preview_email())
