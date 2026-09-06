"""GET /api/records — historical funnel rows, read from Supabase as the signed-in user."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from supabase import Client

from app.db import get_user_client

router = APIRouter(prefix="/api", tags=["records"])

TABLE = "funnel_records"


@router.get("/records")
def list_records(
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    client: Client = Depends(get_user_client),
) -> dict:
    res = (
        client.table(TABLE)
        .select("*", count="exact")
        .order("id")
        .range(offset, offset + limit - 1)
        .execute()
    )
    return {"rows": res.data, "total": res.count, "limit": limit, "offset": offset}
