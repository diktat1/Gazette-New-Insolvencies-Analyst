"""
Email template rendering for outreach.

Templates:
- Single company email
- Multi-company batch email
- Follow-up emails (1st and 2nd)
"""

import logging
from typing import Optional
from jinja2 import Environment, FileSystemLoader, select_autoescape, TemplateNotFound

from src.outreach.config import OUTREACH_CONFIG
from src.outreach.batcher import OutreachBatchData

logger = logging.getLogger(__name__)

# Initialize Jinja2 environment
_env = None


def _get_env() -> Environment:
    """Get or create Jinja2 environment."""
    global _env
    if _env is None:
        _env = Environment(
            loader=FileSystemLoader("templates/outreach"),
            autoescape=select_autoescape(['html']),
        )
    return _env


def _get_sender_info() -> dict:
    """Get sender information from config."""
    return {
        'sender_name': OUTREACH_CONFIG.get('SENDER_NAME', 'Your Name'),
        'sender_email': OUTREACH_CONFIG.get('SENDER_EMAIL', ''),
        'sender_phone': OUTREACH_CONFIG.get('SENDER_PHONE', ''),
        'sender_company': OUTREACH_CONFIG.get('SENDER_COMPANY', ''),
    }


def render_single_company_email(batch: OutreachBatchData) -> tuple[str, str, Optional[str]]:
    """
    Render email for a batch with a single company.

    Returns:
        (subject, body, html_body)
    """
    if not batch.notices:
        raise ValueError("Batch has no notices")

    notice = batch.notices[0]
    recipient = batch.primary_recipient

    # Build subject
    subject = f"Expression of Interest - {notice.company_name}"

    # Build context
    context = {
        **_get_sender_info(),
        'firm': batch.firm,
        'recipient_name': recipient.name if recipient else 'Sir/Madam',
        'company_name': notice.company_name,
        'company_number': notice.company_number,
        'notice_type': notice.notice_type or 'insolvency proceedings',
        'sector': notice.sector,
        'estimated_assets': notice.estimated_assets,
    }

    try:
        env = _get_env()
        template = env.get_template("single_company.txt")
        body = template.render(**context)
    except TemplateNotFound:
        # Fallback to inline template
        body = _render_single_company_fallback(context)

    # Try to render HTML version
    html_body = None
    try:
        env = _get_env()
        html_template = env.get_template("single_company.html")
        html_body = html_template.render(**context)
    except TemplateNotFound:
        pass  # HTML template is optional

    return subject, body, html_body


def render_multi_company_email(batch: OutreachBatchData) -> tuple[str, str, Optional[str]]:
    """
    Render email for a batch with multiple companies.

    Returns:
        (subject, body, html_body)
    """
    if not batch.notices:
        raise ValueError("Batch has no notices")

    # Build subject with company names (max 2)
    company_names = [n.company_name for n in batch.notices[:2]]
    if len(batch.notices) > 2:
        subject = f"Expression of Interest - {company_names[0]} & {len(batch.notices) - 1} others"
    else:
        subject = f"Expression of Interest - {' & '.join(company_names)}"

    # Build context
    context = {
        **_get_sender_info(),
        'firm': batch.firm,
        'recipient_name': f"{batch.firm} Team" if batch.firm != "Unknown Firm" else "Sir/Madam",
        'notices': [n.to_dict() for n in batch.notices],
        'total_companies': len(batch.notices),
    }

    try:
        env = _get_env()
        template = env.get_template("multi_company.txt")
        body = template.render(**context)
    except TemplateNotFound:
        # Fallback to inline template
        body = _render_multi_company_fallback(context)

    # Try to render HTML version
    html_body = None
    try:
        env = _get_env()
        html_template = env.get_template("multi_company.html")
        html_body = html_template.render(**context)
    except TemplateNotFound:
        pass  # HTML template is optional

    return subject, body, html_body


def render_batch_email(batch: OutreachBatchData) -> tuple[str, str, Optional[str]]:
    """
    Render email for a batch (auto-selects single vs multi).

    Returns:
        (subject, body, html_body)
    """
    if len(batch.notices) == 1:
        return render_single_company_email(batch)
    else:
        return render_multi_company_email(batch)


def render_followup_email(
    batch: OutreachBatchData,
    followup_number: int = 1,
) -> tuple[str, str, Optional[str]]:
    """
    Render a follow-up email.

    Args:
        batch: Original batch data
        followup_number: 1 for first follow-up, 2 for final

    Returns:
        (subject, body, html_body)
    """
    # Build subject (Re: original subject)
    if len(batch.notices) == 1:
        original_subject = f"Expression of Interest - {batch.notices[0].company_name}"
    else:
        company_names = [n.company_name for n in batch.notices[:2]]
        if len(batch.notices) > 2:
            original_subject = f"Expression of Interest - {company_names[0]} & {len(batch.notices) - 1} others"
        else:
            original_subject = f"Expression of Interest - {' & '.join(company_names)}"

    subject = f"Re: {original_subject}"

    # Build context
    context = {
        **_get_sender_info(),
        'firm': batch.firm,
        'recipient_name': f"{batch.firm} Team" if batch.firm != "Unknown Firm" else "Sir/Madam",
        'notices': [n.to_dict() for n in batch.notices],
        'total_companies': len(batch.notices),
        'followup_number': followup_number,
        'is_final': followup_number >= 2,
    }

    template_name = f"followup_{followup_number}.txt"

    try:
        env = _get_env()
        template = env.get_template(template_name)
        body = template.render(**context)
    except TemplateNotFound:
        # Fallback to inline template
        body = _render_followup_fallback(context)

    # Try to render HTML version
    html_body = None
    try:
        env = _get_env()
        html_template = env.get_template(f"followup_{followup_number}.html")
        html_body = html_template.render(**context)
    except TemplateNotFound:
        pass  # HTML template is optional

    return subject, body, html_body


# ---------------------------------------------------------------------------
# Fallback templates (used if Jinja2 templates not found)
# ---------------------------------------------------------------------------

def _render_single_company_fallback(ctx: dict) -> str:
    """Fallback template for single company email."""
    assets_str = ", ".join(ctx.get('estimated_assets', [])[:3]) or "the business and assets"

    return f"""Dear {ctx['recipient_name']},

I noticed the recent {ctx['notice_type'].lower()} of {ctx['company_name']}{f" (Company No: {ctx['company_number']})" if ctx.get('company_number') else ""}.

{f"As a {ctx['sector'].lower()} sector opportunity, I would be particularly interested in: {assets_str}." if ctx.get('sector') else f"I would be interested in discussing: {assets_str}."}

I'm actively acquiring businesses and can move quickly on due diligence. I have funds available for the right opportunity.

Would this be suitable for a brief discussion?

Best regards,
{ctx['sender_name']}
{ctx['sender_phone']}

---
If you'd prefer not to receive these emails, simply reply with "unsubscribe"."""


def _render_multi_company_fallback(ctx: dict) -> str:
    """Fallback template for multi-company email."""
    notices = ctx.get('notices', [])

    companies_section = ""
    for i, n in enumerate(notices, 1):
        assets_str = ", ".join(n.get('estimated_assets', [])[:3]) or "Business & Assets"
        companies_section += f"""
{i}. {n['company_name']}
   - Type: {n.get('notice_type', 'Insolvency')}
   - Sector: {n.get('sector', 'Various')}
   - Potential assets: {assets_str}
"""

    return f"""Dear {ctx['recipient_name']},

I noticed your recent appointments and wanted to express interest in the following opportunities:
{companies_section}
I'm actively acquiring businesses in these sectors and can move quickly on due diligence. I have funds available for suitable opportunities.

Would any of these be suitable for a brief discussion?

Best regards,
{ctx['sender_name']}
{ctx['sender_phone']}

---
If you'd prefer not to receive these emails, simply reply with "unsubscribe"."""


def _render_followup_fallback(ctx: dict) -> str:
    """Fallback template for follow-up email."""
    notices = ctx.get('notices', [])
    is_final = ctx.get('is_final', False)

    if len(notices) == 1:
        company_ref = notices[0]['company_name']
    else:
        company_ref = f"the {len(notices)} opportunities I mentioned"

    if is_final:
        return f"""Dear {ctx['recipient_name']},

I wanted to follow up one last time regarding {company_ref}.

If there's an opportunity to discuss or if the assets/business are still available, I remain interested and can move quickly.

If this isn't suitable or the opportunity has passed, no need to reply - I'll remove this from my list.

Best regards,
{ctx['sender_name']}
{ctx['sender_phone']}

---
If you'd prefer not to receive these emails, simply reply with "unsubscribe"."""
    else:
        return f"""Dear {ctx['recipient_name']},

I wanted to follow up on my email from last week regarding {company_ref}.

I remain interested in exploring this opportunity and am happy to work around your timeline.

Would a brief call this week be possible?

Best regards,
{ctx['sender_name']}
{ctx['sender_phone']}

---
If you'd prefer not to receive these emails, simply reply with "unsubscribe"."""
