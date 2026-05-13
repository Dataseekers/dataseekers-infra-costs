#!/usr/bin/env python3
"""Cost collection CLI for dataseekers infrastructure."""

import argparse
import sys
from datetime import date, datetime

from collectors.base import get_bq_client
from collectors.ovh import OVHCollector
from collectors.oci import OCICollector
from collectors.brightdata import BrightDataCollector
from collectors.gcp import GCPCollector
from collectors.bitbucket import BitbucketCollector
from collectors.clickhouse import ClickHouseCollector
from collectors.claude_ai import ClaudeAICollector


COLLECTORS = {
    "ovh": OVHCollector,
    "oci": OCICollector,
    "brightdata": BrightDataCollector,
    "gcp": GCPCollector,
    "bitbucket": BitbucketCollector,
    "clickhouse": ClickHouseCollector,
    "claude_ai": ClaudeAICollector,
}


def get_month_range(month_str: str) -> tuple[date, date]:
    """Parse month string and return (start_date, end_date)."""
    if month_str == "previous":
        today = date.today()
        end = today.replace(day=1)
        start = (end.replace(day=1) - __import__("datetime").timedelta(days=1)).replace(day=1)
        return start, end

    if month_str == "current":
        today = date.today()
        start = today.replace(day=1)
        if start.month == 12:
            end = start.replace(year=start.year + 1, month=1)
        else:
            end = start.replace(month=start.month + 1)
        return start, end

    # Format: YYYY-MM
    year, month = map(int, month_str.split("-"))
    start = date(year, month, 1)
    if month == 12:
        end = date(year + 1, 1, 1)
    else:
        end = date(year, month + 1, 1)
    return start, end


def cmd_collect(args):
    start, end = get_month_range(args.month)
    providers = args.providers.split(",") if args.providers else list(COLLECTORS.keys())
    bq_client = get_bq_client() if not args.dry_run else None

    print(f"Collecting costs: {start} to {end}")
    print(f"Providers: {', '.join(providers)}")
    print()

    failures = 0
    for provider_name in providers:
        if provider_name not in COLLECTORS:
            print(f"  SKIP {provider_name}: unknown provider")
            continue

        print(f"  {provider_name}...", end=" ", flush=True)
        try:
            collector = COLLECTORS[provider_name]()
            records = collector.collect(start, end)
            warnings = collector.validate(records)

            for w in warnings:
                print(f"\n    WARNING: {w}")

            total = sum(r.amount for r in records)
            print(f"{len(records)} records, €{total:,.2f}")

            if args.dry_run:
                for r in records[:10]:
                    print(f"    {r.date} {r.business_unit:15s} {r.category:10s} €{r.amount:>10.2f}  {r.description[:60]}")
                if len(records) > 10:
                    print(f"    ... and {len(records) - 10} more")
            else:
                collector.load(records, bq_client)
                print(f"    Loaded to BigQuery")

        except Exception as e:
            print(f"ERROR: {e}")
            if args.verbose:
                import traceback
                traceback.print_exc()
            failures += 1

    print("\nDone.")
    if failures:
        sys.exit(1)


def cmd_report(args):
    start, end = get_month_range(args.month)
    client = get_bq_client()

    month_label = start.strftime("%B %Y")
    print(f"\nCosts {month_label}")
    print("=" * 50)

    # By business unit
    print("\nBy business unit:")
    rows = client.query(f"""
        SELECT business_unit, SUM(amount) as total
        FROM `dataseekers-core.costs.raw_costs`
        WHERE date >= '{start}' AND date < '{end}'
        GROUP BY 1
        ORDER BY total DESC
    """).result()

    grand_total = 0
    for row in rows:
        grand_total += row.total
        print(f"  {row.business_unit:20s} €{row.total:>10,.2f}")
    print(f"  {'─' * 32}")
    print(f"  {'TOTAL':20s} €{grand_total:>10,.2f}")

    # By provider
    print("\nBy provider:")
    rows = client.query(f"""
        SELECT provider, SUM(amount) as total
        FROM `dataseekers-core.costs.raw_costs`
        WHERE date >= '{start}' AND date < '{end}'
        GROUP BY 1
        ORDER BY total DESC
    """).result()

    for row in rows:
        pct = (row.total / grand_total * 100) if grand_total else 0
        print(f"  {row.provider:20s} €{row.total:>10,.2f}  ({pct:.1f}%)")


def cmd_validate(args):
    start, end = get_month_range(args.month)
    client = get_bq_client()

    print(f"Validating costs: {start} to {end}")

    # Check month-over-month changes
    rows = client.query(f"""
        WITH `current` AS (
            SELECT provider, SUM(amount) as total
            FROM `dataseekers-core.costs.raw_costs`
            WHERE date >= '{start}' AND date < '{end}'
            GROUP BY 1
        ),
        previous AS (
            SELECT provider, SUM(amount) as total
            FROM `dataseekers-core.costs.raw_costs`
            WHERE date >= DATE_SUB('{start}', INTERVAL 1 MONTH)
              AND date < '{start}'
            GROUP BY 1
        )
        SELECT
            COALESCE(c.provider, p.provider) as provider,
            COALESCE(c.total, 0) as current_total,
            COALESCE(p.total, 0) as prev_total,
            SAFE_DIVIDE(COALESCE(c.total, 0) - COALESCE(p.total, 0), p.total) * 100 as change_pct
        FROM `current` c
        FULL OUTER JOIN previous p ON c.provider = p.provider
        ORDER BY ABS(SAFE_DIVIDE(COALESCE(c.total, 0) - COALESCE(p.total, 0), p.total)) DESC
    """).result()

    issues = 0
    for row in rows:
        status = "OK"
        if row.current_total == 0 and row.prev_total > 0:
            status = "ERROR: no data this month"
            issues += 1
        elif row.change_pct and abs(row.change_pct) > 50:
            status = f"WARNING: {row.change_pct:+.1f}% change"
            issues += 1

        print(f"  {row.provider:15s} €{row.current_total:>10,.2f} (prev: €{row.prev_total:>10,.2f}) {status}")

    print(f"\n{issues} issue(s) found.")
    return issues


def main():
    parser = argparse.ArgumentParser(description="Dataseekers cost collection")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # collect
    p_collect = subparsers.add_parser("collect", help="Collect costs from providers")
    p_collect.add_argument("--month", required=True, help="Month (YYYY-MM, 'previous', or 'current')")
    p_collect.add_argument("--providers", help="Comma-separated list of providers (default: all)")
    p_collect.add_argument("--dry-run", action="store_true", help="Print records without loading to BigQuery")
    p_collect.add_argument("--verbose", action="store_true")

    # report
    p_report = subparsers.add_parser("report", help="Show cost report")
    p_report.add_argument("--month", required=True, help="Month (YYYY-MM, 'previous', or 'current')")

    # validate
    p_validate = subparsers.add_parser("validate", help="Validate collected data")
    p_validate.add_argument("--month", required=True, help="Month (YYYY-MM, 'previous', or 'current')")

    args = parser.parse_args()

    if args.command == "collect":
        cmd_collect(args)
    elif args.command == "report":
        cmd_report(args)
    elif args.command == "validate":
        issues = cmd_validate(args)
        if issues:
            sys.exit(1)


if __name__ == "__main__":
    main()
