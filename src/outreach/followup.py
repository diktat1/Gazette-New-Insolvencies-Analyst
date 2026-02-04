"""
Follow-up email logic.

Handles scheduling and sending follow-up emails for batches
that haven't received a response.
"""

import logging
from datetime import datetime, timedelta
from typing import Optional

from src.outreach.config import OUTREACH_CONFIG
from src.outreach.db import (
    OutreachBatch,
    get_batches_for_followup,
    get_batch,
    update_batch_status,
    increment_followup_count,
)
from src.outreach.batcher import OutreachBatchData, OutreachRecipient, NoticeSummary
from src.outreach.templates import render_followup_email
from src.outreach.sender import send_email, is_within_send_window, check_warmup_limit

logger = logging.getLogger(__name__)


def _batch_to_data(batch: OutreachBatch) -> OutreachBatchData:
    """Convert database batch to OutreachBatchData for template rendering."""
    data = OutreachBatchData(firm=batch.firm)

    # Parse recipients
    for r in batch.recipients:
        data.recipients.append(OutreachRecipient(
            name=r.get('name', ''),
            email=r.get('email', ''),
            role=r.get('role', ''),
            firm=r.get('firm', ''),
        ))

    # Parse notices
    for n in batch.notices:
        data.notices.append(NoticeSummary(
            notice_id=n.get('notice_id', ''),
            company_name=n.get('company_name', ''),
            company_number=n.get('company_number', ''),
            notice_type=n.get('notice_type', ''),
            sector=n.get('sector', ''),
            estimated_assets=n.get('estimated_assets', []),
            opportunity_score=n.get('opportunity_score', 0),
            website_url=n.get('website_url'),
        ))

    return data


def get_followups_due(followup_number: int = 1) -> list[OutreachBatch]:
    """
    Get batches that are due for a follow-up.

    Args:
        followup_number: 1 for first follow-up, 2 for second

    Returns:
        List of batches needing follow-up
    """
    if followup_number == 1:
        days = OUTREACH_CONFIG.get('FOLLOWUP_1_DAYS', 7)
        batches = get_batches_for_followup(days)
        # Filter to only those with 0 follow-ups
        return [b for b in batches if b.follow_up_count == 0]
    elif followup_number == 2:
        days = OUTREACH_CONFIG.get('FOLLOWUP_2_DAYS', 14)
        batches = get_batches_for_followup(days)
        # Filter to those with exactly 1 follow-up
        return [b for b in batches if b.follow_up_count == 1]
    else:
        return []


def get_all_followups_due() -> list[tuple[OutreachBatch, int]]:
    """
    Get all batches due for follow-up with their follow-up number.

    Returns:
        List of (batch, followup_number) tuples
    """
    result = []

    # First follow-ups
    for batch in get_followups_due(1):
        result.append((batch, 1))

    # Second follow-ups
    for batch in get_followups_due(2):
        result.append((batch, 2))

    return result


def send_followup(
    batch_id: int,
    followup_number: Optional[int] = None,
    dry_run: bool = False,
) -> dict:
    """
    Send a follow-up email for a batch.

    Args:
        batch_id: ID of the batch to follow up
        followup_number: Override follow-up number (defaults to batch.follow_up_count + 1)
        dry_run: If True, don't actually send

    Returns:
        Result dict with success status and details
    """
    batch = get_batch(batch_id)
    if not batch:
        return {'success': False, 'error': f'Batch {batch_id} not found'}

    # Determine follow-up number
    if followup_number is None:
        followup_number = batch.follow_up_count + 1

    max_followups = OUTREACH_CONFIG.get('MAX_FOLLOWUPS', 2)
    if followup_number > max_followups:
        return {
            'success': False,
            'error': f'Max follow-ups ({max_followups}) already sent',
        }

    # Check if already replied
    if batch.replied_at:
        return {'success': False, 'error': 'Batch already has a reply'}

    # Convert to batch data
    batch_data = _batch_to_data(batch)

    if not batch_data.recipients:
        return {'success': False, 'error': 'No recipients in batch'}

    # Render follow-up email
    subject, body = render_followup_email(batch_data, followup_number)

    # Get recipients
    primary = batch_data.primary_recipient
    cc_emails = [r.email for r in batch_data.cc_recipients]

    if dry_run:
        logger.info(
            "[DRY RUN] Would send follow-up #%d to %s (CC: %s)",
            followup_number, primary.email, cc_emails
        )
        return {
            'success': True,
            'dry_run': True,
            'to': primary.email,
            'cc': cc_emails,
            'subject': subject,
            'body': body,
        }

    # Send
    result = send_email(
        to_email=primary.email,
        subject=subject,
        body=body,
        cc_emails=cc_emails,
    )

    if result.success:
        # Calculate next follow-up date (if not final)
        next_followup = None
        if followup_number < max_followups:
            followup_2_days = OUTREACH_CONFIG.get('FOLLOWUP_2_DAYS', 14)
            next_date = datetime.utcnow() + timedelta(days=followup_2_days)
            next_followup = next_date.date().isoformat()

        # Update database
        increment_followup_count(batch_id, next_followup)

        logger.info(
            "Sent follow-up #%d to %s for batch %d",
            followup_number, primary.email, batch_id
        )

        return {
            'success': True,
            'to': primary.email,
            'cc': cc_emails,
            'followup_number': followup_number,
            'next_followup_date': next_followup,
        }
    else:
        logger.error(
            "Failed to send follow-up #%d for batch %d: %s",
            followup_number, batch_id, result.error
        )
        return {
            'success': False,
            'error': result.error or result.message,
            'bounced': result.bounced,
        }


def process_due_followups(dry_run: bool = False) -> dict:
    """
    Process all due follow-ups.

    Args:
        dry_run: If True, don't actually send

    Returns:
        Summary dict with counts and results
    """
    # Check if we can send
    if not dry_run:
        in_window, reason = is_within_send_window()
        if not in_window:
            return {
                'success': False,
                'error': f'Outside send window: {reason}',
                'sent': 0,
                'failed': 0,
            }

    due = get_all_followups_due()

    if not due:
        return {
            'success': True,
            'message': 'No follow-ups due',
            'sent': 0,
            'failed': 0,
        }

    results = {
        'success': True,
        'sent': 0,
        'failed': 0,
        'skipped_warmup': 0,
        'details': [],
    }

    for batch, followup_num in due:
        # Check warm-up limit before each send
        if not dry_run:
            can_send, sent_today, limit = check_warmup_limit()
            if not can_send:
                results['skipped_warmup'] += 1
                results['details'].append({
                    'batch_id': batch.id,
                    'skipped': True,
                    'reason': f'Warm-up limit reached ({sent_today}/{limit})',
                })
                continue

        result = send_followup(batch.id, followup_num, dry_run)
        results['details'].append({
            'batch_id': batch.id,
            'followup_number': followup_num,
            **result,
        })

        if result.get('success'):
            results['sent'] += 1
        else:
            results['failed'] += 1

    return results
