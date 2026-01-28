"""
Score each insolvency notice for potential acquisition opportunity.

The score (0-100) reflects how likely it is that there are meaningful
assets or a viable business to buy. This is a heuristic – not financial advice.

Key philosophy: the most important signal is whether the company was
actually trading (website exists, filed real accounts, has charges) vs
being a phantom/shell (no website, dormant/micro accounts, no filings).

Scoring factors:
  + Administration / receivership (business may be sold as going concern)
  + Company filed full accounts (substance behind the company)
  + Has charges (secured lending = tangible assets existed)
  + Active SIC codes suggesting physical assets (manufacturing, retail, property)
  + Website exists and verified (operating business)
  + Company has recent filing activity
  + Outstanding charges (assets still encumbered = real assets)
  - Members' voluntary liquidation (solvent wind-down, owners keep proceeds)
  - Company already dissolved
  - Micro-entity / dormant accounts (likely nothing there)
  - Phantom company detected (multiple red flags)
  - No website found
  - Accounts or confirmation statement overdue
"""

import logging
from dataclasses import dataclass, field

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
    signals: list = field(default_factory=list)
    category: str = ""  # "HIGH", "MEDIUM", "LOW", "SKIP"


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
    raw_start = notice.raw_text.lower()[:500] if notice.raw_text else ""

    # -----------------------------------------------------------------------
    # Notice type signals
    # -----------------------------------------------------------------------
    for keyword in _GOOD_OPPORTUNITY_TYPES:
        if keyword in notice_type_lower or keyword in title_lower or keyword in raw_start:
            score += 15
            assessment.signals.append(f"Notice type suggests assets may be available ({keyword})")
            break

    for keyword in _LOW_OPPORTUNITY_TYPES:
        if keyword in notice_type_lower or keyword in title_lower or keyword in raw_start:
            score -= 20
            assessment.signals.append(f"Notice type suggests lower opportunity ({keyword})")
            break

    # -----------------------------------------------------------------------
    # Companies House signals
    # -----------------------------------------------------------------------
    if profile:
        # ----- Phantom company detection (most important signal) -----
        if profile.is_likely_phantom:
            penalty = min(30, len(profile.phantom_reasons) * 10)
            score -= penalty
            assessment.signals.append(
                f"LIKELY PHANTOM/SHELL COMPANY ({len(profile.phantom_reasons)} red flags)"
            )
            for reason in profile.phantom_reasons:
                assessment.signals.append(f"  - {reason}")

        # ----- Company status -----
        status = profile.company_status.lower()
        if status in ("active", "open"):
            score += 5
            assessment.signals.append("Company status: active")
        elif status in ("dissolved", "closed", "converted-closed"):
            score -= 15
            assessment.signals.append("Company already dissolved – likely too late")
        elif status in ("liquidation", "administration", "receivership"):
            score += 3
            assessment.signals.append(f"Company status: {status} (process underway)")

        # ----- Accounts quality -----
        if profile.has_filed_full_accounts:
            score += 12
            assessment.signals.append(
                f"Filed {profile.last_accounts_type} accounts – likely has substance"
            )
        elif profile.last_accounts_type == "dormant":
            score -= 15
            assessment.signals.append("Dormant accounts – company was not trading")
        elif profile.last_accounts_type == "micro-entity":
            score -= 5
            assessment.signals.append("Micro-entity accounts – limited substance")
        elif profile.last_accounts_type in ("unaudited-abridged", "initial"):
            score -= 2
            assessment.signals.append(f"Accounts type: {profile.last_accounts_type}")
        elif not profile.last_accounts_type and not profile.has_accounts_filings:
            score -= 10
            assessment.signals.append("No accounts on file – never filed accounts")

        # ----- Accounts recency -----
        if profile.accounts_overdue:
            score -= 5
            assessment.signals.append("Accounts overdue")
        if profile.confirmation_statement_overdue:
            score -= 3
            assessment.signals.append("Confirmation statement overdue")

        # ----- Charges (secured lending implies assets) -----
        if profile.has_charges:
            score += 10
            charge_detail = f"Has {profile.total_charges} charges"
            if profile.outstanding_charges:
                charge_detail += f" ({profile.outstanding_charges} outstanding)"
                score += 5  # Outstanding charges = assets still in play
            assessment.signals.append(f"{charge_detail} – tangible assets likely existed")

        # ----- SIC codes -----
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
                break

        # ----- Company type -----
        if profile.company_type in ("plc", "european-public-limited-liability-company-se"):
            score += 5
            assessment.signals.append("PLC – likely larger company")

        # ----- Filing activity -----
        if profile.has_recent_activity:
            score += 5
            assessment.signals.append("Recent filing activity")
        elif profile.last_filing_date:
            assessment.signals.append(f"Last filing: {profile.last_filing_date}")

        # ----- Filing history URL -----
        if profile.filing_history_url:
            assessment.signals.append(f"Filings: {profile.filing_history_url}")

        # ----- Insolvency cases from CH -----
        if profile.insolvency_cases:
            latest = profile.insolvency_cases[-1]
            case_info = f"CH insolvency case: {latest.case_type}"
            if latest.practitioner_names:
                case_info += f" (IPs: {', '.join(latest.practitioner_names)})"
            assessment.signals.append(case_info)

    else:
        score -= 5
        assessment.signals.append("Could not find on Companies House – may not be a registered company")

    # -----------------------------------------------------------------------
    # Website – the strongest single signal of a real trading business
    # -----------------------------------------------------------------------
    if has_website:
        score += 15
        assessment.signals.append("Verified company website found – was operating recently")
    else:
        score -= 5
        assessment.signals.append("No website found – may not have been actively trading")

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
