"""
Outreach manager - main orchestration module.

Coordinates:
- Qualifying notices
- Batching by firm
- Sending emails
- Tracking status
- Generating summaries
"""

import json
import logging
from datetime import datetime, date
from typing import Optional

from src.outreach.config import OUTREACH_CONFIG, validate_config
from src.outreach.db import (
    init_outreach_db,
    create_batch,
    get_batch,
    get_queued_batches,
    get_approved_batches,
    update_batch_status,
    get_pipeline_stats,
    get_warmup_stats,
    get_warmup_limit,
    can_send_today,
    record_company_contacted,
    add_to_blocklist,
    OutreachBatch,
)
from src.outreach.qualifier import qualify_notices, get_valid_practitioners
from src.outreach.batcher import batch_by_firm, OutreachBatchData
from src.outreach.templates import render_batch_email
from src.outreach.sender import (
    send_email,
    send_with_delay,
    is_within_send_window,
    check_warmup_limit,
    get_warmup_status,
)
from src.outreach.followup import process_due_followups, get_all_followups_due

logger = logging.getLogger(__name__)


class OutreachManager:
    """
    Main orchestrator for the outreach system.

    Usage:
        manager = OutreachManager()

        # Process new notices
        results = manager.process_notices(analysed_notices)

        # Send queued/approved emails
        send_results = manager.send_pending()

        # Process follow-ups
        followup_results = manager.process_followups()

        # Get status
        status = manager.get_status()
    """

    def __init__(self, dry_run: bool = False):
        """
        Initialize the outreach manager.

        Args:
            dry_run: If True, don't actually send emails
        """
        self.dry_run = dry_run or OUTREACH_CONFIG.get('DRY_RUN', False)

        # Initialize database
        init_outreach_db()

        # Validate config
        errors = validate_config()
        if errors:
            for error in errors:
                logger.warning("Config issue: %s", error)

    def process_notices(self, notices: list) -> dict:
        """
        Process analysed notices: qualify, batch, and queue for sending.

        Args:
            notices: List of AnalysedNotice objects

        Returns:
            Summary dict with counts and batch IDs
        """
        logger.info("Processing %d notices for outreach", len(notices))

        # Step 1: Qualify notices
        qualified, skipped = qualify_notices(notices)

        if not qualified:
            logger.info("No notices qualified for outreach")
            return {
                'total': len(notices),
                'qualified': 0,
                'skipped': len(skipped),
                'batches_created': 0,
                'batch_ids': [],
                'skipped_reasons': [s['reason'] for s in skipped],
            }

        # Step 2: Batch by firm
        batches = batch_by_firm(qualified)

        if not batches:
            logger.info("No batches created")
            return {
                'total': len(notices),
                'qualified': len(qualified),
                'skipped': len(skipped),
                'batches_created': 0,
                'batch_ids': [],
            }

        # Step 3: Create batch records and render emails
        batch_ids = []

        for batch_data in batches:
            # Render email
            subject, body = render_batch_email(batch_data)

            # Create database record
            batch_id = create_batch(
                firm=batch_data.firm,
                recipients=[r.to_dict() for r in batch_data.recipients],
                notices=[n.to_dict() for n in batch_data.notices],
                subject=subject,
                body=body,
            )

            batch_ids.append(batch_id)

            logger.info(
                "Created batch #%d: %s (%d companies, %d recipients)",
                batch_id, batch_data.firm, len(batch_data.notices), len(batch_data.recipients)
            )

        # Step 4: Auto-approve if not requiring manual approval
        if not OUTREACH_CONFIG.get('REQUIRE_APPROVAL', False):
            for batch_id in batch_ids:
                update_batch_status(batch_id, 'approved')
            logger.info("Auto-approved %d batches", len(batch_ids))

        return {
            'total': len(notices),
            'qualified': len(qualified),
            'skipped': len(skipped),
            'batches_created': len(batch_ids),
            'batch_ids': batch_ids,
        }

    def send_pending(self, max_sends: Optional[int] = None) -> dict:
        """
        Send all approved/queued batches (respecting limits).

        Args:
            max_sends: Optional override for max emails to send

        Returns:
            Summary dict with counts and results
        """
        # Check if we're in send window
        if not self.dry_run:
            in_window, reason = is_within_send_window()
            if not in_window:
                return {
                    'success': False,
                    'error': f'Outside send window: {reason}',
                    'sent': 0,
                    'failed': 0,
                    'queued_remaining': len(get_approved_batches()),
                }

        # Get batches to send
        batches = get_approved_batches()
        if not batches:
            batches = get_queued_batches()

        if not batches:
            return {
                'success': True,
                'message': 'No pending batches',
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

        for batch in batches:
            # Check warm-up limit
            if not self.dry_run:
                can_send, sent_today, limit = check_warmup_limit()
                if not can_send:
                    results['skipped_warmup'] += 1
                    results['details'].append({
                        'batch_id': batch.id,
                        'skipped': True,
                        'reason': f'Warm-up limit ({sent_today}/{limit})',
                    })
                    continue

            # Check max sends
            if max_sends and results['sent'] >= max_sends:
                results['details'].append({
                    'batch_id': batch.id,
                    'skipped': True,
                    'reason': 'Max sends reached',
                })
                continue

            # Send the batch
            result = self._send_batch(batch)
            results['details'].append({
                'batch_id': batch.id,
                **result,
            })

            if result.get('success'):
                results['sent'] += 1
            else:
                results['failed'] += 1

        return results

    def _send_batch(self, batch: OutreachBatch) -> dict:
        """Send a single batch."""
        recipients = batch.recipients
        if not recipients:
            return {'success': False, 'error': 'No recipients'}

        primary = recipients[0]
        cc_emails = [r['email'] for r in recipients[1:]]

        if self.dry_run:
            logger.info(
                "[DRY RUN] Would send to %s (CC: %s): %s",
                primary['email'], cc_emails, batch.subject
            )
            return {
                'success': True,
                'dry_run': True,
                'to': primary['email'],
                'cc': cc_emails,
                'subject': batch.subject,
            }

        # Send with delay
        result = send_with_delay(
            to_email=primary['email'],
            subject=batch.subject,
            body=batch.body,
            cc_emails=cc_emails,
        )

        if result.success:
            # Update status
            update_batch_status(batch.id, 'sent')

            # Record company contacts
            for notice in batch.notices:
                company_number = notice.get('company_number')
                if company_number:
                    record_company_contacted(company_number, batch.id)

            logger.info("Sent batch #%d to %s", batch.id, primary['email'])

            return {
                'success': True,
                'to': primary['email'],
                'cc': cc_emails,
            }
        else:
            logger.error("Failed to send batch #%d: %s", batch.id, result.error)

            # Handle bounces
            if result.bounced:
                add_to_blocklist(primary['email'], 'bounce')

            return {
                'success': False,
                'error': result.error or result.message,
                'bounced': result.bounced,
            }

    def process_followups(self) -> dict:
        """Process all due follow-ups."""
        return process_due_followups(dry_run=self.dry_run)

    def get_status(self) -> dict:
        """Get comprehensive outreach status."""
        pipeline = get_pipeline_stats()
        warmup = get_warmup_status()
        followups_due = get_all_followups_due()

        return {
            'date': date.today().isoformat(),
            'pipeline': pipeline,
            'warmup': warmup,
            'followups_due': len(followups_due),
            'pending_batches': len(get_queued_batches()) + len(get_approved_batches()),
        }

    def mark_replied(self, batch_id: int, notes: str = "") -> bool:
        """Mark a batch as having received a reply."""
        batch = get_batch(batch_id)
        if not batch:
            return False

        update_batch_status(batch_id, 'replied', notes=notes)
        logger.info("Marked batch #%d as replied", batch_id)
        return True

    def skip_batch(self, batch_id: int, reason: str = "") -> bool:
        """Skip a queued batch."""
        batch = get_batch(batch_id)
        if not batch:
            return False

        if batch.status not in ('queued', 'approved'):
            return False

        update_batch_status(batch_id, 'closed', notes=f"Skipped: {reason}")
        logger.info("Skipped batch #%d: %s", batch_id, reason)
        return True

    def approve_batch(self, batch_id: int) -> bool:
        """Approve a queued batch for sending."""
        batch = get_batch(batch_id)
        if not batch:
            return False

        if batch.status != 'queued':
            return False

        update_batch_status(batch_id, 'approved')
        logger.info("Approved batch #%d", batch_id)
        return True

    def approve_all(self) -> int:
        """Approve all queued batches. Returns count approved."""
        batches = get_queued_batches()
        count = 0
        for batch in batches:
            if self.approve_batch(batch.id):
                count += 1
        return count


def run_outreach_pipeline(
    notices: list,
    dry_run: bool = False,
    send_immediately: bool = True,
) -> dict:
    """
    Run the full outreach pipeline.

    This is the main entry point for automated outreach.

    Args:
        notices: List of AnalysedNotice objects
        dry_run: If True, don't actually send
        send_immediately: If True, send right after processing

    Returns:
        Combined results from processing and sending
    """
    manager = OutreachManager(dry_run=dry_run)

    # Process notices
    process_results = manager.process_notices(notices)

    results = {
        'processing': process_results,
        'sending': None,
        'followups': None,
    }

    # Send if requested and batches were created
    if send_immediately and process_results['batches_created'] > 0:
        results['sending'] = manager.send_pending()

    # Process follow-ups
    results['followups'] = manager.process_followups()

    return results
