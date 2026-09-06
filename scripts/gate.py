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
    res = _run(["git", "grep", "-iE", "service_role|eyJ[A-Za-z0-9_-]{20,}", "--", ".", ":!*.md", ":!*.html"])
    assert res.returncode != 0, f"possible secret committed:\n{res.stdout}"


GATES: dict[int, list[Check]] = {
    0: [
        ("pytest green", check_pytest),
        ("ruff clean", check_ruff),
        ("no secrets in git", check_no_secrets_in_git),
        ("GitHub Actions latest run on main succeeded", check_ci_green),
        ("live /health returns 200 + status ok", check_live_health),
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
