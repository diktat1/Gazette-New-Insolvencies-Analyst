"""
Configuration for the outreach system.

These can be overridden via environment variables.
"""

import os
from dotenv import load_dotenv

load_dotenv()


def _get_bool(key: str, default: bool = False) -> bool:
    """Get a boolean from environment."""
    val = os.getenv(key, str(default)).lower()
    return val in ('true', '1', 'yes', 'on')


def _get_int(key: str, default: int) -> int:
    """Get an integer from environment."""
    try:
        return int(os.getenv(key, str(default)))
    except ValueError:
        return default


def _get_list(key: str, default: str = "") -> list:
    """Get a comma-separated list from environment."""
    val = os.getenv(key, default)
    return [x.strip() for x in val.split(",") if x.strip()]


OUTREACH_CONFIG = {
    # Sender details
    'SENDER_NAME': os.getenv('OUTREACH_SENDER_NAME', 'Your Name'),
    'SENDER_EMAIL': os.getenv('OUTREACH_SENDER_EMAIL', os.getenv('SMTP_USER', '')),
    'SENDER_PHONE': os.getenv('OUTREACH_SENDER_PHONE', ''),
    'SENDER_COMPANY': os.getenv('OUTREACH_SENDER_COMPANY', ''),

    # SMTP (can use main config or separate outreach config)
    'SMTP_HOST': os.getenv('OUTREACH_SMTP_HOST', os.getenv('SMTP_HOST', 'smtp.gmail.com')),
    'SMTP_PORT': _get_int('OUTREACH_SMTP_PORT', _get_int('SMTP_PORT', 587)),
    'SMTP_USER': os.getenv('OUTREACH_SMTP_USER', os.getenv('SMTP_USER', '')),
    'SMTP_PASSWORD': os.getenv('OUTREACH_SMTP_PASSWORD', os.getenv('SMTP_PASSWORD', '')),

    # Quality thresholds
    'MIN_OUTREACH_SCORE': _get_int('OUTREACH_MIN_SCORE', 40),

    # Timing
    'SEND_WINDOW_START': os.getenv('OUTREACH_SEND_START', '09:00'),
    'SEND_WINDOW_END': os.getenv('OUTREACH_SEND_END', '17:00'),
    'SEND_DAYS': _get_list('OUTREACH_SEND_DAYS', 'Mon,Tue,Wed,Thu,Fri'),
    'MIN_DELAY_BETWEEN_SENDS_SECONDS': _get_int('OUTREACH_SEND_DELAY', 120),

    # Follow-ups
    'FOLLOWUP_1_DAYS': _get_int('OUTREACH_FOLLOWUP_1_DAYS', 7),
    'FOLLOWUP_2_DAYS': _get_int('OUTREACH_FOLLOWUP_2_DAYS', 14),
    'MAX_FOLLOWUPS': _get_int('OUTREACH_MAX_FOLLOWUPS', 2),

    # Warm-up limits (by domain age in days)
    'WARMUP_WEEK_1_DAILY_LIMIT': _get_int('OUTREACH_WARMUP_W1', 5),
    'WARMUP_WEEK_2_DAILY_LIMIT': _get_int('OUTREACH_WARMUP_W2', 15),
    'WARMUP_WEEK_3_DAILY_LIMIT': _get_int('OUTREACH_WARMUP_W3', 30),
    'WARMUP_WEEK_4_DAILY_LIMIT': _get_int('OUTREACH_WARMUP_W4', 50),

    # Approval mode
    'REQUIRE_APPROVAL': _get_bool('OUTREACH_REQUIRE_APPROVAL', False),

    # Dry run mode (don't actually send)
    'DRY_RUN': _get_bool('OUTREACH_DRY_RUN', False),

    # Summary email recipient (defaults to main EMAIL_TO)
    'SUMMARY_EMAIL_TO': os.getenv('OUTREACH_SUMMARY_TO', os.getenv('EMAIL_TO', '')),
    'SEND_SUMMARY_TIME': os.getenv('OUTREACH_SUMMARY_TIME', '18:00'),

    # Company contact cooldown
    'COMPANY_CONTACT_COOLDOWN_DAYS': _get_int('OUTREACH_COMPANY_COOLDOWN', 30),

    # Test mode - redirect all outreach to this email instead of real recipients
    'TEST_RECIPIENT_OVERRIDE': os.getenv('OUTREACH_TEST_RECIPIENT', ''),

    # Max emails to send per run (0 = unlimited)
    'MAX_SENDS_PER_RUN': _get_int('OUTREACH_MAX_SENDS', 0),
}


def get_config() -> dict:
    """Get the outreach configuration."""
    return OUTREACH_CONFIG.copy()


def validate_config() -> list[str]:
    """Validate configuration and return list of errors."""
    errors = []

    if not OUTREACH_CONFIG['SENDER_EMAIL']:
        errors.append("OUTREACH_SENDER_EMAIL or SMTP_USER not set")

    if not OUTREACH_CONFIG['SMTP_USER']:
        errors.append("OUTREACH_SMTP_USER or SMTP_USER not set")

    if not OUTREACH_CONFIG['SMTP_PASSWORD']:
        errors.append("OUTREACH_SMTP_PASSWORD or SMTP_PASSWORD not set")

    if not OUTREACH_CONFIG['SENDER_NAME'] or OUTREACH_CONFIG['SENDER_NAME'] == 'Your Name':
        errors.append("OUTREACH_SENDER_NAME should be set to your actual name")

    return errors
