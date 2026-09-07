"""P6 budget simulator — profiles, presets, validation, simulation on the committed model, and the API."""

from __future__ import annotations

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from app.auth import get_current_user
from app.main import create_app
from ml.features import FUNNEL_RAW
from ml.registry import MODELS_DIR, ModelRegistry
from ml.simulator import (
    TOTAL_BUDGET,
    preset_strategies,
    profit_curve,
    rank_presets,
    render_report_md,
    simulate,
    typical_profile,
    validate_allocation,
)
from tests.conftest import TEST_USER


def _frame() -> pd.DataFrame:
    rows = []
    for budget, leads, profit in [(500, 10, 100.0), (500, 14, 300.0), (2000, 30, 20000.0), (2000, 34, None)]:
        answered = leads // 2
        rows.append(
            {
                "ad_budget": budget,
                "num_leads": leads,
                "leads_answered": answered,
                "leads_not_answered": leads - answered,
                "followup_1": answered,
                "followup_2": answered - 1,
                "followup_3": answered - 2,
                "followup_4": answered - 3,
                "followup_5": answered - 4,
                "not_closed": answered - 5,
                "closed": 1,
                "calls_to_closed": 2,
                "calls_to_not_closed": 4,
                "customer_acquisition_cost": budget,
                "ltv_months": 12,
                "purchased": 1,
                "upsell": 0,
                "cumulative_profit": profit,
                "referred": False,
            }
        )
    return pd.DataFrame(rows)


@pytest.fixture(scope="module")
def registry() -> ModelRegistry:
    reg = ModelRegistry.load(MODELS_DIR)
    assert reg.profit_model is not None and reg.profiles, "run `python -m ml.train_profit` first"
    return reg


def _client() -> TestClient:
    app = create_app()
    app.dependency_overrides[get_current_user] = lambda: TEST_USER
    return TestClient(app)


# ------------------------------------------------------------------ profiles
def test_typical_profile_is_the_median_funnel_per_level():
    prof = typical_profile(_frame())
    assert prof["levels"] == [500, 2000]
    p500 = prof["profiles"]["500"]
    assert set(p500["features"]) == set(FUNNEL_RAW)
    assert p500["features"]["num_leads"] == 12 and p500["features"]["ad_budget"] == 500
    assert p500["n"] == 2 and p500["mean_profit"] == 200.0
    p2000 = prof["profiles"]["2000"]
    assert (
        p2000["n"] == 2 and p2000["n_with_profit"] == 1 and p2000["mean_profit"] == 20000.0
    )  # NaN profit ignored


# ------------------------------------------------------------------ presets + validation
def test_presets_are_five_strategies_that_each_total_50000():
    presets = preset_strategies()
    assert len(presets) == 5
    for p in presets:
        assert sum(a["budget"] * a["count"] for a in p["allocation"]) == TOTAL_BUDGET


def test_validation_rejects_wrong_total_unknown_level_and_empty():
    profiles = {"levels": [500, 2000, 5000]}
    validate_allocation([{"budget": 5000, "count": 10}], profiles)
    with pytest.raises(ValueError, match="must equal"):
        validate_allocation([{"budget": 5000, "count": 9}], profiles)
    with pytest.raises(ValueError, match="unknown budget level"):
        validate_allocation([{"budget": 4200, "count": 1}], profiles)
    with pytest.raises(ValueError, match="empty"):
        validate_allocation([], profiles)
    with pytest.raises(ValueError, match="at least 1"):
        validate_allocation([{"budget": 5000, "count": 0}], profiles)


# ------------------------------------------------------------------ committed model
def test_registry_serves_profit_model_with_16_levels(registry):
    assert "profit" in registry.loaded
    m = registry.metrics["profit"]
    assert set(m["cv"]) == {"xgboost", "lightgbm", "catboost"} and m["served"] in m["cv"]
    assert "cumulative_profit" not in m["features"] and "ltv_months" not in m["features"]
    assert len(registry.profiles["levels"]) == 16 == len(m["profile_levels"])


def test_model_curve_reproduces_the_tier_staircase(registry):
    curve = {c["budget"]: c for c in profit_curve(registry)}
    assert curve[2000]["predicted_profit"] > 3 * curve[20000]["predicted_profit"]
    assert curve[2000]["predicted_profit"] > 3 * curve[500]["predicted_profit"]
    assert all(c["predicted_profit"] >= 0 for c in curve.values())


def test_simulate_sums_campaigns_and_reports_empirical_next_to_model(registry):
    res = simulate([{"budget": 20000, "count": 2}, {"budget": 10000, "count": 1}], registry)
    assert res["total_budget"] == TOTAL_BUDGET and res["n_campaigns"] == 3
    assert len(res["per_campaign"]) == 2
    line = res["per_campaign"][0]
    assert line["expected_profit"] == pytest.approx(2 * line["predicted_profit_per_campaign"], abs=0.2)
    assert res["expected_profit"] == pytest.approx(
        sum(x["expected_profit"] for x in res["per_campaign"]), abs=0.2
    )
    assert res["empirical_profit"] > 0 and res["roi_model"] == pytest.approx(
        res["expected_profit"] / 50000, abs=1e-3
    )


def test_rank_presets_orders_by_expected_profit_and_names_a_winner(registry):
    r = rank_presets(registry)
    s = r["strategies"]
    assert [x["rank"] for x in s] == [1, 2, 3, 4, 5]
    assert all(a["expected_profit"] >= b["expected_profit"] for a, b in zip(s, s[1:], strict=False))
    assert r["winner_model"] == s[0]["name"] and r["verdict"] in {"concentrate", "spread"}
    assert isinstance(r["agree"], bool) and r["best_level_per_1000"] in r["levels"]
    md = render_report_md(r, registry.metrics["profit"])
    assert md.startswith("## P6") and "Verdict" in md and "Caveats" in md


# ------------------------------------------------------------------ API
def test_simulate_endpoints_require_a_token(client):
    assert client.get("/api/simulate/presets").status_code == 401
    assert (
        client.post("/api/simulate/budget", json={"allocation": [{"budget": 5000, "count": 10}]}).status_code
        == 401
    )


def test_simulate_budget_endpoint_validates_and_simulates():
    tc = _client()
    bad_total = tc.post("/api/simulate/budget", json={"allocation": [{"budget": 5000, "count": 9}]})
    assert bad_total.status_code == 422 and "must equal" in bad_total.text
    bad_level = tc.post("/api/simulate/budget", json={"allocation": [{"budget": 4200, "count": 1}]})
    assert bad_level.status_code == 422
    bad_count = tc.post("/api/simulate/budget", json={"allocation": [{"budget": 5000, "count": 0}]})
    assert bad_count.status_code == 422
    ok = tc.post("/api/simulate/budget", json={"allocation": [{"budget": 5000, "count": 10}]})
    assert ok.status_code == 200, ok.text
    body = ok.json()
    assert (
        body["n_campaigns"] == 10
        and body["expected_profit"] > 0
        and body["per_campaign"][0]["budget"] == 5000
    )


def test_presets_endpoint_returns_five_ranked_strategies_and_curve():
    res = _client().get("/api/simulate/presets")
    assert res.status_code == 200, res.text
    body = res.json()
    assert len(body["strategies"]) == 5 and body["strategies"][0]["rank"] == 1
    assert len(body["curve"]) == 16 and body["winner_model"]
