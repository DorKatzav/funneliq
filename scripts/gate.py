"""Milestone gate checks — the "is this milestone really done?" script.

Usage:
    python scripts/gate.py --m 0

Prints one line per check ([PASS] / [FAIL] reason / [SKIP] reason) and a final
"GATE M<N>: PASS k/k" line. Exit code 1 on any failure. Checks that need the
live deployment read LIVE_URL (and, later, GATE_USER_EMAIL / GATE_USER_PASSWORD)
from .env and are SKIPPED — never silently passed — when those are unset.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PY = sys.executable


class Skip(Exception):
    """Raise inside a check to mark it skipped (with a reason)."""


Check = tuple[str, Callable[[], None]]


def _load_dotenv() -> None:
    try:
        from dotenv import load_dotenv

        load_dotenv(ROOT / ".env")
    except ImportError:  # pragma: no cover - dotenv is in requirements
        pass


def _run(cmd: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)


def _live_url() -> str:
    url = os.getenv("LIVE_URL", "").rstrip("/")
    if not url:
        raise Skip("LIVE_URL not set in .env")
    return url


# ---------------------------------------------------------------- M0 checks
def check_pytest() -> None:
    res = _run([PY, "-m", "pytest", "-q"])
    assert res.returncode == 0, res.stdout.strip().splitlines()[-1] if res.stdout else res.stderr


def check_ruff() -> None:
    res = _run([PY, "-m", "ruff", "check", "."])
    assert res.returncode == 0, res.stdout.strip()


def check_ci_green() -> None:
    cmd = ["gh", "run", "list", "--branch", "main", "--limit", "1", "--json", "status,conclusion,headSha"]
    res = _run(cmd)
    if res.returncode != 0:
        raise Skip("gh not available or repo not on GitHub yet")
    runs = json.loads(res.stdout or "[]")
    assert runs, "no GitHub Actions runs on main yet"
    run = runs[0]
    assert run["status"] == "completed" and run["conclusion"] == "success", f"latest run: {run}"


def check_live_health() -> None:
    import httpx

    url = _live_url()
    res = httpx.get(f"{url}/health", timeout=20)
    assert res.status_code == 200, f"HTTP {res.status_code}"
    body = res.json()
    assert body.get("status") == "ok", body


def check_no_secrets_in_git() -> None:
    # real key material only: JWT-shaped strings, new-style secret keys,
    # or a service-key assignment that carries an actual value
    pattern = "|".join(
        [
            r"eyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{10,}",
            r"sb_secret_[A-Za-z0-9]{8,}",
            r"SUPABASE_SERVICE_KEY\s*=\s*eyJ",
        ]
    )
    # exclude docs, this script (contains the pattern itself) and the template
    paths = [".", ":!*.md", ":!*.html", ":!scripts/gate.py", ":!.env.example"]
    res = _run(["git", "grep", "-iE", pattern, "--", *paths])
    assert res.returncode != 0, f"possible secret committed:\n{res.stdout}"


# ---------------------------------------------------------------- M1 checks
def _supabase_env() -> tuple[str, str]:
    url = os.getenv("SUPABASE_URL", "").rstrip("/")
    anon = os.getenv("SUPABASE_ANON_KEY", "")
    if not url or not anon or "placeholder" in url:
        raise Skip("SUPABASE_URL / SUPABASE_ANON_KEY not set in .env")
    return url, anon


def _gate_user_token() -> str:
    """Sign in the gate user through Supabase Auth's REST API and return the access token."""
    import httpx

    url, anon = _supabase_env()
    email, password = os.getenv("GATE_USER_EMAIL", ""), os.getenv("GATE_USER_PASSWORD", "")
    if not email or not password:
        raise Skip("GATE_USER_EMAIL / GATE_USER_PASSWORD not set in .env")
    res = httpx.post(
        f"{url}/auth/v1/token?grant_type=password",
        headers={"apikey": anon, "Content-Type": "application/json"},
        json={"email": email, "password": password},
        timeout=20,
    )
    assert res.status_code == 200, f"sign-in failed: HTTP {res.status_code} {res.text[:200]}"
    return res.json()["access_token"]


def _rest_count(url: str, anon: str, token: str | None) -> int:
    """Row count of funnel_records as seen by anon (token=None) or by a signed-in user."""
    import httpx

    headers = {"apikey": anon, "Prefer": "count=exact", "Range-Unit": "items", "Range": "0-0"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    res = httpx.get(f"{url}/rest/v1/funnel_records?select=id", headers=headers, timeout=20)
    if res.status_code == 401:
        return 0
    assert res.status_code in (200, 206), f"HTTP {res.status_code} {res.text[:200]}"
    content_range = res.headers.get("content-range", "")  # e.g. "0-0/3500" or "*/0"
    return int(content_range.split("/")[-1]) if "/" in content_range else len(res.json())


def check_rows_loaded() -> None:
    url, anon = _supabase_env()
    service = os.getenv("SUPABASE_SERVICE_KEY", "")
    if not service:
        raise Skip("SUPABASE_SERVICE_KEY not set in .env (local only)")
    import httpx

    headers = {
        "apikey": service,
        "Authorization": f"Bearer {service}",
        "Prefer": "count=exact",
        "Range": "0-0",
    }
    res = httpx.get(f"{url}/rest/v1/funnel_records?select=id", headers=headers, timeout=20)
    assert res.status_code in (200, 206), f"HTTP {res.status_code} {res.text[:200]}"
    total = int(res.headers["content-range"].split("/")[-1])
    assert total == 3500, f"funnel_records has {total} rows, expected 3500"


def check_rls_blocks_anon() -> None:
    url, anon = _supabase_env()
    n = _rest_count(url, anon, token=None)
    assert n == 0, f"anon without a JWT can read {n} rows — RLS is not enabled"


def check_rls_allows_authenticated() -> None:
    url, anon = _supabase_env()
    n = _rest_count(url, anon, token=_gate_user_token())
    assert n == 3500, f"signed-in user sees {n} rows, expected 3500"


def check_live_records_requires_token() -> None:
    import httpx

    res = httpx.get(f"{_live_url()}/api/records", timeout=20)
    assert res.status_code == 401, f"expected 401 without token, got {res.status_code}"


def check_live_records_with_token() -> None:
    import httpx

    token = _gate_user_token()
    headers = {"Authorization": f"Bearer {token}"}
    res = httpx.get(f"{_live_url()}/api/records?limit=5", headers=headers, timeout=30)
    assert res.status_code == 200, f"HTTP {res.status_code} {res.text[:200]}"
    body = res.json()
    assert body.get("total") == 3500, f"total={body.get('total')}"
    assert len(body.get("rows", [])) == 5


# ---------------------------------------------------------------- M2 checks
def check_eda_incomplete_rows() -> None:
    sys.path.insert(0, str(ROOT))
    from ml.data import clean, load_raw
    from ml.eda import overview_stats

    stats = overview_stats(clean(load_raw()))
    n = stats["counts"]["incomplete_rows"]
    assert n == 33, f"incomplete rows = {n}, expected 33"
    assert len(stats["conversion_by_tier"]) == 3, "expected 3 budget tiers"
    assert stats["diminishing_returns"]["verdict"] == "diminishing", stats["diminishing_returns"]


def check_findings_written() -> None:
    path = ROOT / "docs" / "FINDINGS.md"
    assert path.exists(), "docs/FINDINGS.md missing"
    text = path.read_text(encoding="utf-8")
    for needle in ("## 1.", "## 3.", "## 4.", "Verdict", "Best-converting tier", "D-M2-1", "D-M2-2"):
        assert needle in text, f"FINDINGS.md lacks '{needle}'"


def check_decisions_logged() -> None:
    text = (ROOT / "PROJECT_LOG.md").read_text(encoding="utf-8")
    assert "D-M2-1" in text and "D-M2-2" in text, "D-M2-1 / D-M2-2 not in PROJECT_LOG.md"
    assert "APPROVED" in text, "decisions not marked approved"


def check_live_overview() -> None:
    import httpx

    token = _gate_user_token()
    headers = {"Authorization": f"Bearer {token}"}
    res = httpx.get(f"{_live_url()}/api/insights/overview", headers=headers, timeout=60)
    assert res.status_code == 200, f"HTTP {res.status_code} {res.text[:200]}"
    body = res.json()
    assert body["counts"]["rows"] == 3500, body["counts"]
    assert {t["tier"] for t in body["conversion_by_tier"]} == {"Low", "Mid", "High"}
    assert body["counts"]["incomplete_rows"] == 33


# ---------------------------------------------------------------- M3 checks
def _metrics() -> dict:
    path = ROOT / "models" / "metrics.json"
    assert path.exists(), "models/metrics.json missing — run python -m ml.train_ltv"
    return json.loads(path.read_text(encoding="utf-8"))


def check_leakage_test_passes() -> None:
    res = _run([PY, "-m", "pytest", "-q", "tests/test_features.py", "-k", "leakage"])
    assert res.returncode == 0, res.stdout.strip().splitlines()[-1]


def check_ltv_metrics_complete() -> None:
    ltv = _metrics().get("ltv")
    assert ltv, "metrics.json has no 'ltv' section"
    for name in ("xgboost", "lightgbm", "catboost"):
        cv = ltv["cv"][name]
        assert 0 < cv["rmse_mean"] and -1 <= cv["r2_mean"] <= 1, cv
        assert (ROOT / "models" / f"ltv_{name}.joblib").exists(), f"ltv_{name}.joblib missing"
        assert ltv["importances"][name], f"no importances for {name}"
    assert "cumulative_profit" not in ltv["features"], "leaked feature in served model"


def check_ablation_documents_leak() -> None:
    ltv = _metrics()["ltv"]
    ab = ltv["ablation_with_profit"]
    assert ab["catboost"]["r2_mean"] > ab["catboost_funnel_only_same_rows"]["r2_mean"], ab


def check_report_p2() -> None:
    text = (ROOT / "docs" / "REPORT.md").read_text(encoding="utf-8")
    for needle in ("## P2", "cumulative_profit", "calls_to_closed", "two sentences"):
        assert needle in text, f"REPORT.md §P2 lacks '{needle}'"


def check_live_predict_ltv() -> None:
    import httpx

    token = _gate_user_token()
    customer = {
        "ad_budget": 3000, "num_leads": 40, "leads_answered": 26, "leads_not_answered": 14,
        "followup_1": 21, "followup_2": 16, "followup_3": 13, "followup_4": 11, "followup_5": 8,
        "not_closed": 4, "closed": 4, "calls_to_closed": 2, "calls_to_not_closed": 3,
        "customer_acquisition_cost": 750,
    }
    headers = {"Authorization": f"Bearer {token}"}
    res = httpx.post(f"{_live_url()}/api/predict/ltv", json=customer, headers=headers, timeout=60)
    assert res.status_code == 200, f"HTTP {res.status_code} {res.text[:200]}"
    body = res.json()
    assert 1 <= body["months"] <= 60, body
    log = httpx.get(f"{_live_url()}/api/predictions?limit=1", headers=headers, timeout=30).json()
    assert log["rows"] and log["rows"][0]["model"] == "ltv", log


# ---------------------------------------------------------------- M4 checks
def check_upsell_metrics_complete() -> None:
    up = _metrics().get("upsell")
    assert up, "metrics.json has no 'upsell' section"
    for v in ("early", "tenure"):
        for name in ("xgboost", "lightgbm", "catboost"):
            cv = up["cv"][v][name]
            assert all(k in cv for k in ("accuracy", "precision", "recall", "f1", "roc_auc")), cv
            artifact = ROOT / "models" / f"upsell_{v}_{name}.joblib"
            assert artifact.exists(), f"{artifact.name} missing"
    assert up["baseline"]["accuracy"] > 0.5 and "use_scale_pos_weight" in up["imbalance"]


def check_upsell_beats_baseline() -> None:
    up = _metrics()["upsell"]
    m = up["cv"][up["variant_served"]][up["model_served"]]
    assert m["roc_auc"] > 0.55, f"ROC-AUC {m['roc_auc']}"
    assert m["f1"] > up["baseline"]["f1"], "F1 not above the majority baseline"


def check_business_rule_compared() -> None:
    br = _metrics()["upsell"]["business_rule"]
    assert br["ltv_threshold"] > 0 and br["cac_threshold"] > 0 and br["cv"]["f1"] > 0
    assert len(br["by_tier"]) == 3, br["by_tier"]


def check_report_p3() -> None:
    text = (ROOT / "docs" / "REPORT.md").read_text(encoding="utf-8")
    needles = (
        "## P3",
        "Is accuracy a sufficient metric",
        "business rule",
        "tenure",
        "One feature or a combination",
    )
    for needle in needles:
        assert needle in text, f"REPORT.md §P3 lacks '{needle}'"


def check_live_predict_upsell() -> None:
    import httpx

    token = _gate_user_token()
    customer = {
        "ad_budget": 3000, "num_leads": 40, "leads_answered": 26, "leads_not_answered": 14,
        "followup_1": 21, "followup_2": 16, "followup_3": 13, "followup_4": 11, "followup_5": 8,
        "not_closed": 4, "closed": 4, "calls_to_closed": 2, "calls_to_not_closed": 3,
        "customer_acquisition_cost": 750, "ltv_months": 30,
    }
    headers = {"Authorization": f"Bearer {token}"}
    res = httpx.post(f"{_live_url()}/api/predict/upsell", json=customer, headers=headers, timeout=60)
    assert res.status_code == 200, f"HTTP {res.status_code} {res.text[:200]}"
    body = res.json()
    assert 0 <= body["probability"] <= 1 and body["rule_flag"] is not None, body


# ---------------------------------------------------------------- M5 checks
def check_super_search_complete() -> None:
    sup = _metrics().get("super")
    assert sup, "metrics.json has no 'super' section"
    assert len(sup["search"]) == 18, f"search has {len(sup['search'])} rows, expected 18"
    best = max(sup["search"], key=lambda r: r["roc_auc"])
    argmax = {k: best[k] for k in ("learning_rate", "depth", "iterations")}
    assert sup["best_params"] == argmax, "best_params != argmax"
    assert (ROOT / "models" / "super.joblib").exists(), "super.joblib missing"
    assert sup["cv"]["roc_auc"] > 0.55, sup["cv"]


def check_super_scores_spread() -> None:
    sys.path.insert(0, str(ROOT))
    import numpy as np

    from ml.data import clean, customers_only, load_raw
    from ml.registry import MODELS_DIR, ModelRegistry

    reg = ModelRegistry.load(MODELS_DIR)
    df = clean(load_raw())
    from ml.features import build_features

    X = build_features(df, "super", categorical=True)
    scores = np.rint(100 * reg.super_model.predict_proba(X)[:, 1])
    assert scores.min() >= 0 and scores.max() <= 100, (scores.min(), scores.max())
    assert scores.std() > 5, f"scores nearly constant (std {scores.std():.2f})"
    assert len(scores) == 3500
    _ = customers_only  # keep import explicit: scoring runs on all rows, training on customers


def check_super_profile() -> None:
    pr = _metrics()["super"]["profile"]
    assert pr["n_super"] > 0 and 0 < pr["share_of_total_profit"] < 1, pr
    assert pr["avg_cac_super"] is not None and pr["avg_cac_others"] is not None


def check_report_p4() -> None:
    text = (ROOT / "docs" / "REPORT.md").read_text(encoding="utf-8")
    for needle in ("## P4", "share of total profit", "spot them earlier", "native categorical"):
        assert needle in text, f"REPORT.md §P4 lacks '{needle}'"


def check_live_super() -> None:
    import httpx

    token = _gate_user_token()
    headers = {"Authorization": f"Bearer {token}"}
    customer = {
        "ad_budget": 3000, "num_leads": 40, "leads_answered": 26, "leads_not_answered": 14,
        "followup_1": 21, "followup_2": 16, "followup_3": 13, "followup_4": 11, "followup_5": 8,
        "not_closed": 4, "closed": 4, "calls_to_closed": 2, "calls_to_not_closed": 3,
        "customer_acquisition_cost": 750,
    }
    res = httpx.post(f"{_live_url()}/api/predict/super-score", json=customer, headers=headers, timeout=60)
    assert res.status_code == 200, f"HTTP {res.status_code} {res.text[:200]}"
    body = res.json()
    assert 0 <= body["score"] <= 100 and body["band"] in ("Low", "Medium", "High"), body
    prof = httpx.get(f"{_live_url()}/api/insights/super-customers", headers=headers, timeout=60)
    assert prof.status_code == 200, f"HTTP {prof.status_code} {prof.text[:200]}"
    assert 0 < prof.json()["share_of_total_profit"] < 1, prof.json()


GATES: dict[int, list[Check]] = {
    0: [
        ("pytest green", check_pytest),
        ("ruff clean", check_ruff),
        ("no secrets in git", check_no_secrets_in_git),
        ("GitHub Actions latest run on main succeeded", check_ci_green),
        ("live /health returns 200 + status ok", check_live_health),
    ],
    1: [
        ("pytest green", check_pytest),
        ("ruff clean", check_ruff),
        ("no secrets in git", check_no_secrets_in_git),
        ("funnel_records has 3500 rows (loader idempotent)", check_rows_loaded),
        ("RLS: anon without JWT sees 0 rows", check_rls_blocks_anon),
        ("RLS: signed-in user sees 3500 rows", check_rls_allows_authenticated),
        ("live /api/records -> 401 without token", check_live_records_requires_token),
        ("live /api/records -> 200 + total 3500 with token", check_live_records_with_token),
    ],
    2: [
        ("pytest green", check_pytest),
        ("ruff clean", check_ruff),
        ("EDA: 33 incomplete rows, 3 tiers, diminishing returns", check_eda_incomplete_rows),
        ("FINDINGS.md answers the three P1 questions", check_findings_written),
        ("D-M2-1 / D-M2-2 approved in PROJECT_LOG", check_decisions_logged),
        ("live /api/insights/overview -> 200 with 3 tiers (Supabase rows)", check_live_overview),
    ],
    3: [
        ("pytest green", check_pytest),
        ("ruff clean", check_ruff),
        ("leakage guard test passes", check_leakage_test_passes),
        ("metrics.json: 3 LTV models with CV, importances, artifacts", check_ltv_metrics_complete),
        ("ablation with profit scores higher (documents the leak)", check_ablation_documents_leak),
        ("REPORT.md §P2 answers the brief", check_report_p2),
        ("live POST /api/predict/ltv -> 200 + logged in prediction_log", check_live_predict_ltv),
    ],
    4: [
        ("pytest green", check_pytest),
        ("ruff clean", check_ruff),
        ("metrics.json: 2 variants x 3 classifiers, full metrics + artifacts", check_upsell_metrics_complete),
        ("served model beats the majority baseline (F1) and ROC-AUC > 0.55", check_upsell_beats_baseline),
        ("business rule tuned, scored, and compared by tier", check_business_rule_compared),
        ("REPORT.md §P3 answers the brief", check_report_p3),
        ("live POST /api/predict/upsell -> 200 with probability + rule verdict", check_live_predict_upsell),
    ],
    5: [
        ("pytest green", check_pytest),
        ("ruff clean", check_ruff),
        ("search table has 18 rows, best_params is the argmax, artifact exists", check_super_search_complete),
        ("scores on all 3,500 rows within 0..100 and not constant", check_super_scores_spread),
        ("super-customer profile: profit share and CAC reported", check_super_profile),
        ("REPORT.md §P4 answers the brief", check_report_p4),
        ("live POST /api/predict/super-score + GET /api/insights/super-customers", check_live_super),
    ],
}


def run_gate(m: int) -> int:
    checks = GATES.get(m)
    if checks is None:
        print(f"No gate defined yet for M{m}")
        return 1
    passed = failed = skipped = 0
    for name, fn in checks:
        try:
            fn()
        except Skip as e:
            skipped += 1
            print(f"[SKIP] {name} — {e}")
        except AssertionError as e:
            failed += 1
            print(f"[FAIL] {name} — {e}")
        except Exception as e:  # noqa: BLE001 - report anything, never crash the gate
            failed += 1
            print(f"[FAIL] {name} — {type(e).__name__}: {e}")
        else:
            passed += 1
            print(f"[PASS] {name}")
    total = passed + failed
    verdict = "PASS" if failed == 0 else "FAIL"
    extra = f" ({skipped} skipped)" if skipped else ""
    print(f"GATE M{m}: {verdict} {passed}/{total}{extra}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--m", type=int, required=True, help="milestone number")
    args = parser.parse_args()
    _load_dotenv()
    sys.exit(run_gate(args.m))
