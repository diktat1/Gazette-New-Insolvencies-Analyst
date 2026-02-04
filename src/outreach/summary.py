"""
Summary email generation for post-send review.

Generates a daily summary of:
- Emails sent today
- Replies received
- Pipeline status
- Follow-ups scheduled
"""

import logging
from datetime import datetime, date
from typing import Optional

from src.outreach.config import OUTREACH_CONFIG
from src.outreach.db import (
    get_pipeline_stats,
    get_recent_replies,
    get_all_batches,
    OutreachBatch,
)
from src.outreach.sender import send_email, get_warmup_status
from src.outreach.followup import get_all_followups_due

logger = logging.getLogger(__name__)


def generate_summary_text(send_results: Optional[dict] = None) -> str:
    """
    Generate plain-text summary of today's outreach activity.

    Args:
        send_results: Optional results from today's send operation

    Returns:
        Plain text summary
    """
    today = date.today()
    today_str = today.strftime("%d %b %Y")

    lines = [
        f"📊 OUTREACH SUMMARY - {today_str}",
        "=" * 50,
        "",
    ]

    # Today's activity from send results
    if send_results:
        processing = send_results.get('processing', {})
        sending = send_results.get('sending', {})
        followups = send_results.get('followups', {})

        lines.append("TODAY'S ACTIVITY")
        lines.append("-" * 30)

        if processing:
            lines.append(f"• Notices analysed: {processing.get('total', 0)}")
            lines.append(f"• Qualified for outreach: {processing.get('qualified', 0)}")
            lines.append(f"• Batches created: {processing.get('batches_created', 0)}")

        if sending:
            lines.append(f"• Emails sent: {sending.get('sent', 0)}")
            if sending.get('failed', 0) > 0:
                lines.append(f"• Failed: {sending.get('failed', 0)}")
            if sending.get('skipped_warmup', 0) > 0:
                lines.append(f"• Skipped (warm-up limit): {sending.get('skipped_warmup', 0)}")

        if followups:
            lines.append(f"• Follow-ups sent: {followups.get('sent', 0)}")

        lines.append("")

    # Pipeline stats
    stats = get_pipeline_stats()
    lines.append("PIPELINE STATUS")
    lines.append("-" * 30)
    lines.append(f"• Queued: {stats.get('queued_count', 0)}")
    lines.append(f"• Awaiting response: {stats.get('awaiting_reply', 0)}")
    lines.append(f"• Replied: {stats.get('replied_count', 0)}")
    lines.append(f"• Response rate: {stats.get('response_rate', 0):.1f}%")
    lines.append("")

    # Recent replies
    recent_replies = get_recent_replies(limit=5)
    if recent_replies:
        lines.append("RECENT REPLIES")
        lines.append("-" * 30)
        for batch in recent_replies:
            company_names = [n.get('company_name', '') for n in batch.notices]
            companies_str = ', '.join(company_names[:2])
            if len(company_names) > 2:
                companies_str += f' + {len(company_names) - 2} more'

            replied_date = batch.replied_at[:10] if batch.replied_at else 'N/A'
            lines.append(f"• {batch.firm}: {companies_str} ({replied_date})")
            if batch.notes:
                lines.append(f"  Notes: {batch.notes[:100]}")
        lines.append("")

    # Follow-ups due
    followups_due = get_all_followups_due()
    if followups_due:
        lines.append(f"FOLLOW-UPS DUE: {len(followups_due)}")
        lines.append("-" * 30)
        for batch, followup_num in followups_due[:5]:
            company_names = [n.get('company_name', '') for n in batch.notices]
            companies_str = ', '.join(company_names[:2])
            lines.append(f"• {batch.firm}: {companies_str} (follow-up #{followup_num})")
        if len(followups_due) > 5:
            lines.append(f"• ... and {len(followups_due) - 5} more")
        lines.append("")

    # Warm-up status
    warmup = get_warmup_status()
    lines.append("WARM-UP STATUS")
    lines.append("-" * 30)
    lines.append(f"• Domain age: {warmup.get('domain_age_days', 0)} days (Week {warmup.get('week', 1)})")
    if warmup.get('daily_limit'):
        lines.append(f"• Today's limit: {warmup.get('daily_limit')}")
        lines.append(f"• Sent today: {warmup.get('sent_today', 0)}")
        remaining = warmup.get('remaining')
        if remaining is not None:
            lines.append(f"• Remaining: {remaining}")
    else:
        lines.append(f"• Sent today: {warmup.get('sent_today', 0)} (no limit)")
    lines.append("")

    # Sent today details
    all_batches = get_all_batches(limit=50)
    today_sent = [b for b in all_batches if b.sent_at and b.sent_at[:10] == today.isoformat()]

    if today_sent:
        lines.append("SENT TODAY")
        lines.append("-" * 30)
        for batch in today_sent:
            company_names = [n.get('company_name', '') for n in batch.notices]
            companies_str = ', '.join(company_names[:2])
            if len(company_names) > 2:
                companies_str += f' + {len(company_names) - 2} more'

            recipient = batch.primary_recipient
            to_email = recipient.get('email', 'N/A') if recipient else 'N/A'
            lines.append(f"• {batch.firm}")
            lines.append(f"  To: {to_email}")
            lines.append(f"  Companies: {companies_str}")
        lines.append("")

    # Footer
    lines.append("-" * 50)
    lines.append("Commands:")
    lines.append("  python outreach.py status     - Full dashboard")
    lines.append("  python outreach.py history    - All sent emails")
    lines.append("  python outreach.py reply <id> - Log a reply")

    return "\n".join(lines)


def send_summary_email(
    send_results: Optional[dict] = None,
    recipient: Optional[str] = None,
    dry_run: bool = False,
) -> bool:
    """
    Send the daily summary email.

    Args:
        send_results: Optional results from today's operations
        recipient: Override recipient (defaults to config)
        dry_run: If True, don't actually send

    Returns:
        True if sent successfully
    """
    to_email = recipient or OUTREACH_CONFIG.get('SUMMARY_EMAIL_TO', '')
    if not to_email:
        logger.warning("No summary email recipient configured")
        return False

    today_str = date.today().strftime("%d %b %Y")
    subject = f"📊 Outreach Summary - {today_str}"

    body = generate_summary_text(send_results)

    if dry_run:
        logger.info("[DRY RUN] Would send summary to %s", to_email)
        print(body)
        return True

    result = send_email(
        to_email=to_email,
        subject=subject,
        body=body,
    )

    if result.success:
        logger.info("Summary email sent to %s", to_email)
        return True
    else:
        logger.error("Failed to send summary: %s", result.error)
        return False


def print_status() -> None:
    """Print current outreach status to console."""
    stats = get_pipeline_stats()
    warmup = get_warmup_status()
    followups_due = get_all_followups_due()

    today = date.today().strftime("%d %b %Y")

    print()
    print("╔" + "═" * 70 + "╗")
    print(f"║{'OUTREACH STATUS - ' + today:^70}║")
    print("╠" + "═" * 70 + "╣")
    print("║" + " " * 70 + "║")

    # Today's stats
    print("║  TODAY" + " " * 63 + "║")
    print(f"║  ├─ Sent today:           {stats.get('sent_today', 0):<43}║")
    print(f"║  └─ Replies today:        {stats.get('replied_today', 0):<43}║")
    print("║" + " " * 70 + "║")

    # Pipeline
    print("║  PIPELINE" + " " * 60 + "║")
    print(f"║  ├─ Queued:               {stats.get('queued_count', 0):<43}║")
    print(f"║  ├─ Awaiting response:    {stats.get('awaiting_reply', 0):<43}║")
    print(f"║  ├─ Replied:              {stats.get('replied_count', 0):<43}║")
    print(f"║  └─ Response rate:        {stats.get('response_rate', 0):.1f}%{' ' * 40}║")
    print("║" + " " * 70 + "║")

    # Warm-up
    print("║  WARM-UP" + " " * 61 + "║")
    age_str = f"{warmup.get('domain_age_days', 0)} days (Week {warmup.get('week', 1)})"
    print(f"║  ├─ Domain age:           {age_str:<43}║")
    if warmup.get('daily_limit'):
        limit_str = f"{warmup.get('sent_today', 0)}/{warmup.get('daily_limit')}"
    else:
        limit_str = f"{warmup.get('sent_today', 0)} (unlimited)"
    print(f"║  └─ Sent/Limit:           {limit_str:<43}║")
    print("║" + " " * 70 + "║")

    # Follow-ups
    if followups_due:
        print(f"║  ⚠ FOLLOW-UPS DUE: {len(followups_due):<50}║")
        print("║" + " " * 70 + "║")

    print("╚" + "═" * 70 + "╝")
    print()
