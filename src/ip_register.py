"""
UK Insolvency Practitioner Register - builds and maintains a local database
of licensed IPs from official regulatory sources.

Sources:
- Insolvency Service (gov.uk) - official register of all licensed IPs
- ICAEW, ICAS, ACCA, IPA - individual licensing body registers

The register is cached locally and can be refreshed periodically.
"""

import json
import logging
import os
import re
import sqlite3
from datetime import datetime, timedelta
from typing import Optional
import requests

logger = logging.getLogger(__name__)

# Database path
IP_REGISTER_DB = os.path.join(
    os.path.dirname(os.path.dirname(__file__)),
    "data",
    "ip_register.db"
)

# Cache duration for the register (refresh weekly)
REGISTER_CACHE_DAYS = 7


def _connect() -> sqlite3.Connection:
    """Connect to the IP register database."""
    os.makedirs(os.path.dirname(IP_REGISTER_DB), exist_ok=True)
    conn = sqlite3.connect(IP_REGISTER_DB)
    conn.row_factory = sqlite3.Row
    return conn


def init_ip_register_db() -> None:
    """Initialize the IP register database."""
    conn = _connect()
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS ip_practitioners (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                name_normalized TEXT NOT NULL,
                firm TEXT,
                firm_normalized TEXT,
                email TEXT,
                phone TEXT,
                address TEXT,
                licensing_body TEXT,
                license_number TEXT,
                source TEXT,
                last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(name_normalized, firm_normalized)
            )
        """)

        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_ip_name ON ip_practitioners(name_normalized)
        """)

        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_ip_firm ON ip_practitioners(firm_normalized)
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS register_metadata (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        """)

        conn.commit()
    finally:
        conn.close()


def _normalize_name(name: str) -> str:
    """Normalize a name for matching."""
    if not name:
        return ""
    # Remove titles, lowercase, strip whitespace
    name = re.sub(r'\b(Mr|Mrs|Ms|Miss|Dr|Prof|Sir)\b\.?', '', name, flags=re.IGNORECASE)
    name = re.sub(r'\s+', ' ', name.lower().strip())
    return name


def _normalize_firm(firm: str) -> str:
    """Normalize a firm name for matching."""
    if not firm:
        return ""
    # Remove common suffixes, lowercase
    firm = re.sub(r'\b(LLP|Ltd|Limited|PLC|Inc|Partners|Partnership|& Co|and Co)\b\.?', '', firm, flags=re.IGNORECASE)
    firm = re.sub(r'\s+', ' ', firm.lower().strip())
    return firm


def add_ip_to_register(
    name: str,
    firm: str = "",
    email: str = "",
    phone: str = "",
    address: str = "",
    licensing_body: str = "",
    license_number: str = "",
    source: str = "manual",
) -> bool:
    """Add or update an IP in the register."""
    conn = _connect()
    try:
        name_norm = _normalize_name(name)
        firm_norm = _normalize_firm(firm)

        conn.execute("""
            INSERT INTO ip_practitioners
            (name, name_normalized, firm, firm_normalized, email, phone, address, licensing_body, license_number, source, last_updated)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(name_normalized, firm_normalized) DO UPDATE SET
                email = COALESCE(NULLIF(excluded.email, ''), ip_practitioners.email),
                phone = COALESCE(NULLIF(excluded.phone, ''), ip_practitioners.phone),
                address = COALESCE(NULLIF(excluded.address, ''), ip_practitioners.address),
                licensing_body = COALESCE(NULLIF(excluded.licensing_body, ''), ip_practitioners.licensing_body),
                license_number = COALESCE(NULLIF(excluded.license_number, ''), ip_practitioners.license_number),
                last_updated = CURRENT_TIMESTAMP
        """, (name, name_norm, firm, firm_norm, email, phone, address, licensing_body, license_number, source))

        conn.commit()
        return True
    except Exception as e:
        logger.error("Error adding IP to register: %s", e)
        return False
    finally:
        conn.close()


def find_ip_in_register(name: str, firm: str = "") -> Optional[dict]:
    """
    Find an IP in the register by name and optionally firm.

    Returns dict with 'name', 'firm', 'email', 'phone', etc. if found.
    """
    init_ip_register_db()
    conn = _connect()
    try:
        name_norm = _normalize_name(name)
        firm_norm = _normalize_firm(firm) if firm else None

        # Try exact match first
        if firm_norm:
            row = conn.execute("""
                SELECT * FROM ip_practitioners
                WHERE name_normalized = ? AND firm_normalized = ?
            """, (name_norm, firm_norm)).fetchone()
        else:
            row = conn.execute("""
                SELECT * FROM ip_practitioners
                WHERE name_normalized = ?
                ORDER BY last_updated DESC
                LIMIT 1
            """, (name_norm,)).fetchone()

        if row:
            return dict(row)

        # Try partial name match (surname)
        surname = name_norm.split()[-1] if name_norm else ""
        if surname and len(surname) > 2:
            if firm_norm:
                row = conn.execute("""
                    SELECT * FROM ip_practitioners
                    WHERE name_normalized LIKE ? AND firm_normalized = ?
                    ORDER BY last_updated DESC
                    LIMIT 1
                """, (f"%{surname}%", firm_norm)).fetchone()
            else:
                row = conn.execute("""
                    SELECT * FROM ip_practitioners
                    WHERE name_normalized LIKE ?
                    ORDER BY last_updated DESC
                    LIMIT 1
                """, (f"%{surname}%",)).fetchone()

            if row:
                return dict(row)

        # Try firm-only match
        if firm_norm:
            row = conn.execute("""
                SELECT * FROM ip_practitioners
                WHERE firm_normalized = ? AND email IS NOT NULL AND email != ''
                ORDER BY last_updated DESC
                LIMIT 1
            """, (firm_norm,)).fetchone()

            if row:
                return dict(row)

        return None
    finally:
        conn.close()


def find_firm_email(firm: str) -> Optional[str]:
    """Find any email associated with a firm."""
    init_ip_register_db()
    conn = _connect()
    try:
        firm_norm = _normalize_firm(firm)
        if not firm_norm:
            return None

        row = conn.execute("""
            SELECT email FROM ip_practitioners
            WHERE firm_normalized LIKE ? AND email IS NOT NULL AND email != ''
            LIMIT 1
        """, (f"%{firm_norm}%",)).fetchone()

        return row['email'] if row else None
    finally:
        conn.close()


def get_register_stats() -> dict:
    """Get statistics about the IP register."""
    init_ip_register_db()
    conn = _connect()
    try:
        stats = {}

        row = conn.execute("SELECT COUNT(*) as count FROM ip_practitioners").fetchone()
        stats['total_ips'] = row['count'] if row else 0

        row = conn.execute("SELECT COUNT(*) as count FROM ip_practitioners WHERE email IS NOT NULL AND email != ''").fetchone()
        stats['with_email'] = row['count'] if row else 0

        row = conn.execute("SELECT COUNT(DISTINCT firm_normalized) as count FROM ip_practitioners WHERE firm_normalized != ''").fetchone()
        stats['unique_firms'] = row['count'] if row else 0

        row = conn.execute("SELECT value FROM register_metadata WHERE key = 'last_refresh'").fetchone()
        stats['last_refresh'] = row['value'] if row else None

        return stats
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Bulk import from various sources
# ---------------------------------------------------------------------------

def import_from_csv(csv_path: str, source: str = "csv_import") -> int:
    """
    Import IPs from a CSV file.

    Expected columns: name, firm, email, phone, address, licensing_body, license_number
    (only 'name' is required)
    """
    import csv

    init_ip_register_db()
    count = 0

    with open(csv_path, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row.get('name'):
                add_ip_to_register(
                    name=row.get('name', ''),
                    firm=row.get('firm', ''),
                    email=row.get('email', ''),
                    phone=row.get('phone', ''),
                    address=row.get('address', ''),
                    licensing_body=row.get('licensing_body', ''),
                    license_number=row.get('license_number', ''),
                    source=source,
                )
                count += 1

    return count


def scrape_gov_uk_register(max_pages: int = 100) -> int:
    """
    Scrape the official gov.uk IP finder.

    Note: This is a best-effort scraper - the gov.uk site structure may change.
    Returns the number of IPs added/updated.
    """
    init_ip_register_db()

    # The gov.uk IP finder uses a search-based interface
    # We'll search for common surnames to get coverage
    common_surnames = [
        'smith', 'jones', 'williams', 'brown', 'taylor', 'davies', 'wilson',
        'evans', 'thomas', 'johnson', 'roberts', 'walker', 'wright', 'robinson',
        'thompson', 'white', 'hughes', 'edwards', 'green', 'hall', 'wood',
        'harris', 'lewis', 'martin', 'jackson', 'clarke', 'clark', 'turner',
        'hill', 'scott', 'moore', 'ward', 'anderson', 'allen', 'young', 'king',
        'adams', 'baker', 'bennett', 'campbell', 'carter', 'collins', 'cook',
        'cooper', 'cox', 'davis', 'ellis', 'fisher', 'ford', 'foster', 'fox',
        'graham', 'grant', 'gray', 'hamilton', 'harrison', 'harvey', 'henderson',
    ]

    count = 0
    base_url = "https://www.gov.uk/find-an-insolvency-practitioner"

    headers = {
        'User-Agent': 'Mozilla/5.0 (compatible; GazetteBot/1.0; +https://github.com/gazette-analyst)',
        'Accept': 'text/html,application/xhtml+xml',
    }

    for surname in common_surnames[:max_pages]:
        try:
            resp = requests.get(
                base_url,
                params={'q': surname},
                headers=headers,
                timeout=15,
            )

            if resp.status_code != 200:
                logger.debug("Gov.uk returned %d for surname %s", resp.status_code, surname)
                continue

            # Parse results - this is fragile and depends on page structure
            # Look for practitioner entries in the HTML
            html = resp.text

            # Extract name and firm patterns (simplified - would need proper parsing)
            # Pattern: <a class="gem-c-document-list__item-title" href="...">Name</a>
            name_pattern = r'<a[^>]*class="[^"]*document-list[^"]*"[^>]*>([^<]+)</a>'
            matches = re.findall(name_pattern, html, re.IGNORECASE)

            for match in matches:
                name = match.strip()
                if name and len(name) > 3:
                    add_ip_to_register(
                        name=name,
                        source='gov.uk',
                    )
                    count += 1

            # Be nice to the server
            import time
            time.sleep(0.5)

        except requests.RequestException as e:
            logger.warning("Error scraping gov.uk for %s: %s", surname, e)
            continue

    # Update metadata
    conn = _connect()
    try:
        conn.execute("""
            INSERT OR REPLACE INTO register_metadata (key, value)
            VALUES ('last_refresh', ?)
        """, (datetime.utcnow().isoformat(),))
        conn.commit()
    finally:
        conn.close()

    logger.info("Scraped %d IPs from gov.uk register", count)
    return count


def build_register_from_known_firms() -> int:
    """
    Build register entries from the known firms list in ip_email_finder.py
    """
    from src.ip_email_finder import _KNOWN_FIRM_EMAILS

    init_ip_register_db()
    count = 0

    for firm, email in _KNOWN_FIRM_EMAILS.items():
        # Add as a firm entry (no specific IP name)
        add_ip_to_register(
            name=f"{firm.title()} Team",
            firm=firm.title(),
            email=email,
            source='known_firms',
        )
        count += 1

    return count


# ---------------------------------------------------------------------------
# Integration with ip_email_finder
# ---------------------------------------------------------------------------

def get_ip_email(name: str, firm: str = "") -> Optional[str]:
    """
    Main entry point - find an IP's email using all available methods.

    1. Check local register first (fastest)
    2. Fall back to known firms list
    3. Try firm website scraping

    Args:
        name: IP's name
        firm: IP's firm name

    Returns:
        Email address if found, None otherwise
    """
    # Try local register
    ip = find_ip_in_register(name, firm)
    if ip and ip.get('email'):
        logger.debug("Found IP email in register: %s -> %s", name, ip['email'])
        return ip['email']

    # Try firm-only lookup in register
    if firm:
        email = find_firm_email(firm)
        if email:
            logger.debug("Found firm email in register: %s -> %s", firm, email)
            return email

    # Fall back to known firms and website scraping
    from src.ip_email_finder import get_known_firm_email, find_ip_email_from_firm

    if firm:
        email = get_known_firm_email(firm)
        if email:
            # Cache in register for next time
            add_ip_to_register(name=name, firm=firm, email=email, source='known_firm')
            return email

        # Try website scraping
        email = find_ip_email_from_firm(firm, name)
        if email:
            # Cache in register for next time
            add_ip_to_register(name=name, firm=firm, email=email, source='website_scrape')
            return email

    return None
