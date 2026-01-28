import os
from dotenv import load_dotenv

load_dotenv()


# ---------------------------------------------------------------------------
# Gazette feed configuration
# ---------------------------------------------------------------------------
# Category codes for insolvency notices where assets may be available to buy.
#
# Corporate insolvency (category 24) sub-types:
#   G305010100 – Winding-up petitions
#   G305010200 – Winding-up orders
#   G305010300 – Voluntary liquidation (creditors')
#   G305010500 – Appointments of administrators / receivers
#   G405010001 – Administration orders
#   G405010002 – Appointment of administrators
#   G405010004 – Appointment of receivers
#   G405010005 – Meetings of creditors
#   G405010007 – Voluntary arrangements
#
# We include all of these because each can signal available assets.
GAZETTE_CATEGORY_CODES = [
    "G305010100",
    "G305010200",
    "G305010300",
    "G305010500",
    "G405010001",
    "G405010002",
    "G405010004",
    "G405010005",
    "G405010007",
]

# Base URL for the Gazette Atom feed
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
