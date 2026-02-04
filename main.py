#!/usr/bin/env python3
"""
UK Gazette Insolvency Analyst
==============================

Daily monitor for UK Gazette insolvency notices. Analyses each notice,
enriches it with Companies House data and website checks, scores the
opportunity for asset/business acquisition, and emails a report.

Optionally runs automated outreach to Insolvency Practitioners.

Usage:
    python main.py                     # Run once (fetch, analyse, email)
    python main.py --no-email          # Run analysis only, print to stdout
    python main.py --schedule          # Run daily on a schedule
    python main.py --days 7            # Look back 7 days instead of default
    python main.py --output report.html  # Save HTML report to file
    python main.py --outreach          # Enable automated IP outreach
    python main.py --outreach-dry-run  # Preview outreach without sending
"""

import argparse
import logging
import sys
import os

# Ensure project root is on the path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.analyser import analyse_notices
from src.email_report import send_email, generate_email_html, generate_email_plain
from src import config

# Outreach system
from src.outreach import (
    run_outreach_pipeline,
    send_summary_email,
    init_outreach_db,
    OUTREACH_CONFIG,
)


def setup_logging(verbose: bool = False) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    # Quieten noisy libraries
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("requests").setLevel(logging.WARNING)


def run_once(
    days: int | None = None,
    send: bool = True,
    output_file: str | None = None,
    outreach: bool = False,
    outreach_dry_run: bool = False,
) -> None:
    """Run a single analysis + report cycle."""
    logger = logging.getLogger("main")

    logger.info("Starting Gazette insolvency analysis...")
    results = analyse_notices(lookback_days=days)

    if not results:
        logger.info("No new insolvency notices found.")
        return

    logger.info("Found %d notices to report", len(results))

    # Print summary to stdout
    high = sum(1 for r in results if r.opportunity_category == "HIGH")
    medium = sum(1 for r in results if r.opportunity_category == "MEDIUM")
    low = sum(1 for r in results if r.opportunity_category in ("LOW", "SKIP"))
    print(f"\n{'=' * 60}")
    print(f"  Gazette Insolvency Report")
    print(f"  {len(results)} notices: {high} HIGH, {medium} MEDIUM, {low} LOW")
    print(f"{'=' * 60}\n")

    for r in results:
        score_str = f"[{r.opportunity_category:6s} {r.opportunity_score:3d}/100]"
        phantom_tag = " *** PHANTOM ***" if r.ch_is_phantom else ""
        print(f"  {score_str}  {r.company_name}{phantom_tag}")
        if r.company_number:
            print(f"             Co #{r.company_number} | {r.notice_type}")
        if r.ch_status:
            print(f"             Status: {r.ch_status} | Accounts: {r.ch_accounts_type or 'none'}")
        if r.ch_url:
            print(f"             CH: {r.ch_url}")
        if r.ch_filing_history_url:
            print(f"             Filings: {r.ch_filing_history_url}")
        if r.website_url:
            print(f"             Web: {r.website_url}")
        else:
            print(f"             Web: NOT FOUND")
        if r.ch_has_charges:
            charges_str = f"             Charges: {r.ch_total_charges} total"
            if r.ch_outstanding_charges:
                charges_str += f" ({r.ch_outstanding_charges} outstanding)"
            print(charges_str)
        if r.practitioners:
            for p in r.practitioners:
                parts = [p.name, p.role, p.firm, p.email, p.phone]
                ip_str = " | ".join(x for x in parts if x)
                print(f"             IP: {ip_str}")
        print()

    # Save HTML if requested
    if output_file:
        html = generate_email_html(results)
        with open(output_file, "w", encoding="utf-8") as f:
            f.write(html)
        logger.info("HTML report saved to %s", output_file)

    # Run outreach if enabled
    outreach_results = None
    if outreach:
        logger.info("Running outreach pipeline%s...", " (dry run)" if outreach_dry_run else "")
        init_outreach_db()
        outreach_results = run_outreach_pipeline(
            results,
            dry_run=outreach_dry_run,
            send_immediately=True,
        )

        # Log outreach results
        proc = outreach_results.get('processing', {})
        sending = outreach_results.get('sending', {})
        logger.info(
            "Outreach: %d qualified, %d batches, %d sent",
            proc.get('qualified', 0),
            proc.get('batches_created', 0),
            sending.get('sent', 0) if sending else 0,
        )

        # Send summary email
        if not outreach_dry_run:
            send_summary_email(outreach_results)
            logger.info("Outreach summary email sent")

    # Send report email
    if send:
        if config.SMTP_USER and config.EMAIL_TO:
            success = send_email(results)
            if success:
                logger.info("Email sent successfully")
            else:
                logger.error("Failed to send email")
        else:
            logger.warning("Email not configured (set SMTP_USER and EMAIL_TO in .env)")


def run_scheduled(outreach: bool = True) -> None:
    """Run on a daily schedule."""
    import schedule
    import time

    logger = logging.getLogger("main")
    logger.info("Scheduling daily run at %s", config.DAILY_SEND_TIME)

    # Create scheduled job with outreach enabled
    def scheduled_run():
        run_once(outreach=outreach)

    schedule.every().day.at(config.DAILY_SEND_TIME).do(scheduled_run)

    # Also run immediately on startup
    run_once(outreach=outreach)

    while True:
        schedule.run_pending()
        time.sleep(60)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="UK Gazette Insolvency Analyst – daily insolvency opportunity finder"
    )
    parser.add_argument(
        "--no-email", action="store_true",
        help="Run analysis without sending email",
    )
    parser.add_argument(
        "--schedule", action="store_true",
        help="Run daily on a schedule (stays running)",
    )
    parser.add_argument(
        "--days", type=int, default=None,
        help="How many days back to look (overrides LOOKBACK_DAYS)",
    )
    parser.add_argument(
        "--output", type=str, default=None,
        help="Save HTML report to this file path",
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true",
        help="Enable debug logging",
    )
    parser.add_argument(
        "--outreach", action="store_true",
        help="Enable automated IP outreach after analysis",
    )
    parser.add_argument(
        "--outreach-dry-run", action="store_true",
        help="Run outreach in dry-run mode (no actual emails sent)",
    )

    args = parser.parse_args()
    setup_logging(args.verbose)

    if args.schedule:
        run_scheduled(outreach=args.outreach)
    else:
        run_once(
            days=args.days,
            send=not args.no_email,
            output_file=args.output,
            outreach=args.outreach,
            outreach_dry_run=args.outreach_dry_run,
        )


if __name__ == "__main__":
    main()
