# CLAUDE.md — FunnelIQ working agreement

Read this first in every session. Then read the tail of `PROJECT_LOG.md` (last milestone entry) to know where we are.

## Language and reporting (Dor's preferences)

- **Terminal conversation: English**, short and professional.
- **After every big action** (a milestone, a gate, a deploy, a large refactor): a **Hebrew summary as an HTML page**
  (`docs/reports/M<N>_HE.html` for milestones; `docs/notes/*_HE.html` for anything else), opened in the browser.
  Small things: a short English summary in the terminal, no HTML.
- All code, UI text, file names, commits, PR titles and bodies: English.
- Hebrew HTML pages: `lang="he" dir="rtl"`, Northwind design system (Suez One + Assistant + IBM Plex Mono;
  paper / wind / tape / gate palette — copy the `<style>` block from the latest `docs/reports/M*_HE.html`).
  Numbers in tables use `class="num"` (LTR, monospace). Verify RTL rendering in the browser before calling it done.
- Report findings as they are, even when they are unflattering to the model (M4: the business rule beat the model).

## Sources of truth (do not re-derive, do not contradict)

- `DESIGN_HE.html` — design decisions D1–D10 (approved 2026-09-06).
- `PLAN.md` — contracts, milestones M0–M8 (+ optional M9), gate checks per milestone, per-milestone protocol (§5), standing rules (§6).
- `PROJECT_LOG.md` — decisions `D-M<N>-<n>`, experiments, metrics, incidents, lessons. Append; never rewrite history.
- `docs/REPORT.md` — business write-up per package (P2–P6). Numbers come from `models/metrics.json` / `ml.eda.overview_stats`, never typed by hand.
- Obsidian vault `~/Documents/Obsidian Vault/Projects/FunnelIQ/` — Hebrew notebook (home page status table, `שלבים/`, `Log/`, `החלטות.md`).

## Per-milestone protocol (PLAN.md §5 — every M, no shortcuts)

1. `git checkout -b feat/m<N>-<slug>` from an up-to-date `main`; one feature branch + PR per milestone.
2. Build with tests next to the code; small commits with `feat:` / `test:` / `docs:` / `fix:` prefixes.
3. `python scripts/gate.py --m <N>` must print `GATE M<N>: PASS k/k`. Fix, don't skip. Live checks read `.env`.
4. Hebrew report `docs/reports/M<N>_HE.html` with a live screenshot in `docs/reports/img/m<N>_*.jpg`.
5. Short English terminal summary: what was built, gate result, what's next.
6. Obsidian: home status table, milestone note, `Log/<date> — M<N>.md`, `החלטות.md` for any `D-M<N>-x`.
7. `PROJECT_LOG.md` entry; push; `gh pr create`; CI green; **Dor reviews the Hebrew report and approves the merge**;
   confirm Railway redeployed (`/health` commit hash) and the feature works on `LIVE_URL`.
8. Docs of a milestone (report, log, README status) go on a separate `docs/m<N>-report` branch + PR after the feature PR.

## Standing rules (PLAN.md §6)

- Models use **FUNNEL** (acquisition-time) features only. "The model must never have future information."
  Any OUTCOME column used as a feature needs a written justification in `docs/REPORT.md` and an entry in
  `ml/features.py::ALLOWED_OUTCOMES` (so far only `ltv_months` for the upsell-tenure variant, D-M4-1).
- `assert_no_leakage` is a test, not a comment. Ablations only through a local allow-list in the trainer, labelled `ablation_*` in metrics.
- Customer models (LTV, upsell, super) train on `purchased = 1` only; the profit model keeps all rows (D-M2-1).
  Targets are never imputed; drop rows missing the target only for that task (D-M2-2).
- Any data surprise becomes a `D-M<N>-x` decision with alternatives and cost, not a silent patch.
- Secrets only in `.env` (gitignored) and Railway variables. `SUPABASE_SERVICE_KEY` is never on Railway and never committed.
  `git grep -iE "service_role|eyJ[A-Za-z0-9_-]{20,}"` must stay empty before every push.
- Provided files (`data/funnel_marketing_data.csv`, `FunnelIQ_Assignment.html`) are never modified.

## Environment

- conda env `AI_dev` (Python 3.11): `source ~/miniconda3/etc/profile.d/conda.sh && conda activate AI_dev`.
- Run: `uvicorn app.main:app --reload` · test: `pytest -q && ruff check .` · train: `python -m ml.train_ltv|train_upsell|train_super`.
- macOS: `brew install libomp` for lightgbm/xgboost. Railpack image needs `libgomp1` (already in `railpack.json`).
- `gh` is logged in as DorKatzav. Live: https://funneliq-production-4b63.up.railway.app (`/health` shows the commit).
- Browser screenshots of the signed-in dashboard: mint a session with the gate user via the Supabase password grant
  (same as `scripts/gate.py`) and set `localStorage["sb-<project-ref>-auth-token"]` on the live origin;
  never type the password into the browser.

## Lessons already paid for (don't repeat)

- Supabase SQL editor runs only the highlighted selection; verify policies took effect with a count query.
- Railway domains are global — copy the URL from the Networking panel; a similar-looking domain may be someone else's app.
- Railway may switch to Railpack: keep the start command explicit in `railpack.json` + `railway.json`.
- Form defaults must satisfy the funnel identities (answered + not answered = leads, etc.); use a real representative row, not column medians.
- sklearn `clone()` fails on CatBoost with `cat_features`; `ml/evaluate.py::fresh()` rebuilds from `get_params()`.
- The secret-scan in `scripts/gate.py` must match key material only (it once matched itself and a SQL comment).
- Don't commit `catboost_info/` (ignored since PR #16).
