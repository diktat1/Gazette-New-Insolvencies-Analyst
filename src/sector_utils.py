"""
Sector identification and asset estimation utilities.

Uses UK SIC codes to identify company sectors and estimate likely assets.
"""

# SIC Section to Sector Name mapping
SIC_SECTIONS = {
    "A": "Agriculture, Forestry & Fishing",
    "B": "Mining & Quarrying",
    "C": "Manufacturing",
    "D": "Energy & Utilities",
    "E": "Water & Waste Management",
    "F": "Construction",
    "G": "Wholesale & Retail Trade",
    "H": "Transportation & Storage",
    "I": "Hospitality & Food Service",
    "J": "Information & Communication",
    "K": "Financial Services",
    "L": "Real Estate",
    "M": "Professional Services",
    "N": "Administrative Services",
    "O": "Public Administration",
    "P": "Education",
    "Q": "Healthcare & Social Work",
    "R": "Arts & Entertainment",
    "S": "Other Services",
    "T": "Household Activities",
    "U": "Extraterritorial",
}

# SIC code prefixes to section mapping (first 2 digits)
SIC_PREFIX_TO_SECTION = {
    "01": "A", "02": "A", "03": "A",
    "05": "B", "06": "B", "07": "B", "08": "B", "09": "B",
    "10": "C", "11": "C", "12": "C", "13": "C", "14": "C", "15": "C", "16": "C", "17": "C", "18": "C",
    "19": "C", "20": "C", "21": "C", "22": "C", "23": "C", "24": "C", "25": "C", "26": "C", "27": "C",
    "28": "C", "29": "C", "30": "C", "31": "C", "32": "C", "33": "C",
    "35": "D",
    "36": "E", "37": "E", "38": "E", "39": "E",
    "41": "F", "42": "F", "43": "F",
    "45": "G", "46": "G", "47": "G",
    "49": "H", "50": "H", "51": "H", "52": "H", "53": "H",
    "55": "I", "56": "I",
    "58": "J", "59": "J", "60": "J", "61": "J", "62": "J", "63": "J",
    "64": "K", "65": "K", "66": "K",
    "68": "L",
    "69": "M", "70": "M", "71": "M", "72": "M", "73": "M", "74": "M", "75": "M",
    "77": "N", "78": "N", "79": "N", "80": "N", "81": "N", "82": "N",
    "84": "O",
    "85": "P",
    "86": "Q", "87": "Q", "88": "Q",
    "90": "R", "91": "R", "92": "R", "93": "R",
    "94": "S", "95": "S", "96": "S",
    "97": "T", "98": "T",
    "99": "U",
}

# Typical assets by sector
SECTOR_ASSETS = {
    "A": ["Farmland", "Agricultural equipment", "Livestock", "Crops/inventory", "Vehicles"],
    "B": ["Mining rights/licenses", "Heavy machinery", "Land", "Equipment"],
    "C": ["Machinery & plant", "Inventory/stock", "IP/patents", "Warehouse/factory", "Vehicles", "Customer contracts"],
    "D": ["Infrastructure", "Equipment", "Licenses", "Customer contracts"],
    "E": ["Vehicles", "Equipment", "Contracts", "Licenses"],
    "F": ["Construction equipment", "Vehicles", "Property/land", "Material inventory", "Customer contracts", "Scaffolding"],
    "G": ["Inventory/stock", "Retail premises", "Customer database", "Brand/goodwill", "Vehicles", "Fixtures & fittings"],
    "H": ["Vehicles/fleet", "Warehouse facilities", "Customer contracts", "Logistics equipment"],
    "I": ["Property/premises", "Kitchen equipment", "Fixtures & fittings", "Liquor license", "Brand/goodwill", "Inventory"],
    "J": ["Software/IP", "Customer contracts", "Brand", "Equipment", "Domain names", "Source code"],
    "K": ["Customer book", "Licenses", "Brand", "Office equipment"],
    "L": ["Property portfolio", "Land", "Tenant contracts", "Development rights"],
    "M": ["Client relationships", "IP/methodologies", "Brand", "Office equipment"],
    "N": ["Customer contracts", "Equipment", "Vehicles", "Staff expertise"],
    "O": ["N/A - Public sector"],
    "P": ["Property", "Equipment", "Brand/reputation", "Student contracts"],
    "Q": ["Property", "Medical equipment", "Care contracts", "Licenses", "Vehicles"],
    "R": ["IP/content rights", "Equipment", "Venue/property", "Brand"],
    "S": ["Equipment", "Customer database", "Premises", "Brand"],
    "T": ["N/A"],
    "U": ["N/A"],
}


def get_sector_from_sic(sic_codes: list) -> tuple[str, str]:
    """
    Identify the primary sector from SIC codes.

    Returns: (sector_name, section_code)
    """
    if not sic_codes:
        return "Unknown", ""

    # Use first SIC code as primary
    primary_sic = str(sic_codes[0]).strip()
    if len(primary_sic) < 2:
        return "Unknown", ""

    prefix = primary_sic[:2]
    section = SIC_PREFIX_TO_SECTION.get(prefix, "")
    sector_name = SIC_SECTIONS.get(section, "Unknown")

    return sector_name, section


def estimate_key_assets(
    sic_codes: list,
    has_charges: bool = False,
    has_property_charge: bool = False,
    accounts_type: str = "",
    company_type: str = "",
) -> list[str]:
    """
    Estimate likely key assets based on sector and other signals.

    Returns a list of likely asset types.
    """
    sector_name, section = get_sector_from_sic(sic_codes)

    assets = []

    # Get sector-specific assets
    if section and section in SECTOR_ASSETS:
        assets = SECTOR_ASSETS[section].copy()

    # Add signals from charges
    if has_charges:
        if "Property/premises" not in assets and "Property" not in assets:
            assets.insert(0, "Secured assets (see charges)")

    # Filter for likely phantom companies
    if accounts_type in ("dormant", "micro-entity") and not has_charges:
        return ["Likely minimal assets - dormant/micro company"]

    # Limit to top 5 most relevant
    return assets[:5] if assets else ["Assets unknown - research required"]


def get_sic_description(sic_code: str) -> str:
    """Get a brief description of the SIC code activity."""
    # Common SIC codes with descriptions
    SIC_DESCRIPTIONS = {
        "47910": "Retail via mail order/internet",
        "62020": "IT consultancy",
        "62090": "Other IT services",
        "68100": "Buying/selling own real estate",
        "68209": "Letting of own property",
        "70229": "Management consultancy",
        "41100": "Property development",
        "41201": "Construction of houses",
        "43290": "Other construction",
        "56101": "Restaurant",
        "56302": "Pub",
        "55100": "Hotel",
        "49410": "Freight transport",
        "46900": "Wholesale trade",
        "25620": "Machining",
        "82990": "Other business support",
        "96090": "Other personal services",
        "74909": "Other professional services",
        "86210": "General medical practice",
        "93110": "Sports facilities",
        "01110": "Growing cereals",
        "10110": "Meat processing",
    }

    code = str(sic_code).strip()
    return SIC_DESCRIPTIONS.get(code, "")
