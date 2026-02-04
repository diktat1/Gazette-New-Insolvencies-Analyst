"""
Batching logic for outreach.

Groups qualified notices by IP firm and collects all practitioners
to be included in each email (To + CC).
"""

import logging
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class OutreachRecipient:
    """A single email recipient."""
    name: str
    email: str
    role: str = ""
    firm: str = ""

    def to_dict(self) -> dict:
        return {
            'name': self.name,
            'email': self.email,
            'role': self.role,
            'firm': self.firm,
        }


@dataclass
class NoticeSummary:
    """Summary of a notice for inclusion in batch."""
    notice_id: str
    company_name: str
    company_number: str
    notice_type: str
    sector: str
    estimated_assets: list
    opportunity_score: int
    website_url: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            'notice_id': self.notice_id,
            'company_name': self.company_name,
            'company_number': self.company_number,
            'notice_type': self.notice_type,
            'sector': self.sector,
            'estimated_assets': self.estimated_assets,
            'opportunity_score': self.opportunity_score,
            'website_url': self.website_url,
        }


@dataclass
class OutreachBatchData:
    """Data for a batch of notices to send to one firm."""
    firm: str
    recipients: list[OutreachRecipient] = field(default_factory=list)
    notices: list[NoticeSummary] = field(default_factory=list)

    @property
    def primary_recipient(self) -> Optional[OutreachRecipient]:
        return self.recipients[0] if self.recipients else None

    @property
    def cc_recipients(self) -> list[OutreachRecipient]:
        return self.recipients[1:] if len(self.recipients) > 1 else []

    @property
    def max_score(self) -> int:
        """Highest opportunity score in this batch."""
        return max((n.opportunity_score for n in self.notices), default=0)

    @property
    def total_companies(self) -> int:
        return len(self.notices)

    def to_dict(self) -> dict:
        return {
            'firm': self.firm,
            'recipients': [r.to_dict() for r in self.recipients],
            'notices': [n.to_dict() for n in self.notices],
            'max_score': self.max_score,
            'total_companies': self.total_companies,
        }


def _extract_firm_name(practitioner) -> str:
    """Extract firm name from a practitioner object."""
    if isinstance(practitioner, dict):
        return practitioner.get('firm', '') or 'Unknown Firm'

    firm = getattr(practitioner, 'firm', None)
    if firm:
        return firm

    # Try to extract from email domain
    email = getattr(practitioner, 'email', None)
    if email and '@' in email:
        domain = email.split('@')[1]
        # Remove common TLDs and clean up
        domain_parts = domain.split('.')
        if len(domain_parts) >= 2:
            return domain_parts[0].replace('-', ' ').title()

    return 'Unknown Firm'


def _extract_recipient(practitioner) -> Optional[OutreachRecipient]:
    """Extract recipient info from a practitioner object."""
    if isinstance(practitioner, dict):
        email = practitioner.get('email', '')
        if not email:
            return None
        return OutreachRecipient(
            name=practitioner.get('name', ''),
            email=email,
            role=practitioner.get('role', ''),
            firm=practitioner.get('firm', ''),
        )

    email = getattr(practitioner, 'email', None)
    if not email:
        return None

    return OutreachRecipient(
        name=getattr(practitioner, 'name', '') or '',
        email=email,
        role=getattr(practitioner, 'role', '') or '',
        firm=getattr(practitioner, 'firm', '') or '',
    )


def _extract_notice_summary(notice) -> NoticeSummary:
    """Extract summary from an AnalysedNotice object."""
    return NoticeSummary(
        notice_id=getattr(notice, 'notice_id', ''),
        company_name=getattr(notice, 'company_name', ''),
        company_number=getattr(notice, 'company_number', ''),
        notice_type=getattr(notice, 'notice_type', ''),
        sector=getattr(notice, 'sector', ''),
        estimated_assets=getattr(notice, 'estimated_assets', []) or [],
        opportunity_score=getattr(notice, 'opportunity_score', 0),
        website_url=getattr(notice, 'website_url', None),
    )


def batch_by_firm(notices: list) -> list[OutreachBatchData]:
    """
    Group notices by IP firm.

    Each batch contains:
    - All notices for that firm
    - All practitioners (deduplicated by email) as recipients

    Args:
        notices: List of AnalysedNotice objects

    Returns:
        List of OutreachBatchData objects, sorted by max score descending
    """
    # Group notices by firm
    by_firm: dict[str, list] = defaultdict(list)

    for notice in notices:
        practitioners = getattr(notice, 'practitioners', []) or []
        if not practitioners:
            logger.debug("Skipping notice %s - no practitioners", notice.company_name)
            continue

        # Use first practitioner's firm as the grouping key
        firm = _extract_firm_name(practitioners[0])
        by_firm[firm].append(notice)

    # Build batches
    batches = []

    for firm, firm_notices in by_firm.items():
        batch = OutreachBatchData(firm=firm)

        # Collect all unique practitioners across all notices for this firm
        seen_emails = set()

        for notice in firm_notices:
            # Add notice summary
            batch.notices.append(_extract_notice_summary(notice))

            # Add practitioners
            practitioners = getattr(notice, 'practitioners', []) or []
            for p in practitioners:
                recipient = _extract_recipient(p)
                if recipient and recipient.email.lower() not in seen_emails:
                    seen_emails.add(recipient.email.lower())
                    batch.recipients.append(recipient)

        if batch.recipients and batch.notices:
            batches.append(batch)
            logger.debug(
                "Created batch for %s: %d notices, %d recipients",
                firm, len(batch.notices), len(batch.recipients)
            )

    # Sort by max score descending (prioritize high-value batches)
    batches.sort(key=lambda b: b.max_score, reverse=True)

    logger.info(
        "Batching complete: %d notices grouped into %d batches",
        len(notices), len(batches)
    )

    return batches
