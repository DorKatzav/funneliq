"""/api/insights/overview — computed from rows fetched with the user's client (faked here)."""

from fastapi.testclient import TestClient

from app.auth import get_current_user
from app.db import get_user_client
from app.main import create_app
from app.routers import insights
from ml.data import clean, load_raw, to_records
from tests.conftest import TEST_USER, FakeSupabase


def _db_like_rows(n: int) -> list[dict]:
    """Rows shaped like the database returns them: id instead of row_id, budget_tier present."""
    rows = to_records(clean(load_raw()).head(n))
    for r in rows:
        r["id"] = r.pop("row_id")
    return rows


def _client(rows: list[dict]) -> TestClient:
    insights.clear_cache()
    app = create_app()
    app.dependency_overrides[get_current_user] = lambda: TEST_USER
    app.dependency_overrides[get_user_client] = lambda: FakeSupabase({"funnel_records": rows})
    return TestClient(app)


def test_overview_requires_token(client):
    assert client.get("/api/insights/overview").status_code == 401


def test_overview_pages_through_all_rows_and_returns_stats():
    rows = _db_like_rows(2500)  # more than one PostgREST page (1000)
    res = _client(rows).get("/api/insights/overview")
    assert res.status_code == 200
    body = res.json()
    assert body["counts"]["rows"] == 2500
    assert {t["tier"] for t in body["conversion_by_tier"]} == {"Low", "Mid", "High"}
    assert body["diminishing_returns"]["verdict"] == "diminishing"
    assert body["correlations_with_profit"][0]["column"] == "ltv_months"


def test_overview_is_cached_between_calls():
    rows = _db_like_rows(120)
    tc = _client(rows)
    first = tc.get("/api/insights/overview").json()
    rows.clear()  # if the second call recomputed, counts would drop to 0
    second = tc.get("/api/insights/overview").json()
    assert first["counts"]["rows"] == second["counts"]["rows"] == 120
