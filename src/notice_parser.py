"""
Parse the HTML content of a Gazette insolvency notice to extract
structured data: company name, company number, IP details, addresses, etc.

Gazette notices are semi-structured HTML. The parser uses a combination
of regex patterns and HTML parsing to extract fields.
"""

import re
import logging
from dataclasses import dataclass, field

from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)


@dataclass
class InsolvencyPractitioner:
    name: str = ""
    firm: str = ""
    address: str = ""
    phone: str = ""
    email: str = ""
    ip_number: str = ""
    role: str = ""  # e.g. "Joint Administrator", "Liquidator"


@dataclass
class ParsedNotice:
    # Company identification
    company_name: str = ""
    company_number: str = ""
    trading_name: str = ""
    registered_address: str = ""

    # Notice metadata
    notice_type_label: str = ""
    notice_date: str = ""
    court_name: str = ""
    court_case_number: str = ""

    # Insolvency practitioners
    practitioners: list = field(default_factory=list)

    # Raw text fallback
    raw_text: str = ""


# ---------------------------------------------------------------------------
# Regex patterns
# ---------------------------------------------------------------------------

# Company number: 8 digits, sometimes preceded by text like "Company No." / "(No."
_COMPANY_NUMBER_RE = re.compile(
    r"(?:company\s*(?:number|no\.?|registration\s*(?:number|no\.?))\s*[:.]?\s*)"
    r"(\d{6,8})",
    re.IGNORECASE,
)

# SC / NI / OC prefixed company numbers (Scotland, N. Ireland, LLPs)
_PREFIXED_COMPANY_NUMBER_RE = re.compile(
    r"(?:company\s*(?:number|no\.?)\s*[:.]?\s*)?"
    r"\b((?:SC|NI|OC|SO|NC|IP|RC|CE|FC|NF|GE|LP|SL|NL)\d{5,8})\b",
    re.IGNORECASE,
)

# Registered office / address block – capture up to a UK postcode or end of line
_REGISTERED_OFFICE_RE = re.compile(
    r"(?:registered\s+(?:office|address)\s*[:.]?\s*)"
    r"(.*?[A-Z]{1,2}\d[\dA-Z]?\s*\d[A-Z]{2})",
    re.IGNORECASE | re.DOTALL,
)
# Fallback: capture up to the first sentence-ending period
_REGISTERED_OFFICE_RE_FALLBACK = re.compile(
    r"(?:registered\s+(?:office|address)\s*[:.]?\s*)"
    r"([^.]{10,120})",
    re.IGNORECASE,
)

# Trading as / t/a – stop at period, comma, newline, or end of string
_TRADING_AS_RE = re.compile(
    r"(?:trading\s+as|t/a|formerly\s+known\s+as|also\s+known\s+as)\s*[:.]?\s*(.+?)(?:[.\n,]|$)",
    re.IGNORECASE,
)

# Court and case info – require "court" or "tribunal" preceded by "in/of/at the"
_COURT_RE = re.compile(
    r"(?:in|of|at)\s+the\s+([\w\s]{5,60}?(?:court|tribunal))\b",
    re.IGNORECASE,
)
# Case number – require explicit "case" or "ref" prefix with CR-/BR- style numbers
_CASE_NUMBER_RE = re.compile(
    r"(?:case\s*(?:no\.?|number)?\s*[:.]?\s*)((?:CR|BR|IC|IP)[\s\-]?\d[\d\-/]+\d)",
    re.IGNORECASE,
)

# IP / practitioner patterns
_IP_NUMBER_RE = re.compile(r"\bIP\s*(?:No\.?\s*)?(\d{4,6})\b", re.IGNORECASE)

# Phone numbers (UK format)
_PHONE_RE = re.compile(r"\b((?:\+44|0)\s*\d[\d\s\-]{8,13}\d)\b")

# Email addresses
_EMAIL_RE = re.compile(r"\b([a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,})\b")

# Role keywords for practitioners
_ROLE_KEYWORDS = [
    "joint administrator",
    "administrator",
    "joint liquidator",
    "liquidator",
    "joint receiver",
    "receiver",
    "administrative receiver",
    "supervisor",
    "trustee",
    "nominee",
    "insolvency practitioner",
    "official receiver",
    "provisional liquidator",
]


def parse_notice(title: str, content_html: str, notice_type: str = "") -> ParsedNotice:
    """
    Extract structured data from a Gazette notice.

    The notice HTML typically contains:
    - Company name (often in the title or a heading)
    - Company registration number
    - Registered address
    - Details of the insolvency event
    - Insolvency practitioner name, firm, address, contact info
    """
    result = ParsedNotice()
    result.notice_type_label = notice_type

    # Parse HTML to plain text
    soup = BeautifulSoup(content_html, "html.parser")
    text = soup.get_text(separator="\n", strip=True)
    result.raw_text = text

    # -----------------------------------------------------------------------
    # Company name – usually in the title or first line of the notice.
    # Gazette titles often look like: "COMPANY NAME LIMITED" or
    # "COMPANY NAME LTD (in liquidation)"
    # -----------------------------------------------------------------------
    result.company_name = _extract_company_name(title, text)

    # -----------------------------------------------------------------------
    # Company number
    # -----------------------------------------------------------------------
    m = _COMPANY_NUMBER_RE.search(text)
    if m:
        num = m.group(1).zfill(8)  # pad to 8 digits
        result.company_number = num
    else:
        m = _PREFIXED_COMPANY_NUMBER_RE.search(text)
        if m:
            result.company_number = m.group(1).upper()

    # -----------------------------------------------------------------------
    # Trading name
    # -----------------------------------------------------------------------
    m = _TRADING_AS_RE.search(text)
    if m:
        result.trading_name = m.group(1).strip().strip('"\'')

    # -----------------------------------------------------------------------
    # Registered address – try postcode-anchored regex first, then fallback
    # -----------------------------------------------------------------------
    m = _REGISTERED_OFFICE_RE.search(text)
    if not m:
        m = _REGISTERED_OFFICE_RE_FALLBACK.search(text)
    if m:
        addr = m.group(1).strip()
        # Clean up multi-line addresses
        addr = re.sub(r"\s+", " ", addr).strip()
        result.registered_address = addr

    # -----------------------------------------------------------------------
    # Court information
    # -----------------------------------------------------------------------
    m = _COURT_RE.search(text)
    if m:
        result.court_name = m.group(1).strip()

    m = _CASE_NUMBER_RE.search(text)
    if m:
        result.court_case_number = m.group(1).strip()

    # -----------------------------------------------------------------------
    # Insolvency practitioners
    # -----------------------------------------------------------------------
    result.practitioners = _extract_practitioners(text)

    return result


def _extract_company_name(title: str, text: str) -> str:
    """
    Extract the company name from the notice title or body.

    Common patterns:
    - Title is the company name with optional suffix like "(in liquidation)"
    - First bold or heading element in the body
    """
    name = title.strip()

    # Remove common suffixes from title
    for suffix in [
        "(in liquidation)",
        "(in administration)",
        "(in receivership)",
        "(in compulsory liquidation)",
        "(in voluntary liquidation)",
        "(in creditors' voluntary liquidation)",
        "(in members' voluntary liquidation)",
        "- winding-up petition",
        "- winding-up order",
    ]:
        name = re.sub(re.escape(suffix), "", name, flags=re.IGNORECASE).strip()

    # If title is empty or generic, try first line of body
    if not name or name.lower() in ("notice", "insolvency notice", ""):
        lines = [l.strip() for l in text.split("\n") if l.strip()]
        if lines:
            name = lines[0]

    return name.strip()


def _extract_practitioners(text: str) -> list[InsolvencyPractitioner]:
    """
    Extract insolvency practitioner details from the notice text.

    This is inherently fuzzy because notices are semi-structured.
    We look for:
    - Sections mentioning practitioners by role
    - Contact details (phone, email) near those mentions
    - IP registration numbers
    """
    practitioners: list[InsolvencyPractitioner] = []

    # Collect all emails and phones from the entire text
    all_emails = _EMAIL_RE.findall(text)
    all_phones = _PHONE_RE.findall(text)
    all_ip_numbers = _IP_NUMBER_RE.findall(text)

    # Try to find named practitioners by looking for role keywords
    text_lower = text.lower()
    found_roles: list[tuple[int, str]] = []
    for role in _ROLE_KEYWORDS:
        for m in re.finditer(re.escape(role), text_lower):
            found_roles.append((m.start(), role))

    # Sort by position in text
    found_roles.sort(key=lambda x: x[0])

    # Deduplicate role matches: if "joint liquidator" appears at pos 100,
    # "liquidator" will also match at pos 106. Keep only the longest role
    # at each approximate position.
    if found_roles:
        deduped_roles: list[tuple[int, str]] = []
        for pos, role in found_roles:
            # Check if a longer role already covers this position
            dominated = False
            for other_pos, other_role in found_roles:
                if other_role != role and abs(other_pos - pos) < len(role) + 5 and len(other_role) > len(role):
                    dominated = True
                    break
            if not dominated:
                deduped_roles.append((pos, role))
        found_roles = deduped_roles

    if found_roles:
        # For each role mention, try to extract the name that follows
        for idx, (pos, role) in enumerate(found_roles):
            ip = InsolvencyPractitioner()
            ip.role = role.title()

            # Look at the text around the role mention
            # Names often follow the role: "Joint Administrator, John Smith of Firm LLP"
            # Or precede it: "John Smith, Joint Administrator"
            context_start = max(0, pos - 200)
            context_end = min(len(text), pos + 300)
            context = text[context_start:context_end]

            # Try to get the name after the role
            after_role = text[pos + len(role):pos + len(role) + 200]
            name_match = re.match(
                r"[,:\s]*([A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,3})",
                after_role,
            )
            if name_match:
                ip.name = name_match.group(1).strip()

            # If no name after, try before
            if not ip.name:
                before_role = text[max(0, pos - 100):pos]
                name_match = re.search(
                    r"([A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,3})\s*[,]?\s*$",
                    before_role,
                )
                if name_match:
                    ip.name = name_match.group(1).strip()

            # Look for firm name near the role (often "of FIRM LLP" or "at FIRM")
            firm_match = re.search(
                r"\bof\s+(.+?)(?:\.|,|\d|$)",
                after_role,
                re.IGNORECASE,
            )
            if firm_match:
                ip.firm = firm_match.group(1).strip()

            # Assign contact details
            context_emails = _EMAIL_RE.findall(context)
            if context_emails:
                ip.email = context_emails[0]

            context_phones = _PHONE_RE.findall(context)
            if context_phones:
                ip.phone = context_phones[0].strip()

            context_ips = _IP_NUMBER_RE.findall(context)
            if context_ips:
                ip.ip_number = context_ips[0]

            # Deduplicate – skip if we already have an IP with this name or email
            if ip.name and any(p.name == ip.name for p in practitioners):
                continue
            if not ip.name and ip.email and any(p.email == ip.email for p in practitioners):
                continue

            if ip.name or ip.email or ip.phone:
                practitioners.append(ip)

    # If we found no practitioners from roles, create one from available contact data
    if not practitioners and (all_emails or all_phones):
        ip = InsolvencyPractitioner()
        if all_emails:
            ip.email = all_emails[0]
        if all_phones:
            ip.phone = all_phones[0].strip()
        if all_ip_numbers:
            ip.ip_number = all_ip_numbers[0]
        practitioners.append(ip)

    return practitioners
