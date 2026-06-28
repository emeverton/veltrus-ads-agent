#!/usr/bin/env python3
"""
Sync Supabase → BigQuery para a camada de analytics.

Uso:
  python scripts/sync_to_bigquery.py
  python scripts/sync_to_bigquery.py --tables campaigns daily_metrics leads deals
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from agent.tools.bigquery_sync import SYNC_TABLES, run_sync  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="Sync Supabase → BigQuery")
    parser.add_argument(
        "--tables",
        nargs="+",
        choices=SYNC_TABLES,
        help="Tabelas específicas (default: todas)",
    )
    args = parser.parse_args()
    results = run_sync(args.tables)
    failed = [t for t, n in results.items() if n < 0]
    if failed:
        sys.exit(1)
    print(f"Sync OK: {results}")


if __name__ == "__main__":
    main()
