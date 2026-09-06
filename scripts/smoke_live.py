"""Live end-to-end sanity sweep against the deployed app (auth, validation, prediction sanity, log, latency).

    python scripts/smoke_live.py

Reads LIVE_URL, SUPABASE_URL, SUPABASE_ANON_KEY, SUPABASE_SERVICE_KEY, GATE_USER_EMAIL, GATE_USER_PASSWORD
from .env. Prints [PASS]/[FAIL] per check and a summary; exit code 1 on any failure.
"""

from __future__ import annotations

import os
import statistics
import sys
import time
from pathlib import Path

import httpx
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

BASE = {
    "ad_budget": 3000, "num_leads": 42, "leads_answered": 28, "leads_not_answered": 14,
    "followup_1": 22, "followup_2": 16, "followup_3": 13, "followup_4": 11, "followup_5": 8,
    "not_closed": 5, "closed": 3, "calls_to_closed": 3, "calls_to_not_closed": 4,
    "customer_acquisition_cost": 1000,
}
results: list[tuple[str, bool]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, bool(ok)))
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))


def main() -> int:
    load_dotenv(ROOT / ".env")
    url, sb = os.getenv("LIVE_URL", "").rstrip("/"), os.getenv("SUPABASE_URL", "").rstrip("/")
    anon, svc = os.getenv("SUPABASE_ANON_KEY", ""), os.getenv("SUPABASE_SERVICE_KEY", "")
    if not all([url, sb, anon, os.getenv("GATE_USER_EMAIL"), os.getenv("GATE_USER_PASSWORD")]):
        print("missing LIVE_URL / SUPABASE_* / GATE_USER_* in .env")
        return 1
    res = httpx.post(
        f"{sb}/auth/v1/token?grant_type=password",
        headers={"apikey": anon},
        json={"email": os.getenv("GATE_USER_EMAIL"), "password": os.getenv("GATE_USER_PASSWORD")},
        timeout=20,
    )
    tok = res.json()["access_token"]
    H = {"Authorization": f"Bearer {tok}"}

    def predict(c: dict, headers: dict = H) -> httpx.Response:
        return httpx.post(f"{url}/api/predict/ltv", json=c, headers=headers, timeout=60)

    print("== A. auth")
    check("no token -> 401", httpx.post(f"{url}/api/predict/ltv", json=BASE, timeout=30).status_code == 401)
    check("garbage token -> 401", predict(BASE, {"Authorization": "Bearer abc.def.ghi"}).status_code == 401)
    check("anon key as bearer -> 401", predict(BASE, {"Authorization": f"Bearer {anon}"}).status_code == 401)
    if svc:
        check("service key as bearer -> 401", predict(BASE, {"Authorization": f"Bearer {svc}"}).status_code == 401)
    check("/api/models needs token", httpx.get(f"{url}/api/models", timeout=30).status_code == 401)
    rows = httpx.get(f"{sb}/rest/v1/prediction_log?select=id", headers={"apikey": anon}, timeout=20).json()
    check("RLS: anon cannot read prediction_log", rows == [])

    print("== B. validation")
    check("negative -> 422", predict({**BASE, "ad_budget": -1}).status_code == 422)
    check("answered mismatch -> 422", predict({**BASE, "leads_answered": 30}).status_code == 422)
    check("increasing follow-ups -> 422", predict({**BASE, "followup_3": 20}).status_code == 422)
    check("missing field -> 422", predict({k: v for k, v in BASE.items() if k != "closed"}).status_code == 422)
    check("string number -> 422", predict({**BASE, "num_leads": "many"}).status_code == 422)

    print("== C. prediction sanity")
    by_calls = {k: predict({**BASE, "calls_to_closed": k}).json()["months"] for k in range(1, 10)}
    seq = [by_calls[k] for k in range(1, 10)]
    check("lifetime non-increasing in calls_to_closed", all(a >= b - 0.5 for a, b in zip(seq, seq[1:], strict=False)), str(by_calls))
    check("2 calls ≈ 36 months", 33 <= by_calls[2] <= 40)
    check("5 calls ≈ 12 months", 9 <= by_calls[5] <= 15)
    r = predict({**BASE, "ad_budget": 10**9, "customer_acquisition_cost": 10**9}).json()
    check("absurd budget still in range", 1 <= r["months"] <= 60, str(r["months"]))
    by = predict(BASE).json()["by_model"]
    check("three models within 3 months", max(by.values()) - min(by.values()) < 3, str(by))

    print("== D. live == local artifacts")
    from ml.registry import MODELS_DIR, ModelRegistry

    reg = ModelRegistry.load(MODELS_DIR)
    diffs = [abs(reg.predict_ltv({**BASE, "calls_to_closed": k})["months"] - by_calls[k]) for k in (1, 3, 5, 7)]
    check("max diff < 0.05", max(diffs) < 0.05, f"{max(diffs):.3f}")

    print("== E. log + latency")
    n0 = len(httpx.get(f"{url}/api/predictions?limit=100", headers=H, timeout=30).json()["rows"])
    t = []
    for _ in range(3):
        s = time.perf_counter()
        predict(BASE)
        t.append(time.perf_counter() - s)
    n1 = len(httpx.get(f"{url}/api/predictions?limit=100", headers=H, timeout=30).json()["rows"])
    check("prediction_log grows by 3", n1 - n0 == 3, f"{n0} -> {n1}")
    check("median latency < 2s", statistics.median(t) < 2, f"{statistics.median(t) * 1000:.0f} ms")
    h = httpx.get(f"{url}/health", timeout=30).json()
    check("health lists models + supabase configured", bool(h["models_loaded"]) and h["supabase_configured"])

    passed = sum(ok for _, ok in results)
    print(f"\nSMOKE: {passed}/{len(results)} passed")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
