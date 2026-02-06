"""
Automated outreach system for contacting Insolvency Practitioners.

This module handles:
- Qualifying opportunities for outreach
- Batching multiple companies by IP firm
- Sending personalized emails to all practitioners
- Tracking sent emails and responses
- Automated follow-ups (day 7, day 14)
- Domain warm-up to protect deliverability
"""

from src.outreach.db import init_outreach_db, OutreachBatch
from src.outreach.manager import OutreachManager, run_outreach_pipeline
from src.outreach.qualifier import should_queue_outreach, qualify_notices
from src.outreach.batcher import batch_by_firm, OutreachBatchData
from src.outreach.sender import send_email, get_warmup_status
from src.outreach.summary import send_summary_email, print_status
from src.outreach.config import OUTREACH_CONFIG

__all__ = [
    'init_outreach_db',
    'OutreachBatch',
    'OutreachManager',
    'run_outreach_pipeline',
    'should_queue_outreach',
    'qualify_notices',
    'batch_by_firm',
    'OutreachBatchData',
    'send_email',
    'get_warmup_status',
    'send_summary_email',
    'print_status',
    'OUTREACH_CONFIG',
]
