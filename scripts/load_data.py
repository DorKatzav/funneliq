"""Load data/funnel_marketing_data.csv into Supabase — repeatable, local-only.

    python scripts/load_data.py            # upsert all 3,500 rows (safe to re-run)
    python scripts/load_data.py --truncate # delete everything first, then load

Uses SUPABASE_SERVICE_KEY from .env. This key bypasses Row Level Security, which is
exactly why it is used here (bulk load) and NEVER on the deployed API.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from ml.data import clean, load_raw, to_records  # noqa: E402

TABLE = "funnel_records"
BATCH = 500


def get_admin_client():
    from supabase import create_client
    from supabase.lib.client_options import SyncClientOptions

    url = os.getenv("SUPABASE_URL", "")
    key = os.getenv("SUPABASE_SERVICE_KEY", "")
    if not url or not key:
        sys.exit("SUPABASE_URL and SUPABASE_SERVICE_KEY must be set in .env")
    options = SyncClientOptions(auto_refresh_token=False, persist_session=False)
    return create_client(url, key, options=options)


def count_rows(client) -> int:
    res = client.table(TABLE).select("id", count="exact").limit(1).execute()
    return int(res.count or 0)


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--truncate", action="store_true", help="delete all rows before loading")
    args = parser.parse_args()

    load_dotenv(ROOT / ".env")
    client = get_admin_client()

    if args.truncate:
        client.table(TABLE).delete().gte("id", 0).execute()
        print(f"truncated {TABLE}; rows now: {count_rows(client)}")

    df = clean(load_raw())
    records = to_records(df)
    for rec in records:
        rec["id"] = rec.pop("row_id")
        rec.pop("budget_tier", None)  # generated column in the database

    for start in range(0, len(records), BATCH):
        chunk = records[start : start + BATCH]
        client.table(TABLE).upsert(chunk, on_conflict="id").execute()
        print(f"upserted rows {start}–{start + len(chunk) - 1}")

    total = count_rows(client)
    print(f"done: {TABLE} has {total} rows (expected {len(records)})")
    if total != len(records):
        sys.exit(1)


if __name__ == "__main__":
    main()
