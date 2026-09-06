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

## 2026-09-06 — M1 code complete (offline), waiting on Supabase manual steps
- Branch `feat/m1-supabase-auth`, draft PR #4. 24 tests: data module, JWT verification (ES256 via JWKS + HS256, forged key rejected), records API (401 / paginated 200), static pages.
- Design note: `app/db.py` binds the user's JWT to the postgrest client per request (`client.postgrest.auth(token)`), so RLS is enforced by Postgres, not by our code.
- Blocked on: Supabase project + keys, SQL run, team user, Railway variables (user away from desk).

## 2026-09-06 — M2 offline half started early (user approved working ahead while blocked)
- Branch `feat/m2-eda-overview` based on the M1 branch (needs ml/data.py). Only the CSV is read; nothing touches M1 files.
- `ml/eda.py::overview_stats` + `render_findings_md` → `docs/FINDINGS.md` fully generated (no hand-typed numbers). 12 EDA tests + 3 endpoint tests. `GET /api/insights/overview` pages through Supabase rows (1,000/page) with a 10-minute cache; dashboard Overview tab with Chart.js (budget→leads, tier conversion, correlations).
- Findings: 33 incomplete rows (27 customers / 6 non-customers); leads per ₪1,000 fall 25.7 → 6.1 (log-log elasticity 0.61 → diminishing); Mid tier converts best (8.3% vs High 5.4%, Low 4.7%) and carries ~4× the profit of High (₪21.8k vs ₪5.2k) with LTV 33.6 vs 13.2 months; strongest funnel-feature correlate of profit is calls_to_closed (r = −0.55); funnel identities hold on 100% of rows.
- Non-purchasers (337): profit is 0 for all, upsell 0 for all, yet 98.8% have ltv_months > 0 and 46% have closed > 0.
- **Proposed, pending user approval:**
  - D-M2-1: customer models (P2 LTV, P3 upsell, P4 super) train on purchased = 1 only; the P6 profit model keeps all rows (zero-profit campaigns are real outcomes for the simulator).
  - D-M2-2: never impute a target; drop rows missing `ltv_months` only for the LTV model and rows missing `cumulative_profit` only for the profit model; keep everything elsewhere; NULL in the database.
