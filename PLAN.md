# FunnelIQ — Implementation Plan

> Working language: conversation in Hebrew (masculine forms), all code / UI / files / commits in English.
> Spec: `DESIGN_HE.html` (design doc, approved D1–D10 on 2026-09-06). This plan argues from that spec.
> Environment: conda `AI_dev` (Python 3.11). Accounts: Supabase + Railway exist. gh CLI is logged in.
> Keep `PROJECT_LOG.md` (decisions, experiments, metrics, lessons) · git commit after every passed gate ·
> one feature branch + PR per milestone · Hebrew HTML report + Obsidian update after every milestone.

**Goal:** Ship FunnelIQ — a login-gated marketing-intelligence app (predictions, follow-up insight, budget simulator) for Northbound Media, deployed on Railway, data + auth on Supabase, code + CI on a public GitHub repo.

**Architecture:** One FastAPI service serves JSON endpoints and the static HTML/JS dashboard. The browser signs in with Supabase Auth (anon key) and sends the user's JWT to the API; the API verifies the JWT and queries Supabase *with that token*, so Row Level Security is enforced by Postgres. Models are trained offline into `models/*.joblib` and loaded at startup. The service-role key never leaves the local machine (loader script only).

**Tech stack:** Python 3.11 · FastAPI · uvicorn · pydantic-settings · supabase-py · PyJWT · pandas · scikit-learn · xgboost · lightgbm · catboost · joblib · pytest · ruff · vanilla HTML/JS · Chart.js + supabase-js (CDN) · GitHub Actions · Railway (Nixpacks).

## Global constraints (from the spec)

- Feature policy: models use **FUNNEL** features only (see §3). Any OUTCOME column used as a feature needs a written justification in `docs/REPORT.md` and an explicit allow-list entry in `ml/features.py`.
- Secrets: only in `.env` (gitignored) locally and Railway variables in production. `SUPABASE_SERVICE_KEY` is **never** set on Railway and never committed.
- Anon key in the browser, service key on the (local) server side only.
- Provided dataset `data/funnel_marketing_data.csv` is read-only and committed (small). Generated artifacts other than `models/` are gitignored.
- Budget tiers: Low ≤ 1500 · Mid 2000–5000 · High > 5000 (values are discrete: 500…20000, no value falls between tiers).
- Missing values: 33 rows (4 in `ltv_months`, 29 in `cumulative_profit`). Never impute a target; drop rows only for the task whose target is missing.
- No `git add -A` from the course root. The project has its **own** git repo; the course repo ignores this folder.
- UI language English; our reports Hebrew (`docs/reports/M<N>_HE.html`), terminal summaries English.

---

## 1. Architecture & data flow

```text
data/funnel_marketing_data.csv  (3,500 rows, provided)
        │
        ├──▶ scripts/load_data.py  (SERVICE key, local only, idempotent)
        │        └──▶ Supabase Postgres: funnel_records (RLS: authenticated SELECT), prediction_log (RLS: own rows)
        │
        └──▶ ml/data.py ──▶ ml/features.py ──▶ ml/train_*.py ──▶ models/*.joblib + models/metrics.json
                                                                        │
Browser ── supabase-js (ANON key) ── signInWithPassword ──▶ JWT           │
   │                                                                     ▼
   └── fetch(/api/..., Authorization: Bearer JWT) ──▶ FastAPI (Railway) ── ml/registry.py loads models
                                                       ├─ app/auth.py   verifies JWT (JWKS ES256, HS256 fallback)
                                                       ├─ app/db.py     supabase client bound to the user's JWT → RLS
                                                       ├─ /api/records, /api/insights/*      ← Supabase rows
                                                       ├─ /api/predict/{ltv,upsell,super-score} ← models
                                                       ├─ /api/simulate/budget               ← profit model + ml/simulator.py
                                                       └─ /static (login.html, dashboard.html, app.js)
GitHub push → Actions (ruff + pytest) ; Railway watches main → redeploy → /health
```

## 2. Repository structure

```text
Funnell_IQ/                 git root; GitHub: DorKatzav/funneliq (public)
├── app/
│   ├── __init__.py
│   ├── main.py            create_app(): mounts routers + /static, GET /health, GET /api/config
│   ├── config.py          Settings (pydantic-settings): SUPABASE_URL, SUPABASE_ANON_KEY, SUPABASE_JWT_SECRET?, APP_ENV, MODELS_DIR
│   ├── auth.py            get_current_user() dependency → UserContext(user_id, email, token)
│   ├── db.py              get_user_client(user) → supabase Client with the user's JWT
│   ├── schemas.py         CustomerInput, LtvPrediction, UpsellPrediction, SuperScore, BudgetAllocation, SimulationResult, …
│   └── routers/
│       ├── records.py     GET /api/records?limit&offset
│       ├── insights.py    GET /api/insights/overview | followups | super-customers
│       ├── predict.py     POST /api/predict/ltv | upsell | super-score ; GET /api/models ; GET /api/predictions
│       └── simulate.py    POST /api/simulate/budget
├── ml/
│   ├── __init__.py
│   ├── data.py            load_raw(), clean(), budget_tier()
│   ├── features.py        FUNNEL_RAW, ENGINEERED, OUTCOMES, TASK_FEATURES, build_features(), assert_no_leakage()
│   ├── evaluate.py        cv_regression(), cv_classification(), importances(), majority_baseline()
│   ├── eda.py             overview_stats(df) → dict (P1)
│   ├── train_ltv.py       P2
│   ├── train_upsell.py    P3 (+ business_rule())
│   ├── train_super.py     P4 (+ super_customer_profile())
│   ├── train_profit.py    P6 model
│   ├── followups.py       P5 dropout_table(), closed_deals_followups(), recommendation()
│   ├── simulator.py       P6 typical_profile(), simulate(), preset_strategies()
│   └── registry.py        ModelRegistry.load(models_dir) → .predict_ltv(), .predict_upsell(), .super_score(), .predict_profit(), .metrics
├── models/                committed: ltv_xgboost.joblib, ltv_lightgbm.joblib, ltv_catboost.joblib, upsell_*.joblib, super.joblib, profit.joblib, metrics.json
├── static/                login.html, dashboard.html, app.js, styles.css
├── scripts/
│   ├── load_data.py       CSV → Supabase (service key)
│   ├── train_all.py       runs all trainers, writes models/ + metrics.json
│   └── gate.py            python scripts/gate.py --m N  → prints "GATE M<N>: PASS k/k" or lists failures, exit code 1
├── db/
│   ├── schema.sql
│   └── policies.sql
├── tests/                 test_data.py, test_features.py, test_api.py, test_registry.py, test_simulator.py, test_followups.py, conftest.py
├── docs/
│   ├── FINDINGS.md        P1 findings note
│   ├── REPORT.md          business write-up, all six packages (grows per milestone)
│   └── reports/           M0_HE.html … M8_HE.html (Hebrew milestone reports)
├── data/funnel_marketing_data.csv
├── .github/workflows/ci.yml
├── requirements.txt       pinned
├── runtime.txt            python-3.11
├── railway.json
├── .env.example  .gitignore  README.md  PLAN.md  PLAN_HE.html  DESIGN_HE.html  PROJECT_LOG.md
└── FunnelIQ_Assignment.html (provided brief)
```

## 3. Shared contracts (single source of truth — every milestone builds on these)

### 3.1 `ml/data.py`
```python
RAW_COLUMNS = [...19 columns in CSV order...]
def load_raw(path: str | Path = "data/funnel_marketing_data.csv") -> pd.DataFrame   # exactly as on disk, referred as str
def clean(df: pd.DataFrame) -> pd.DataFrame
    # - referred: "Yes"/"No" → bool column `referred`
    # - adds `budget_tier` (category: Low/Mid/High) via budget_tier()
    # - adds `row_id` = original CSV row index (0-based) — stable id shared with the DB
    # - does NOT drop or impute anything; NaNs preserved
def budget_tier(ad_budget: pd.Series | float) -> pd.Series | str   # Low ≤1500, Mid 2000–5000, High >5000
def customers_only(df) -> pd.DataFrame   # purchased == 1 (decision recorded in M2; see D-M2-1 in PROJECT_LOG)
```

### 3.2 `ml/features.py`
```python
FUNNEL_RAW = ["ad_budget","num_leads","leads_answered","leads_not_answered",
              "followup_1","followup_2","followup_3","followup_4","followup_5",
              "not_closed","closed","calls_to_closed","calls_to_not_closed","customer_acquisition_cost"]
ENGINEERED = ["answer_rate","conversion_rate","cost_per_lead","budget_tier"]   # budget_tier numeric-coded except for CatBoost (native cat)
OUTCOMES   = ["ltv_months","purchased","upsell","cumulative_profit","referred"]
TASK_FEATURES = {
    "ltv":           FUNNEL_RAW + ENGINEERED,
    "upsell_early":  FUNNEL_RAW + ENGINEERED,
    "upsell_tenure": FUNNEL_RAW + ENGINEERED + ["ltv_months"],      # ALLOWED_OUTCOMES["upsell_tenure"] = ["ltv_months"], justified in REPORT.md §P3
    "super":         FUNNEL_RAW + ENGINEERED,                       # budget_tier passed as categorical to CatBoost
    "profit":        FUNNEL_RAW + ENGINEERED,
}
ALLOWED_OUTCOMES = {"upsell_tenure": ["ltv_months"]}
def build_features(df: pd.DataFrame, task: str, categorical: bool = False) -> pd.DataFrame
    # answer_rate = leads_answered/num_leads ; conversion_rate = closed/num_leads ; cost_per_lead = ad_budget/num_leads (num_leads==0 → 0)
def assert_no_leakage(feature_names: list[str], task: str) -> None   # raises ValueError if an OUTCOME not in ALLOWED_OUTCOMES[task] is present
```

### 3.3 `ml/evaluate.py`
```python
def cv_regression(model, X, y, n_splits=5, seed=42) -> dict      # {"rmse_mean","rmse_std","r2_mean","r2_std"}
def cv_classification(model, X, y, n_splits=5, seed=42) -> dict  # stratified; {"accuracy","precision","recall","f1","roc_auc"} each mean+std
def majority_baseline(y) -> dict                                 # {"accuracy","precision","recall","f1","roc_auc":0.5}
def importances(model, feature_names) -> dict[str, float]        # normalized to sum 1; works for xgb/lgbm/catboost
```

### 3.4 `models/metrics.json` (written by trainers, read by `/api/models` and the dashboard)
```json
{
  "ltv":    {"trained_at": "...", "n_train": 0, "features": [], "served": "catboost|ensemble",
             "cv": {"xgboost": {...}, "lightgbm": {...}, "catboost": {...}},
             "importances": {"xgboost": {}, "lightgbm": {}, "catboost": {}},
             "ablation_with_profit": {"catboost": {...}}},
  "upsell": {"trained_at": "...", "variant_served": "early|tenure", "class_balance": {"0": 0, "1": 0},
             "baseline": {...}, "cv": {"early": {"xgboost": {...}, ...}, "tenure": {...}},
             "importances": {...}, "business_rule": {"ltv_threshold": 0, "cac_threshold": 0, "accuracy": 0, "precision": 0, "recall": 0, "f1": 0}},
  "super":  {"trained_at": "...", "search": [{"learning_rate": 0, "depth": 0, "iterations": 0, "roc_auc": 0}], "best_params": {}, "cv": {...}, "importances": {}},
  "profit": {"trained_at": "...", "cv": {...}, "importances": {}, "profile_levels": [500, 800, ...]}
}
```

### 3.5 `ml/registry.py`
```python
class ModelRegistry:
    @classmethod
    def load(cls, models_dir: Path) -> "ModelRegistry"
    metrics: dict
    def predict_ltv(self, customer: dict) -> dict      # {"months": float, "by_model": {"xgboost": x, "lightgbm": y, "catboost": z}}
    def predict_upsell(self, customer: dict) -> dict   # {"probability": float, "flag": bool, "rule_flag": bool}
    def super_score(self, customer: dict) -> dict      # {"score": int 0..100, "probability": float}
    def predict_profit(self, row: dict) -> float
```
`customer` is a dict with the 14 `FUNNEL_RAW` keys (the API's `CustomerInput`). Engineered features are computed inside via `build_features`.

### 3.6 `app/auth.py`
```python
@dataclass
class UserContext: user_id: str; email: str | None; token: str
async def get_current_user(authorization: str = Header(...)) -> UserContext
    # "Bearer <jwt>"; verify with PyJWT: JWKS at f"{SUPABASE_URL}/auth/v1/.well-known/jwks.json" (ES256, cached PyJWKClient),
    # fallback HS256 with SUPABASE_JWT_SECRET if set; audience "authenticated"; 401 on any failure.
```
Tests override this dependency with `app.dependency_overrides[get_current_user] = lambda: UserContext("test-user", "t@example.com", "x")`.

### 3.7 `app/db.py`
```python
def get_user_client(user: UserContext = Depends(get_current_user)) -> Client
    # create_client(SUPABASE_URL, SUPABASE_ANON_KEY); client.postgrest.auth(user.token) → RLS applies
```

### 3.8 `scripts/gate.py`
Each milestone has a list of `(name, callable)` checks. Prints one line per check (`[PASS]`/`[FAIL] reason`) then `GATE M<N>: PASS k/k`. Exit code 1 on any failure. Live checks read `LIVE_URL`, `GATE_USER_EMAIL`, `GATE_USER_PASSWORD` from `.env` and are skipped with `[SKIP]` when unset (never silently passed).

### 3.9 Supabase schema (`db/schema.sql`)
```sql
create table if not exists public.funnel_records (
  id integer primary key,                     -- row_id from CSV
  ad_budget integer not null, num_leads integer not null, leads_answered integer not null, leads_not_answered integer not null,
  followup_1 integer not null, followup_2 integer not null, followup_3 integer not null, followup_4 integer not null, followup_5 integer not null,
  not_closed integer not null, closed integer not null, calls_to_closed integer not null, calls_to_not_closed integer not null,
  customer_acquisition_cost integer not null,
  ltv_months real, purchased smallint not null, upsell smallint not null, cumulative_profit real, referred boolean not null,
  budget_tier text generated always as (case when ad_budget <= 1500 then 'Low' when ad_budget <= 5000 then 'Mid' else 'High' end) stored
);
create table if not exists public.prediction_log (
  id bigserial primary key,
  user_id uuid not null default auth.uid(),
  model text not null, input jsonb not null, output jsonb not null,
  created_at timestamptz not null default now()
);
```
`db/policies.sql`: enable RLS on both; `funnel_records`: `select` to `authenticated`; `prediction_log`: `insert` with check `user_id = auth.uid()`, `select` using `user_id = auth.uid()`.

---

## 4. Milestones

Every milestone follows the protocol in §5. Branch names and report files are fixed here so nothing is invented later.

### M0 — Deployed skeleton on day one
- **Branch:** `feat/m0-skeleton` · **Report:** `docs/reports/M0_HE.html`
- **Goal:** "hello" running on Railway with CI green, before any ML code.
- **Tasks:**
  1. `git init`; `.gitignore` (`.env`, `__pycache__/`, `.pytest_cache/`, `.ruff_cache/`, `*.pyc`, `.DS_Store`, `data/*.parquet`, `notebooks/`, `*.log`); add this folder to the course repo's `.gitignore`.
  2. `conda activate AI_dev` and install: `fastapi uvicorn pydantic-settings supabase PyJWT[crypto] xgboost lightgbm catboost ruff pytest httpx joblib python-dotenv`. macOS: `brew install libomp` before lightgbm import. Freeze to `requirements.txt` with pins.
  3. `app/config.py`, `app/main.py` with `GET /health` → `{"status":"ok","version":<git sha or "dev">,"models_loaded":[],"uptime_s":n}` and `GET /api/config` → `{"supabase_url","supabase_anon_key"}`; `static/` placeholder index.
  4. `tests/test_api.py::test_health` using `httpx`/`TestClient`; `ruff.toml` (line-length 110).
  5. `.github/workflows/ci.yml`: on push + pull_request → setup-python 3.11 → pip install -r requirements.txt → `ruff check .` → `pytest -q`.
  6. `railway.json`: `{"build":{"builder":"NIXPACKS"},"deploy":{"startCommand":"uvicorn app.main:app --host 0.0.0.0 --port $PORT","healthcheckPath":"/health","healthcheckTimeout":120,"restartPolicyType":"ON_FAILURE"}}`; `runtime.txt` = `python-3.11`.
  7. `gh repo create DorKatzav/funneliq --public --source . --push`; README skeleton; open PR from branch → merge.
  8. **User (manual):** Railway → New project → Deploy from GitHub repo → select `funneliq` → add variables `SUPABASE_URL`, `SUPABASE_ANON_KEY` (placeholders OK for M0) → generate public domain. Put the domain in `.env` as `LIVE_URL`.
- **Gate (gate.py --m 0):** (1) `pytest` green locally; (2) `ruff check .` clean; (3) latest GitHub Actions run on main = success (`gh run list --limit 1`); (4) `GET {LIVE_URL}/health` = 200 with `status: ok`; (5) after a manual restart in Railway, /health still 200 (user confirms; gate re-checks).
- **Failure signals:** lightgbm import error (libomp); Railway build timeout (catboost wheel) → pin versions, retry; healthcheck fails → wrong `$PORT` binding.
- **PROJECT_LOG:** pinned versions, live URL, CI badge.

### M1 — Supabase: data, RLS, login
- **Branch:** `feat/m1-supabase-auth` · **Report:** `docs/reports/M1_HE.html`
- **Goal:** all three pillars connected: rows in Postgres behind RLS, real login screen, API reading with the user's token.
- **Tasks:**
  1. **User (manual):** Supabase → new project `funneliq` → copy Project URL, anon key, service_role key, and check *Settings → API → JWT* (JWKS available? legacy secret?) into `.env`. Auth → Providers → Email: enable, **disable "Allow new users to sign up"**. Auth → Users → add a user (e.g. `dor@northbound.test`) — put its credentials in `.env` as `GATE_USER_EMAIL/PASSWORD`.
  2. `db/schema.sql` + `db/policies.sql` (§3.9); user runs them in the SQL editor (gate verifies the effect).
  3. `ml/data.py` (`load_raw`, `clean`, `budget_tier`) + `tests/test_data.py` (3,500 rows; 33 rows with NaN; referred bool; row_id unique 0..3499; tier counts computed and asserted against pandas).
  4. `scripts/load_data.py`: `clean(load_raw())` → NaN→None → `upsert` in batches of 500 on `id` using the SERVICE key (from `.env`), `--truncate` flag deletes first. Prints row count after load via `select count`.
  5. `app/auth.py` (§3.6) + `app/db.py` (§3.7) + `app/routers/records.py` (`GET /api/records?limit=50&offset=0` → `{"rows":[...],"total":n}`) + `tests/test_api.py` additions: 401 without header; 200 with overridden dependency and a fake client.
  6. `static/login.html` (email+password form, error text, supabase-js v2 from CDN, config fetched from `/api/config`), `static/dashboard.html` shell (nav tabs, sign-out, session check → redirect to `/static/login.html` if no session), `static/app.js` (`api(path, opts)` helper adding the Bearer header; `requireSession()`; `signOut()`), `static/styles.css`. Root `/` redirects to `/static/dashboard.html`.
  7. Add Railway variable `SUPABASE_JWT_SECRET` only if the project is legacy HS256.
- **Gate (--m 1):** (1) `load_data.py` run twice → `select count(*)` = 3500; (2) REST call with anon key and **no** JWT → 0 rows (or 401), with the gate user's JWT → 3500; (3) `/api/records` → 401 without token; (4) `/api/records` with gate user token on `LIVE_URL` → 200 and `total == 3500`; (5) browser: login → dashboard → sign-out → back to login (manual, recorded in report with screenshots); (6) `SUPABASE_SERVICE_KEY` absent from Railway variables (user confirms) and `git grep -i service_role` empty.
- **Failure signals:** JWT verify fails with "invalid audience"/"alg" → check ES256 vs HS256 path; RLS returns rows to anon → policy not enabled (`alter table ... enable row level security`); loader inserts duplicates → upsert key not `id`.
- **PROJECT_LOG:** JWT algorithm found, user created, row count, D-M1-x decisions.

### M2 — P1: exploration, cleaning, Overview panel
- **Branch:** `feat/m2-eda-overview` · **Report:** `docs/reports/M2_HE.html`
- **Goal:** trust the data before modeling; first insight panel live.
- **Tasks:**
  1. `ml/eda.py::overview_stats(df) -> dict` returning: `missing` (per column + rows_incomplete), `correlations_with_profit` (Pearson, all numeric columns, sorted), `budget_vs_leads` (per distinct `ad_budget`: n, mean leads, leads_per_1000_shekel), `conversion_by_tier` (closed/num_leads per tier, plus mean profit and mean CAC per tier), `purchased_zero_profile` (n, share with ltv>0, share with profit>0), `counts` (rows, customers).
  2. Decide and record **D-M2-1** (customers-only training if `purchased==0` rows carry ltv/profit anyway) and **D-M2-2** (missing-value policy applied per task) in `PROJECT_LOG.md`.
  3. `docs/FINDINGS.md`: answers to the three P1 questions (incomplete rows + handling; proportional vs diminishing leads with the number; best-converting tier and whether it surprises), with the tables from `overview_stats`.
  4. `app/routers/insights.py::GET /api/insights/overview` → computes `overview_stats` from `funnel_records` fetched with the user's client (paginate 1000/page). Cache in-process for 10 minutes.
  5. Dashboard **Overview** tab: KPI cards (rows, incomplete rows, overall conversion), Chart.js line "ad_budget → mean leads", bar "conversion by tier", horizontal bar "correlation with cumulative_profit".
  6. `tests/test_eda.py` on a 20-row synthetic frame with known answers.
- **Gate (--m 2):** (1) `overview_stats` reports rows_incomplete == 33; (2) `FINDINGS.md` contains the three answers with numbers; (3) `/api/insights/overview` on `LIVE_URL` returns 200 with `conversion_by_tier` having 3 tiers; (4) D-M2-1 and D-M2-2 written in PROJECT_LOG; (5) tests green.
- **Failure signals:** correlation with profit dominated by `ltv_months` (expected — it's an outcome; note it, it motivates P2's leakage decision); leads_per_1000 flat across budgets (no diminishing returns → say so honestly).

### M3 — P2: predict customer lifetime (regression)
- **Branch:** `feat/m3-ltv-regression` · **Report:** `docs/reports/M3_HE.html`
- **Goal:** three compared regressors, leakage decision proven, prediction live.
- **Tasks:**
  1. `ml/features.py` (§3.2) + `tests/test_features.py`: `assert_no_leakage(["ad_budget","cumulative_profit"], "ltv")` raises; `build_features(df,"ltv")` has exactly `TASK_FEATURES["ltv"]` columns; engineered values correct on a 3-row frame; `num_leads==0` → rates 0.
  2. `ml/evaluate.py` (§3.3) + `tests/test_evaluate.py` (majority baseline on `[0,0,0,1]`; importances sum to 1).
  3. `ml/train_ltv.py`: data = `customers_only(clean(load_raw()))` (per D-M2-1) minus rows with NaN `ltv_months`; X = `build_features(...,"ltv")`, y = `ltv_months`; models: `XGBRegressor(n_estimators=400, learning_rate=0.05, max_depth=4, subsample=0.9, colsample_bytree=0.9, random_state=42)`, `LGBMRegressor(n_estimators=400, learning_rate=0.05, num_leaves=15, random_state=42, verbose=-1)`, `CatBoostRegressor(iterations=600, learning_rate=0.05, depth=4, random_seed=42, verbose=0)`; 5-fold CV each; fit each on all rows; save `models/ltv_<name>.joblib`; importances; **ablation**: repeat CatBoost with `cumulative_profit` added (via a local allow-list, never through `TASK_FEATURES`) and record `ablation_with_profit`; choose `served` = best CV RMSE (or `ensemble` mean if within 1 std); write `metrics["ltv"]`.
  4. `ml/registry.py` (§3.5) `predict_ltv` + `tests/test_registry.py` (loads real artifacts; a plausible customer → 1 ≤ months ≤ 60).
  5. `app/schemas.py::CustomerInput` (14 FUNNEL_RAW ints/floats with `ge=0` validation) + `app/routers/predict.py::POST /api/predict/ltv` → `LtvPrediction{months, by_model, served}`; logs to `prediction_log` via the user's client (insert; failures logged, not fatal). `GET /api/models` → metrics.json. `GET /api/predictions?limit=20` → the user's own recent rows.
  6. Dashboard **Predict** tab: customer form (14 fields with sensible defaults from column medians), "Predict" → shows LTV months + per-model values; **Findings** tab shows `/api/models` tables (CV, importances chart).
  7. `docs/REPORT.md` §P2: should `cumulative_profit` be a feature (no; the ablation numbers as evidence); which features dominate and do the three models agree; the two-sentence lever + recommendation.
- **Gate (--m 3):** (1) `pytest tests/test_features.py` green incl. leakage test; (2) `metrics.json["ltv"]["cv"]` has all three models with rmse/r2; (3) ablation R² > served R² (documents the leak; if not, explain in REPORT); (4) `POST {LIVE_URL}/api/predict/ltv` with gate token → 200 and 1 ≤ months ≤ 60; (5) `prediction_log` has ≥1 row for the gate user; (6) REPORT §P2 answers present.
- **Failure signals:** R² near 1 on FUNNEL-only features → something leaks (check `closed`/`CAC` derivations against ltv); R² near 0 → check target filter and NaN handling; CatBoost slow → reduce iterations, keep seed.

### M4 — P3: upsell probability (classification)
- **Branch:** `feat/m4-upsell` · **Report:** `docs/reports/M4_HE.html`
- **Goal:** honest classifier vs baseline vs a business rule.
- **Tasks:**
  1. `ml/train_upsell.py`: class balance (expect ≈42% positive) → decide `scale_pos_weight`/`class_weight` (train both ways on one model, keep if F1 improves, record reason); three classifiers (XGB/LGBM/CatBoost, same style params as M3, `eval_metric='logloss'`), stratified 5-fold, metrics + majority baseline; two variants **early** and **tenure** (`TASK_FEATURES["upsell_tenure"]`); choose `variant_served` by ROC-AUC with the justification text in REPORT; importances plot data for the best model; **business_rule(df, ltv_threshold, cac_threshold)** = `ltv_months > X and customer_acquisition_cost < Y` with X,Y = grid-searched on train folds for best F1; confusion comparison rule vs model (where the rule wins/loses: by tier). Save `models/upsell_<variant>_<name>.joblib`, `metrics["upsell"]`.
  2. `registry.predict_upsell` (probability from served model; `flag = p ≥ 0.5`; `rule_flag` computed from the stored thresholds — requires `ltv_months` in the input for the tenure variant, so `CustomerInput` gets an optional `ltv_months`; when absent and variant is tenure, respond 422 with a clear message).
  3. `POST /api/predict/upsell` → `UpsellPrediction{probability, flag, rule_flag, variant}`; Predict tab shows probability + rule verdict side by side.
  4. `docs/REPORT.md` §P3: is accuracy sufficient (no — show precision/recall at the baseline), baseline vs model delta, one feature or a combination (importance spread), where the rule wins/loses.
- **Gate (--m 4):** (1) `metrics["upsell"]["baseline"]` and per-model CV present for both variants; (2) served model ROC-AUC > 0.5 + 0.05 and F1 > baseline F1; (3) `business_rule` numbers present; (4) live endpoint 200 with probability in [0,1]; (5) REPORT §P3 answers present.
- **Failure signals:** tenure variant ROC-AUC ≫ early (ltv is doing all the work → say so; consider serving early anyway if the business use is pre-purchase); all importances on one feature → check for a derived duplicate of the target.

### M5 — P4: the super-customer score
- **Branch:** `feat/m5-super-score` · **Report:** `docs/reports/M5_HE.html`
- **Goal:** tuned CatBoost with native categorical tier, 0–100 score live, profile of super customers.
- **Tasks:**
  1. `ml/train_super.py`: X = `build_features(df,"super",categorical=True)` (`budget_tier` as str, `cat_features=["budget_tier"]`), y = `referred`; grid: `learning_rate ∈ {0.03, 0.1}`, `depth ∈ {4, 6, 8}`, `iterations ∈ {300, 600, 1000}` = 18 fits × 5 folds (stratified) scored by ROC-AUC; record the whole `search` table; refit best on all rows → `models/super.joblib`; importances; `super_customer_profile(df)`: super = `referred & upsell==1 & ltv_months ≥ 75th percentile` → `{n, share_of_customers, share_of_total_profit, avg_cac, avg_cac_others, avg_ltv, tier_distribution}`; write `metrics["super"]` + `metrics["super"]["profile"]`.
  2. `registry.super_score` → `round(100*p)`; `POST /api/predict/super-score` → `SuperScore{score, probability, band}` with band Low <40 / Medium 40–70 / High >70.
  3. `GET /api/insights/super-customers` → the profile (computed from Supabase rows at runtime, same function as training).
  4. Predict tab: score gauge + band; Findings tab: profile card + search table (top 5 configs).
  5. `docs/REPORT.md` §P4: profile numbers, share of profit, avg CAC, and how to spot them earlier (which early features carry the signal).
- **Gate (--m 5):** (1) `search` has 18 rows; (2) `best_params` matches the max ROC-AUC row; (3) scores on all 3,500 rows are within 0..100 and not constant (std > 5); (4) live endpoint 200; (5) `/api/insights/super-customers` shows `share_of_total_profit` in (0,1); (6) REPORT §P4 present.
- **Failure signals:** grid takes > 15 min → cut to 3-fold for the search, keep 5-fold for the final CV; CatBoost complains about categorical dtype → pass strings, not pandas category.

### M6 — P5: the follow-up paradox
- **Branch:** `feat/m6-followups` · **Report:** `docs/reports/M6_HE.html`
- **Goal:** answer the sales manager with data, on the dashboard.
- **Tasks:**
  1. `ml/followups.py`: `dropout_table(df)` → per stage (answered→f1, f1→f2, …, f4→f5, f5→closed): `remaining_mean`, `dropout_rate` (1 − next/prev, aggregated over sums), `dropout_rate_by_tier`; `closed_deals_followups(df)` → distribution of `calls_to_closed` (mean, median, p25/p75, share > 3) and same for `calls_to_not_closed`; `recommendation(dropout, closed_stats)` → `{"verdict": "keep|cut_after_3|extend", "reason": str, "unexpected_stage": str}` using explicit rules: the "unexpected" stage is the one whose dropout deviates most from the median of the others; verdict = cut only if share of closed deals needing > 3 calls < 15%, else keep.
  2. `GET /api/insights/followups` → these three dicts; Dashboard **Follow-ups** tab: funnel/line chart of remaining leads, bar of dropout per stage, histogram of calls-to-close, recommendation card.
  3. `tests/test_followups.py` on a synthetic frame where stage 4 is engineered to be anomalous.
  4. `docs/REPORT.md` §P5: which stage behaves unexpectedly, typical follow-ups for closed deals, yes/no recommendation and why.
- **Gate (--m 6):** (1) tests green; (2) live endpoint 200 with 6 stages; (3) recommendation card visible with a non-empty reason; (4) REPORT §P5 present.
- **Failure signals:** dropout monotonic and boring → the "paradox" may be in `calls_to_closed` instead (e.g. most closed deals took 4–5 calls) — report what the data says.

### M7 — P6: profit model and budget simulator
- **Branch:** `feat/m7-budget-simulator` · **Report:** `docs/reports/M7_HE.html`
- **Goal:** where should ₪50,000 go — concentrated or spread — with a model behind it.
- **Tasks:**
  1. `ml/train_profit.py`: rows with non-null `cumulative_profit`; X = `build_features(df,"profit")`, y = `cumulative_profit`; three regressors, CV; serve best → `models/profit.joblib`; `metrics["profit"]` incl. `profile_levels` (the 16 distinct budgets).
  2. `ml/simulator.py`: `typical_profile(df) -> dict[int, dict]` = median of every `FUNNEL_RAW` feature per distinct `ad_budget` (stored into `models/profiles.json` at training time so the API needs no DB for simulation); `simulate(allocation: list[{budget:int, count:int}], registry) -> {"total_budget", "expected_profit", "per_campaign": [...], "empirical_profit": sum(count × mean observed profit at that budget)}`; `preset_strategies()` = `[2×20000+1×10000, 10×5000, 25×2000, 100×500]` plus `5×10000`; validation: budgets ∈ profile_levels, `sum(budget×count) == 50000`, else 422.
  3. `POST /api/simulate/budget` (`BudgetAllocation{allocation, total=50000}`) → `SimulationResult`; `GET /api/simulate/presets` → all presets ranked.
  4. Dashboard **Budget** tab: preset table ranked by expected profit (model vs empirical side by side), free builder with running total and a disabled button until it equals 50,000.
  5. `docs/REPORT.md` §P6: concentrate vs spread verdict from the model's curve, caveats (capacity to handle 100 campaigns; extrapolation), what to tell the founder next month.
- **Gate (--m 7):** (1) `tests/test_simulator.py`: sum validation, unknown level rejected, presets all total 50,000; (2) live presets endpoint 200 with 5 ranked strategies; (3) free builder blocks a wrong total (manual, screenshot); (4) model vs empirical ranking agree on the winner or the disagreement is explained in REPORT; (5) REPORT §P6 present.
- **Failure signals:** model predicts the same profit per campaign at every budget → profile fill-in too flat, check medians; expected profit of 100×500 wildly high → per-campaign profit at 500 is noisy; show n per level.

### M8 — Wrap-up
- **Branch:** `feat/m8-wrapup` · **Report:** `docs/reports/M8_HE.html` (final)
- **Tasks:** README (overview, architecture diagram, local setup incl. conda + `.env.example`, load/train/run commands, live URL, CI badge, screenshots, credits); `docs/REPORT.md` complete with an executive summary for the founder; `PROJECT_LOG.md` closed; Obsidian home marked complete; "stranger test": a fresh browser profile → login → prediction → follow-ups → budget → findings; optional 3–5 min screen recording (`docs/demo.md` with the link).
- **Gate (--m 8):** every DoD box below checked; gate runs M0–M7 gates in sequence (offline checks only) and all pass.

### M9 — React front-end (portfolio track; **deferred by Dor on 2026-09-07**. Draft plan: `docs/notes/M9_PLAN_HE.html`. When resumed, a full plan is to be written that also folds in the M10 candidates below.)
- **Goal:** the same five screens in React + TypeScript, served by the same FastAPI service at the same URL; zero changes to `app/`, `ml/`, Supabase or Railway. Parity plus five UX gains: real routes, live funnel validation, a shared "current customer" from Predict to Budget, loading/error states, and hash-named assets (no stale caches).
- **Decisions (to approve):** D-M9-1 stack = Vite + React 18 + TS, react-router, TanStack Query, react-chartjs-2, supabase-js, Vitest + Playwright. D-M9-2 build committed: `npm run build` locally → `static/app/` in git; CI rebuilds and fails on drift (the D2 principle). D-M9-3 coexistence: React at `/app/`, legacy at `/static/dashboard.html` until the stranger test passes; cutover + deletion only in M9c. D-M9-4 English UI, RTL-ready.
- **Layout:** `frontend/` (src/lib/api.ts typed from `/api/openapi.json`, `lib/funnel.ts` identities, `state/customer.tsx`, `components/`, `pages/`, `tests/`, `e2e/stranger.spec.ts`), `static/app/` (built), one line in `app/main.py` at cutover (`/` → `/app/`), one CI step (node 20 → npm ci → lint → test → build → drift check).
- **PRs and gates:**
  - **M9a** `feat/m9a-react-shell` (5–6 h): Node via nvm, scaffold, session guard + login, typed API client, shell + routing, Overview + Findings at parity, CI build + drift, live at `/app/`. Gate: npm lint/test/build green, drift check, pytest + ruff unchanged, live `/app/` 200 + login + same numbers as legacy (side-by-side screenshot).
  - **M9b** `feat/m9b-react-screens` (5–6 h): Predict (live validation, three results, novelty warning, log), Follow-ups, Budget (presets, curve, locked builder, "customers like this" from Predict); Vitest for identities + builder lock. Gate: all tests green; live results equal the API's; builder locks on a wrong total; Budget receives the Predict customer.
  - **M9c** `feat/m9c-react-cutover` (3–4 h): Playwright stranger test (11 steps, local server, .env test user, not in CI), `/` → `/app/`, delete the legacy static files, responsive + keyboard polish, README + 30-second GIF, Hebrew M9 report, PROJECT_LOG, Obsidian, version 1.0.0. Gate: Playwright passes locally; Dor's stranger test PASS on React; `gate.py --m 9`.
- **Gate (--m 9):** (1) pytest + ruff; (2) `npm run lint && npm test && npm run build`; (3) `static/app/` equals the build output; (4) every M0–M8 offline check; (5) live `/` redirects to `/app/`, bundle loads, `/health` shows 1.0.0; (6) legacy dashboard gone from the tree; (7) React stranger test recorded PASS; (8) README / REPORT / M9 report updated.
- **M10 candidates (to be folded into the full plan on resumption):** Hebrew i18n with an RTL toggle; saved budget scenarios per user in Supabase (new table + RLS policies, list/compare/delete); scenario comparison side by side (two customers, two allocations); Recharts or a designed chart system; user management (invite team members, roles) or a read-only guest login for portfolio visitors; mobile-first layout; a 30-second demo GIF and `docs/demo.md`; static asset hashing already covered by the Vite build.
- **Failure signals:** CI build differs from local → pin `.nvmrc` + `npm ci`; Railway serves stale `/app/` → assets are hash-named, only `index.html` is `no-cache`; day 2 overruns → Budget moves to day 3, the GIF can wait, the legacy UI is never deleted before the stranger test.

---

## 5. Per-milestone protocol (the checklist for every M)

1. `git checkout -b <branch>` from an up-to-date `main`.
2. Start the session with a plain-Hebrew paragraph: what this milestone does and why (user request from Northwind).
3. Build with tests next to code; commit small (`feat:`, `test:`, `docs:`, `fix:` prefixes).
4. `python scripts/gate.py --m N` → must print `PASS k/k`. Fix, don't skip.
5. Write `docs/reports/M<N>_HE.html` (Hebrew, RTL, Northwind design system: Suez One + Assistant + IBM Plex Mono, paper/wind/tape/gate palette) and open it in the browser; verify RTL with the `rtl-accessible-sites` check.
6. Terminal summary in short professional English: what was built, gate result, what's next.
7. Obsidian (`~/Documents/Obsidian Vault/Projects/FunnelIQ/`): update the home page status table, the milestone note, today's log under `Log/`, and `החלטות.md` for any D-M<N>-x decision.
8. `PROJECT_LOG.md` entry; push; `gh pr create`; CI green; merge; confirm Railway redeployed (`/health` version changes) and the new feature works on `LIVE_URL`.

## 6. Standing rules
- Provided files (`data/funnel_marketing_data.csv`, `FunnelIQ_Assignment.html`) are never modified.
- Leakage guard is a test, not a comment. Ablations are allowed only through a local allow-list inside the trainer and must be labeled `ablation_*` in metrics.
- Numbers in REPORT/FINDINGS come from `metrics.json` / `overview_stats`, never typed by hand.
- Any data surprise is logged as a decision (D-M<N>-x) with alternatives and cost, not silently patched.
- Secrets: `.env` only; `git grep -iE "service_role|eyJ[A-Za-z0-9_-]{20,}"` must stay empty before every push.

## 7. Manual steps the user owns (collected)
- **M0:** Railway project from GitHub repo, variables, public domain → `LIVE_URL` in `.env`.
- **M1:** Supabase project + keys into `.env`; disable self sign-up; create the team user; run `schema.sql` + `policies.sql` in the SQL editor; add `SUPABASE_JWT_SECRET` to Railway only if the project is HS256.
- **Every M:** review the Hebrew report, approve the PR merge.

## 8. Definition of Done
- [ ] Public GitHub repo with README, `db/schema.sql`, green CI badge, ≥1 merged PR (target: one per milestone)
- [ ] Live Railway URL: `/health` 200, survives restart, redeploys on push
- [ ] Login: unauthenticated visitor sees only the login page; sign-out clears the session
- [ ] RLS proven: anon without JWT → 0 rows; with JWT → 3,500
- [ ] Service key absent from Railway and from git history
- [ ] Loader script idempotent; 3,500 rows in `funnel_records`
- [ ] P1 `docs/FINDINGS.md` answers all three questions with numbers
- [ ] P2 three regressors, 5-fold RMSE/R², importances compared, leakage justified with ablation, prediction live
- [ ] P3 three classifiers, stratified CV, baseline, imbalance decision, rule vs model, prediction live
- [ ] P4 tuned CatBoost with categorical tier, 0–100 score live, super-customer profile
- [ ] P5 dropout chart + recommendation on the dashboard
- [ ] P6 simulator live with ranked strategies + founder recommendation
- [ ] `docs/REPORT.md` complete; `PROJECT_LOG.md` complete; Obsidian home/decisions/stage notes/logs complete
- [ ] Stranger test passed end-to-end
