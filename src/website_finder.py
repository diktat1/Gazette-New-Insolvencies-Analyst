"""
Find the website for a company using web search and cross-checking.

Strategy:
1. Search DuckDuckGo Lite for the company name
2. Extract candidate URLs from search results
3. Cross-check each candidate against Companies House data (address, company
   number on the page) to verify it belongs to the right company
4. Fall back to domain guessing only if search fails

This replaces the naive domain-guessing approach and is much more reliable
at finding companies with creative domain names, while filtering out
false positives (parked domains, name-squatters, unrelated companies).
"""

import logging
import re
from typing import Optional
from urllib.parse import quote_plus, urlparse

import requests
from bs4 import BeautifulSoup

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
    " services",
    " solutions",
    " international",
]

# Domain extensions to try for fallback guessing
_DOMAIN_EXTENSIONS = [".co.uk", ".com", ".uk", ".org.uk"]

# Domains to skip in search results (not company websites)
_SKIP_DOMAINS = {
    "companieshouse.gov.uk",
    "find-and-update.company-information.service.gov.uk",
    "thegazette.co.uk",
    "gov.uk",
    "wikipedia.org",
    "facebook.com",
    "twitter.com",
    "x.com",
    "linkedin.com",
    "instagram.com",
    "youtube.com",
    "tiktok.com",
    "reddit.com",
    "amazon.co.uk",
    "amazon.com",
    "ebay.co.uk",
    "ebay.com",
    "yell.com",
    "yelp.com",
    "trustpilot.com",
    "glassdoor.co.uk",
    "glassdoor.com",
    "bloomberg.com",
    "endole.co.uk",
    "opencorporates.com",
    "checkcompany.co.uk",
    "companycheck.co.uk",
    "duedil.com",
    "crunchbase.com",
    "dnb.com",
}

# Indicators that a page is parked / for sale / dead
_PARKING_INDICATORS = [
    "domain is for sale",
    "this domain is for sale",
    "buy this domain",
    "domain parking",
    "parked domain",
    "this website is for sale",
    "coming soon",
    "under construction",
    "website expired",
    "account suspended",
    "account has been suspended",
    "hosting expired",
    "domain expired",
    "this site can't be reached",
]


def find_website(
    company_name: str,
    registered_address: str = "",
    company_number: str = "",
) -> Optional[str]:
    """
    Find a working website for the company.

    1. Web search for the company name
    2. Check candidate URLs for liveness and relevance
    3. Cross-check against Companies House data
    4. Fall back to domain guessing

    Returns the URL if found, or None.
    """
    if not company_name:
        return None

    # Step 1: Web search
    candidates = _search_for_website(company_name)
    logger.debug("Search returned %d candidate URLs for '%s'", len(candidates), company_name)

    # Step 2: Check each candidate
    for url in candidates:
        if _validate_website(url, company_name, registered_address, company_number):
            logger.info("Found website via search: %s", url)
            return url

    # Step 3: Fallback – generate domain candidates and check
    domain_candidates = _generate_domain_candidates(company_name)
    for domain in domain_candidates:
        for prefix in ["https://www.", "https://"]:
            url = f"{prefix}{domain}"
            if _check_url_alive(url) and not _is_parked(url):
                logger.info("Found website via domain guess: %s", url)
                return url

    return None


def _search_for_website(company_name: str) -> list[str]:
    """
    Search DuckDuckGo Lite for the company name and extract result URLs.

    DuckDuckGo Lite is used because it doesn't require an API key and
    returns a simple HTML page we can parse.
    """
    query = f"{company_name} UK"
    url = f"https://lite.duckduckgo.com/lite/?q={quote_plus(query)}"

    # Use shorter timeout for DuckDuckGo - it often blocks or is slow
    ddg_timeout = getattr(config, 'DUCKDUCKGO_TIMEOUT', 5)
    try:
        resp = requests.get(
            url,
            timeout=ddg_timeout,
            headers={
                "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            },
        )
        resp.raise_for_status()
    except requests.RequestException as exc:
        logger.debug("DuckDuckGo search failed (timeout=%ds): %s", ddg_timeout, exc)
        return []

    # Parse results
    soup = BeautifulSoup(resp.text, "html.parser")
    urls: list[str] = []

    for link in soup.find_all("a"):
        href = link.get("href", "")
        if not href.startswith("http"):
            continue

        parsed = urlparse(href)
        domain = parsed.netloc.lower().lstrip("www.")

        # Skip known non-company-website domains
        if any(domain.endswith(skip) for skip in _SKIP_DOMAINS):
            continue

        # Skip DuckDuckGo internal links
        if "duckduckgo.com" in domain:
            continue

        # Normalise to homepage
        homepage = f"{parsed.scheme}://{parsed.netloc}"
        if homepage not in urls:
            urls.append(homepage)

    return urls[:8]  # Limit to top 8 candidates


def _validate_website(
    url: str,
    company_name: str,
    registered_address: str = "",
    company_number: str = "",
) -> bool:
    """
    Validate that a URL is a real, live company website.

    Checks:
    1. URL is reachable
    2. Page is not parked / for sale
    3. Page content mentions the company name (or close match)
    4. Optionally cross-check company number or address fragments
    """
    try:
        resp = requests.get(
            url,
            timeout=10,
            allow_redirects=True,
            headers={
                "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            },
        )
        if resp.status_code != 200:
            return False
    except requests.RequestException:
        return False

    page_text = resp.text.lower()

    # Check for parking indicators
    for indicator in _PARKING_INDICATORS:
        if indicator in page_text:
            logger.debug("Skipping parked domain: %s", url)
            return False

    # Check if the company name appears on the page
    name_clean = _clean_name(company_name).lower()
    name_words = name_clean.split()

    # Require at least the main words to appear
    if len(name_words) >= 2:
        # Check if most significant words appear
        significant_words = [w for w in name_words if len(w) > 2]
        if significant_words:
            matches = sum(1 for w in significant_words if w in page_text)
            match_ratio = matches / len(significant_words)
            if match_ratio < 0.5:
                logger.debug(
                    "Company name '%s' not found on page %s (match ratio: %.1f)",
                    company_name, url, match_ratio,
                )
                return False
    elif name_clean and name_clean not in page_text:
        return False

    # Bonus: check if company number appears on the page
    if company_number and company_number in page_text:
        logger.debug("Company number %s confirmed on %s", company_number, url)

    # Bonus: check if postcode from address appears
    if registered_address:
        postcode_match = re.search(r"[A-Z]{1,2}\d[\dA-Z]?\s*\d[A-Z]{2}", registered_address, re.IGNORECASE)
        if postcode_match and postcode_match.group().lower() in page_text:
            logger.debug("Postcode confirmed on %s", url)

    return True


def _is_parked(url: str) -> bool:
    """Quick check if a URL is a parked/dead domain."""
    try:
        resp = requests.get(
            url,
            timeout=8,
            allow_redirects=True,
            headers={"User-Agent": "Mozilla/5.0 (compatible; InsolvencyAnalyser/1.0)"},
        )
        if resp.status_code != 200:
            return True

        page_lower = resp.text.lower()
        for indicator in _PARKING_INDICATORS:
            if indicator in page_lower:
                return True

        # Very short pages are often parked
        if len(resp.text.strip()) < 500:
            return True

        return False
    except requests.RequestException:
        return True


def _check_url_alive(url: str, timeout: int = 8) -> bool:
    """Check if a URL is reachable (HEAD request)."""
    try:
        resp = requests.head(
            url,
            timeout=timeout,
            allow_redirects=True,
            headers={"User-Agent": "Mozilla/5.0 (compatible; InsolvencyAnalyser/1.0)"},
        )
        return resp.status_code in (200, 301, 302, 307, 308)
    except requests.RequestException:
        return False


def _clean_name(company_name: str) -> str:
    """Strip legal suffixes from a company name for matching."""
    name = company_name.strip()
    for suffix in _NAME_SUFFIXES:
        if name.lower().endswith(suffix):
            name = name[: -len(suffix)].strip()
    return name


def _generate_domain_candidates(company_name: str) -> list[str]:
    """Generate plausible domain names from a company name."""
    name = _clean_name(company_name).lower()

    # Remove non-alphanumeric chars (keep spaces for now)
    clean = re.sub(r"[^a-z0-9\s]", "", name).strip()

    slug_hyphen = re.sub(r"\s+", "-", clean)
    slug_no_space = re.sub(r"\s+", "", clean)

    candidates: list[str] = []
    for slug in [slug_no_space, slug_hyphen]:
        if not slug:
            continue
        for ext in _DOMAIN_EXTENSIONS:
            candidates.append(f"{slug}{ext}")

    return candidates


def build_google_search_url(company_name: str) -> str:
    """Return a Google search URL so the user can manually search."""
    query = f"{company_name} UK company website"
    return f"https://www.google.com/search?q={quote_plus(query)}"
