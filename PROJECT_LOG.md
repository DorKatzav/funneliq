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

## 2026-09-06 — M4: P3 upsell classification — GATE PASSED (7/7)
- Customers only (n = 3,163), 46.3% positive. scale_pos_weight 1.16 tested on the early variant: F1 0.741 → 0.749; kept because it cleared the pre-declared +0.005 bar — marginal, documented as such.
- CV (stratified 5-fold): early/CatBoost AUC 0.778 F1 0.754; tenure/CatBoost AUC 0.795 F1 0.771 (served). Majority baseline: accuracy 53.6%, F1 0. Accuracy alone is not a sufficient metric (REPORT §P3).
- Business rule from the brief, tuned on train folds and scored OOF: LTV > 12 and CAC < 2,000 → F1 0.786, above the model's OOF F1 0.771. By tier: rule wins Low (0.708 vs 0.685) and Mid (0.827 vs 0.814), ties High (0.489 vs 0.490). Recommendation: rule for existing customers, early model at signing (ranks by probability; no tenure needed).
- Upsell is a combination, not one feature: early importances calls_to_closed 0.23, CAC 0.10, conversion_rate 0.10; with tenure allowed ltv_months 0.32.
- D-M4-1: ltv_months is the only outcome allowed as a feature, and only for the tenure variant — outreach targets existing customers whose tenure is known (past, not future). Registered in ml/features.ALLOWED_OUTCOMES.
- Auth hardened: token role must be "authenticated" (service/anon tokens rejected by policy, tests added). scripts/smoke_live.py added.
- Live: POST /api/predict/upsell verified; Predict tab shows 72.9% "likely to buy more" for the default customer with tenure 30, and the rule agrees. PR #14 merged.
- Next: M5 — P4 super-customer score (CatBoost with categorical tier, grid search, 0–100 score, profile).

## 2026-09-06 — M5: P4 super-customer score — GATE PASSED (7/7)
- Customers only (n = 3,163), referral rate 42.7% (majority baseline accuracy 57.3%, F1 0). CatBoost with `budget_tier` as a native categorical; 18-config grid (lr {0.03, 0.1} × depth {4, 6, 8} × iterations {300, 600, 1000}) scored by stratified 3-fold ROC-AUC. Best lr 0.03 / depth 8 / 300 iterations (search AUC 0.7867); worst lr 0.1 / depth 8 / 1000 (0.7633). Pattern: more iterations and the higher learning rate hurt — the search is mostly choosing how little to fit.
- Final 5-fold on the chosen config: ROC-AUC 0.784, F1 0.734, precision 0.676, recall 0.802, accuracy 75.1%. Importances: calls_to_closed 0.30, calls_to_not_closed 0.09, budget_tier 0.08, answer_rate 0.07.
- Score = round(100 × p); on the training customers mean 43, std 28, range 3–90; bands Low 1,447 / Medium 940 / High 776.
- Profile (referred = Yes ∧ upsell = 1 ∧ ltv_months ≥ 34, the 75th percentile): 529 super customers = 16.7% of customers and 33.6% of profit; avg profit ₪28,235 vs ₪11,189; avg CAC ₪991 vs ₪1,527 (cheaper, not dearer); tenure 37.2 vs 20.1 months; 99.8% Mid tier (vs 42.2%); 97.0% closed in ≤ 2 calls (vs 21.3%). Visible at signing → recommendation: route Mid-tier customers closed in ≤ 2 calls into referral + retention tracks; use the score to prioritise, not to exclude.
- D-M5-1: hyperparameter search on 3-fold (the fallback PLAN §M5 allowed), final CV on 5-fold; both numbers reported separately, `search_splits: 3` in metrics.json. Cost: search AUC and served AUC differ slightly (0.7867 vs 0.7836).
- Technical: sklearn `clone()` fails for CatBoost with `cat_features` → `ml/evaluate.py::fresh()` rebuilds from `get_params()`. 67 tests.
- Live: PR #17 merged; Railway serves commit ec889d3 with `super` in models_loaded. POST /api/predict/super-score → default customer scores 63 (Medium); GET /api/insights/super-customers computes the profile from Supabase rows. Dashboard: score bar on Predict, P4 profile + top-5 search table on Findings (screenshots in docs/reports/img/m5_*.jpg).
- Observation (not blocking): the Findings profile table clips the "everyone else" column at a normal viewport width; candidate for the M8 polish list next to the "far from training data" warning.
- Housekeeping this session: `CLAUDE.md` added (language + reporting preferences, protocol, standing rules, lessons) so every new session starts with the same rules; APP_VERSION bumped to 0.5.0.
- Next: M6 — P5 follow-up paradox (`ml/followups.py`, dropout table, closed-deal call distribution, keep/cut recommendation, Follow-ups tab).

## 2026-09-06 — M6: P5 follow-up paradox — GATE PASSED (5/5)
- `ml/followups.py`: dropout per stage = 1 − next/prev aggregated over sums (not a mean of per-row ratios), overall and by tier; calls-to-close distribution for customers (n = 3,163) and for lost deals (3,451 campaigns with ≥ 1 lost deal); value of a sale by calls bucket; `recommendation()` with declared thresholds. REPORT.md §P5 is rendered by `python -m ml.followups --write-report` (no hand-typed numbers).
- Dropout: answered→f1 21.7%, f1→f2 25.7%, f2→f3 18.6%, **f3→f4 10.4%**, f4→f5 29.2%, f5→closed 64.1%; the same shape in every tier (Low/Mid/High within ±3 points). Unexpected stage = follow-up 3 → follow-up 4 (10.4% vs 23.7% median of the other follow-up transitions): leads still talking after the third call are the committed ones.
- Calls to close: median 3, IQR 2–5, mean 3.70; **48.0% of closed deals needed > 3 calls**, 16.5% needed > 5. Lost deals: median 4, mean 3.99 — call count alone does not separate a sale from a loss.
- Value by calls (customers): 1–2 calls 1,073 (33.9%) → 36.4 months, ₪24,777, upsell 69%; 3 calls 571 → 28.2 mo, ₪18,944; 4–5 calls 997 → 14.0 mo, ₪5,993, upsell 28%; 6+ calls 522 (16.5%) → 6.7 mo, ₪2,001, upsell 9%.
- **Verdict: keep** (do not stop after the third call). Reason served by the API: 48% of sales needed > 3 calls; 16.5% needed > 5 (below the extend bar). Recommendation to the founder: the lever is whom to keep calling and with what expectation (late closes are real but small), not whether.
- D-M6-1: the close transition (f5→closed) is reported but excluded from the "unexpected stage" nomination — it is a close rate (64%), and including it would nominate it every time and hide the follow-up signal the brief asks about. Alternative (include it) rejected for that reason; cost: one more rule to explain.
- D-M6-2: thresholds declared up front — cut_after_3 only if < 15% of closed deals needed > 3 calls (PLAN §M6); extend only if ≥ 25% needed > 5 (not in the plan; 25% chosen as "a quarter of sales happen outside the tracked window"). Both returned by the API next to the verdict. Cost: the extend bar is a judgement call; with 16.5% > 5 calls the verdict would flip to extend at a 15% bar, so the bar is written down.
- UI: Follow-ups tab (KPIs, verdict card, remaining-leads line, dropout-by-tier bars + overall line, calls histogram closed vs lost, value table). Two fixes on the way: compact tables in half-width cards wrap instead of clipping (closes the M5 note), charts resize when their tab becomes visible (Chart.js hidden-canvas first paint; the docs PR adds an `update("none")` after the resize because resize alone left the data drawn at the old scale, verified on the live site).
- Tests: 78 (synthetic frame with f3→f4 engineered anomalous; cut / keep / extend rules; endpoint). PR #19.
- Next: M7 — P6 profit model + ₪50,000 budget simulator (`ml/train_profit.py`, `ml/simulator.py`, `/api/simulate/*`, Budget tab).

## 2026-09-07 — M7: P6 profit model + ₪50,000 budget simulator — GATE PASSED (7/7)
- Profit model on all 3,471 campaigns with a recorded profit (non-purchasers at ₪0, D-M2-1; 29 rows without profit dropped, D-M2-2), FUNNEL features only. 5-fold: XGBoost RMSE ₪6,661 / R² 0.647, LightGBM ₪6,594 / 0.654, **CatBoost ₪6,515 / 0.662 (served)**. Target std ₪11,228; 9.7% zero-profit rows. Importances: calls_to_closed 0.53, answer_rate 0.06, budget_tier 0.06.
- The curve is a staircase: model profit per campaign ₪1,184 at ₪500 → ₪3,300 at ₪1,500 → **₪21,758 at ₪2,000** … ₪21,562 at ₪5,000 → ₪5,334 at ₪6,000 → ₪4,892 at ₪20,000; observed means within a few percent at every level. Best level per ₪1,000: ₪2,000 (₪10,879).
- Presets ranked (model / observed means): 25×2,000 ₪543,950 / ₪543,720 (10.9×); 10×5,000 ₪215,620 / ₪217,251; 100×500 ₪118,430 / ₪110,970; 5×10,000 ₪25,737 / ₪25,536; 2×20,000+1×10,000 ₪14,932 / ₪14,632. **Verdict: spread** (within the Mid tier); model and data agree on the winner and the whole ranking.
- D-M7-1: the plan's "typical profile" (median of each feature per level) fed to the model reproduced the plan's own failure signal — ₪500 campaigns at ₪4,615 vs ₪1,110 observed, pushing 100×500 to rank 2. Cause: a non-linear model on a column-wise median that is not a real campaign. Decision: at training time store, per level, the served model averaged over the real campaigns (`model_mean_profit` in profiles.json) and use that in the simulator; keep the median-profile prediction (`model_typical_profit`) for transparency. Alternatives: keep the median approach and caveat it (rejected: wrong ranking); query the DB at serve time (rejected: the plan wants a DB-free simulator). Cost: the simulator only knows the 16 observed levels — by design.
- API: POST /api/simulate/budget (422 on a wrong total or unknown level), GET /api/simulate/presets (ranking, curve, agreement). Dashboard Budget tab: KPIs, ranked presets, curve chart with n per level, free builder with a running total and a button locked until exactly ₪50,000.
- Caveats written for the founder: capacity to run 25 campaigns, noisy small levels, no extrapolation beyond the 16 levels, and that profit ≈ tier is this practice dataset's structure.
- Tests: 88 (10 new). PR #21. ruff: per-file E501 ignore for the §P6 prose renderer, as for eda.py.
- Next: M8 — wrap-up (README, executive summary in REPORT, PROJECT_LOG + Obsidian closed, stranger test, polish list: "far from training data" warning).

## 2026-09-07 — M8: wrap-up — GATE PASSED (10/10)
- README rewritten for a stranger (what it answers with numbers, architecture, setup, data + retraining, screenshots, security model, map). `docs/REPORT.md` opens with an executive summary for the founder: six answers, every number generated.
- Polish items closed: (1) "far from the training data" warning — `ml/stats.py` writes `models/input_stats.json` (mean/std/min/max of the 14 funnel features over the 3,163 training customers); `POST /api/predict/ltv` returns `novelty` (max |z|, the feature, values outside the observed range) and the Predict tab shows a warning beyond 3σ; the all-zero funnel and the ₪800-with-42-leads case from the post-M3 sweep now warn. (2) Browsers served the previous `dashboard.html` after the M7 deploy → `/static/*` now sends `Cache-Control: no-cache`.
- `scripts/train_all.py` retrains every model and regenerates FINDINGS / REPORT §P5 §P6 / input stats in dependency order. `docs/STRANGER_TEST.md` records the end-to-end acceptance walk-through.
- Gate M8 re-runs every M0–M7 offline check (all pass), then README / REPORT / log / reports M0–M8 / input stats / stranger test / live health.
- Tests: 91. PR #23.
- Lessons of the project (the short list): the plan's failure signals were worth writing down — two of them fired (M7's median-profile trap, M3's identity-violating form defaults) and were caught by the gate; a fair model-vs-rule comparison needs the rule tuned and scored on the same folds (M4); Chart.js needs resize + update after a hidden tab is shown (M6); Supabase's SQL editor runs only the highlighted selection (M1); Railway domains are global — copy from the Networking panel (M0).
- Not done, by choice: M9 (React front-end) — the vanilla dashboard covers the brief; a 3–5 minute demo recording (`docs/demo.md`) is optional and left to Dor. React (M9): worth it only if the tool outlives the course or as a portfolio piece — analysis, UI changes and an hours estimate (12–18 session hours for full parity) in `docs/notes/REACT_HE.html`.

**PROJECT CLOSED — 2026-09-07.** Nine milestones (M0–M8), 24 pull requests, six analytical packages live behind login at https://funneliq-production-4b63.up.railway.app. Stranger test: see `docs/STRANGER_TEST.md`.
