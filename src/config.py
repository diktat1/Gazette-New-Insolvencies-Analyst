import os
from dotenv import load_dotenv

load_dotenv()


# ---------------------------------------------------------------------------
# Gazette feed configuration
# ---------------------------------------------------------------------------
# Category 24 = Corporate Insolvency (all types: winding-up, administration,
# receivership, CVL, meetings of creditors, voluntary arrangements)
GAZETTE_CATEGORY_CODES = ["24"]

# Base URL for the Gazette feed
# Using all-notices endpoint with category filter (more reliable than /insolvency/)
GAZETTE_FEED_BASE = "https://www.thegazette.co.uk/all-notices/notice"

# Individual notice detail (HTML)
GAZETTE_NOTICE_URL = "https://www.thegazette.co.uk/notice/"

# Page size for feed pagination
GAZETTE_PAGE_SIZE = 100

# How many days back to look for new notices
LOOKBACK_DAYS = int(os.getenv("LOOKBACK_DAYS", "1"))

# ---------------------------------------------------------------------------
# Companies House API
# ---------------------------------------------------------------------------
COMPANIES_HOUSE_API_KEY = os.getenv("COMPANIES_HOUSE_API_KEY", "")
COMPANIES_HOUSE_BASE_URL = "https://api.company-information.service.gov.uk"

# ---------------------------------------------------------------------------
# Email / SMTP
# ---------------------------------------------------------------------------
SMTP_HOST = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
EMAIL_FROM = os.getenv("EMAIL_FROM", "")
EMAIL_TO = os.getenv("EMAIL_TO", "")
EMAIL_CC = [e.strip() for e in os.getenv("EMAIL_CC", "").split(",") if e.strip()]

# ---------------------------------------------------------------------------
# Scheduling
# ---------------------------------------------------------------------------
DAILY_SEND_TIME = os.getenv("DAILY_SEND_TIME", "08:00")

# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------
MIN_OPPORTUNITY_SCORE = int(os.getenv("MIN_OPPORTUNITY_SCORE", "0"))

# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------
DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "gazette_tracker.db")

# ---------------------------------------------------------------------------
# Request settings
# ---------------------------------------------------------------------------
REQUEST_TIMEOUT = 30  # seconds
REQUEST_HEADERS = {
    "User-Agent": "GazetteInsolvencyAnalyser/1.0",
    "Accept": "application/atom+xml",
}
