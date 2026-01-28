"""
Generate and send the daily insolvency opportunity email report.
"""

import logging
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime
from typing import Optional

from jinja2 import Environment, FileSystemLoader, select_autoescape

from src import config

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Data structure for a fully-analysed notice (passed to the template)
# ---------------------------------------------------------------------------

class AnalysedNotice:
    """All the data we've gathered about a single insolvency notice."""

    def __init__(self):
        # From Gazette
        self.notice_id: str = ""
        self.notice_url: str = ""
        self.notice_type: str = ""
        self.published_date: str = ""

        # Parsed from notice
        self.company_name: str = ""
        self.company_number: str = ""
        self.trading_name: str = ""
        self.registered_address: str = ""
        self.court_name: str = ""
        self.court_case_number: str = ""

        # Insolvency practitioners
        self.practitioners: list = []

        # Companies House
        self.ch_status: str = ""
        self.ch_type: str = ""
        self.ch_sic_codes: list = []
        self.ch_url: str = ""
        self.ch_has_charges: bool = False
        self.ch_accounts_type: str = ""
        self.ch_created: str = ""

        # Website
        self.website_url: Optional[str] = None
        self.google_search_url: str = ""

        # Opportunity assessment
        self.opportunity_score: int = 0
        self.opportunity_category: str = ""
        self.opportunity_signals: list = []


def generate_email_html(notices: list[AnalysedNotice], date_str: str = "") -> str:
    """Render the email HTML from the Jinja2 template."""
    if not date_str:
        date_str = datetime.utcnow().strftime("%d %B %Y")

    # Sort by opportunity score descending
    notices_sorted = sorted(notices, key=lambda n: n.opportunity_score, reverse=True)

    # Group by category
    high = [n for n in notices_sorted if n.opportunity_category == "HIGH"]
    medium = [n for n in notices_sorted if n.opportunity_category == "MEDIUM"]
    low = [n for n in notices_sorted if n.opportunity_category == "LOW"]
    skip = [n for n in notices_sorted if n.opportunity_category == "SKIP"]

    env = Environment(
        loader=FileSystemLoader("templates"),
        autoescape=select_autoescape(["html"]),
    )
    template = env.get_template("email_report.html")

    return template.render(
        date=date_str,
        total_count=len(notices),
        high_opportunities=high,
        medium_opportunities=medium,
        low_opportunities=low,
        skip_opportunities=skip,
        high_count=len(high),
        medium_count=len(medium),
        low_count=len(low),
        skip_count=len(skip),
    )


def generate_email_plain(notices: list[AnalysedNotice], date_str: str = "") -> str:
    """Generate a plain-text fallback of the email."""
    if not date_str:
        date_str = datetime.utcnow().strftime("%d %B %Y")

    lines = [
        f"UK Gazette Insolvency Report – {date_str}",
        f"{'=' * 50}",
        f"Total notices analysed: {len(notices)}",
        "",
    ]

    notices_sorted = sorted(notices, key=lambda n: n.opportunity_score, reverse=True)

    for n in notices_sorted:
        lines.append(f"[{n.opportunity_category}] {n.company_name} (Score: {n.opportunity_score}/100)")
        if n.company_number:
            lines.append(f"  Company No: {n.company_number}")
        lines.append(f"  Type: {n.notice_type}")
        if n.ch_url:
            lines.append(f"  Companies House: {n.ch_url}")
        if n.website_url:
            lines.append(f"  Website: {n.website_url}")
        if n.notice_url:
            lines.append(f"  Gazette: {n.notice_url}")
        if n.practitioners:
            for p in n.practitioners:
                parts = []
                if p.name:
                    parts.append(p.name)
                if p.role:
                    parts.append(f"({p.role})")
                if p.firm:
                    parts.append(f"at {p.firm}")
                if p.email:
                    parts.append(f"- {p.email}")
                if p.phone:
                    parts.append(f"- {p.phone}")
                lines.append(f"  IP: {' '.join(parts)}")
        if n.opportunity_signals:
            for sig in n.opportunity_signals:
                lines.append(f"  • {sig}")
        lines.append("")

    return "\n".join(lines)


def send_email(notices: list[AnalysedNotice]) -> bool:
    """Send the daily email report. Returns True on success."""
    if not config.SMTP_USER or not config.EMAIL_TO:
        logger.error("SMTP_USER or EMAIL_TO not configured – cannot send email")
        return False

    date_str = datetime.utcnow().strftime("%d %B %Y")
    high_count = sum(1 for n in notices if n.opportunity_category == "HIGH")

    subject = f"Gazette Insolvency Report – {date_str}"
    if high_count:
        subject += f" – {high_count} high-potential opportunities"

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = config.EMAIL_FROM or config.SMTP_USER
    msg["To"] = config.EMAIL_TO
    if config.EMAIL_CC:
        msg["Cc"] = ", ".join(config.EMAIL_CC)

    # Plain text part
    plain = generate_email_plain(notices, date_str)
    msg.attach(MIMEText(plain, "plain", "utf-8"))

    # HTML part
    try:
        html = generate_email_html(notices, date_str)
        msg.attach(MIMEText(html, "html", "utf-8"))
    except Exception as exc:
        logger.warning("Could not render HTML template, sending plain text only: %s", exc)

    # All recipients
    recipients = [config.EMAIL_TO] + config.EMAIL_CC

    try:
        with smtplib.SMTP(config.SMTP_HOST, config.SMTP_PORT) as server:
            server.ehlo()
            server.starttls()
            server.ehlo()
            server.login(config.SMTP_USER, config.SMTP_PASSWORD)
            server.sendmail(config.EMAIL_FROM or config.SMTP_USER, recipients, msg.as_string())
        logger.info("Email sent to %s", ", ".join(recipients))
        return True
    except smtplib.SMTPException as exc:
        logger.error("Failed to send email: %s", exc)
        return False
