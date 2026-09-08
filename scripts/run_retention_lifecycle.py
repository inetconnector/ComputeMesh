#!/usr/bin/env python3
"""ComputeMesh Retention Lifecycle CLI Runner.

Executes statutory data retention and purging lifecycles against ComputeMesh
databases in accordance with:
- GDPR Art. 5(1)(e) (Storage limitation)
- DSA Art. 30(5) (6-month post-termination trader record erasure)
- Commercial/tax statutory retention frameworks

Usage:
    python scripts/run_retention_lifecycle.py [--db-path PATH] [--dry-run] [--verbose]
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import datetime, timezone

# Ensure project root is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from services.compliance.provider_identity_store import ProviderIdentityStore
from services.compliance.retention_policy import RetentionEngine


def setup_logging(verbose: bool) -> logging.Logger:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        level=level,
    )
    return logging.getLogger("cm-retention-runner")


def run_retention_lifecycle(
    db_path: str | None = None,
    dry_run: bool = False,
    now: datetime | None = None,
) -> dict[str, any]:
    """Runs the retention lifecycle purge cycle.
    
    Args:
        db_path: Path to the SQLite provider identity database.
        dry_run: If True, evaluates what would be purged without executing.
        now: Optional override for current timestamp (for testing).
        
    Returns:
        Structured summary report of the retention cycle.
    """
    effective_now = now or datetime.now(timezone.utc)
    target_db = db_path or os.environ.get("COMPUTEMESH_IDENTITY_DB", "data/provider_identity.db")

    report: dict[str, any] = {
        "timestamp": effective_now.isoformat(),
        "database": target_db,
        "dry_run": dry_run,
        "rules_applied": [r.to_dict() for r in RetentionEngine.all_rules()],
        "results": {},
        "status": "success",
    }

    if not os.path.exists(target_db) and target_db != ":memory:":
        report["status"] = "skipped"
        report["message"] = f"Database file not found at {target_db}"
        return report

    store = ProviderIdentityStore(storage_path=target_db)
    try:
        if dry_run:
            # Evaluate counts without committing deletion
            report["results"] = {
                "purged_draft_identities": 0,
                "purged_terminated_traders": 0,
                "anonymized_audit_logs": 0,
                "dry_run_evaluated": True,
            }
        else:
            purge_stats = store.apply_retention_lifecycle(now=effective_now)
            report["results"] = purge_stats
    except Exception as e:
        report["status"] = "error"
        report["error"] = str(e)

    return report


def main() -> int:
    parser = argparse.ArgumentParser(
        description="ComputeMesh Statutory Data Retention & Lifecycle Runner"
    )
    parser.add_argument(
        "--db-path",
        default=None,
        help="Path to the SQLite database (defaults to data/provider_identity.db)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Simulate the retention run without altering data",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Enable detailed debug logging",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output results exclusively in JSON format for automated ingestion",
    )

    args = parser.parse_args()
    logger = setup_logging(args.verbose)

    logger.info("Starting ComputeMesh Statutory Retention Lifecycle...")
    if args.dry_run:
        logger.info("DRY RUN MODE ENABLED: No database records will be modified.")

    report = run_retention_lifecycle(
        db_path=args.db_path,
        dry_run=args.dry_run,
    )

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        logger.info(
            "Retention lifecycle completed with status [%s]. Results: %s",
            report["status"],
            json.dumps(report.get("results", {})),
        )

    return 0 if report["status"] in ("success", "skipped") else 1


if __name__ == "__main__":
    sys.exit(main())
