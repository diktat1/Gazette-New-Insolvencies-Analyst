"""Fetch and parse the Gazette Atom feed for insolvency notices."""

import logging
import time
from datetime import datetime, timedelta
from typing import Optional
from urllib.parse import urlencode

import requests
from bs4 import BeautifulSoup

from src import config

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

class GazetteEntry:
    """One insolvency notice from the Gazette feed."""

    def __init__(
        self,
        notice_id: str,
        title: str,
        published: str,
        updated: str,
        notice_code: str,
        notice_type: str,
        content_html: str,
        notice_url: str,
    ):
        self.notice_id = notice_id
        self.title = title
        self.published = published
        self.updated = updated
        self.notice_code = notice_code
        self.notice_type = notice_type
        self.content_html = content_html
        self.notice_url = notice_url

    def __repr__(self) -> str:
        return f"<GazetteEntry {self.notice_id}: {self.title[:60]}>"


# ---------------------------------------------------------------------------
# Feed fetching
# ---------------------------------------------------------------------------

def _build_feed_url(page: int = 1, start_date: Optional[str] = None, end_date: Optional[str] = None) -> str:
    """Build the Atom feed URL for insolvency notices."""
    params: list[tuple[str, str]] = []

    # Only add categorycode if NOT using the /insolvency/ endpoint
    # (the /insolvency/ endpoint already filters to insolvency notices)
    if "/insolvency/" not in config.GAZETTE_FEED_BASE:
        for code in config.GAZETTE_CATEGORY_CODES:
            params.append(("categorycode", code))

    if start_date:
        params.append(("start-publish-date", start_date))
    if end_date:
        params.append(("end-publish-date", end_date))

    params.append(("sort-by", "latest-date"))
    params.append(("results-page-size", str(config.GAZETTE_PAGE_SIZE)))
    params.append(("results-page", str(page)))

    return f"{config.GAZETTE_FEED_BASE}/data.feed?{urlencode(params)}"


def _fetch_page(url: str, retries: int = 3) -> Optional[str]:
    """Fetch a single page of the feed with retry logic."""
    for attempt in range(retries):
        try:
            resp = requests.get(
                url,
                headers=config.REQUEST_HEADERS,
                timeout=config.REQUEST_TIMEOUT,
            )
            resp.raise_for_status()
            return resp.text
        except requests.RequestException as exc:
            wait = 2 ** (attempt + 1)
            logger.warning("Feed fetch attempt %d failed (%s), retrying in %ds", attempt + 1, exc, wait)
            time.sleep(wait)
    logger.error("Failed to fetch feed after %d retries: %s", retries, url)
    return None


def _parse_feed(xml_text: str) -> list[GazetteEntry]:
    """Parse Atom XML into GazetteEntry objects."""
    soup = BeautifulSoup(xml_text, "lxml-xml")
    entries: list[GazetteEntry] = []

    for entry in soup.find_all("entry"):
        notice_id = ""
        id_tag = entry.find("id")
        if id_tag:
            notice_id = id_tag.get_text(strip=True)

        title = ""
        title_tag = entry.find("title")
        if title_tag:
            title = title_tag.get_text(strip=True)

        published = ""
        pub_tag = entry.find("published")
        if pub_tag:
            published = pub_tag.get_text(strip=True)

        updated = ""
        upd_tag = entry.find("updated")
        if upd_tag:
            updated = upd_tag.get_text(strip=True)

        # The Gazette uses f:notice-code for the numeric notice type code
        notice_code = ""
        code_tag = entry.find("f:notice-code") or entry.find("notice-code")
        if code_tag:
            notice_code = code_tag.get_text(strip=True)

        # Notice type from category element or title
        notice_type = ""
        category_tag = entry.find("category")
        if category_tag:
            notice_type = category_tag.get("term", "") or category_tag.get("label", "")

        content_html = ""
        content_tag = entry.find("content")
        if content_tag:
            content_html = content_tag.decode_contents()

        # Build notice URL from ID or link
        notice_url = ""
        link_tag = entry.find("link", rel="alternate")
        if link_tag:
            notice_url = link_tag.get("href", "")
        elif notice_id and notice_id.isdigit():
            notice_url = f"{config.GAZETTE_NOTICE_URL}{notice_id}"

        entries.append(
            GazetteEntry(
                notice_id=notice_id,
                title=title,
                published=published,
                updated=updated,
                notice_code=notice_code,
                notice_type=notice_type,
                content_html=content_html,
                notice_url=notice_url,
            )
        )

    return entries


def _get_total_results(xml_text: str) -> int:
    """Extract total result count from feed metadata."""
    soup = BeautifulSoup(xml_text, "lxml-xml")
    total_tag = soup.find("f:total") or soup.find("openSearch:totalResults")
    if total_tag:
        try:
            return int(total_tag.get_text(strip=True))
        except ValueError:
            pass
    return 0


def fetch_latest_notices(lookback_days: Optional[int] = None) -> list[GazetteEntry]:
    """
    Fetch all insolvency notices from the last N days.

    Paginates through the Atom feed automatically.
    """
    days = lookback_days if lookback_days is not None else config.LOOKBACK_DAYS
    end_date = datetime.utcnow().strftime("%Y-%m-%d")
    start_date = (datetime.utcnow() - timedelta(days=days)).strftime("%Y-%m-%d")

    logger.info("Fetching Gazette notices from %s to %s", start_date, end_date)

    all_entries: list[GazetteEntry] = []
    page = 1

    while True:
        url = _build_feed_url(page=page, start_date=start_date, end_date=end_date)
        logger.debug("Fetching page %d: %s", page, url)

        xml_text = _fetch_page(url)
        if not xml_text:
            break

        entries = _parse_feed(xml_text)
        if not entries:
            break

        all_entries.extend(entries)

        # Check if there are more pages
        total = _get_total_results(xml_text)
        if total and len(all_entries) >= total:
            break

        page += 1

        # Safety valve – don't paginate forever
        if page > 50:
            logger.warning("Hit pagination safety limit at page 50")
            break

        # Be polite
        time.sleep(0.5)

    logger.info("Fetched %d notices across %d pages", len(all_entries), page)
    return all_entries
