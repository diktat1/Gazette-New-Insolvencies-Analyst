#!/usr/bin/env python3
"""
Outreach CLI - Command-line interface for the automated outreach system.

Usage:
    python outreach.py status           Show current status
    python outreach.py queue            Show pending batches
    python outreach.py preview <id>     Preview email for a batch
    python outreach.py approve <id>     Approve a batch for sending
    python outreach.py approve --all    Approve all pending batches
    python outreach.py skip <id>        Skip a batch
    python outreach.py send             Send approved batches
    python outreach.py send --dry-run   Preview what would be sent
    python outreach.py followups        Process due follow-ups
    python outreach.py reply <id>       Mark batch as replied
    python outreach.py block <email>    Block an email address
    python outreach.py history          Show send history
    python outreach.py stats            Show detailed statistics
"""

import argparse
import logging
import sys
from datetime import date

from src.outreach.db import (
    init_outreach_db,
    get_queued_batches,
    get_approved_batches,
    get_batch,
    get_all_batches,
    get_blocklist,
    add_to_blocklist,
    remove_from_blocklist,
    update_batch_status,
)
from src.outreach.manager import OutreachManager
from src.outreach.summary import print_status, generate_summary_text
from src.outreach.sender import get_warmup_status
from src.outreach.followup import get_all_followups_due

logging.basicConfig(
    level=logging.INFO,
    format='%(message)s',
)
logger = logging.getLogger(__name__)


def cmd_status(args):
    """Show current outreach status."""
    init_outreach_db()
    print_status()


def cmd_queue(args):
    """Show pending batches."""
    init_outreach_db()

    queued = get_queued_batches()
    approved = get_approved_batches()
    pending = queued + approved

    if not pending:
        print("\n✓ No pending batches\n")
        return

    print()
    print("╔" + "═" * 76 + "╗")
    print(f"║{'OUTREACH QUEUE - ' + str(len(pending)) + ' batches':^76}║")
    print("╠" + "═" * 76 + "╣")

    for batch in pending:
        status_icon = "📋" if batch.status == 'queued' else "✅"
        companies = batch.notices
        recipients = batch.recipients

        company_names = [c.get('company_name', 'Unknown') for c in companies]
        max_score = max((c.get('opportunity_score', 0) for c in companies), default=0)

        print("║" + " " * 76 + "║")
        print(f"║  {status_icon} #{batch.id}  {batch.firm[:40]:<40} Score: {max_score:<6} ║")
        print("║  " + "─" * 72 + "  ║")

        for name in company_names[:3]:
            print(f"║    • {name[:65]:<65}  ║")
        if len(company_names) > 3:
            print(f"║    • ... and {len(company_names) - 3} more{' ' * 55}║")

        if recipients:
            primary = recipients[0]
            print(f"║    To: {primary.get('email', 'N/A')[:63]:<63}  ║")
            if len(recipients) > 1:
                cc_list = ', '.join(r.get('email', '') for r in recipients[1:3])
                if len(recipients) > 3:
                    cc_list += f' + {len(recipients) - 3} more'
                print(f"║    CC: {cc_list[:63]:<63}  ║")

    print("║" + " " * 76 + "║")
    print("╠" + "═" * 76 + "╣")
    print("║  Commands: approve --all | approve <id> | skip <id> | preview <id> | send  ║")
    print("╚" + "═" * 76 + "╝")
    print()


def cmd_preview(args):
    """Preview email for a batch."""
    init_outreach_db()

    batch = get_batch(args.batch_id)
    if not batch:
        print(f"\n✗ Batch #{args.batch_id} not found\n")
        return

    recipients = batch.recipients
    primary = recipients[0] if recipients else {}
    cc = recipients[1:] if len(recipients) > 1 else []

    print()
    print("╔" + "═" * 76 + "╗")
    print(f"║{'EMAIL PREVIEW - Batch #' + str(batch.id):^76}║")
    print("╠" + "═" * 76 + "╣")
    print("║" + " " * 76 + "║")
    print(f"║  To:      {primary.get('email', 'N/A')[:63]:<63}  ║")
    if cc:
        cc_str = ', '.join(r.get('email', '') for r in cc)
        print(f"║  CC:      {cc_str[:63]:<63}  ║")
    print(f"║  Subject: {batch.subject[:63]:<63}  ║")
    print("║" + " " * 76 + "║")
    print("║  " + "─" * 72 + "  ║")
    print("║" + " " * 76 + "║")

    # Print body with wrapping
    for line in batch.body.split('\n'):
        while len(line) > 70:
            print(f"║  {line[:70]}  ║")
            line = line[70:]
        print(f"║  {line:<70}  ║")

    print("║" + " " * 76 + "║")
    print("╠" + "═" * 76 + "╣")
    print(f"║  Status: {batch.status:<66}║")
    print("╚" + "═" * 76 + "╝")
    print()


def cmd_approve(args):
    """Approve batches for sending."""
    init_outreach_db()
    manager = OutreachManager()

    if args.all:
        count = manager.approve_all()
        print(f"\n✓ Approved {count} batches\n")
    elif args.batch_ids:
        for batch_id in args.batch_ids:
            if manager.approve_batch(batch_id):
                print(f"✓ Approved batch #{batch_id}")
            else:
                print(f"✗ Could not approve batch #{batch_id}")
        print()
    else:
        print("\n✗ Specify batch IDs or --all\n")


def cmd_skip(args):
    """Skip a batch."""
    init_outreach_db()
    manager = OutreachManager()

    reason = args.reason or "Skipped via CLI"

    if manager.skip_batch(args.batch_id, reason):
        print(f"\n✓ Skipped batch #{args.batch_id}\n")
    else:
        print(f"\n✗ Could not skip batch #{args.batch_id}\n")


def cmd_send(args):
    """Send approved batches."""
    init_outreach_db()
    manager = OutreachManager(dry_run=args.dry_run)

    if args.dry_run:
        print("\n🔍 DRY RUN MODE - No emails will be sent\n")

    results = manager.send_pending()

    if results.get('error'):
        print(f"\n✗ {results['error']}\n")
        return

    sent = results.get('sent', 0)
    failed = results.get('failed', 0)
    skipped = results.get('skipped_warmup', 0)

    print(f"\n{'[DRY RUN] ' if args.dry_run else ''}Results:")
    print(f"  ✓ Sent: {sent}")
    if failed:
        print(f"  ✗ Failed: {failed}")
    if skipped:
        print(f"  ⚠ Skipped (warm-up): {skipped}")

    # Show details
    for detail in results.get('details', []):
        batch_id = detail.get('batch_id')
        if detail.get('success'):
            to = detail.get('to', 'N/A')
            print(f"  #{batch_id}: Sent to {to}")
        elif detail.get('skipped'):
            print(f"  #{batch_id}: Skipped - {detail.get('reason')}")
        else:
            print(f"  #{batch_id}: Failed - {detail.get('error')}")

    print()


def cmd_followups(args):
    """Process due follow-ups."""
    init_outreach_db()
    manager = OutreachManager(dry_run=args.dry_run)

    if args.dry_run:
        print("\n🔍 DRY RUN MODE\n")

    results = manager.process_followups()

    if results.get('error'):
        print(f"\n✗ {results['error']}\n")
        return

    sent = results.get('sent', 0)
    failed = results.get('failed', 0)

    if sent == 0 and failed == 0:
        print("\n✓ No follow-ups due\n")
    else:
        print(f"\n{'[DRY RUN] ' if args.dry_run else ''}Follow-up results:")
        print(f"  ✓ Sent: {sent}")
        if failed:
            print(f"  ✗ Failed: {failed}")
        print()


def cmd_reply(args):
    """Mark a batch as having received a reply."""
    init_outreach_db()
    manager = OutreachManager()

    notes = args.note or ""

    if manager.mark_replied(args.batch_id, notes):
        print(f"\n✓ Marked batch #{args.batch_id} as replied\n")
    else:
        print(f"\n✗ Could not mark batch #{args.batch_id} as replied\n")


def cmd_block(args):
    """Block or unblock an email address."""
    init_outreach_db()

    if args.remove:
        remove_from_blocklist(args.email)
        print(f"\n✓ Removed {args.email} from blocklist\n")
    else:
        reason = args.reason or "manual"
        add_to_blocklist(args.email, reason)
        print(f"\n✓ Added {args.email} to blocklist\n")


def cmd_blocklist(args):
    """Show the blocklist."""
    init_outreach_db()

    blocked = get_blocklist()

    if not blocked:
        print("\n✓ Blocklist is empty\n")
        return

    print(f"\nBlocklist ({len(blocked)} entries):")
    for entry in blocked:
        print(f"  • {entry['email']} ({entry['reason']}) - {entry['added_at'][:10]}")
    print()


def cmd_history(args):
    """Show send history."""
    init_outreach_db()

    batches = get_all_batches(limit=args.limit)

    if not batches:
        print("\n✓ No outreach history\n")
        return

    print(f"\nOutreach history (last {len(batches)}):")
    print("-" * 80)

    for batch in batches:
        companies = batch.notices
        company_names = [c.get('company_name', 'Unknown') for c in companies]
        companies_str = ', '.join(company_names[:2])
        if len(company_names) > 2:
            companies_str += f' +{len(company_names) - 2}'

        status_icon = {
            'queued': '📋',
            'approved': '✅',
            'sent': '📤',
            'replied': '💬',
            'closed': '🔒',
        }.get(batch.status, '❓')

        date_str = (batch.sent_at or batch.created_at or '')[:10]

        print(f"{status_icon} #{batch.id:3d} | {date_str} | {batch.firm[:25]:<25} | {companies_str[:30]}")

    print("-" * 80)
    print()


def cmd_stats(args):
    """Show detailed statistics."""
    init_outreach_db()

    print()
    print(generate_summary_text())
    print()


def main():
    parser = argparse.ArgumentParser(
        description="Outreach CLI - Automated IP outreach system",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )

    subparsers = parser.add_subparsers(dest='command', help='Commands')

    # status
    subparsers.add_parser('status', help='Show current status')

    # queue
    subparsers.add_parser('queue', help='Show pending batches')

    # preview
    preview_parser = subparsers.add_parser('preview', help='Preview email for a batch')
    preview_parser.add_argument('batch_id', type=int, help='Batch ID')

    # approve
    approve_parser = subparsers.add_parser('approve', help='Approve batches for sending')
    approve_parser.add_argument('batch_ids', type=int, nargs='*', help='Batch IDs to approve')
    approve_parser.add_argument('--all', action='store_true', help='Approve all pending')

    # skip
    skip_parser = subparsers.add_parser('skip', help='Skip a batch')
    skip_parser.add_argument('batch_id', type=int, help='Batch ID')
    skip_parser.add_argument('--reason', '-r', help='Reason for skipping')

    # send
    send_parser = subparsers.add_parser('send', help='Send approved batches')
    send_parser.add_argument('--dry-run', action='store_true', help='Preview without sending')

    # followups
    followups_parser = subparsers.add_parser('followups', help='Process due follow-ups')
    followups_parser.add_argument('--dry-run', action='store_true', help='Preview without sending')

    # reply
    reply_parser = subparsers.add_parser('reply', help='Mark batch as replied')
    reply_parser.add_argument('batch_id', type=int, help='Batch ID')
    reply_parser.add_argument('--note', '-n', help='Add a note')

    # block
    block_parser = subparsers.add_parser('block', help='Block an email address')
    block_parser.add_argument('email', help='Email to block')
    block_parser.add_argument('--reason', '-r', help='Reason for blocking')
    block_parser.add_argument('--remove', action='store_true', help='Remove from blocklist')

    # blocklist
    subparsers.add_parser('blocklist', help='Show blocklist')

    # history
    history_parser = subparsers.add_parser('history', help='Show send history')
    history_parser.add_argument('--limit', '-l', type=int, default=50, help='Max entries')

    # stats
    subparsers.add_parser('stats', help='Show detailed statistics')

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return

    # Command dispatch
    commands = {
        'status': cmd_status,
        'queue': cmd_queue,
        'preview': cmd_preview,
        'approve': cmd_approve,
        'skip': cmd_skip,
        'send': cmd_send,
        'followups': cmd_followups,
        'reply': cmd_reply,
        'block': cmd_block,
        'blocklist': cmd_blocklist,
        'history': cmd_history,
        'stats': cmd_stats,
    }

    cmd_func = commands.get(args.command)
    if cmd_func:
        cmd_func(args)
    else:
        parser.print_help()


if __name__ == '__main__':
    main()
