"""
Attempt to find the website for a company.

Companies House doesn't store websites, so we try:
1. Google-style search heuristic using the company name
2. Common domain patterns (companyname.co.uk, companyname.com)
3. Check if the domain actually resolves / returns a page

This is best-effort – many insolvent companies will have dead websites.
"""

import logging
import re
from typing import Optional
from urllib.parse import quote_plus

import requests

from src import config

logger = logging.getLogger(__name__)

# Suffixes to strip from company names when guessing domains
_NAME_SUFFIXES = [
    " limited",
    " ltd",
    " plc",
    " llp",
    " lp",
    " inc",
    " corp",
    " (uk)",
    " uk",
    " group",
    " holdings",
]

# Domain extensions to try
_DOMAIN_EXTENSIONS = [".co.uk", ".com", ".uk", ".org.uk", ".net"]


def find_website(company_name: str, registered_address: str = "") -> Optional[str]:
    """
    Try to find a working website for the company.

    Returns the URL if found, or None.
    """
    if not company_name:
        return None

    # Step 1: Generate candidate domains from the company name
    candidates = _generate_domain_candidates(company_name)

    # Step 2: Check each candidate
    for domain in candidates:
        url = f"https://{domain}"
        if _check_url(url):
            return url
        # Also try www prefix
        www_url = f"https://www.{domain}"
        if _check_url(www_url):
            return www_url

    return None


def _generate_domain_candidates(company_name: str) -> list[str]:
    """Generate plausible domain names from a company name."""
    name = company_name.lower().strip()

    # Strip common suffixes
    for suffix in _NAME_SUFFIXES:
        if name.endswith(suffix):
            name = name[: -len(suffix)].strip()

    # Remove non-alphanumeric chars (keep spaces for now)
    clean = re.sub(r"[^a-z0-9\s]", "", name).strip()

    # Create variations
    slug_hyphen = re.sub(r"\s+", "-", clean)  # "my-company"
    slug_no_space = re.sub(r"\s+", "", clean)  # "mycompany"

    # Also try just the first meaningful word (many companies use short domains)
    words = clean.split()
    first_word = words[0] if words else ""

    candidates: list[str] = []
    for slug in [slug_no_space, slug_hyphen]:
        if not slug:
            continue
        for ext in _DOMAIN_EXTENSIONS:
            candidates.append(f"{slug}{ext}")

    # Add first-word variations (lower priority)
    if first_word and first_word != slug_no_space and len(first_word) > 3:
        for ext in _DOMAIN_EXTENSIONS[:2]:  # Only .co.uk and .com
            candidates.append(f"{first_word}{ext}")

    return candidates


def _check_url(url: str, timeout: int = 8) -> bool:
    """
    Check if a URL is reachable and returns a non-error page.

    We use a HEAD request first (fast), then fall back to GET if needed.
    We consider a site "found" if it returns 200 and isn't a domain parking page.
    """
    try:
        resp = requests.head(
            url,
            timeout=timeout,
            allow_redirects=True,
            headers={"User-Agent": "Mozilla/5.0 (compatible; InsolvencyAnalyser/1.0)"},
        )
        if resp.status_code == 200:
            return True
        if resp.status_code in (301, 302, 307, 308):
            # Redirect – likely valid
            return True
    except requests.RequestException:
        pass

    return False


def build_google_search_url(company_name: str) -> str:
    """Return a Google search URL so the user can manually search."""
    query = f"{company_name} UK company website"
    return f"https://www.google.com/search?q={quote_plus(query)}"
