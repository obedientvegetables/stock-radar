"""
Email Delivery System

Sends daily signal emails via SMTP.
Supports both plain text and HTML multipart emails.
"""

import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import date
from typing import Optional

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from utils.config import config
from output.formatter import format_daily_email


def send_email(
    subject: str,
    text_body: str,
    html_body: Optional[str] = None,
    to_email: Optional[str] = None,
) -> dict:
    """
    Send an email via SMTP.

    Args:
        subject: Email subject
        text_body: Plain text content
        html_body: HTML content (optional)
        to_email: Recipient email (default: from config)

    Returns:
        Dict with 'success' bool and 'message'
    """
    # Validate config
    if not config.EMAIL_SMTP_SERVER:
        return {"success": False, "message": "EMAIL_SMTP_SERVER not configured"}
    if not config.EMAIL_USERNAME:
        return {"success": False, "message": "EMAIL_USERNAME not configured"}
    if not config.EMAIL_PASSWORD:
        return {"success": False, "message": "EMAIL_PASSWORD not configured"}

    to_email = to_email or config.EMAIL_TO or config.EMAIL_USERNAME

    try:
        # Create message
        if html_body:
            msg = MIMEMultipart('alternative')
            msg.attach(MIMEText(text_body, 'plain'))
            msg.attach(MIMEText(html_body, 'html'))
        else:
            msg = MIMEText(text_body, 'plain')

        msg['Subject'] = subject
        msg['From'] = config.EMAIL_USERNAME
        msg['To'] = to_email

        # Connect and send
        with smtplib.SMTP(config.EMAIL_SMTP_SERVER, config.EMAIL_SMTP_PORT) as server:
            server.starttls()
            server.login(config.EMAIL_USERNAME, config.EMAIL_PASSWORD)
            server.sendmail(config.EMAIL_USERNAME, to_email, msg.as_string())

        return {"success": True, "message": f"Email sent to {to_email}"}

    except smtplib.SMTPAuthenticationError:
        return {"success": False, "message": "SMTP authentication failed. Check EMAIL_USERNAME and EMAIL_PASSWORD."}
    except smtplib.SMTPException as e:
        return {"success": False, "message": f"SMTP error: {str(e)}"}
    except Exception as e:
        return {"success": False, "message": f"Error: {str(e)}"}


def send_daily_email(target_date: Optional[date] = None, to_email: Optional[str] = None) -> dict:
    """
    Generate and send the daily signal email.

    Args:
        target_date: Date to generate email for (default: today)
        to_email: Recipient email (default: from config)

    Returns:
        Dict with 'success' bool and 'message'
    """
    if target_date is None:
        target_date = date.today()

    # Generate email content
    email = format_daily_email(target_date)

    # Send
    result = send_email(
        subject=email['subject'],
        text_body=email['text'],
        html_body=email['html'],
        to_email=to_email,
    )

    return result


def test_email_connection() -> dict:
    """
    Test SMTP connection without sending an email.

    Returns:
        Dict with 'success' bool and 'message'
    """
    if not config.EMAIL_SMTP_SERVER:
        return {"success": False, "message": "EMAIL_SMTP_SERVER not configured"}
    if not config.EMAIL_USERNAME:
        return {"success": False, "message": "EMAIL_USERNAME not configured"}
    if not config.EMAIL_PASSWORD:
        return {"success": False, "message": "EMAIL_PASSWORD not configured"}

    try:
        with smtplib.SMTP(config.EMAIL_SMTP_SERVER, config.EMAIL_SMTP_PORT) as server:
            server.starttls()
            server.login(config.EMAIL_USERNAME, config.EMAIL_PASSWORD)
            server.noop()

        return {"success": True, "message": "SMTP connection successful"}

    except smtplib.SMTPAuthenticationError:
        return {"success": False, "message": "Authentication failed. Check credentials."}
    except smtplib.SMTPException as e:
        return {"success": False, "message": f"SMTP error: {str(e)}"}
    except Exception as e:
        return {"success": False, "message": f"Connection error: {str(e)}"}


def send_test_email(to_email: Optional[str] = None) -> dict:
    """
    Send a test email to verify configuration.

    Args:
        to_email: Recipient email (default: from config)

    Returns:
        Dict with 'success' bool and 'message'
    """
    subject = "Stock Radar - Test Email"
    text_body = """This is a test email from Stock Radar.

If you received this, your email configuration is working correctly.

Configuration:
  SMTP Server: {server}
  SMTP Port: {port}
  From: {username}

Stock Radar is configured and ready to send daily signals.
""".format(
        server=config.EMAIL_SMTP_SERVER,
        port=config.EMAIL_SMTP_PORT,
        username=config.EMAIL_USERNAME,
    )

    html_body = """<!DOCTYPE html>
<html>
<head>
    <style>
        body { font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto; padding: 20px; }
        .container { background: #f5f5f5; padding: 20px; border-radius: 8px; }
        h1 { color: #333; }
        .success { color: #28a745; font-size: 18px; }
        .config { background: white; padding: 15px; border-radius: 4px; margin: 15px 0; }
    </style>
</head>
<body>
    <div class="container">
        <h1>Stock Radar</h1>
        <p class="success">Test email received successfully!</p>

        <div class="config">
            <strong>Configuration:</strong><br>
            SMTP Server: {server}<br>
            SMTP Port: {port}<br>
            From: {username}
        </div>

        <p>Stock Radar is configured and ready to send daily signals.</p>
    </div>
</body>
</html>
""".format(
        server=config.EMAIL_SMTP_SERVER,
        port=config.EMAIL_SMTP_PORT,
        username=config.EMAIL_USERNAME,
    )

    return send_email(subject, text_body, html_body, to_email)


if __name__ == "__main__":
    print("Testing email system...")
    print()

    # Test connection
    print("Testing SMTP connection...")
    result = test_email_connection()
    print(f"  {result['message']}")

    if result['success']:
        print()
        print("Sending test email...")
        result = send_test_email()
        print(f"  {result['message']}")
