"""
IP Email Finder - Look up Insolvency Practitioner email addresses.

Strategies:
1. Extract email from notice (already done in notice_parser)
2. Guess firm website and find contact page
3. Search Insolvency Service register (future)
4. Web search for "[firm name] insolvency practitioners contact"

This module provides fallback email lookup when the Gazette notice
doesn't include the IP's email address directly.
"""

import logging
import re
import requests
from typing import Optional
from urllib.parse import urljoin, urlparse

logger = logging.getLogger(__name__)

# Common UK IP firm domain patterns
_DOMAIN_SUFFIXES = ['.co.uk', '.com', '.uk', '.org.uk']

# Email regex
_EMAIL_RE = re.compile(r'\b([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})\b')

# Words to remove from firm names when guessing domains
_STOP_WORDS = [
    'llp', 'ltd', 'limited', 'plc', 'partnership', 'partners', 'and', 'the',
    'advisory', 'advisors', 'advisers', 'consulting', 'consultants',
    'restructuring', 'recovery', 'insolvency', 'services', 'group', 'uk',
    '&', 'international', 'business'
]


def _clean_firm_name(firm_name: str) -> str:
    """Clean a firm name for domain guessing."""
    name = firm_name.lower()
    # Remove punctuation
    name = re.sub(r'[^\w\s]', ' ', name)
    # Remove stop words
    words = name.split()
    words = [w for w in words if w not in _STOP_WORDS]
    return ''.join(words)


def _guess_firm_domains(firm_name: str) -> list[str]:
    """Generate possible domain names for a firm."""
    clean_name = _clean_firm_name(firm_name)
    if not clean_name:
        return []

    domains = []
    for suffix in _DOMAIN_SUFFIXES:
        domains.append(f"www.{clean_name}{suffix}")
        # Also try with hyphens for multi-word names
        if ' ' in firm_name.lower():
            hyphenated = re.sub(r'[^\w\s]', '', firm_name.lower()).replace(' ', '-')
            hyphenated = re.sub(r'-+', '-', hyphenated).strip('-')
            if hyphenated and hyphenated != clean_name:
                domains.append(f"www.{hyphenated}{suffix}")

    return domains


def _fetch_page(url: str, timeout: int = 10) -> Optional[str]:
    """Fetch a web page and return its content."""
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (compatible; GazetteBot/1.0; +https://github.com)',
        }
        response = requests.get(url, headers=headers, timeout=timeout, allow_redirects=True)
        if response.status_code == 200:
            return response.text
    except Exception as e:
        logger.debug("Failed to fetch %s: %s", url, e)
    return None


def _find_contact_page(base_url: str) -> Optional[str]:
    """Try to find the contact page URL on a website."""
    # Common contact page paths
    contact_paths = [
        '/contact', '/contact-us', '/contact.html', '/contactus',
        '/get-in-touch', '/about/contact', '/about-us/contact',
        '/team', '/our-team', '/people', '/about/team',
        '/about', '/about-us',
    ]

    for path in contact_paths:
        url = urljoin(base_url, path)
        content = _fetch_page(url)
        if content:
            return content

    return None


def _extract_emails_from_html(html: str) -> list[str]:
    """Extract email addresses from HTML content."""
    # Decode HTML entities
    html = html.replace('&#64;', '@').replace('&#46;', '.')
    html = re.sub(r'&#(\d+);', lambda m: chr(int(m.group(1))), html)

    # Find all emails
    emails = _EMAIL_RE.findall(html)

    # Filter out common non-person emails
    filtered = []
    exclude_patterns = [
        'noreply', 'no-reply', 'donotreply', 'do-not-reply',
        'info@', 'support@', 'admin@', 'webmaster@', 'privacy@',
        'example.com', 'example.org', 'test.com',
    ]
    for email in emails:
        email_lower = email.lower()
        if not any(pat in email_lower for pat in exclude_patterns):
            filtered.append(email)

    return list(set(filtered))


def find_ip_email_from_firm(firm_name: str, ip_name: Optional[str] = None) -> Optional[str]:
    """
    Try to find an email address for an IP based on their firm name.

    Args:
        firm_name: The IP's firm name (e.g., "Smith & Williamson LLP")
        ip_name: Optional IP name to help filter results

    Returns:
        Email address if found, None otherwise
    """
    if not firm_name:
        return None

    logger.debug("Looking up email for firm: %s", firm_name)

    # Try guessed domains
    domains = _guess_firm_domains(firm_name)

    for domain in domains:
        base_url = f"https://{domain}"

        # First check if domain exists
        content = _fetch_page(base_url)
        if not content:
            continue

        logger.debug("Found website: %s", base_url)

        # Look for contact page
        contact_content = _find_contact_page(base_url)
        search_content = contact_content or content

        # Extract emails
        emails = _extract_emails_from_html(search_content)

        if emails:
            # If we have an IP name, try to find a matching email
            if ip_name:
                name_parts = ip_name.lower().split()
                for email in emails:
                    email_lower = email.lower()
                    # Check if any name part is in the email
                    if any(part in email_lower for part in name_parts if len(part) > 2):
                        logger.info("Found matching email for %s: %s", ip_name, email)
                        return email

            # Return first email as fallback
            logger.info("Found firm email for %s: %s", firm_name, emails[0])
            return emails[0]

    logger.debug("No email found for firm: %s", firm_name)
    return None


def enrich_practitioner_emails(practitioners: list) -> list:
    """
    Enrich a list of practitioners with email addresses where missing.

    Modifies the practitioners in place and returns the list.
    """
    for p in practitioners:
        # Skip if already has email
        email = getattr(p, 'email', None) or (p.get('email') if isinstance(p, dict) else None)
        if email:
            continue

        # Get firm and name
        if isinstance(p, dict):
            firm = p.get('firm', '')
            name = p.get('name', '')
        else:
            firm = getattr(p, 'firm', '')
            name = getattr(p, 'name', '')

        if not firm:
            continue

        # Try to find email
        found_email = find_ip_email_from_firm(firm, name)

        if found_email:
            if isinstance(p, dict):
                p['email'] = found_email
            else:
                p.email = found_email

    return practitioners


# Known UK IP firm contact info (manually curated fallback)
_KNOWN_FIRM_EMAILS = {
    'begbies traynor': 'enquiries@begbies-traynor.com',
    'kpmg': 'restructuring@kpmg.co.uk',
    'pwc': 'restructuring.uk@pwc.com',
    'deloitte': 'restructuring@deloitte.co.uk',
    'ey': 'restructuring@uk.ey.com',
    'ernst & young': 'restructuring@uk.ey.com',
    'grant thornton': 'restructuring@uk.gt.com',
    'bdo': 'restructuring@bdo.co.uk',
    'smith & williamson': 'restructuring@smithandwilliamson.com',
    'interpath advisory': 'info@interpathadvisory.com',
    'teneo': 'info@teneo.com',
    'fti consulting': 'info@fticonsulting.com',
    'alvarez & marsal': 'info@alvarezandmarsal.com',
    'quantuma': 'info@quantuma.com',
    'leonard curtis': 'info@leonardcurtis.co.uk',
    'moorfields': 'info@moorfieldscr.com',
    'duff & phelps': 'info@duffandphelps.com',
    'kroll': 'info@kroll.com',
}


def get_known_firm_email(firm_name: str) -> Optional[str]:
    """Look up email for well-known IP firms."""
    if not firm_name:
        return None

    firm_lower = firm_name.lower()
    for known_firm, email in _KNOWN_FIRM_EMAILS.items():
        if known_firm in firm_lower:
            logger.debug("Found known firm email: %s -> %s", firm_name, email)
            return email

    return None
