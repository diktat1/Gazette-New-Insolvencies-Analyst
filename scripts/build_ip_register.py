#!/usr/bin/env python3
"""
Build/refresh the local IP register database.

Usage:
    python scripts/build_ip_register.py [--scrape] [--csv PATH] [--stats]

Options:
    --scrape    Scrape gov.uk for IPs (slow, be respectful of rate limits)
    --csv PATH  Import IPs from a CSV file
    --stats     Show register statistics

The CSV file should have columns: name, firm, email, phone, address, licensing_body
(only 'name' is required, others are optional)
"""

import argparse
import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.ip_register import (
    init_ip_register_db,
    build_register_from_known_firms,
    scrape_gov_uk_register,
    import_from_csv,
    get_register_stats,
)


def main():
    parser = argparse.ArgumentParser(description='Build/refresh the IP register')
    parser.add_argument('--scrape', action='store_true', help='Scrape gov.uk for IPs')
    parser.add_argument('--csv', type=str, help='Import from CSV file')
    parser.add_argument('--stats', action='store_true', help='Show statistics')
    parser.add_argument('--known-firms', action='store_true', help='Import known firms list')

    args = parser.parse_args()

    # Initialize database
    print("Initializing IP register database...")
    init_ip_register_db()

    if args.known_firms:
        print("\nImporting known firms...")
        count = build_register_from_known_firms()
        print(f"  Added {count} firm entries")

    if args.csv:
        print(f"\nImporting from CSV: {args.csv}")
        if not os.path.exists(args.csv):
            print(f"  Error: File not found: {args.csv}")
            sys.exit(1)
        count = import_from_csv(args.csv)
        print(f"  Imported {count} IPs")

    if args.scrape:
        print("\nScraping gov.uk IP register...")
        print("  (This may take a few minutes)")
        count = scrape_gov_uk_register(max_pages=50)
        print(f"  Found {count} IPs")

    if args.stats or not any([args.scrape, args.csv, args.known_firms]):
        stats = get_register_stats()
        print("\n=== IP Register Statistics ===")
        print(f"  Total IPs:     {stats['total_ips']}")
        print(f"  With email:    {stats['with_email']}")
        print(f"  Unique firms:  {stats['unique_firms']}")
        print(f"  Last refresh:  {stats['last_refresh'] or 'Never'}")

    if not any([args.scrape, args.csv, args.stats, args.known_firms]):
        print("\nTo build the register, use one of:")
        print("  python scripts/build_ip_register.py --known-firms  # Import known firms")
        print("  python scripts/build_ip_register.py --scrape       # Scrape gov.uk")
        print("  python scripts/build_ip_register.py --csv ips.csv  # Import from CSV")


if __name__ == '__main__':
    main()
