"""
SQLite database for outreach tracking.

Tables:
- outreach_batches: Email batches (grouped by firm)
- batch_notices: Individual notices within each batch
- outreach_blocklist: Opted-out or bounced emails
- domain_warmup: Daily send counts for warm-up tracking
"""

import json
import os
import sqlite3
from datetime import datetime, date
from typing import Optional
from dataclasses import dataclass

# Database path (same directory as main tracker db)
OUTREACH_DB_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
    "data",
    "outreach.db"
)


@dataclass
class OutreachBatch:
    """Represents an email batch to be sent to an IP firm."""
    id: Optional[int] = None
    firm: str = ""
    status: str = "queued"  # queued, approved, sent, replied, closed
    recipients_json: str = "[]"
    notices_json: str = "[]"
    subject: str = ""
    body: str = ""
    created_at: Optional[str] = None
    approved_at: Optional[str] = None
    sent_at: Optional[str] = None
    replied_at: Optional[str] = None
    follow_up_count: int = 0
    next_follow_up_date: Optional[str] = None
    notes: str = ""

    @property
    def recipients(self) -> list[dict]:
        return json.loads(self.recipients_json) if self.recipients_json else []

    @property
    def notices(self) -> list[dict]:
        return json.loads(self.notices_json) if self.notices_json else []

    @property
    def primary_recipient(self) -> Optional[dict]:
        recipients = self.recipients
        return recipients[0] if recipients else None

    @property
    def cc_recipients(self) -> list[dict]:
        recipients = self.recipients
        return recipients[1:] if len(recipients) > 1 else []


def _connect() -> sqlite3.Connection:
    """Connect to the outreach database, creating tables if needed."""
    os.makedirs(os.path.dirname(OUTREACH_DB_PATH), exist_ok=True)
    conn = sqlite3.connect(OUTREACH_DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_outreach_db() -> None:
    """Initialize all outreach tables."""
    conn = _connect()
    try:
        # Main batches table
        conn.execute("""
            CREATE TABLE IF NOT EXISTS outreach_batches (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                firm TEXT NOT NULL,
                status TEXT DEFAULT 'queued',
                recipients_json TEXT,
                notices_json TEXT,
                subject TEXT,
                body TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                approved_at TIMESTAMP,
                sent_at TIMESTAMP,
                replied_at TIMESTAMP,
                follow_up_count INTEGER DEFAULT 0,
                next_follow_up_date DATE,
                notes TEXT
            )
        """)

        # Individual notices within batches
        conn.execute("""
            CREATE TABLE IF NOT EXISTS batch_notices (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                batch_id INTEGER REFERENCES outreach_batches(id),
                notice_id TEXT NOT NULL,
                company_name TEXT,
                company_number TEXT,
                opportunity_score INTEGER,
                UNIQUE(batch_id, notice_id)
            )
        """)

        # Blocklist for opt-outs and bounces
        conn.execute("""
            CREATE TABLE IF NOT EXISTS outreach_blocklist (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email TEXT UNIQUE NOT NULL,
                reason TEXT,
                added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Domain warm-up tracking
        conn.execute("""
            CREATE TABLE IF NOT EXISTS domain_warmup (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date DATE UNIQUE NOT NULL,
                emails_sent INTEGER DEFAULT 0,
                first_send_date DATE
            )
        """)

        # Company contact history (to avoid re-contacting about same company)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS company_contact_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                company_number TEXT NOT NULL,
                contacted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                batch_id INTEGER REFERENCES outreach_batches(id)
            )
        """)

        conn.commit()
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Batch operations
# ---------------------------------------------------------------------------

def create_batch(
    firm: str,
    recipients: list[dict],
    notices: list[dict],
    subject: str,
    body: str,
) -> int:
    """Create a new outreach batch. Returns the batch ID."""
    conn = _connect()
    try:
        cursor = conn.execute(
            """
            INSERT INTO outreach_batches
            (firm, recipients_json, notices_json, subject, body)
            VALUES (?, ?, ?, ?, ?)
            """,
            (firm, json.dumps(recipients), json.dumps(notices), subject, body)
        )
        batch_id = cursor.lastrowid

        # Insert individual notice records
        for notice in notices:
            conn.execute(
                """
                INSERT OR IGNORE INTO batch_notices
                (batch_id, notice_id, company_name, company_number, opportunity_score)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    batch_id,
                    notice.get('notice_id', ''),
                    notice.get('company_name', ''),
                    notice.get('company_number', ''),
                    notice.get('opportunity_score', 0),
                )
            )

        conn.commit()
        return batch_id
    finally:
        conn.close()


def get_batch(batch_id: int) -> Optional[OutreachBatch]:
    """Get a single batch by ID."""
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT * FROM outreach_batches WHERE id = ?", (batch_id,)
        ).fetchone()
        if row:
            return OutreachBatch(**dict(row))
        return None
    finally:
        conn.close()


def get_batches_by_status(status: str) -> list[OutreachBatch]:
    """Get all batches with a given status."""
    conn = _connect()
    try:
        rows = conn.execute(
            "SELECT * FROM outreach_batches WHERE status = ? ORDER BY created_at",
            (status,)
        ).fetchall()
        return [OutreachBatch(**dict(row)) for row in rows]
    finally:
        conn.close()


def get_queued_batches() -> list[OutreachBatch]:
    """Get all batches waiting to be sent."""
    return get_batches_by_status('queued')


def get_approved_batches() -> list[OutreachBatch]:
    """Get all approved batches ready to send."""
    return get_batches_by_status('approved')


def update_batch_status(batch_id: int, status: str, **kwargs) -> None:
    """Update batch status and optional fields."""
    conn = _connect()
    try:
        # Build dynamic update
        updates = ["status = ?"]
        values = [status]

        # Add timestamp for certain statuses
        if status == 'approved' and 'approved_at' not in kwargs:
            kwargs['approved_at'] = datetime.utcnow().isoformat()
        elif status == 'sent' and 'sent_at' not in kwargs:
            kwargs['sent_at'] = datetime.utcnow().isoformat()
        elif status == 'replied' and 'replied_at' not in kwargs:
            kwargs['replied_at'] = datetime.utcnow().isoformat()

        for key, value in kwargs.items():
            updates.append(f"{key} = ?")
            values.append(value)

        values.append(batch_id)
        conn.execute(
            f"UPDATE outreach_batches SET {', '.join(updates)} WHERE id = ?",
            values
        )
        conn.commit()
    finally:
        conn.close()


def get_batches_for_followup(days_since_sent: int) -> list[OutreachBatch]:
    """Get batches that need follow-up (sent N days ago, no reply, not maxed out)."""
    conn = _connect()
    try:
        rows = conn.execute(
            """
            SELECT * FROM outreach_batches
            WHERE status = 'sent'
            AND replied_at IS NULL
            AND follow_up_count < 2
            AND date(sent_at) <= date('now', ? || ' days')
            ORDER BY sent_at
            """,
            (f"-{days_since_sent}",)
        ).fetchall()
        return [OutreachBatch(**dict(row)) for row in rows]
    finally:
        conn.close()


def increment_followup_count(batch_id: int, next_followup_date: Optional[str] = None) -> None:
    """Increment follow-up count after sending a follow-up."""
    conn = _connect()
    try:
        conn.execute(
            """
            UPDATE outreach_batches
            SET follow_up_count = follow_up_count + 1,
                next_follow_up_date = ?
            WHERE id = ?
            """,
            (next_followup_date, batch_id)
        )
        conn.commit()
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Blocklist operations
# ---------------------------------------------------------------------------

def is_email_blocked(email: str) -> bool:
    """Check if an email is on the blocklist."""
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT 1 FROM outreach_blocklist WHERE LOWER(email) = LOWER(?)",
            (email,)
        ).fetchone()
        return row is not None
    finally:
        conn.close()


def add_to_blocklist(email: str, reason: str = "manual") -> None:
    """Add an email to the blocklist."""
    conn = _connect()
    try:
        conn.execute(
            "INSERT OR IGNORE INTO outreach_blocklist (email, reason) VALUES (?, ?)",
            (email.lower(), reason)
        )
        conn.commit()
    finally:
        conn.close()


def remove_from_blocklist(email: str) -> None:
    """Remove an email from the blocklist."""
    conn = _connect()
    try:
        conn.execute(
            "DELETE FROM outreach_blocklist WHERE LOWER(email) = LOWER(?)",
            (email,)
        )
        conn.commit()
    finally:
        conn.close()


def get_blocklist() -> list[dict]:
    """Get all blocked emails."""
    conn = _connect()
    try:
        rows = conn.execute(
            "SELECT email, reason, added_at FROM outreach_blocklist ORDER BY added_at DESC"
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Warm-up tracking
# ---------------------------------------------------------------------------

def get_warmup_stats() -> dict:
    """Get warm-up statistics including first send date and today's count."""
    conn = _connect()
    try:
        # Get first send date
        row = conn.execute(
            "SELECT MIN(first_send_date) as first_date FROM domain_warmup WHERE first_send_date IS NOT NULL"
        ).fetchone()
        first_send_date = row['first_date'] if row else None

        # Get today's count
        today = date.today().isoformat()
        row = conn.execute(
            "SELECT emails_sent FROM domain_warmup WHERE date = ?",
            (today,)
        ).fetchone()
        today_sent = row['emails_sent'] if row else 0

        # Calculate domain age in days
        domain_age_days = 0
        if first_send_date:
            first_date = datetime.fromisoformat(first_send_date).date()
            domain_age_days = (date.today() - first_date).days

        return {
            'first_send_date': first_send_date,
            'domain_age_days': domain_age_days,
            'today_sent': today_sent,
        }
    finally:
        conn.close()


def record_email_sent() -> None:
    """Record that an email was sent today (for warm-up tracking)."""
    conn = _connect()
    try:
        today = date.today().isoformat()

        # Check if today's record exists
        row = conn.execute(
            "SELECT id, first_send_date FROM domain_warmup WHERE date = ?",
            (today,)
        ).fetchone()

        if row:
            # Update count
            conn.execute(
                "UPDATE domain_warmup SET emails_sent = emails_sent + 1 WHERE date = ?",
                (today,)
            )
        else:
            # Get first send date
            first_row = conn.execute(
                "SELECT MIN(first_send_date) as first_date FROM domain_warmup WHERE first_send_date IS NOT NULL"
            ).fetchone()
            first_date = first_row['first_date'] if first_row and first_row['first_date'] else today

            # Create new record
            conn.execute(
                "INSERT INTO domain_warmup (date, emails_sent, first_send_date) VALUES (?, 1, ?)",
                (today, first_date)
            )

        conn.commit()
    finally:
        conn.close()


def get_warmup_limit() -> Optional[int]:
    """Get today's sending limit based on domain age. Returns None for unlimited."""
    stats = get_warmup_stats()
    age = stats['domain_age_days']

    if age < 7:
        return 5  # Week 1
    elif age < 14:
        return 15  # Week 2
    elif age < 21:
        return 30  # Week 3
    elif age < 28:
        return 50  # Week 4
    else:
        return None  # Unlimited


def can_send_today() -> tuple[bool, int, Optional[int]]:
    """Check if we can send more emails today. Returns (can_send, sent_today, limit)."""
    stats = get_warmup_stats()
    limit = get_warmup_limit()
    sent = stats['today_sent']

    if limit is None:
        return True, sent, None

    return sent < limit, sent, limit


# ---------------------------------------------------------------------------
# Company contact history
# ---------------------------------------------------------------------------

def was_company_contacted_recently(company_number: str, days: int = 30) -> bool:
    """Check if we've contacted about this company within N days."""
    if not company_number:
        return False

    conn = _connect()
    try:
        row = conn.execute(
            """
            SELECT 1 FROM company_contact_history
            WHERE company_number = ?
            AND contacted_at >= datetime('now', ? || ' days')
            """,
            (company_number, f"-{days}")
        ).fetchone()
        return row is not None
    finally:
        conn.close()


def record_company_contacted(company_number: str, batch_id: int) -> None:
    """Record that we contacted about this company."""
    if not company_number:
        return

    conn = _connect()
    try:
        conn.execute(
            "INSERT INTO company_contact_history (company_number, batch_id) VALUES (?, ?)",
            (company_number, batch_id)
        )
        conn.commit()
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Statistics
# ---------------------------------------------------------------------------

def get_pipeline_stats() -> dict:
    """Get pipeline statistics."""
    conn = _connect()
    try:
        stats = {}

        # Count by status
        for status in ['queued', 'approved', 'sent', 'replied', 'closed']:
            row = conn.execute(
                "SELECT COUNT(*) as count FROM outreach_batches WHERE status = ?",
                (status,)
            ).fetchone()
            stats[f'{status}_count'] = row['count'] if row else 0

        # Sent but awaiting reply
        row = conn.execute(
            """
            SELECT COUNT(*) as count FROM outreach_batches
            WHERE status = 'sent' AND replied_at IS NULL
            """
        ).fetchone()
        stats['awaiting_reply'] = row['count'] if row else 0

        # Today's activity
        today = date.today().isoformat()
        row = conn.execute(
            "SELECT COUNT(*) as count FROM outreach_batches WHERE date(sent_at) = ?",
            (today,)
        ).fetchone()
        stats['sent_today'] = row['count'] if row else 0

        row = conn.execute(
            "SELECT COUNT(*) as count FROM outreach_batches WHERE date(replied_at) = ?",
            (today,)
        ).fetchone()
        stats['replied_today'] = row['count'] if row else 0

        # Response rate (all time)
        row = conn.execute(
            """
            SELECT
                COUNT(*) as total_sent,
                SUM(CASE WHEN replied_at IS NOT NULL THEN 1 ELSE 0 END) as total_replied
            FROM outreach_batches
            WHERE status IN ('sent', 'replied', 'closed')
            """
        ).fetchone()
        total_sent = row['total_sent'] if row else 0
        total_replied = row['total_replied'] if row else 0
        stats['response_rate'] = (total_replied / total_sent * 100) if total_sent > 0 else 0

        return stats
    finally:
        conn.close()


def get_recent_replies(limit: int = 10) -> list[OutreachBatch]:
    """Get recent batches that received replies."""
    conn = _connect()
    try:
        rows = conn.execute(
            """
            SELECT * FROM outreach_batches
            WHERE replied_at IS NOT NULL
            ORDER BY replied_at DESC
            LIMIT ?
            """,
            (limit,)
        ).fetchall()
        return [OutreachBatch(**dict(row)) for row in rows]
    finally:
        conn.close()


def get_all_batches(limit: int = 100) -> list[OutreachBatch]:
    """Get all batches, most recent first."""
    conn = _connect()
    try:
        rows = conn.execute(
            "SELECT * FROM outreach_batches ORDER BY created_at DESC LIMIT ?",
            (limit,)
        ).fetchall()
        return [OutreachBatch(**dict(row)) for row in rows]
    finally:
        conn.close()
