"""GET /api/insights/* — analyses computed at runtime from the rows in Supabase.

Rows are fetched with the signed-in user's token (RLS applies) and cached in-process
for a few minutes, because the dataset is static and the computations are cheap.
"""

from __future__ import annotations

import time

import pandas as pd
from fastapi import APIRouter, Depends
from supabase import Client

from app.db import get_user_client
from ml.eda import overview_stats

router = APIRouter(prefix="/api/insights", tags=["insights"])

TABLE = "funnel_records"
PAGE = 1000
CACHE_TTL_S = 600
_cache: dict[str, tuple[float, dict]] = {}


def fetch_all_records(client: Client) -> pd.DataFrame:
    """Page through the whole table (PostgREST caps a single response at 1,000 rows)."""
    rows: list[dict] = []
    start = 0
    while True:
        res = client.table(TABLE).select("*").order("id").range(start, start + PAGE - 1).execute()
        rows.extend(res.data)
        if len(res.data) < PAGE:
            break
        start += PAGE
    return pd.DataFrame(rows)


def _cached(key: str, compute) -> dict:
    now = time.time()
    hit = _cache.get(key)
    if hit and now - hit[0] < CACHE_TTL_S:
        return hit[1]
    value = compute()
    _cache[key] = (now, value)
    return value


def clear_cache() -> None:
    _cache.clear()


@router.get("/overview")
def overview(client: Client = Depends(get_user_client)) -> dict:
    """P1: missing values, correlations with profit, budget→leads curve, conversion by tier."""
    return _cached("overview", lambda: overview_stats(fetch_all_records(client)))
