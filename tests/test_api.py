def test_health_reports_ok_with_expected_fields(client):
    res = client.get("/health")
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "ok"
    for key in ("version", "commit", "env", "supabase_configured", "models_loaded", "uptime_s"):
        assert key in body
    assert isinstance(body["models_loaded"], list)


def test_public_config_exposes_only_public_values(client):
    body = client.get("/api/config").json()
    assert set(body) == {"supabase_url", "supabase_anon_key"}
    assert "service" not in " ".join(body).lower()


def test_root_redirects_to_dashboard(client):
    res = client.get("/", follow_redirects=False)
    assert res.status_code in (302, 307)
    assert res.headers["location"] == "/static/dashboard.html"


def test_static_pages_are_served(client):
    for page in ("login.html", "dashboard.html", "app.js", "styles.css"):
        res = client.get(f"/static/{page}")
        assert res.status_code == 200, page
    assert "FunnelIQ" in client.get("/static/login.html").text


# --- protected routes -------------------------------------------------------


def test_records_requires_bearer_token(client):
    res = client.get("/api/records")
    assert res.status_code == 401
    assert res.headers.get("www-authenticate") == "Bearer"


def test_records_rejects_garbage_token(client):
    res = client.get("/api/records", headers={"Authorization": "Bearer not-a-jwt"})
    assert res.status_code == 401
    assert "invalid token" in res.json()["detail"]


def test_records_returns_rows_and_total_for_signed_in_user(authed_client):
    res = authed_client.get("/api/records?limit=3&offset=2")
    assert res.status_code == 200
    body = res.json()
    assert body["total"] == 7
    assert [r["id"] for r in body["rows"]] == [2, 3, 4]
    assert body["limit"] == 3 and body["offset"] == 2


def test_records_validates_pagination(authed_client):
    assert authed_client.get("/api/records?limit=0").status_code == 422
    assert authed_client.get("/api/records?limit=501").status_code == 422
    assert authed_client.get("/api/records?offset=-1").status_code == 422
