"""LTV prediction: registry on the committed artifacts + the API with faked auth/db."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.auth import get_current_user
from app.db import get_user_client
from app.main import create_app
from ml.registry import MODELS_DIR, ModelRegistry
from tests.conftest import TEST_USER, FakeSupabase

EASY_CLOSE = {  # a Mid-tier customer closed in 2 calls -> long tenure expected
    "ad_budget": 3000, "num_leads": 40, "leads_answered": 26, "leads_not_answered": 14,
    "followup_1": 21, "followup_2": 16, "followup_3": 13, "followup_4": 11, "followup_5": 8,
    "not_closed": 4, "closed": 4, "calls_to_closed": 2, "calls_to_not_closed": 3,
    "customer_acquisition_cost": 750,
}
HARD_CLOSE = {**EASY_CLOSE, "ad_budget": 15000, "calls_to_closed": 6, "customer_acquisition_cost": 3750}


@pytest.fixture(scope="module")
def registry() -> ModelRegistry:
    reg = ModelRegistry.load(MODELS_DIR)
    assert reg.loaded, "run `python -m ml.train_ltv` first — models/ must be committed"
    return reg


def test_registry_loads_three_ltv_models_and_metrics(registry):
    assert {"ltv_xgboost", "ltv_lightgbm", "ltv_catboost"} <= set(registry.loaded)
    ltv = registry.metrics["ltv"]
    assert set(ltv["cv"]) >= {"xgboost", "lightgbm", "catboost", "ensemble"}
    assert ltv["served"] in ltv["cv"]
    assert "cumulative_profit" not in ltv["features"]
    assert ltv["ablation_with_profit"]["catboost"]["r2_mean"] > ltv["cv"]["catboost"]["r2_mean"]


def test_predict_ltv_is_plausible_and_ordered(registry):
    easy = registry.predict_ltv(EASY_CLOSE)
    hard = registry.predict_ltv(HARD_CLOSE)
    for res in (easy, hard):
        assert 1 <= res["months"] <= 60
        assert set(res["by_model"]) == {"xgboost", "lightgbm", "catboost"}
    assert easy["months"] > hard["months"] + 10  # 2 calls vs 6 calls: the dominant signal


def test_predict_ltv_rejects_missing_fields(registry):
    with pytest.raises(ValueError, match="missing fields"):
        registry.predict_ltv({"ad_budget": 1})


# --- API --------------------------------------------------------------------------------


class _LoggingFake(FakeSupabase):
    def __init__(self):
        super().__init__({"prediction_log": []})
        self.inserted: list[dict] = []

    def table(self, name):
        fake = self

        class _Q:
            def insert(self, row):
                fake.inserted.append({"table": name, **row})
                return self

            def select(self, *_, **__):
                return self

            def order(self, *_, **__):
                return self

            def limit(self, *_):
                return self

            def execute(self):
                class R:
                    data = [
                        dict(r, id=i + 1, created_at="2026-09-06T00:00:00Z")
                        for i, r in enumerate(fake.inserted)
                    ]
                    count = len(fake.inserted)

                return R()

        return _Q()


@pytest.fixture
def api():
    app = create_app()
    fake = _LoggingFake()
    app.dependency_overrides[get_current_user] = lambda: TEST_USER
    app.dependency_overrides[get_user_client] = lambda: fake
    return TestClient(app), fake


def test_predict_endpoint_requires_token(client):
    assert client.post("/api/predict/ltv", json=EASY_CLOSE).status_code == 401


def test_predict_endpoint_returns_prediction_and_logs_it(api):
    tc, fake = api
    res = tc.post("/api/predict/ltv", json=EASY_CLOSE)
    assert res.status_code == 200, res.text
    body = res.json()
    assert 1 <= body["months"] <= 60 and body["served"] and body["rmse_months"] > 0
    assert fake.inserted
    assert fake.inserted[0]["table"] == "prediction_log" and fake.inserted[0]["model"] == "ltv"
    assert fake.inserted[0]["output"]["months"] == body["months"]


def test_predict_endpoint_validates_funnel_shape(api):
    tc, _ = api
    bad = {**EASY_CLOSE, "leads_answered": 99}  # answered + not answered != leads
    res = tc.post("/api/predict/ltv", json=bad)
    assert res.status_code == 422
    assert "num_leads" in res.text


def test_models_and_predictions_endpoints(api):
    tc, _ = api
    info = tc.get("/api/models").json()
    assert "ltv" in info["metrics"] and "ltv_catboost" in info["loaded"]
    tc.post("/api/predict/ltv", json=EASY_CLOSE)
    rows = tc.get("/api/predictions?limit=5").json()["rows"]
    assert len(rows) == 1 and rows[0]["model"] == "ltv"


def test_health_lists_loaded_models(client):
    assert "ltv_catboost" in client.get("/health").json()["models_loaded"]


# --- P3 upsell ---------------------------------------------------------------------------


def test_registry_loads_upsell_models(registry):
    assert any(k.startswith("upsell_") for k in registry.loaded)
    up = registry.metrics["upsell"]
    assert up["variant_served"] in ("early", "tenure") and up["baseline"]["accuracy"] > 0.5
    assert up["business_rule"]["ltv_threshold"] > 0 and up["business_rule"]["cac_threshold"] > 0


def test_predict_upsell_falls_back_to_early_without_tenure(registry):
    res = registry.predict_upsell(EASY_CLOSE)
    assert 0 <= res["probability"] <= 1 and res["variant"] == "early" and res["rule_flag"] is None


def test_predict_upsell_uses_tenure_and_rule_when_ltv_given(registry):
    long = registry.predict_upsell({**EASY_CLOSE, "ltv_months": 36})
    short = registry.predict_upsell({**HARD_CLOSE, "ltv_months": 3})
    assert long["variant"] == registry.metrics["upsell"]["variant_served"]
    assert long["rule_flag"] is True and short["rule_flag"] is False
    assert long["probability"] > short["probability"]


def test_upsell_endpoint(api):
    tc, fake = api
    res = tc.post("/api/predict/upsell", json={**EASY_CLOSE, "ltv_months": 30})
    assert res.status_code == 200, res.text
    body = res.json()
    assert 0 <= body["probability"] <= 1 and isinstance(body["flag"], bool) and body["rule"]
    assert any(r["model"] == "upsell" for r in fake.inserted)


# --- P4 super-customer score ---------------------------------------------------------------


def test_registry_loads_super_model_and_search(registry):
    assert "super" in registry.loaded
    sup = registry.metrics["super"]
    assert len(sup["search"]) == 18
    best = max(sup["search"], key=lambda r: r["roc_auc"])
    assert sup["best_params"] == {k: best[k] for k in ("learning_rate", "depth", "iterations")}
    assert sup["profile"]["n_super"] > 0 and 0 < sup["profile"]["share_of_total_profit"] < 1


def test_super_score_range_and_ordering(registry):
    easy = registry.super_score(EASY_CLOSE)  # Mid tier, 2 calls -> the super-customer profile
    hard = registry.super_score(HARD_CLOSE)  # High tier, 6 calls
    for r in (easy, hard):
        assert 0 <= r["score"] <= 100 and r["band"] in ("Low", "Medium", "High")
        assert abs(r["score"] - 100 * r["probability"]) <= 0.5
    assert easy["score"] > hard["score"] + 20


def test_super_score_endpoint_and_profile_endpoint(api):
    tc, fake = api
    res = tc.post("/api/predict/super-score", json=EASY_CLOSE)
    assert res.status_code == 200, res.text
    body = res.json()
    assert 0 <= body["score"] <= 100 and body["band"] and any(r["model"] == "super" for r in fake.inserted)


def test_novelty_flags_inputs_far_from_training(registry):
    assert registry.input_stats, "run `python -m ml.stats` first"
    typical = registry.novelty(EASY_CLOSE)
    assert typical["flag"] is False and typical["max_z"] < 3
    weird = {**EASY_CLOSE, "ad_budget": 800, "num_leads": 400, "leads_answered": 386}
    far = registry.novelty(weird)
    assert far["flag"] is True and far["note"]
    assert "num_leads" in far["outside_training_range"] or far["feature"] in ("num_leads", "leads_answered")


def test_predict_ltv_endpoint_returns_novelty():
    app = create_app()
    app.dependency_overrides[get_current_user] = lambda: TEST_USER
    app.dependency_overrides[get_user_client] = lambda: FakeSupabase({"prediction_log": []})
    res = TestClient(app).post("/api/predict/ltv", json=EASY_CLOSE)
    assert res.status_code == 200, res.text
    assert res.json()["novelty"]["flag"] is False


def test_static_files_are_not_cached_stale(client):
    res = client.get("/static/dashboard.html")
    assert res.status_code == 200 and res.headers["cache-control"] == "no-cache"
