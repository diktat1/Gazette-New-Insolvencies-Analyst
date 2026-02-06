"""
IP Email Finder - Look up Insolvency Practitioner email addresses.

Strategies (in order of priority):
1. Local IP register database (cached from official sources - see ip_register.py)
2. Known firm emails (fast fallback for major firms)
3. Search Insolvency Service register (gov.uk)
4. Guess firm website and scrape contact page

This module provides fallback email lookup when the Gazette notice
doesn't include the IP's email address directly.

For best results, build the local register first:
    python scripts/build_ip_register.py --known-firms --scrape
"""

import logging
import re
import requests
from typing import Optional
from urllib.parse import urljoin, urlparse, quote_plus

logger = logging.getLogger(__name__)

# Insolvency Service IP Register URLs
_IP_REGISTER_SEARCH = "https://www.insolvencydirect.bis.gov.uk/eiir/IIRSearch.asp"
_IP_REGISTER_DETAIL = "https://www.insolvencydirect.bis.gov.uk/eiir/"


def find_ip_email(name: str, firm: str = "") -> Optional[str]:
    """
    Main entry point - find an IP's email using all available methods.

    This is the recommended function to call from other modules.
    It checks the local register first, then falls back to other methods.

    Args:
        name: IP's full name
        firm: IP's firm name (optional but improves accuracy)

    Returns:
        Email address if found, None otherwise
    """
    # Strategy 1: Try the local register first (fastest, most complete)
    try:
        from src.ip_register import get_ip_email
        email = get_ip_email(name, firm)
        if email:
            logger.debug("Found IP email in register: %s -> %s", name, email)
            return email
    except ImportError:
        logger.debug("IP register module not available, using fallbacks")

    # Strategy 2: Known firms list
    if firm:
        email = get_known_firm_email(firm)
        if email:
            return email

    # Strategy 3: Full contact lookup (includes gov.uk and website scraping)
    result = find_ip_contact_details(name, firm)
    if result and result.get('email'):
        return result['email']

    return None

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
# This covers the major UK insolvency practices
_KNOWN_FIRM_EMAILS = {
    # Big 4 and major accounting firms
    'begbies traynor': 'enquiries@begbies-traynor.com',
    'kpmg': 'restructuring@kpmg.co.uk',
    'pwc': 'restructuring.uk@pwc.com',
    'pricewaterhousecoopers': 'restructuring.uk@pwc.com',
    'deloitte': 'restructuring@deloitte.co.uk',
    'ey': 'restructuring@uk.ey.com',
    'ernst & young': 'restructuring@uk.ey.com',
    'ernst young': 'restructuring@uk.ey.com',
    'grant thornton': 'restructuring@uk.gt.com',
    'bdo': 'restructuring@bdo.co.uk',
    'mazars': 'restructuring@mazars.co.uk',
    'rsm': 'restructuring@rsmuk.com',
    'rsm uk': 'restructuring@rsmuk.com',
    'crowe': 'info@crowe.co.uk',

    # Major restructuring specialists
    'smith & williamson': 'restructuring@smithandwilliamson.com',
    'interpath advisory': 'info@interpathadvisory.com',
    'interpath': 'info@interpathadvisory.com',
    'teneo': 'info@teneo.com',
    'fti consulting': 'info@fticonsulting.com',
    'fti': 'info@fticonsulting.com',
    'alvarez & marsal': 'info@alvarezandmarsal.com',
    'alvarez and marsal': 'info@alvarezandmarsal.com',
    'a&m': 'info@alvarezandmarsal.com',
    'quantuma': 'info@quantuma.com',
    'leonard curtis': 'info@leonardcurtis.co.uk',
    'moorfields': 'info@moorfieldscr.com',
    'moorfields advisory': 'info@moorfieldscr.com',
    'duff & phelps': 'info@duffandphelps.com',
    'kroll': 'info@kroll.com',

    # FRP Advisory (major UK firm)
    'frp advisory': 'info@frpadvisory.com',
    'frp': 'info@frpadvisory.com',

    # Other significant UK IP firms
    'menzies': 'info@menzies.co.uk',
    'btg advisory': 'info@btgadvisory.com',
    'btg': 'info@btgadvisory.com',
    'cvr global': 'info@cvr.global',
    'cvr': 'info@cvr.global',
    'opus restructuring': 'info@opusllp.com',
    'opus': 'info@opusllp.com',
    'wilkin chapman': 'info@wilkinchapman.co.uk',
    'mha': 'info@mha.co.uk',
    'mha macintyre hudson': 'info@mha.co.uk',
    'macintyre hudson': 'info@mha.co.uk',
    'pkf': 'info@pkf.co.uk',
    'pkf littlejohn': 'info@pkf-l.com',
    'haysmacintyre': 'info@haysmacintyre.com',
    'hays macintyre': 'info@haysmacintyre.com',
    'saffery champness': 'info@saffery.com',
    'saffery': 'info@saffery.com',
    'moore kingston smith': 'info@mks.co.uk',
    'kingston smith': 'info@mks.co.uk',
    'azets': 'info@azets.co.uk',
    'blick rothenberg': 'info@blickrothenberg.com',

    # Regional and specialist firms
    'price bailey': 'info@pricebailey.co.uk',
    'shorts': 'info@shorts.uk.com',
    'wilson field': 'info@wilsonfield.co.uk',
    'cork gully': 'info@corkgully.com',
    'insolvency practitioners association': 'info@ipa.uk.com',
    'milsted langdon': 'info@milstedlangdon.co.uk',
    'crawfords': 'info@crawfordsaccountants.co.uk',
    'bcr': 'info@bcr.ltd.uk',
    'business rescue': 'info@businessrescue.co.uk',
    'companydebt': 'info@companydebt.com',
    'real business rescue': 'info@realbusinessrescue.co.uk',
    'hudson weir': 'info@hudsonweir.co.uk',
    'handley stevens': 'info@handleystevens.co.uk',
    'harrisons': 'info@harrisonsba.co.uk',
    'k2 partners': 'info@k2partners.co.uk',
    'david rubin': 'info@drpartners.com',
    'david rubin & partners': 'info@drpartners.com',
    'begbies': 'enquiries@begbies-traynor.com',
    'bt advisory': 'enquiries@begbies-traynor.com',

    # Scottish firms
    'french duncan': 'info@frenchduncan.co.uk',
    'johnston carmichael': 'info@jcca.co.uk',
    'anderson strathern': 'info@andersonstrathern.co.uk',
    'azets scotland': 'info@azets.co.uk',

    # Northern Ireland
    'kpmg belfast': 'restructuring@kpmg.co.uk',
    'pwc belfast': 'restructuring.uk@pwc.com',

    # Specialist turnaround
    'alix partners': 'info@alixpartners.com',
    'alixpartners': 'info@alixpartners.com',
    'zolfo cooper': 'info@zolfocooper.com',
    'focus management': 'info@focusmanagement.co.uk',

    # Newer/boutique firms
    'seneca partners': 'info@senecapartners.co.uk',
    'pbc business recovery': 'info@pbcbusinessrecovery.co.uk',
    'griffins': 'info@griffins.uk.com',
    'mcr': 'info@mcr.uk.com',
    'leading': 'info@leading.uk.com',
    'resolve': 'info@resolvegroup.co.uk',
    'insolvency support': 'info@insolvencysupport.co.uk',
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


def search_insolvency_service_register(ip_name: str) -> Optional[dict]:
    """
    Search the official Insolvency Service IP register for practitioner details.

    The register is at https://www.gov.uk/find-an-insolvency-practitioner
    It provides contact details for licensed IPs.

    Args:
        ip_name: Name of the insolvency practitioner

    Returns:
        Dict with 'email', 'phone', 'firm', 'address' if found, None otherwise
    """
    if not ip_name or len(ip_name) < 3:
        return None

    # The gov.uk IP finder search endpoint
    search_url = "https://www.gov.uk/find-an-insolvency-practitioner"

    try:
        # First, get the search form page
        headers = {
            'User-Agent': 'Mozilla/5.0 (compatible; GazetteBot/1.0)',
        }

        # Try searching via the direct URL pattern
        # The actual API is behind the gov.uk frontend
        # We'll try the search page and look for results

        # Prepare the search - use the surname (last word of name)
        name_parts = ip_name.strip().split()
        if len(name_parts) >= 2:
            surname = name_parts[-1]
        else:
            surname = ip_name

        # Search the register
        search_params = {
            'q': surname,
        }

        resp = requests.get(
            search_url,
            params=search_params,
            headers=headers,
            timeout=10,
            allow_redirects=True,
        )

        if resp.status_code != 200:
            logger.debug("Insolvency Service register returned %d", resp.status_code)
            return None

        # Parse the results page for matching IPs
        html = resp.text.lower()

        # Look for the full name in results
        full_name_lower = ip_name.lower()
        if full_name_lower not in html:
            logger.debug("IP %s not found in register results", ip_name)
            return None

        # Try to extract contact details from the page
        # Look for email patterns near the name
        email_match = _EMAIL_RE.search(resp.text)
        if email_match:
            email = email_match.group(1)
            logger.info("Found email from IP register for %s: %s", ip_name, email)
            return {
                'email': email,
                'name': ip_name,
            }

        logger.debug("IP %s found in register but no email extracted", ip_name)
        return None

    except requests.RequestException as e:
        logger.debug("Insolvency Service register lookup failed: %s", e)
        return None


def find_ip_contact_details(ip_name: str, firm_name: str = "") -> Optional[dict]:
    """
    Try all methods to find contact details for an IP.

    Args:
        ip_name: Name of the insolvency practitioner
        firm_name: Optional firm name for fallback lookups

    Returns:
        Dict with at least 'email' key if found, None otherwise
    """
    # Strategy 1: Known firm emails (fastest)
    if firm_name:
        email = get_known_firm_email(firm_name)
        if email:
            return {'email': email, 'source': 'known_firm'}

    # Strategy 2: Insolvency Service register
    result = search_insolvency_service_register(ip_name)
    if result and result.get('email'):
        result['source'] = 'insolvency_register'
        return result

    # Strategy 3: Firm website lookup
    if firm_name:
        email = find_ip_email_from_firm(firm_name, ip_name)
        if email:
            return {'email': email, 'source': 'firm_website'}

    return None
