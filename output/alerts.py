"""
V2 Alert System

Sends notifications for important events:
- Breakout alerts
- Stop/target hits
- Watchlist additions
- Daily reports

Supports email delivery (SMS can be added later).
"""

from datetime import datetime, date
from typing import Optional, List, Dict
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from utils.db import get_db
from utils.config import config
from output.emailer import send_email


def send_alert(
    alert_type: str,
    ticker: str,
    message: str,
    send_email_flag: bool = True
) -> int:
    """
    Send an alert and log it to database.
    
    Alert types:
    - BREAKOUT: New entry opportunity
    - STOP_HIT: Position stopped out
    - TARGET_HIT: Profit target reached
    - WATCHLIST_ADD: New stock added to watchlist
    - DAILY_REPORT: End of day summary
    - MORNING_SCAN: Morning scan results
    - WARNING: Risk warning
    
    Args:
        alert_type: Type of alert
        ticker: Stock symbol (or 'SYSTEM' for portfolio-level alerts)
        message: Alert message body
        send_email_flag: Whether to send email notification
    
    Returns:
        alert_id
    """
    # Log to database
    with get_db() as conn:
        cursor = conn.execute("""
            INSERT INTO alerts_v2 (ticker, alert_type, message, delivered)
            VALUES (?, ?, ?, ?)
        """, (ticker, alert_type, message, False))
        
        alert_id = cursor.lastrowid
    
    # Send notification
    if send_email_flag and config.ALERT_EMAIL:
        subject = f"[Stock Radar V2] {alert_type}: {ticker}"
        success = _send_email_notification(subject, message, alert_id)
        
        if success:
            with get_db() as conn:
                conn.execute(
                    "UPDATE alerts_v2 SET delivered = 1 WHERE id = ?",
                    (alert_id,)
                )
    
    return alert_id


def _send_email_notification(subject: str, message: str, alert_id: int) -> bool:
    """Send email notification."""
    try:
        send_email(
            to=config.EMAIL_TO,
            subject=subject,
            body=message
        )
        return True
    except Exception as e:
        print(f"Failed to send alert email: {e}")
        return False


# =============================================================================
# Alert Formatters
# =============================================================================

def format_breakout_alert(
    ticker: str,
    pivot: float,
    price: float,
    volume_ratio: float,
    quality: str = "B"
) -> str:
    """Format a breakout alert message."""
    return f"""
🚀 BREAKOUT ALERT: {ticker} (Grade: {quality})
{'=' * 50}

Pivot Price: ${pivot:.2f}
Current Price: ${price:.2f} (+{((price-pivot)/pivot)*100:.1f}%)
Volume: {volume_ratio:.1f}x average

ACTION REQUIRED: Review for potential entry

Entry Guidelines:
• Enter near current price if volume confirms
• Stop: ${pivot * 0.93:.2f} (7% below pivot)
• Target: ${price * 1.20:.2f} (20% profit)

⚠️  Check earnings calendar before entering!

---
Stock Radar V2 | {datetime.now().strftime('%Y-%m-%d %H:%M')}
"""


def format_stop_hit_alert(
    ticker: str,
    entry: float,
    exit_price: float,
    return_pct: float,
    return_dollars: float,
    days_held: int
) -> str:
    """Format a stop hit alert message."""
    return f"""
🛑 STOP HIT: {ticker}
{'=' * 50}

Position Closed (Stop Loss Triggered)

Entry Price: ${entry:.2f}
Exit Price: ${exit_price:.2f}
Return: {return_pct:+.1f}% (${return_dollars:+,.2f})
Days Held: {days_held}

The stop loss was triggered automatically to protect capital.

Remember: Cutting losses quickly is key to long-term success.

---
Stock Radar V2 | {datetime.now().strftime('%Y-%m-%d %H:%M')}
"""


def format_target_hit_alert(
    ticker: str,
    entry: float,
    exit_price: float,
    return_pct: float,
    return_dollars: float,
    days_held: int
) -> str:
    """Format a target hit alert message."""
    return f"""
🎯 TARGET HIT: {ticker}
{'=' * 50}

Profit Target Reached! 🎉

Entry Price: ${entry:.2f}
Exit Price: ${exit_price:.2f}
Return: {return_pct:+.1f}% (${return_dollars:+,.2f})
Days Held: {days_held}

Congratulations! The profit target was reached.

---
Stock Radar V2 | {datetime.now().strftime('%Y-%m-%d %H:%M')}
"""


def format_watchlist_alert(
    ticker: str,
    pivot: float,
    trend_score: int,
    rs_rating: float,
    notes: str = ""
) -> str:
    """Format a watchlist addition alert."""
    return f"""
👁️ WATCHLIST ADD: {ticker}
{'=' * 50}

New Setup Added to Watchlist

Pivot Price: ${pivot:.2f}
Trend Template: {trend_score}/8 criteria passing
RS Rating: {rs_rating:.1f}

{notes}

Monitor for breakout with volume confirmation.

---
Stock Radar V2 | {datetime.now().strftime('%Y-%m-%d %H:%M')}
"""


def format_morning_scan_alert(
    passing_count: int,
    top_stocks: List[Dict],
    breakout_candidates: List[Dict]
) -> str:
    """Format morning scan results alert."""
    lines = [
        f"☀️ MORNING SCAN RESULTS",
        "=" * 50,
        "",
        f"Stocks Passing Trend Template: {passing_count}",
        "",
    ]
    
    if top_stocks:
        lines.append("Top Candidates by RS Rating:")
        lines.append("-" * 40)
        for i, s in enumerate(top_stocks[:5], 1):
            lines.append(f"{i}. {s['ticker']:<6} RS: {s.get('rs_rating', 0):.1f}  Price: ${s.get('price', 0):.2f}")
        lines.append("")
    
    if breakout_candidates:
        lines.append("⚡ Near Breakout (within 3% of pivot):")
        lines.append("-" * 40)
        for s in breakout_candidates[:5]:
            lines.append(f"   {s['ticker']:<6} Pivot: ${s.get('pivot', 0):.2f}  Current: ${s.get('price', 0):.2f}")
        lines.append("")
    
    lines.extend([
        "Run 'v2-watchlist' for full list.",
        "",
        "---",
        f"Stock Radar V2 | {datetime.now().strftime('%Y-%m-%d %H:%M')}",
    ])
    
    return "\n".join(lines)


def format_daily_report_alert(
    portfolio_value: float,
    daily_pnl: float,
    daily_pnl_pct: float,
    total_pnl: float,
    total_pnl_pct: float,
    open_positions: List[Dict],
    trades_today: List[Dict]
) -> str:
    """Format end of day portfolio report."""
    lines = [
        f"📊 DAILY PORTFOLIO REPORT",
        "=" * 50,
        "",
        f"Portfolio Value: ${portfolio_value:,.2f}",
        f"Today's P&L: ${daily_pnl:+,.2f} ({daily_pnl_pct:+.2f}%)",
        f"Total P&L: ${total_pnl:+,.2f} ({total_pnl_pct:+.2f}%)",
        "",
    ]
    
    if open_positions:
        lines.append(f"Open Positions ({len(open_positions)}):")
        lines.append("-" * 40)
        for pos in open_positions:
            pnl = pos.get('pnl_pct', 0)
            lines.append(
                f"  {pos['ticker']:<6} {pos['shares']:>4} sh  "
                f"Entry: ${pos['entry']:.2f}  P&L: {pnl:+.1f}%"
            )
        lines.append("")
    
    if trades_today:
        lines.append(f"Trades Today ({len(trades_today)}):")
        lines.append("-" * 40)
        for trade in trades_today:
            lines.append(
                f"  {trade['ticker']:<6} {trade['action']:<6} @ ${trade['price']:.2f}  "
                f"{trade.get('return_pct', 0):+.1f}%"
            )
        lines.append("")
    
    lines.extend([
        "---",
        f"Stock Radar V2 | {datetime.now().strftime('%Y-%m-%d %H:%M')}",
    ])
    
    return "\n".join(lines)


def format_warning_alert(ticker: str, warning_type: str, details: str) -> str:
    """Format a warning alert."""
    return f"""
⚠️ WARNING: {ticker}
{'=' * 50}

Type: {warning_type}

{details}

Please review and take appropriate action.

---
Stock Radar V2 | {datetime.now().strftime('%Y-%m-%d %H:%M')}
"""


# =============================================================================
# Alert Retrieval
# =============================================================================

def get_recent_alerts(limit: int = 20, alert_type: str = None) -> List[Dict]:
    """Get recent alerts from database."""
    with get_db() as conn:
        if alert_type:
            cursor = conn.execute("""
                SELECT * FROM alerts_v2
                WHERE alert_type = ?
                ORDER BY sent_at DESC
                LIMIT ?
            """, (alert_type, limit))
        else:
            cursor = conn.execute("""
                SELECT * FROM alerts_v2
                ORDER BY sent_at DESC
                LIMIT ?
            """, (limit,))
        
        return [dict(row) for row in cursor.fetchall()]


def get_undelivered_alerts() -> List[Dict]:
    """Get alerts that failed to deliver."""
    with get_db() as conn:
        cursor = conn.execute("""
            SELECT * FROM alerts_v2
            WHERE delivered = 0
            ORDER BY sent_at DESC
        """)
        return [dict(row) for row in cursor.fetchall()]


def retry_failed_alerts() -> int:
    """Retry sending failed alerts."""
    failed = get_undelivered_alerts()
    retried = 0
    
    for alert in failed:
        subject = f"[Stock Radar V2] {alert['alert_type']}: {alert['ticker']}"
        if _send_email_notification(subject, alert['message'], alert['id']):
            with get_db() as conn:
                conn.execute(
                    "UPDATE alerts_v2 SET delivered = 1 WHERE id = ?",
                    (alert['id'],)
                )
            retried += 1
    
    return retried


# Quick test
if __name__ == "__main__":
    print("Testing Alert System")
    print("=" * 50)
    
    # Test formatting
    print("\nBreakout Alert:")
    print(format_breakout_alert('NVDA', 130.0, 135.50, 2.3, 'A'))
    
    print("\nStop Hit Alert:")
    print(format_stop_hit_alert('AAPL', 180.0, 167.40, -7.0, -630.0, 5))
    
    print("\nTarget Hit Alert:")
    print(format_target_hit_alert('MSFT', 400.0, 480.0, 20.0, 4000.0, 15))
