# Stranger test — end-to-end walk-through in a fresh browser profile

The final acceptance check (PLAN §M8): someone who has never seen the project opens the live URL
in a clean browser profile and gets through every screen. Record the result at the bottom.

**URL:** https://funneliq-production-4b63.up.railway.app

| # | Step | Expected | Result |
| --- | --- | --- | --- |
| 1 | Open the URL in a fresh profile / incognito window | Redirected to the login page; no data visible |pass|
| 2 | Sign in with the team account | Dashboard opens on **Overview**: 3,500 records, 33 incomplete rows, 6.5% conversion, Mid tier, three charts |pass|
| 3 | **Predict** → press *Predict* with the defaults | Lifetime ≈ 27.6 months, upsell ≈ 73%, super score ≈ 63 (Medium); a row appears in *Your recent predictions* |pass|
| 4 | Predict → set `num_leads` to 400 and `leads_answered` to 386 → *Predict* | An orange "Far from the training data" warning appears under the lifetime | fail on the first run — the test ran before PR #23 was deployed (live was 0.7.0). Re-verified after deploy: `/api/predict/ltv` returns `novelty.flag = true` (leads_answered 25σ, num_leads + leads_answered outside the training range) → **pass** |
| 5 | Predict → set `leads_answered` so the funnel does not add up → *Predict* | A plain-language validation message, no crash |pass|
| 6 | **Follow-ups** | Verdict card "keep", 48% of sales needed more than 3 calls, unexpected stage follow-up 3 → 4, three charts, value table |pass|
| 7 | **Budget** | Five strategies ranked, 25 × ₪2,000 first; builder starts at ₪50,000 with *Simulate* enabled |pass|
| 8 | Budget → change a count so the total is not ₪50,000 | *Simulate* is disabled and the running total says how far off it is |pass|
| 9 | Budget → restore ₪50,000 → *Simulate* | Expected profit and a per-line table appear |pass|
| 10 | **Findings** | P2 model table + importances, P3 model vs rule tables, P4 profile card | pass, but the two P4 tables were not aligned (the right column had an intro line, the left did not) — fixed in PR #24 |
| 11 | **Sign out** | Back on the login page; reloading the dashboard URL redirects to login again |pass|

## Result

- Date: 2026-09-07
- Tester: Dor (fresh browser profile, real login); step 4 re-verified by Claude on the deployed build via the API
- Browser / profile: Chrome, incognito window
- Outcome: PASS — 11/11 after the two notes above (one timing issue, one cosmetic fix)
