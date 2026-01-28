"""
Score each insolvency notice for potential acquisition opportunity.

The score (0-100) reflects how likely it is that there are meaningful
assets or a viable business to buy. This is a heuristic – not financial advice.

Scoring factors:
  + Administration / receivership (business may be sold as going concern)
  + Company filed full accounts (substance behind the company)
  + Has charges (secured lending = tangible assets existed)
  + Active SIC codes suggesting physical assets (manufacturing, retail, property)
  + Website exists (operating business)
  + Company has recent activity / not ancient dormant shell
  - Members' voluntary liquidation (solvent wind-down, owners keep proceeds)
  - Company already dissolved
  - Micro-entity / dormant accounts (likely nothing there)
  - Very old company with no recent filings
"""

import logging
from dataclasses import dataclass

from src.notice_parser import ParsedNotice
from src.companies_house import CompanyProfile

logger = logging.getLogger(__name__)

# SIC code prefixes that suggest tangible assets
_ASSET_RICH_SIC_PREFIXES = [
    "01",  # Agriculture
    "10", "11",  # Food & drink manufacturing
    "13", "14", "15",  # Textiles, clothing, leather
    "16", "17",  # Wood, paper
    "20", "21", "22", "23", "24", "25",  # Chemicals, pharma, rubber, metals
    "26", "27", "28", "29", "30",  # Electronics, machinery, vehicles
    "31", "32",  # Furniture, other manufacturing
    "41", "42", "43",  # Construction
    "45", "46", "47",  # Wholesale & retail
    "49", "50", "51", "52",  # Transport & storage
    "55", "56",  # Hospitality
    "68",  # Real estate
    "71",  # Architecture & engineering
    "86",  # Healthcare
    "93",  # Sports & recreation
]

# Notice type keywords that suggest better buying opportunities
_GOOD_OPPORTUNITY_TYPES = [
    "administration",
    "administrator",
    "receiver",
    "receivership",
    "administrative receiver",
    "creditors' voluntary",
    "creditors voluntary",
    "winding-up order",
    "winding up order",
    "meetings of creditors",
    "voluntary arrangement",
]

# Notice types that suggest LESS opportunity
_LOW_OPPORTUNITY_TYPES = [
    "members' voluntary",
    "members voluntary",
    "striking off",
    "dissolution",
]


@dataclass
class OpportunityAssessment:
    score: int = 0  # 0-100
    signals: list = None  # Human-readable reasons
    category: str = ""  # "HIGH", "MEDIUM", "LOW", "SKIP"

    def __post_init__(self):
        if self.signals is None:
            self.signals = []


def score_opportunity(
    notice: ParsedNotice,
    profile: CompanyProfile | None,
    has_website: bool = False,
) -> OpportunityAssessment:
    """
    Score an insolvency notice for acquisition potential.

    Returns an OpportunityAssessment with a score 0-100 and reasoning.
    """
    assessment = OpportunityAssessment()
    score = 30  # Base score – every insolvency notice has _some_ potential

    notice_type_lower = (notice.notice_type_label or "").lower()
    title_lower = (notice.company_name or "").lower()

    # -----------------------------------------------------------------------
    # Notice type signals
    # -----------------------------------------------------------------------
    for keyword in _GOOD_OPPORTUNITY_TYPES:
        if keyword in notice_type_lower or keyword in title_lower or keyword in notice.raw_text.lower()[:500]:
            score += 15
            assessment.signals.append(f"Notice type suggests assets may be available ({keyword})")
            break

    for keyword in _LOW_OPPORTUNITY_TYPES:
        if keyword in notice_type_lower or keyword in title_lower or keyword in notice.raw_text.lower()[:500]:
            score -= 20
            assessment.signals.append(f"Notice type suggests lower opportunity ({keyword})")
            break

    # -----------------------------------------------------------------------
    # Companies House signals
    # -----------------------------------------------------------------------
    if profile:
        # Company status
        status = profile.company_status.lower()
        if status in ("active", "open"):
            score += 5
            assessment.signals.append("Company status: active")
        elif status in ("dissolved", "closed", "converted-closed"):
            score -= 15
            assessment.signals.append("Company already dissolved – likely too late")

        # Filed full accounts (suggests substance)
        if profile.has_filed_full_accounts:
            score += 10
            assessment.signals.append("Filed full/audited accounts – likely has substance")
        elif profile.last_accounts_type in ("micro-entity", "dormant", "unaudited-abridged"):
            score -= 10
            assessment.signals.append(f"Only filed {profile.last_accounts_type} accounts – may be a shell")

        # Has charges (secured lending implies assets existed)
        if profile.has_charges:
            score += 10
            assessment.signals.append("Has secured charges – tangible assets likely existed")

        # SIC codes suggesting physical assets
        if profile.sic_codes:
            for sic in profile.sic_codes:
                for prefix in _ASSET_RICH_SIC_PREFIXES:
                    if str(sic).startswith(prefix):
                        score += 10
                        assessment.signals.append(
                            f"SIC code {sic} suggests asset-rich industry"
                        )
                        break
                else:
                    continue
                break  # Only count SIC bonus once

        # Company type
        if profile.company_type in ("plc", "european-public-limited-liability-company-se"):
            score += 5
            assessment.signals.append("PLC – likely larger company with more assets")

        # Recent activity
        if profile.has_recent_activity:
            score += 5
            assessment.signals.append("Company has recent activity")
    else:
        # No Companies House data found
        score -= 5
        assessment.signals.append("Could not find on Companies House – may not be a registered company")

    # -----------------------------------------------------------------------
    # Website exists
    # -----------------------------------------------------------------------
    if has_website:
        score += 10
        assessment.signals.append("Company website found – was operating recently")

    # -----------------------------------------------------------------------
    # Practitioner contact available
    # -----------------------------------------------------------------------
    if notice.practitioners:
        score += 5
        ip_names = [p.name for p in notice.practitioners if p.name]
        if ip_names:
            assessment.signals.append(f"IP contact found: {', '.join(ip_names)}")
        else:
            assessment.signals.append("IP contact details found in notice")

    # -----------------------------------------------------------------------
    # Clamp and categorise
    # -----------------------------------------------------------------------
    score = max(0, min(100, score))
    assessment.score = score

    if score >= 65:
        assessment.category = "HIGH"
    elif score >= 40:
        assessment.category = "MEDIUM"
    elif score >= 20:
        assessment.category = "LOW"
    else:
        assessment.category = "SKIP"

    return assessment
