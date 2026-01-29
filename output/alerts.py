"""
Alert System

Sends notifications for important trading events.
Supports email (default) and SMS (optional via Twilio).

Alert types:
- BREAKOUT: New entry opportunity
- STOP_HIT: Position stopped out
- TARGET_HIT: Profit target reached
- WATCHLIST_ADD: New stock added to watchlist
- PATTERN_FORMING: VCP pattern detected
- WEEKLY_SCAN: Weekly screening summary
"""

import json
import sys
from pathlib import Path
from datetime import datetime
from typing import Optional, List, Dict

sys.path.insert(0, str(Path(__file__).parent.parent))
from utils.db import get_db
from utils.config import config


# Alert type priorities
ALERT_PRIORITIES = {
    'BREAKOUT': 'HIGH',
    'STOP_HIT': 'HIGH',
    'TARGET_HIT': 'HIGH',
    'WATCHLIST_ADD': 'NORMAL',
    'PATTERN_FORMING': 'LOW',
    'WEEKLY_SCAN': 'NORMAL',
}


def send_alert(
    alert_type: str,
    ticker: str,
    message: str,
    details: Optional[Dict] = None,
    send_notification: bool = True
) -> int:
    """
    Send an alert and log it to database.

    Args:
        alert_type: Type of alert (BREAKOUT, STOP_HIT, etc.)
        ticker: Stock ticker symbol
        message: Alert message
        details: Optional dict with additional context
        send_notification: Whether to send email/SMS

    Returns:
        Alert ID
    """
    priority = ALERT_PRIORITIES.get(alert_type, 'NORMAL')

    # Log to database
    with get_db() as conn:
        cursor = conn.execute("""
            INSERT INTO alerts
            (ticker, alert_type, priority, message, details, delivered)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            ticker,
            alert_type,
            priority,
            message,
            json.dumps(details) if details else None,
            False
        ))
        alert_id = cursor.lastrowid

    # Send notification
    if send_notification:
        delivered = _send_notification(alert_type, ticker, message, priority, alert_id)

        if delivered:
            with get_db() as conn:
                conn.execute(
                    "UPDATE alerts SET delivered = 1 WHERE id = ?",
                    (alert_id,)
                )

    return alert_id


def _send_notification(
    alert_type: str,
    ticker: str,
    message: str,
    priority: str,
    alert_id: int
) -> bool:
    """Send notification via configured channels."""
    delivered = False

    # Email notification
    if config.ALERT_EMAIL:
        try:
            subject = f"[Stock Radar V2] {alert_type}: {ticker}"
            delivered = _send_email_alert(subject, message)
        except Exception as e:
            print(f"Email alert failed: {e}")

    # SMS notification (for high priority only)
    if config.ALERT_SMS and priority == 'HIGH':
        try:
            _send_sms_alert(f"{alert_type}: {ticker}\n{message}")
        except Exception as e:
            print(f"SMS alert failed: {e}")

    return delivered


def _send_email_alert(subject: str, body: str) -> bool:
    """Send email alert using existing emailer."""
    try:
        # Import the existing emailer
        from output.emailer import send_email

        send_email(
            to=config.EMAIL_TO,
            subject=subject,
            body=body
        )
        return True
    except ImportError:
        # Fallback to direct SMTP if emailer not available
        import smtplib
        from email.mime.text import MIMEText

        msg = MIMEText(body)
        msg['Subject'] = subject
        msg['From'] = config.EMAIL_FROM
        msg['To'] = config.EMAIL_TO

        with smtplib.SMTP(config.EMAIL_SMTP_SERVER, config.EMAIL_SMTP_PORT) as server:
            server.starttls()
            server.login(config.EMAIL_USERNAME, config.EMAIL_PASSWORD)
            server.send_message(msg)

        return True
    except Exception as e:
        print(f"Failed to send email: {e}")
        return False


def _send_sms_alert(message: str) -> bool:
    """Send SMS alert via Twilio."""
    if not all([config.TWILIO_ACCOUNT_SID, config.TWILIO_AUTH_TOKEN,
                config.TWILIO_FROM_NUMBER, config.ALERT_PHONE_NUMBER]):
        return False

    try:
        from twilio.rest import Client

        client = Client(config.TWILIO_ACCOUNT_SID, config.TWILIO_AUTH_TOKEN)
        client.messages.create(
            body=message[:160],  # SMS limit
            from_=config.TWILIO_FROM_NUMBER,
            to=config.ALERT_PHONE_NUMBER
        )
        return True
    except Exception as e:
        print(f"Failed to send SMS: {e}")
        return False


# ============================================================================
# Alert Formatters
# ============================================================================

def format_breakout_alert(
    ticker: str,
    pivot: float,
    price: float,
    volume_ratio: float,
    entry: float,
    stop: float,
    target: float,
    shares: int
) -> str:
    """Format a breakout alert message."""
    return f"""
BREAKOUT ALERT: {ticker}

Pivot Price: ${pivot:.2f}
Current Price: ${price:.2f} (+{((price-pivot)/pivot)*100:.1f}%)
Volume: {volume_ratio:.1f}x average

SUGGESTED TRADE:
  Entry: ${entry:.2f}
  Stop: ${stop:.2f} ({((entry-stop)/entry)*100:.1f}% risk)
  Target: ${target:.2f} (+{((target-entry)/entry)*100:.1f}%)
  Shares: {shares}
  Position: ${shares * entry:,.0f}

ACTION: Review for potential entry

---
Stock Radar V2
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
STOP HIT: {ticker}

Entry Price: ${entry:.2f}
Exit Price: ${exit_price:.2f}
Return: {return_pct:+.1f}% (${return_dollars:+,.2f})
Days Held: {days_held}

Position closed automatically.

---
Stock Radar V2
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
TARGET HIT: {ticker}

Entry Price: ${entry:.2f}
Exit Price: ${exit_price:.2f}
Return: {return_pct:+.1f}% (${return_dollars:+,.2f})
Days Held: {days_held}

Profit target reached! Position closed.

---
Stock Radar V2
"""


def format_watchlist_add_alert(
    ticker: str,
    pivot: float,
    stop: float,
    target: float,
    trend_score: int,
    pattern_score: int,
    rs_rating: float
) -> str:
    """Format a watchlist add alert message."""
    return f"""
WATCHLIST ADD: {ticker}

Pivot Price: ${pivot:.2f}
Stop: ${stop:.2f}
Target: ${target:.2f}

Scores:
  Trend Template: {trend_score}
  VCP Pattern: {pattern_score}
  RS Rating: {rs_rating:.0f}

Monitoring for breakout with volume confirmation.

---
Stock Radar V2
"""


def format_weekly_scan_alert(
    passing_trend: int,
    passing_fundamentals: int,
    vcp_patterns: int,
    watchlist_count: int,
    top_picks: List[Dict]
) -> str:
    """Format weekly scan summary alert."""
    picks_text = "\n".join([
        f"  {p['ticker']}: Score {p['score']}, RS {p['rs']:.0f}, Pivot ${p['pivot']:.2f}"
        for p in top_picks[:5]
    ])

    return f"""
WEEKLY SCAN RESULTS

Screening Summary:
  Passing Trend Template: {passing_trend}
  Strong Fundamentals: {passing_fundamentals}
  VCP Patterns Detected: {vcp_patterns}
  Total Watchlist: {watchlist_count}

Top Picks This Week:
{picks_text}

---
Stock Radar V2
"""


# ============================================================================
# Alert Retrieval
# ============================================================================

def get_recent_alerts(limit: int = 20, alert_type: str = None) -> List[Dict]:
    """
    Get recent alerts from database.

    Args:
        limit: Maximum number of alerts to return
        alert_type: Filter by alert type

    Returns:
        List of alert dicts
    """
    with get_db() as conn:
        if alert_type:
            cursor = conn.execute("""
                SELECT * FROM alerts
                WHERE alert_type = ?
                ORDER BY sent_at DESC
                LIMIT ?
            """, (alert_type, limit))
        else:
            cursor = conn.execute("""
                SELECT * FROM alerts
                ORDER BY sent_at DESC
                LIMIT ?
            """, (limit,))

        return [dict(row) for row in cursor.fetchall()]


def get_undelivered_alerts() -> List[Dict]:
    """Get alerts that failed to deliver."""
    with get_db() as conn:
        cursor = conn.execute("""
            SELECT * FROM alerts
            WHERE delivered = 0
            ORDER BY sent_at DESC
        """)
        return [dict(row) for row in cursor.fetchall()]


def retry_undelivered_alerts() -> int:
    """Retry sending undelivered alerts."""
    alerts = get_undelivered_alerts()
    count = 0

    for alert in alerts:
        try:
            subject = f"[Stock Radar V2] {alert['alert_type']}: {alert['ticker']}"
            if _send_email_alert(subject, alert['message']):
                with get_db() as conn:
                    conn.execute(
                        "UPDATE alerts SET delivered = 1 WHERE id = ?",
                        (alert['id'],)
                    )
                count += 1
        except Exception as e:
            print(f"Retry failed for alert {alert['id']}: {e}")

    return count


if __name__ == "__main__":
    # Test alert system
    print("Testing Alert System")
    print("=" * 50)

    # Test breakout alert format
    msg = format_breakout_alert(
        ticker='NVDA',
        pivot=140.00,
        price=142.50,
        volume_ratio=2.3,
        entry=142.50,
        stop=130.20,
        target=171.00,
        shares=35
    )
    print("\nBreakout Alert Preview:")
    print(msg)

    # Test stop hit alert format
    msg = format_stop_hit_alert(
        ticker='AAPL',
        entry=185.00,
        exit_price=172.05,
        return_pct=-7.0,
        return_dollars=-452.30,
        days_held=5
    )
    print("\nStop Hit Alert Preview:")
    print(msg)

    # Check recent alerts
    recent = get_recent_alerts(5)
    print(f"\nRecent alerts in database: {len(recent)}")
    for alert in recent:
        print(f"  {alert['sent_at']}: {alert['alert_type']} - {alert['ticker']}")
