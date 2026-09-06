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

## 2026-09-06 — M1: Supabase data, RLS, login — GATE PASSED (8/8)
- Supabase project `pcztrnvcymvxwwmcbxbt` (ES256 JWKS → no JWT secret anywhere). Self sign-up disabled (verified via /auth/v1/settings). Team user created; credentials only in .env.
- Loader ran twice → 3,500 rows both times. RLS proven: anon 0 rows, signed-in user 3,500 rows. Live API: 401 without token, 200 + total 3500 with token. Browser: redirect to login, sign-in, dashboard with email + table, sign-out clears session.
- Deploy incident: Railway switched the service to Railpack → "No start command detected"; old deploy kept serving. Fixed in PR #6 (railpack.json + railway.json builder RAILPACK).
- RLS incident: policies.sql had not actually executed (SQL editor runs only the highlighted selection) → RLS on with no policies → 0 rows for everyone. Resolved with a single query that creates policies and returns counts (3500 | 3 | postgres).
- Gate fix: secret scan now matches key material only (JWT shape, sb_secret_, SERVICE_KEY=eyJ...), after the word service_role in a SQL comment tripped it.
- PRs: #4 (M1) merged, #6 (Railpack) merged. Next: approve D-M2-1 / D-M2-2, merge #5, verify Overview on the live URL.

## 2026-09-06 — D-M2-1 / D-M2-2 APPROVED by the user
- User's wording: the model must never have future information; it is built only on what has already happened.
- D-M2-1: customer models (P2 LTV, P3 upsell, P4 super) train on purchased = 1; P6 profit model keeps all rows.
- D-M2-2: targets are never imputed; drop rows missing the target only for that task; NULL in the database.
- Standing rule reinforced: FUNNEL features only (acquisition-time), enforced by ml/features.py::assert_no_leakage in M3.

## 2026-09-06 — M2: P1 exploration, cleaning, Overview panel — GATE PASSED (6/6)
- PR #8 merged (re-opened from #5 after the M1 base branch was deleted). Live v0.3.0.
- Live `/api/insights/overview` computes from 3,500 Supabase rows with the user's token (paged 1,000/page, cached 10 min). Dashboard Overview verified signed-in: KPIs 3,500 / 33 / 6.5% / Mid; three charts rendered; tier table.
- Numbers that drive the next milestones: elasticity of leads vs budget 0.608 (diminishing); Mid tier converts 8.3% with mean profit ₪21,792 and LTV 33.6 months vs High 5.4% / ₪5,186 / 13.2 and Low 4.7% / ₪2,291 / 7.9; calls_to_closed r = −0.546 with profit.
- Feature-policy note for M3: `ltv_months` (r = 0.846), `upsell` (0.652) and `referred` (0.585) dominate the profit correlation — all outcomes; none is ever a feature for another outcome.
- Next: M3 — P2 LTV regression (features.py + leakage guard, evaluate.py, three regressors, ablation, /api/predict/ltv, Predict tab).

## 2026-09-06 — M3: P2 customer-lifetime regression — GATE PASSED (7/7)
- Feature policy (`ml/features.py`): FUNNEL_RAW (14) + ENGINEERED (4); OUTCOMES never features; the only allowance is ltv_months for the upsell-tenure variant (M4). `assert_no_leakage` is a tested guard.
- Training (customers only, n = 3,163; 4 rows without ltv dropped): XGBoost R² 0.944 / RMSE 2.84, LightGBM 0.943 / 2.86, CatBoost 0.946 / 2.80 (served), ensemble 0.945 / 2.81. Target std 12.0 months.
- Ablation: adding cumulative_profit lifts CatBoost R² 0.946 → 0.975 on the same rows — the leak, documented and excluded.
- What the models learned: calls_to_closed = 83–92% of gain importance in all three (LightGBM switched to gain importance so the three are comparable). Lifetime is a staircase on calls-to-close (36 / 28 / 18 / 12 / ~7 months for 1–2 / 3 / 4 / 5 / 6+ calls, ±3 within steps; r = −0.95). Budget tier acts mostly through it.
- User asked how funnel data can predict anything about the customer; answered in docs/notes/LTV_EXPLAINER_HE.html (calls_to_closed and CAC are the customer's own acquisition journey) with an explicit caveat that R² 0.95 is a property of this practice dataset.
- Live incidents: (1) first M3 deploy crashed with 502 — the Railpack runtime image lacks OpenMP; fixed by `aptPackages: ["libgomp1"]` in railpack.json (PR #11). (2) Form defaults built from column medians violated the funnel identity (28 + 14 ≠ 41) → 422; fixed by using the real customer nearest the medians as defaults + plain-language validation messages (PR #12).
- API: POST /api/predict/ltv (validated funnel shape, logged to prediction_log through the user's token), GET /api/models, GET /api/predictions. Dashboard: Predict + Findings tabs. REPORT.md §P2 written from metrics.json.
- PRs #10, #11, #12 merged. Next: M4 — P3 upsell classification (early vs tenure variants, baseline, business rule).

## 2026-09-06 — Live end-to-end sanity sweep after M3 (user-requested) — 32/32
- Auth: no/garbage token, Basic scheme, the anon key and even the service key used as a bearer → all 401 (legacy HS256 keys are rejected because no HS256 secret is configured; hardening to also require role == "authenticated" scheduled for M4). RLS: anon cannot read prediction_log.
- Validation: negative, inconsistent funnel (answered sum, increasing follow-ups, closed sum), missing field, string number, empty body, limit > 500 → 422; unknown extra field ignored.
- Predictions: non-increasing in calls_to_closed (35.7 → 35.6 → 27.6 → 19.2 → 12.9 → 7.0 → 6.9 → 6.8 → 6.3), within ±1.4 months of the empirical group means, three models within 1 month of each other, live == local artifacts (diff 0.000), absurd inputs stay in range.
- Observations to keep in mind (not bugs): an all-zero funnel still returns a plausible-looking 24.7 months, and atypical combinations (₪800 budget with 42 leads) extrapolate — a "distance from training data" warning in the form is a candidate improvement for M8.
- prediction_log grew exactly by the number of calls; median latency 671 ms (Railway ↔ Supabase round trip incl. the log insert); overview and health consistent.
