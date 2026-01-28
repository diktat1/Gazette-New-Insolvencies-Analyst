"""Fetch and parse the Gazette feed for insolvency notices."""

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

def _build_feed_url(page: int = 1, start_date: Optional[str] = None, end_date: Optional[str] = None, fmt: str = "json") -> str:
    """
    Build the feed URL for insolvency notices.

    Args:
        page: Page number for pagination
        start_date: Start date in YYYY-MM-DD format
        end_date: End date in YYYY-MM-DD format
        fmt: Format - 'json' for JSON, 'feed' for Atom XML
    """
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

    extension = ".json" if fmt == "json" else ".feed"
    return f"{config.GAZETTE_FEED_BASE}/data{extension}?{urlencode(params)}"


def _get_request_headers(fmt: str = "json") -> dict:
    """Get appropriate headers for the format."""
    headers = {
        # Use a standard User-Agent - custom ones may be blocked by WAF
        "User-Agent": "Mozilla/5.0 (compatible; GazetteBot/1.0)",
        "Accept": "*/*",
    }
    return headers


def _fetch_page(url: str, fmt: str = "json", retries: int = 3) -> Optional[str]:
    """Fetch a single page of the feed with retry logic."""
    headers = _get_request_headers(fmt)

    for attempt in range(retries):
        try:
            logger.debug("Fetching URL: %s (attempt %d)", url, attempt + 1)
            resp = requests.get(
                url,
                headers=headers,
                timeout=config.REQUEST_TIMEOUT,
            )

            if resp.status_code == 500:
                logger.warning("Server error (500), attempt %d/%d", attempt + 1, retries)
                if attempt < retries - 1:
                    time.sleep(2 ** (attempt + 1))
                continue

            resp.raise_for_status()
            return resp.text
        except requests.RequestException as exc:
            wait = 2 ** (attempt + 1)
            logger.warning("Feed fetch attempt %d failed (%s), retrying in %ds", attempt + 1, exc, wait)
            time.sleep(wait)

    logger.error("Failed to fetch feed after %d retries: %s", retries, url)
    return None


def _parse_json_feed(json_text: str) -> tuple[list[GazetteEntry], int]:
    """Parse JSON response into GazetteEntry objects."""
    import json

    try:
        data = json.loads(json_text)
    except json.JSONDecodeError as e:
        logger.error("Failed to parse JSON response: %s", e)
        return [], 0

    entries: list[GazetteEntry] = []
    total = 0

    # The JSON structure may vary - try common patterns
    # Pattern 1: {"results": [...], "total": N}
    # Pattern 2: {"entries": [...]}
    # Pattern 3: {"notice": [...]}

    results = None
    if isinstance(data, dict):
        total = data.get("total", 0) or data.get("totalResults", 0) or 0
        results = data.get("results") or data.get("entries") or data.get("notice") or data.get("notices")

        # Sometimes it's nested under a "feed" key
        if not results and "feed" in data:
            feed = data["feed"]
            total = feed.get("total", 0) or feed.get("totalResults", 0) or 0
            results = feed.get("entry") or feed.get("entries") or feed.get("results")
    elif isinstance(data, list):
        results = data

    if not results:
        logger.warning("No results found in JSON response. Keys: %s", list(data.keys()) if isinstance(data, dict) else "list")
        return [], total

    for item in results:
        if not isinstance(item, dict):
            continue

        # Extract notice ID - try various field names
        notice_id = str(
            item.get("notice-id") or
            item.get("noticeId") or
            item.get("id") or
            item.get("notice", {}).get("id", "") or
            ""
        )

        # Extract title
        title = (
            item.get("title") or
            item.get("notice-title") or
            item.get("noticeTitle") or
            ""
        )
        if isinstance(title, dict):
            title = title.get("value", "") or title.get("#text", "") or str(title)

        # Extract dates
        published = item.get("published") or item.get("publication-date") or item.get("publicationDate") or ""
        updated = item.get("updated") or item.get("update-date") or published

        # Notice type/code
        notice_code = str(item.get("notice-code") or item.get("noticeCode") or item.get("notice-type") or "")
        notice_type = item.get("notice-type-name") or item.get("noticeTypeName") or item.get("category") or ""

        # Content - might be in various fields
        content_html = item.get("content") or item.get("summary") or item.get("description") or ""
        if isinstance(content_html, dict):
            content_html = content_html.get("value", "") or content_html.get("#text", "") or ""

        # Build notice URL
        notice_url = item.get("link") or item.get("url") or ""
        if isinstance(notice_url, list) and notice_url:
            # Find alternate link
            for link in notice_url:
                if isinstance(link, dict) and link.get("rel") == "alternate":
                    notice_url = link.get("href", "")
                    break
            if isinstance(notice_url, list):
                notice_url = notice_url[0] if notice_url else ""
        if isinstance(notice_url, dict):
            notice_url = notice_url.get("href", "") or notice_url.get("url", "")

        if not notice_url and notice_id:
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

    return entries, total


def _parse_atom_feed(xml_text: str) -> tuple[list[GazetteEntry], int]:
    """Parse Atom XML into GazetteEntry objects."""
    soup = BeautifulSoup(xml_text, "lxml-xml")
    entries: list[GazetteEntry] = []

    # Get total count
    total = 0
    total_tag = soup.find("f:total") or soup.find("openSearch:totalResults")
    if total_tag:
        try:
            total = int(total_tag.get_text(strip=True))
        except ValueError:
            pass

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

    return entries, total


def fetch_latest_notices(lookback_days: Optional[int] = None) -> list[GazetteEntry]:
    """
    Fetch all insolvency notices from the last N days.

    Tries JSON format first, falls back to Atom XML if needed.
    Paginates through the feed automatically.
    """
    days = lookback_days if lookback_days is not None else config.LOOKBACK_DAYS
    end_date = datetime.utcnow().strftime("%Y-%m-%d")
    start_date = (datetime.utcnow() - timedelta(days=days)).strftime("%Y-%m-%d")

    logger.info("Fetching Gazette notices from %s to %s", start_date, end_date)

    # Try JSON format first, fall back to Atom
    for fmt in ["json", "feed"]:
        logger.info("Trying %s format...", fmt.upper())

        all_entries: list[GazetteEntry] = []
        page = 1
        total_known = 0

        while True:
            url = _build_feed_url(page=page, start_date=start_date, end_date=end_date, fmt=fmt)
            logger.debug("Fetching page %d: %s", page, url)

            response_text = _fetch_page(url, fmt=fmt)
            if not response_text:
                logger.warning("Failed to fetch page %d with %s format", page, fmt)
                break

            # Parse based on format
            if fmt == "json":
                entries, total = _parse_json_feed(response_text)
            else:
                entries, total = _parse_atom_feed(response_text)

            if total > 0:
                total_known = total

            if not entries:
                if page == 1:
                    logger.warning("No entries found on first page with %s format", fmt)
                break

            all_entries.extend(entries)
            logger.info("Page %d: got %d entries (total so far: %d)", page, len(entries), len(all_entries))

            # Check if there are more pages
            if total_known and len(all_entries) >= total_known:
                break

            page += 1

            # Safety valve – don't paginate forever
            if page > 50:
                logger.warning("Hit pagination safety limit at page 50")
                break

            # Be polite
            time.sleep(0.5)

        if all_entries:
            logger.info("Successfully fetched %d notices using %s format", len(all_entries), fmt.upper())
            return all_entries

        logger.warning("No entries found with %s format, trying next...", fmt)

    logger.error("Failed to fetch notices with any format")
    return []
