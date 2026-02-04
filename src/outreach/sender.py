"""
Email sending with warm-up awareness.

Handles:
- SMTP connection and sending
- Domain warm-up limits
- Business hours enforcement
- Delay between sends
"""

import logging
import smtplib
import time
from datetime import datetime, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Optional

from src.outreach.config import OUTREACH_CONFIG
from src.outreach.db import (
    can_send_today,
    record_email_sent,
    get_warmup_stats,
    get_warmup_limit,
)

logger = logging.getLogger(__name__)


class SendResult:
    """Result of an email send attempt."""
    def __init__(
        self,
        success: bool,
        message: str = "",
        error: Optional[str] = None,
        bounced: bool = False,
    ):
        self.success = success
        self.message = message
        self.error = error
        self.bounced = bounced


def is_within_send_window() -> tuple[bool, str]:
    """Check if current time is within the send window."""
    now = datetime.now()

    # Check day of week
    day_name = now.strftime('%a')
    allowed_days = OUTREACH_CONFIG.get('SEND_DAYS', ['Mon', 'Tue', 'Wed', 'Thu', 'Fri'])
    if day_name not in allowed_days:
        return False, f"Today ({day_name}) is not a send day"

    # Check time window
    start_str = OUTREACH_CONFIG.get('SEND_WINDOW_START', '09:00')
    end_str = OUTREACH_CONFIG.get('SEND_WINDOW_END', '17:00')

    try:
        start_time = datetime.strptime(start_str, '%H:%M').time()
        end_time = datetime.strptime(end_str, '%H:%M').time()
        current_time = now.time()

        if current_time < start_time:
            return False, f"Before send window (starts at {start_str})"
        if current_time > end_time:
            return False, f"After send window (ended at {end_str})"

        return True, "Within send window"
    except ValueError as e:
        logger.error("Invalid time format in config: %s", e)
        return True, "Time check failed, allowing send"


def check_warmup_limit() -> tuple[bool, int, Optional[int]]:
    """
    Check if we can send based on warm-up limits.

    Returns:
        (can_send, sent_today, daily_limit)
    """
    return can_send_today()


def get_warmup_status() -> dict:
    """Get current warm-up status for display."""
    stats = get_warmup_stats()
    limit = get_warmup_limit()
    can_send, sent, _ = can_send_today()

    # Calculate week number
    age = stats['domain_age_days']
    if age < 7:
        week = 1
    elif age < 14:
        week = 2
    elif age < 21:
        week = 3
    elif age < 28:
        week = 4
    else:
        week = 5

    return {
        'domain_age_days': age,
        'week': week,
        'sent_today': sent,
        'daily_limit': limit,
        'remaining': (limit - sent) if limit else None,
        'can_send': can_send,
        'first_send_date': stats.get('first_send_date'),
    }


def send_email(
    to_email: str,
    subject: str,
    body: str,
    cc_emails: Optional[list[str]] = None,
    html_body: Optional[str] = None,
    dry_run: bool = False,
) -> SendResult:
    """
    Send a single email.

    Args:
        to_email: Primary recipient
        subject: Email subject
        body: Plain text body
        cc_emails: List of CC recipients
        html_body: Optional HTML version of body
        dry_run: If True, don't actually send

    Returns:
        SendResult with success/failure info
    """
    cc_emails = cc_emails or []

    # Check if dry run
    if dry_run or OUTREACH_CONFIG.get('DRY_RUN', False):
        logger.info("[DRY RUN] Would send email to %s (CC: %s)", to_email, cc_emails)
        return SendResult(
            success=True,
            message=f"[DRY RUN] Would send to {to_email}",
        )

    # Check warm-up limit
    can_send, sent, limit = check_warmup_limit()
    if not can_send:
        return SendResult(
            success=False,
            message=f"Warm-up limit reached ({sent}/{limit} today)",
            error="warmup_limit",
        )

    # Get SMTP config
    smtp_host = OUTREACH_CONFIG.get('SMTP_HOST', 'smtp.gmail.com')
    smtp_port = OUTREACH_CONFIG.get('SMTP_PORT', 587)
    smtp_user = OUTREACH_CONFIG.get('SMTP_USER', '')
    smtp_password = OUTREACH_CONFIG.get('SMTP_PASSWORD', '')
    sender_email = OUTREACH_CONFIG.get('SENDER_EMAIL', smtp_user)
    sender_name = OUTREACH_CONFIG.get('SENDER_NAME', '')

    if not smtp_user or not smtp_password:
        return SendResult(
            success=False,
            message="SMTP credentials not configured",
            error="config_error",
        )

    # Build message
    if html_body:
        msg = MIMEMultipart('alternative')
        msg.attach(MIMEText(body, 'plain', 'utf-8'))
        msg.attach(MIMEText(html_body, 'html', 'utf-8'))
    else:
        msg = MIMEText(body, 'plain', 'utf-8')

    # Set headers
    if sender_name:
        msg['From'] = f"{sender_name} <{sender_email}>"
    else:
        msg['From'] = sender_email
    msg['To'] = to_email
    msg['Subject'] = subject

    if cc_emails:
        msg['Cc'] = ', '.join(cc_emails)

    # All recipients
    all_recipients = [to_email] + cc_emails

    try:
        with smtplib.SMTP(smtp_host, smtp_port, timeout=30) as server:
            server.ehlo()
            server.starttls()
            server.ehlo()
            server.login(smtp_user, smtp_password)
            server.sendmail(sender_email, all_recipients, msg.as_string())

        # Record successful send
        record_email_sent()

        logger.info("Email sent to %s (CC: %s)", to_email, cc_emails)
        return SendResult(
            success=True,
            message=f"Sent to {to_email}",
        )

    except smtplib.SMTPRecipientsRefused as e:
        logger.error("Recipients refused: %s", e)
        return SendResult(
            success=False,
            message="Recipients refused",
            error=str(e),
            bounced=True,
        )
    except smtplib.SMTPException as e:
        logger.error("SMTP error: %s", e)
        return SendResult(
            success=False,
            message="SMTP error",
            error=str(e),
        )
    except Exception as e:
        logger.error("Unexpected error sending email: %s", e)
        return SendResult(
            success=False,
            message="Unexpected error",
            error=str(e),
        )


def send_with_delay(
    to_email: str,
    subject: str,
    body: str,
    cc_emails: Optional[list[str]] = None,
    html_body: Optional[str] = None,
    dry_run: bool = False,
) -> SendResult:
    """
    Send email and wait for the configured delay afterward.

    This should be used when sending multiple emails to space them out.
    """
    result = send_email(to_email, subject, body, cc_emails, html_body, dry_run)

    if result.success and not dry_run:
        delay = OUTREACH_CONFIG.get('MIN_DELAY_BETWEEN_SENDS_SECONDS', 120)
        if delay > 0:
            logger.debug("Waiting %d seconds before next send", delay)
            time.sleep(delay)

    return result


def calculate_next_send_time() -> datetime:
    """
    Calculate when the next email can be sent.

    Takes into account:
    - Business hours
    - Weekdays only
    - Minimum delay between sends
    """
    now = datetime.now()

    # Parse send window
    start_str = OUTREACH_CONFIG.get('SEND_WINDOW_START', '09:00')
    end_str = OUTREACH_CONFIG.get('SEND_WINDOW_END', '17:00')
    allowed_days = OUTREACH_CONFIG.get('SEND_DAYS', ['Mon', 'Tue', 'Wed', 'Thu', 'Fri'])

    try:
        start_time = datetime.strptime(start_str, '%H:%M').time()
        end_time = datetime.strptime(end_str, '%H:%M').time()
    except ValueError:
        # Default to 9-5
        start_time = datetime.strptime('09:00', '%H:%M').time()
        end_time = datetime.strptime('17:00', '%H:%M').time()

    next_time = now

    # If after end time today, move to tomorrow
    if next_time.time() > end_time:
        next_time = next_time.replace(hour=start_time.hour, minute=start_time.minute, second=0)
        next_time += timedelta(days=1)

    # If before start time, move to start time
    if next_time.time() < start_time:
        next_time = next_time.replace(hour=start_time.hour, minute=start_time.minute, second=0)

    # Skip to next allowed day if needed
    day_names = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
    while day_names[next_time.weekday()] not in allowed_days:
        next_time += timedelta(days=1)
        next_time = next_time.replace(hour=start_time.hour, minute=start_time.minute, second=0)

    return next_time
