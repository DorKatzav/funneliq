from fastapi.testclient import TestClient

from app.main import create_app


def _client() -> TestClient:
    return TestClient(create_app())


def test_health_reports_ok_with_expected_fields():
    res = _client().get("/health")
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "ok"
    for key in ("version", "commit", "env", "models_loaded", "uptime_s"):
        assert key in body
    assert isinstance(body["models_loaded"], list)


def test_public_config_exposes_only_public_values():
    body = _client().get("/api/config").json()
    assert set(body) == {"supabase_url", "supabase_anon_key"}
    assert "service" not in " ".join(body).lower()


def test_root_redirects_to_static_index():
    res = _client().get("/", follow_redirects=False)
    assert res.status_code in (302, 307)
    assert res.headers["location"] == "/static/index.html"


def test_static_index_is_served():
    res = _client().get("/static/index.html")
    assert res.status_code == 200
    assert "FunnelIQ" in res.text
