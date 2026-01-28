"""
Companies House API integration.

Looks up companies by number or name to get:
- Company status (active, dissolved, in liquidation, etc.)
- SIC codes (industry)
- Filing history (accounts, confirmation statements)
- Registered address
- Officers

Free API: https://developer.company-information.service.gov.uk/
Rate limit: 600 requests per 5 minutes.
"""

import logging
import time
from dataclasses import dataclass, field
from typing import Optional

import requests

from src import config

logger = logging.getLogger(__name__)


@dataclass
class CompanyProfile:
    company_number: str = ""
    company_name: str = ""
    company_status: str = ""
    company_type: str = ""
    date_of_creation: str = ""
    date_of_cessation: str = ""
    sic_codes: list = field(default_factory=list)
    registered_address: str = ""
    has_charges: bool = False  # secured debt = possible tangible assets
    has_insolvency_history: bool = False
    last_accounts_date: str = ""
    last_accounts_type: str = ""
    confirmation_statement_overdue: bool = False
    companies_house_url: str = ""
    officers: list = field(default_factory=list)
    # Quick signals about whether there may be substance
    has_filed_full_accounts: bool = False
    has_recent_activity: bool = False


def _api_get(endpoint: str, params: Optional[dict] = None) -> Optional[dict]:
    """Make an authenticated GET request to the Companies House API."""
    if not config.COMPANIES_HOUSE_API_KEY:
        logger.warning("No Companies House API key configured – skipping lookup")
        return None

    url = f"{config.COMPANIES_HOUSE_BASE_URL}{endpoint}"
    try:
        resp = requests.get(
            url,
            params=params,
            auth=(config.COMPANIES_HOUSE_API_KEY, ""),  # API key as username, no password
            timeout=config.REQUEST_TIMEOUT,
        )
        if resp.status_code == 404:
            logger.debug("Companies House 404 for %s", endpoint)
            return None
        if resp.status_code == 429:
            logger.warning("Companies House rate limit hit – backing off")
            time.sleep(60)
            return _api_get(endpoint, params)
        resp.raise_for_status()
        return resp.json()
    except requests.RequestException as exc:
        logger.error("Companies House API error for %s: %s", endpoint, exc)
        return None


def lookup_by_number(company_number: str) -> Optional[CompanyProfile]:
    """Look up a company by its Companies House registration number."""
    if not company_number:
        return None

    # Normalise: pad to 8 digits if purely numeric
    num = company_number.strip().upper()
    if num.isdigit():
        num = num.zfill(8)

    data = _api_get(f"/company/{num}")
    if not data:
        return None

    return _build_profile(data)


def search_by_name(company_name: str) -> Optional[CompanyProfile]:
    """
    Search Companies House by company name and return the best match.

    This is a fallback when we don't have a company number from the notice.
    """
    if not company_name:
        return None

    data = _api_get("/search/companies", params={"q": company_name, "items_per_page": 5})
    if not data or not data.get("items"):
        return None

    # Try to find an exact-ish match
    name_upper = company_name.upper().strip()
    for item in data["items"]:
        if item.get("title", "").upper().strip() == name_upper:
            return lookup_by_number(item.get("company_number", ""))

    # Fall back to first result if close enough
    first = data["items"][0]
    first_name = first.get("title", "").upper()
    # Simple fuzzy: check if the core words match
    name_words = set(name_upper.replace("LIMITED", "LTD").split())
    first_words = set(first_name.replace("LIMITED", "LTD").split())
    overlap = name_words & first_words
    if len(overlap) >= len(name_words) * 0.6:
        return lookup_by_number(first.get("company_number", ""))

    logger.info("No close Companies House match for '%s'", company_name)
    return None


def _build_profile(data: dict) -> CompanyProfile:
    """Build a CompanyProfile from the Companies House API response."""
    profile = CompanyProfile()
    profile.company_number = data.get("company_number", "")
    profile.company_name = data.get("company_name", "")
    profile.company_status = data.get("company_status", "")
    profile.company_type = data.get("type", "")
    profile.date_of_creation = data.get("date_of_creation", "")
    profile.date_of_cessation = data.get("date_of_cessation", "")
    profile.sic_codes = data.get("sic_codes", [])
    profile.has_charges = data.get("has_charges", False)
    profile.has_insolvency_history = data.get("has_insolvency_history", False)
    profile.companies_house_url = (
        f"https://find-and-update.company-information.service.gov.uk/company/{profile.company_number}"
    )

    # Registered address
    addr = data.get("registered_office_address", {})
    parts = [
        addr.get("premises", ""),
        addr.get("address_line_1", ""),
        addr.get("address_line_2", ""),
        addr.get("locality", ""),
        addr.get("region", ""),
        addr.get("postal_code", ""),
        addr.get("country", ""),
    ]
    profile.registered_address = ", ".join(p for p in parts if p)

    # Accounts
    accounts = data.get("accounts", {})
    last_acc = accounts.get("last_accounts", {})
    profile.last_accounts_date = last_acc.get("made_up_to", "")
    profile.last_accounts_type = last_acc.get("type", "")
    profile.has_filed_full_accounts = profile.last_accounts_type in (
        "full", "group", "medium", "small", "audit-exemption-subsidiary",
    )

    # Confirmation statement
    conf = data.get("confirmation_statement", {})
    profile.confirmation_statement_overdue = conf.get("overdue", False)

    # Recent activity heuristic: created less than 10 years ago and has filings
    if profile.date_of_creation:
        try:
            from datetime import datetime
            created = datetime.strptime(profile.date_of_creation, "%Y-%m-%d")
            age_years = (datetime.utcnow() - created).days / 365.25
            profile.has_recent_activity = age_years < 10
        except (ValueError, TypeError):
            pass

    return profile


def get_officers(company_number: str) -> list[dict]:
    """Get the list of officers (directors, secretaries) for a company."""
    if not company_number:
        return []

    num = company_number.strip().upper()
    if num.isdigit():
        num = num.zfill(8)

    data = _api_get(f"/company/{num}/officers")
    if not data:
        return []

    officers = []
    for item in data.get("items", []):
        if item.get("resigned_on"):
            continue  # skip resigned officers
        officers.append({
            "name": item.get("name", ""),
            "role": item.get("officer_role", ""),
            "appointed_on": item.get("appointed_on", ""),
            "nationality": item.get("nationality", ""),
        })

    return officers
