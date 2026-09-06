# Project Log — FunnelIQ

Decisions, experiments, metrics, failures, lessons. Newest entries last.
Decision ids: `D-M<milestone>-<n>`. Design-level decisions D1–D10 live in `DESIGN_HE.html`.

## 2026-09-05 — Planning (design)
- Read the brief (`FunnelIQ_Assignment.html`) and profiled the CSV: 3,500 rows, 19 columns, 33 incomplete rows (4 `ltv_months`, 29 `cumulative_profit`), `purchased` 3163/337, `upsell` 42% positive, `referred` 39% "Yes", 16 discrete `ad_budget` levels (500–20,000).
- Locked with the user: own git repo (not a subtree of the course repo), FastAPI + static HTML/JS (React optional as M9), ML as a tested Python package (no notebooks), existing Supabase + Railway accounts.
- Design doc written and reviewed in the browser: `DESIGN_HE.html`.

## 2026-09-06 — Planning (approved) 
- User approved D1–D10 ("מאשר הכל"): data via the API with the user's JWT (RLS enforced, service key local-only); models committed as joblib + metrics.json; single Railway service; FUNNEL-only feature policy with an early/tenure pair for upsell; `prediction_log` table; CSV committed; self-signup disabled; per-milestone protocol; M0–M8 order with M9 optional; repo name `funneliq`.
- `PLAN.md` (contracts + milestones + gates) and `PLAN_HE.html` written. Obsidian project pages created.
- Environment check: conda `AI_dev` has pandas 3.0.3, scikit-learn 1.9.0, pytest, uvicorn, httpx, joblib, pydantic 2.13; missing xgboost, lightgbm, catboost, fastapi, supabase → install in M0. `gh` logged in as DorKatzav. No node/docker/railway CLI.
- Next: M0 (skeleton deployed).

## 2026-09-06 — M0: deployed skeleton — GATE PASSED (5/5)
- Own git repo initialised; course repo ignores the folder. GitHub: https://github.com/DorKatzav/funneliq (public). PR #1 (skeleton) and PR #2 (gate fix) merged via CI.
- Installed into AI_dev and pinned: fastapi 0.141.1, uvicorn 0.52.3, pydantic-settings 2.15.0, supabase 2.31.0, PyJWT 2.13.0, xgboost 3.2.0, lightgbm 4.7.0, catboost 1.2.10, ruff 0.16.6 (pandas 3.0.3 / scikit-learn 1.9.0 / numpy 2.4.6 already present).
- Surprise: `brew list libomp` looked installed but the dylib was missing → xgboost/lightgbm import failed until `brew install libomp`. Documented in README.
- Gate lesson: the secret-scan regex matched itself inside scripts/gate.py → the script is now excluded from its own scan (PR #2).
- Railway: service from GitHub main, Nixpacks, healthcheck `/health`; domain https://funneliq-production-4b63.up.railway.app. First domain the user pasted (`funneliq-production.up.railway.app`) belonged to a *different* Railway user's app — domains are global; always copy from the Networking panel.
- Live `/health` reports the exact main commit (4cf8e93) → push-to-redeploy proven. Manual restart in Railway → `/health` 200 again with uptime reset (115.9 s), same commit → restart survival proven.
- Next: M1 (Supabase project, schema + RLS, loader, JWT auth, login page).

## 2026-09-06 — M1: Supabase data, RLS, login — GATE PASSED (8/8)
- Supabase project `pcztrnvcymvxwwmcbxbt` (ES256 JWKS → no JWT secret anywhere). Self sign-up disabled (verified via /auth/v1/settings). Team user created; credentials only in .env.
- Loader ran twice → 3,500 rows both times. RLS proven: anon 0 rows, signed-in user 3,500 rows. Live API: 401 without token, 200 + total 3500 with token. Browser: redirect to login, sign-in, dashboard with email + table, sign-out clears session.
- Deploy incident: Railway switched the service to Railpack → "No start command detected"; old deploy kept serving. Fixed in PR #6 (railpack.json + railway.json builder RAILPACK).
- RLS incident: policies.sql had not actually executed (SQL editor runs only the highlighted selection) → RLS on with no policies → 0 rows for everyone. Resolved with a single query that creates policies and returns counts (3500 | 3 | postgres).
- Gate fix: secret scan now matches key material only (JWT shape, sb_secret_, SERVICE_KEY=eyJ...), after the word service_role in a SQL comment tripped it.
- PRs: #4 (M1) merged, #6 (Railpack) merged. Next: approve D-M2-1 / D-M2-2, merge #5, verify Overview on the live URL.
