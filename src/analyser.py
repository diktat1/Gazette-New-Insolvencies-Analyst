"""
Core orchestrator: fetches notices, enriches each one, scores them,
and returns fully-analysed results ready for the email report.
"""

import logging
import time
from typing import Optional

from src import config
from src.gazette_feed import GazetteEntry, fetch_latest_notices
from src.notice_parser import parse_notice
from src.companies_house import lookup_by_number, search_by_name, get_officers
from src.website_finder import find_website, build_google_search_url
from src.opportunity_scorer import score_opportunity
from src.email_report import AnalysedNotice
from src.db import is_notice_processed, mark_notice_processed

logger = logging.getLogger(__name__)


def analyse_notices(lookback_days: Optional[int] = None) -> list[AnalysedNotice]:
    """
    Full pipeline:
    1. Fetch new insolvency notices from the Gazette
    2. Skip already-processed notices
    3. Parse each notice to extract structured data
    4. Look up the company on Companies House
    5. Try to find the company's website (web search + cross-check)
    6. Score the opportunity
    7. Return fully-enriched notices sorted by score
    """
    entries = fetch_latest_notices(lookback_days)
    logger.info("Fetched %d raw notices from the Gazette", len(entries))

    results: list[AnalysedNotice] = []

    for i, entry in enumerate(entries, 1):
        # Skip duplicates
        if is_notice_processed(entry.notice_id):
            logger.debug("Skipping already-processed notice %s", entry.notice_id)
            continue

        logger.info(
            "[%d/%d] Processing notice %s: %s",
            i, len(entries), entry.notice_id, entry.title[:80],
        )

        try:
            result = _analyse_single(entry)
            results.append(result)
        except Exception:
            logger.exception("Error processing notice %s", entry.notice_id)
            continue

        # Mark as processed
        mark_notice_processed(entry.notice_id, entry.title, entry.published)

        # Rate-limit courtesy – don't hammer APIs
        time.sleep(0.3)

    # Filter by minimum score
    if config.MIN_OPPORTUNITY_SCORE > 0:
        results = [r for r in results if r.opportunity_score >= config.MIN_OPPORTUNITY_SCORE]

    # Sort by score descending
    results.sort(key=lambda r: r.opportunity_score, reverse=True)

    logger.info("Analysis complete: %d notices ready for report", len(results))
    return results


def _analyse_single(entry: GazetteEntry) -> AnalysedNotice:
    """Analyse a single Gazette entry end-to-end."""
    notice = AnalysedNotice()

    # -----------------------------------------------------------------------
    # Step 1: Parse the notice HTML
    # -----------------------------------------------------------------------
    parsed = parse_notice(entry.title, entry.content_html, entry.notice_type)

    notice.notice_id = entry.notice_id
    notice.notice_url = entry.notice_url
    notice.notice_type = entry.notice_type or parsed.notice_type_label
    notice.published_date = entry.published
    notice.company_name = parsed.company_name
    notice.company_number = parsed.company_number
    notice.trading_name = parsed.trading_name
    notice.registered_address = parsed.registered_address
    notice.court_name = parsed.court_name
    notice.court_case_number = parsed.court_case_number
    notice.practitioners = parsed.practitioners

    # -----------------------------------------------------------------------
    # Step 2: Companies House lookup
    # -----------------------------------------------------------------------
    profile = None
    if parsed.company_number:
        profile = lookup_by_number(parsed.company_number)

    # Fall back to name search if no number found or lookup failed
    if not profile and parsed.company_name:
        profile = search_by_name(parsed.company_name)

    if profile:
        notice.company_number = notice.company_number or profile.company_number
        notice.company_name = notice.company_name or profile.company_name
        notice.ch_status = profile.company_status
        notice.ch_type = profile.company_type
        notice.ch_sic_codes = profile.sic_codes
        notice.ch_url = profile.companies_house_url
        notice.ch_has_charges = profile.has_charges
        notice.ch_accounts_type = profile.last_accounts_type
        notice.ch_created = profile.date_of_creation

        # New: filing history and insolvency data
        notice.ch_filing_history_url = profile.filing_history_url
        notice.ch_total_filings = profile.total_filings
        notice.ch_recent_filings = profile.recent_filings
        notice.ch_insolvency_cases = profile.insolvency_cases
        notice.ch_total_charges = profile.total_charges
        notice.ch_outstanding_charges = profile.outstanding_charges
        notice.ch_is_phantom = profile.is_likely_phantom
        notice.ch_phantom_reasons = profile.phantom_reasons

        # Prefer Companies House address if we didn't get one from the notice
        if not notice.registered_address:
            notice.registered_address = profile.registered_address

    # -----------------------------------------------------------------------
    # Step 3: Website lookup (web search + cross-check)
    # -----------------------------------------------------------------------
    website = find_website(
        notice.company_name,
        registered_address=notice.registered_address,
        company_number=notice.company_number,
    )
    notice.website_url = website
    notice.google_search_url = build_google_search_url(notice.company_name)

    # -----------------------------------------------------------------------
    # Step 4: Score the opportunity
    # -----------------------------------------------------------------------
    assessment = score_opportunity(
        parsed,
        profile,
        has_website=website is not None,
    )
    notice.opportunity_score = assessment.score
    notice.opportunity_category = assessment.category
    notice.opportunity_signals = assessment.signals

    return notice
