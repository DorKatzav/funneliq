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
    pattern = "service_role|eyJ[A-Za-z0-9_-]{20,}"
    # exclude docs and this script (which contains the pattern itself)
    paths = [".", ":!*.md", ":!*.html", ":!scripts/gate.py"]
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
