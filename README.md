# FunnelIQ

[![CI](https://github.com/DorKatzav/funneliq/actions/workflows/ci.yml/badge.svg)](https://github.com/DorKatzav/funneliq/actions/workflows/ci.yml)

Marketing-intelligence tool for Northbound Media: predicts customer lifetime, upsell
probability and a 0–100 "super customer" score, answers the follow-up paradox, and
simulates how to split a ₪50,000 monthly ad budget. Login-gated internal tool built
with gradient boosting (XGBoost, LightGBM, CatBoost), FastAPI, Supabase (Postgres + Auth
+ Row Level Security) and Railway.

> Status: **M4 — lifetime + upsell predictions live; business rule compared to the model.** Live: https://funneliq-production-4b63.up.railway.app (health: `/health`)

## Architecture (short version)

```text
browser (static HTML/JS, supabase-js with the public anon key)
   │  Authorization: Bearer <user JWT>
   ▼
FastAPI on Railway ── verifies the JWT ── queries Supabase WITH the user's token → RLS enforced
   ├── /api/predict/*      ← models/*.joblib (trained offline, committed)
   ├── /api/insights/*     ← computed from Supabase rows at runtime
   └── /api/simulate/*     ← profit model + budget simulator
```

The service-role key never leaves the local machine (it is used only by the data loader).
Full design: `DESIGN_HE.html` · implementation plan: `PLAN.md`.

## Local setup

```bash
conda activate AI_dev                 # or any Python 3.11 env
pip install -r requirements.txt
cp .env.example .env                  # fill in your Supabase values
uvicorn app.main:app --reload         # http://127.0.0.1:8000  (docs at /api/docs)
pytest -q && ruff check .
python scripts/load_data.py           # CSV → Supabase (needs SUPABASE_SERVICE_KEY locally)
python -m ml.eda --write docs/FINDINGS.md   # regenerate the P1 findings note
python -m ml.train_ltv                # P2: train the LTV regressors -> models/
python -m ml.train_upsell             # P3: train the upsell classifiers -> models/
python scripts/gate.py --m 4          # milestone gate (offline + live checks)
python scripts/smoke_live.py          # live end-to-end sanity sweep
```

macOS note: `lightgbm` needs `brew install libomp`.

Railway note: the service builds with **Railpack**; the start command lives in `railpack.json` (and `railway.json`) so the platform never has to guess it.

## Repository map

| Path | What |
| --- | --- |
| `app/` | FastAPI service (config, auth, routers, schemas) |
| `ml/` | data cleaning, features + leakage guard, training, evaluation, simulator |
| `models/` | committed model artifacts + `metrics.json` |
| `static/` | login + dashboard (vanilla HTML/JS, Chart.js) |
| `scripts/` | `load_data.py` (CSV → Supabase), `train_all.py`, `gate.py` |
| `db/` | `schema.sql`, `policies.sql` |
| `docs/` | `FINDINGS.md`, `REPORT.md`, Hebrew milestone reports |
| `data/` | the provided dataset (3,500 rows) |

## Credits

Brief and dataset: course assignment "FunnelIQ — Self-Directed Project Brief".
Built with FastAPI, Supabase, Railway, XGBoost, LightGBM, CatBoost, scikit-learn, pandas, Chart.js.
