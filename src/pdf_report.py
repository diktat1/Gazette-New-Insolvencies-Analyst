"""
PDF report generator for insolvency opportunities.

Generates a professional PDF with:
- Page 1: Executive summary
- Subsequent pages: One company profile per page, grouped by sector
"""

import io
import logging
from collections import defaultdict
from datetime import datetime
from typing import Optional

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    PageBreak, HRFlowable
)

logger = logging.getLogger(__name__)

# Page dimensions
PAGE_WIDTH, PAGE_HEIGHT = A4
MARGIN = 20 * mm


def generate_pdf_report(notices: list, date_str: str = "") -> bytes:
    """
    Generate a PDF report from analysed notices.

    Returns PDF as bytes.
    """
    if not date_str:
        date_str = datetime.utcnow().strftime("%d %B %Y")

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=MARGIN,
        rightMargin=MARGIN,
        topMargin=MARGIN,
        bottomMargin=MARGIN,
    )

    # Styles
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(
        name='Title',
        parent=styles['Heading1'],
        fontSize=24,
        spaceAfter=12,
        textColor=colors.HexColor('#1a365d'),
    ))
    styles.add(ParagraphStyle(
        name='SectionHeader',
        parent=styles['Heading2'],
        fontSize=16,
        spaceBefore=12,
        spaceAfter=6,
        textColor=colors.HexColor('#2c5282'),
    ))
    styles.add(ParagraphStyle(
        name='SubHeader',
        parent=styles['Heading3'],
        fontSize=12,
        spaceBefore=8,
        spaceAfter=4,
        textColor=colors.HexColor('#4a5568'),
    ))
    styles.add(ParagraphStyle(
        name='BodyText',
        parent=styles['Normal'],
        fontSize=10,
        spaceBefore=2,
        spaceAfter=2,
    ))
    styles.add(ParagraphStyle(
        name='SmallText',
        parent=styles['Normal'],
        fontSize=8,
        textColor=colors.HexColor('#718096'),
    ))
    styles.add(ParagraphStyle(
        name='CompanyName',
        parent=styles['Heading2'],
        fontSize=14,
        spaceBefore=0,
        spaceAfter=6,
        textColor=colors.HexColor('#1a365d'),
    ))
    styles.add(ParagraphStyle(
        name='HighScore',
        parent=styles['Normal'],
        fontSize=11,
        textColor=colors.HexColor('#276749'),
        fontName='Helvetica-Bold',
    ))
    styles.add(ParagraphStyle(
        name='MediumScore',
        parent=styles['Normal'],
        fontSize=11,
        textColor=colors.HexColor('#c05621'),
        fontName='Helvetica-Bold',
    ))
    styles.add(ParagraphStyle(
        name='LowScore',
        parent=styles['Normal'],
        fontSize=11,
        textColor=colors.HexColor('#c53030'),
        fontName='Helvetica-Bold',
    ))

    story = []

    # =========================================================================
    # PAGE 1: Executive Summary
    # =========================================================================
    story.append(Paragraph(f"Insolvency Opportunities Report", styles['Title']))
    story.append(Paragraph(f"{date_str}", styles['SmallText']))
    story.append(Spacer(1, 10 * mm))

    # Summary stats
    high = [n for n in notices if n.opportunity_category == "HIGH"]
    medium = [n for n in notices if n.opportunity_category == "MEDIUM"]
    low = [n for n in notices if n.opportunity_category == "LOW"]
    skip = [n for n in notices if n.opportunity_category == "SKIP"]

    summary_data = [
        ["Category", "Count", "Description"],
        ["HIGH POTENTIAL", str(len(high)), "Strong signals of real business with assets"],
        ["MEDIUM POTENTIAL", str(len(medium)), "Some positive signals, worth investigating"],
        ["LOW POTENTIAL", str(len(low)), "Limited signals, possible shell company"],
        ["SKIP", str(len(skip)), "Likely phantom/dormant company"],
    ]

    summary_table = Table(summary_data, colWidths=[50*mm, 25*mm, 90*mm])
    summary_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#2c5282')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 10),
        ('BACKGROUND', (0, 1), (-1, 1), colors.HexColor('#c6f6d5')),
        ('BACKGROUND', (0, 2), (-1, 2), colors.HexColor('#feebc8')),
        ('BACKGROUND', (0, 3), (-1, 3), colors.HexColor('#fed7d7')),
        ('BACKGROUND', (0, 4), (-1, 4), colors.HexColor('#e2e8f0')),
        ('FONTSIZE', (0, 1), (-1, -1), 9),
        ('ALIGN', (1, 0), (1, -1), 'CENTER'),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#a0aec0')),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('TOPPADDING', (0, 0), (-1, -1), 6),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
    ]))
    story.append(summary_table)
    story.append(Spacer(1, 10 * mm))

    # Group by sector
    sectors = defaultdict(list)
    for n in notices:
        sector = n.sector or "Unknown Sector"
        sectors[sector].append(n)

    story.append(Paragraph("By Sector", styles['SectionHeader']))
    sector_data = [["Sector", "High", "Medium", "Low", "Skip"]]
    for sector, sector_notices in sorted(sectors.items()):
        h = sum(1 for n in sector_notices if n.opportunity_category == "HIGH")
        m = sum(1 for n in sector_notices if n.opportunity_category == "MEDIUM")
        l = sum(1 for n in sector_notices if n.opportunity_category == "LOW")
        s = sum(1 for n in sector_notices if n.opportunity_category == "SKIP")
        sector_data.append([sector[:30], str(h), str(m), str(l), str(s)])

    if len(sector_data) > 1:
        sector_table = Table(sector_data, colWidths=[70*mm, 25*mm, 25*mm, 25*mm, 25*mm])
        sector_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#4a5568')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, -1), 9),
            ('ALIGN', (1, 0), (-1, -1), 'CENTER'),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#a0aec0')),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('TOPPADDING', (0, 0), (-1, -1), 4),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ]))
        story.append(sector_table)

    story.append(Spacer(1, 10 * mm))

    # High potential quick list
    if high:
        story.append(Paragraph("High Potential Opportunities", styles['SectionHeader']))
        for n in high[:10]:
            line = f"<b>{n.company_name}</b> ({n.sector or 'Unknown'}) - Score: {n.opportunity_score}/100"
            story.append(Paragraph(line, styles['BodyText']))
        story.append(Spacer(1, 5 * mm))

    # =========================================================================
    # SUBSEQUENT PAGES: One company per page, grouped by sector
    # =========================================================================
    # Sort notices: HIGH first, then MEDIUM, then by score
    sorted_notices = sorted(
        [n for n in notices if n.opportunity_category in ("HIGH", "MEDIUM")],
        key=lambda x: (-{"HIGH": 2, "MEDIUM": 1}.get(x.opportunity_category, 0), -x.opportunity_score)
    )

    current_sector = None
    for notice in sorted_notices:
        story.append(PageBreak())

        # Sector header if changed
        if notice.sector != current_sector:
            current_sector = notice.sector
            story.append(Paragraph(f"Sector: {current_sector or 'Unknown'}", styles['SectionHeader']))
            story.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor('#2c5282')))
            story.append(Spacer(1, 5 * mm))

        # Company header
        score_style = 'HighScore' if notice.opportunity_category == 'HIGH' else 'MediumScore'
        story.append(Paragraph(notice.company_name, styles['CompanyName']))
        story.append(Paragraph(f"Score: {notice.opportunity_score}/100 ({notice.opportunity_category})", styles[score_style]))
        story.append(Spacer(1, 3 * mm))

        # Company details table
        details = []
        if notice.company_number:
            details.append(["Company Number", notice.company_number])
        if notice.notice_type:
            details.append(["Notice Type", notice.notice_type])
        if notice.ch_status:
            details.append(["CH Status", notice.ch_status])
        if notice.ch_accounts_type:
            details.append(["Accounts Type", notice.ch_accounts_type])
        if notice.registered_address:
            addr = notice.registered_address[:60] + "..." if len(notice.registered_address) > 60 else notice.registered_address
            details.append(["Address", addr])
        if notice.ch_created:
            details.append(["Incorporated", notice.ch_created])

        if details:
            details_table = Table(details, colWidths=[40*mm, 125*mm])
            details_table.setStyle(TableStyle([
                ('FONTSIZE', (0, 0), (-1, -1), 9),
                ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
                ('TEXTCOLOR', (0, 0), (0, -1), colors.HexColor('#4a5568')),
                ('VALIGN', (0, 0), (-1, -1), 'TOP'),
                ('TOPPADDING', (0, 0), (-1, -1), 2),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 2),
            ]))
            story.append(details_table)
            story.append(Spacer(1, 4 * mm))

        # Estimated Assets
        if notice.estimated_assets:
            story.append(Paragraph("Estimated Key Assets", styles['SubHeader']))
            assets_text = " • ".join(notice.estimated_assets)
            story.append(Paragraph(assets_text, styles['BodyText']))
            story.append(Spacer(1, 3 * mm))

        # Charges info
        if notice.ch_has_charges:
            story.append(Paragraph("Secured Charges", styles['SubHeader']))
            charges_text = f"{notice.ch_total_charges} total charges"
            if notice.ch_outstanding_charges:
                charges_text += f" ({notice.ch_outstanding_charges} outstanding)"
            story.append(Paragraph(charges_text, styles['BodyText']))
            story.append(Spacer(1, 3 * mm))

        # Links
        story.append(Paragraph("Links", styles['SubHeader']))
        links = []
        if notice.ch_url:
            links.append(f"Companies House: {notice.ch_url}")
        if notice.notice_url:
            links.append(f"Gazette Notice: {notice.notice_url}")
        if notice.website_url:
            links.append(f"Website: {notice.website_url}")
        for link in links:
            story.append(Paragraph(link, styles['SmallText']))
        story.append(Spacer(1, 4 * mm))

        # Insolvency Practitioners
        if notice.practitioners:
            story.append(Paragraph("Insolvency Practitioners", styles['SubHeader']))
            for p in notice.practitioners[:2]:
                parts = []
                if hasattr(p, 'name') and p.name:
                    parts.append(f"<b>{p.name}</b>")
                if hasattr(p, 'role') and p.role:
                    parts.append(f"({p.role})")
                if hasattr(p, 'firm') and p.firm:
                    parts.append(f"at {p.firm}")
                story.append(Paragraph(" ".join(parts), styles['BodyText']))
                contact_parts = []
                if hasattr(p, 'email') and p.email:
                    contact_parts.append(f"Email: {p.email}")
                if hasattr(p, 'phone') and p.phone:
                    contact_parts.append(f"Tel: {p.phone}")
                if contact_parts:
                    story.append(Paragraph(" | ".join(contact_parts), styles['SmallText']))
            story.append(Spacer(1, 4 * mm))

        # Draft Email
        if notice.draft_email_body:
            story.append(Paragraph("Draft Contact Email", styles['SubHeader']))
            story.append(Paragraph(f"<b>Subject:</b> {notice.draft_email_subject}", styles['SmallText']))
            # Show first few lines of draft
            preview = notice.draft_email_body[:300] + "..." if len(notice.draft_email_body) > 300 else notice.draft_email_body
            preview = preview.replace('\n', '<br/>')
            story.append(Paragraph(preview, styles['SmallText']))

        # Signals
        if notice.opportunity_signals:
            story.append(Spacer(1, 3 * mm))
            story.append(Paragraph("Assessment Signals", styles['SubHeader']))
            for sig in notice.opportunity_signals[:5]:
                story.append(Paragraph(f"• {sig}", styles['SmallText']))

        # Phantom warning
        if notice.ch_is_phantom:
            story.append(Spacer(1, 4 * mm))
            story.append(Paragraph("⚠️ PHANTOM COMPANY WARNING", styles['LowScore']))
            for reason in notice.ch_phantom_reasons[:3]:
                story.append(Paragraph(f"• {reason}", styles['SmallText']))

    # Build PDF
    doc.build(story)
    pdf_bytes = buffer.getvalue()
    buffer.close()

    return pdf_bytes


def save_pdf_report(notices: list, output_path: str, date_str: str = "") -> str:
    """Generate and save PDF report to a file."""
    pdf_bytes = generate_pdf_report(notices, date_str)
    with open(output_path, 'wb') as f:
        f.write(pdf_bytes)
    logger.info("PDF report saved to %s", output_path)
    return output_path
