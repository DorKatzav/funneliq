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
