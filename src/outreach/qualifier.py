"""
Qualification logic for outreach.

Determines which notices should be queued for outreach based on:
- Opportunity score threshold
- Valid practitioner emails
- Blocklist status
- Recent contact history
- Company status
"""

import re
import logging
from typing import Optional

from src.outreach.db import is_email_blocked, was_company_contacted_recently
from src.outreach.config import OUTREACH_CONFIG
from src.ip_email_finder import find_ip_email_from_firm, get_known_firm_email

logger = logging.getLogger(__name__)


def _try_find_practitioner_email(practitioner) -> Optional[str]:
    """Try to find email for a practitioner via firm lookup."""
    if isinstance(practitioner, dict):
        firm = practitioner.get('firm', '')
        name = practitioner.get('name', '')
    else:
        firm = getattr(practitioner, 'firm', '')
        name = getattr(practitioner, 'name', '')

    if not firm:
        return None

    # Try known firm emails first (fast)
    email = get_known_firm_email(firm)
    if email:
        return email

    # Try firm website lookup (slower)
    email = find_ip_email_from_firm(firm, name)
    return email


def is_valid_email(email: str) -> bool:
    """Check if an email address is valid format."""
    if not email:
        return False
    # Basic email validation
    pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    return bool(re.match(pattern, email.strip()))


def get_valid_practitioners(practitioners: list) -> list:
    """Filter practitioners to those with valid email addresses."""
    valid = []
    for p in practitioners:
        email = getattr(p, 'email', None) or (p.get('email') if isinstance(p, dict) else None)
        if email and is_valid_email(email):
            valid.append(p)
    return valid


def should_queue_outreach(notice, practitioners: Optional[list] = None) -> tuple[bool, str]:
    """
    Determine if a notice should be queued for outreach.

    Args:
        notice: AnalysedNotice object
        practitioners: Optional list of practitioners (defaults to notice.practitioners)

    Returns:
        (should_queue: bool, reason: str)
    """
    if practitioners is None:
        practitioners = getattr(notice, 'practitioners', []) or []

    # Gate 1: Minimum quality threshold
    min_score = OUTREACH_CONFIG.get('MIN_OUTREACH_SCORE', 40)
    score = getattr(notice, 'opportunity_score', 0)
    if score < min_score:
        return False, f"Score {score} below threshold {min_score}"

    # Gate 2: Must have at least one valid practitioner email
    valid_practitioners = get_valid_practitioners(practitioners)
    if not valid_practitioners:
        # Try to look up emails for practitioners without them
        for p in practitioners:
            existing_email = getattr(p, 'email', None) or (p.get('email') if isinstance(p, dict) else None)
            if not existing_email or not is_valid_email(existing_email):
                found_email = _try_find_practitioner_email(p)
                if found_email:
                    # Update the practitioner with found email
                    if isinstance(p, dict):
                        p['email'] = found_email
                    else:
                        p.email = found_email
                    logger.info("Found email via firm lookup: %s", found_email)

        # Check again after lookup
        valid_practitioners = get_valid_practitioners(practitioners)

    if not valid_practitioners:
        # Log what we did find for debugging
        if practitioners:
            firms_found = [getattr(p, 'firm', p.get('firm') if isinstance(p, dict) else None) for p in practitioners]
            return False, f"No valid emails in {len(practitioners)} practitioners (firms: {firms_found})"
        return False, "No practitioners found in notice"

    # Gate 3: Check blocklist
    for p in valid_practitioners:
        email = getattr(p, 'email', None) or (p.get('email') if isinstance(p, dict) else None)
        if email and is_email_blocked(email):
            return False, f"Practitioner {email} is on blocklist"

    # Gate 4: Don't re-contact about same company within 30 days
    company_number = getattr(notice, 'company_number', None)
    if company_number and was_company_contacted_recently(company_number, days=30):
        return False, f"Already contacted about company {company_number} recently"

    # Gate 5: Skip dissolved companies
    ch_status = getattr(notice, 'ch_status', '').lower()
    if ch_status in ['dissolved', 'closed', 'converted-closed']:
        return False, f"Company status is {ch_status}"

    # Gate 6: Skip if notice type is unfavorable (e.g., MVL typically means solvent)
    notice_type = getattr(notice, 'notice_type', '').lower()
    if 'members voluntary' in notice_type or 'mvl' in notice_type.replace("'", ""):
        # MVL is typically a solvent liquidation, less interesting
        if score < 60:  # Allow high-scoring MVLs through
            return False, "Members voluntary liquidation (typically solvent)"

    return True, "Qualified for outreach"


def qualify_notices(notices: list, max_qualified: int = 0) -> tuple[list, list]:
    """
    Qualify a list of notices for outreach.

    Args:
        notices: List of AnalysedNotice objects
        max_qualified: Stop after finding this many qualified notices (0 = no limit)

    Returns:
        (qualified_notices, skipped_with_reasons)
    """
    # Get limit from config if not specified
    if max_qualified == 0:
        max_qualified = OUTREACH_CONFIG.get('MAX_SENDS_PER_RUN', 0)

    qualified = []
    skipped = []

    for notice in notices:
        # Early stop if we have enough
        if max_qualified > 0 and len(qualified) >= max_qualified:
            logger.info("Reached max qualified limit (%d), stopping early", max_qualified)
            break

        should_queue, reason = should_queue_outreach(notice)
        if should_queue:
            qualified.append(notice)
            logger.debug("Qualified: %s (%s)", notice.company_name, reason)
        else:
            skipped.append({
                'notice': notice,
                'reason': reason,
            })
            # Log skip reasons at INFO level for debugging
            logger.info("Skipped: %s - %s", notice.company_name, reason)

    logger.info(
        "Qualification complete: %d qualified, %d skipped",
        len(qualified), len(skipped)
    )

    return qualified, skipped
