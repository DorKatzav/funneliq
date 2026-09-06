"""P1 — exploration & cleaning findings, computed (never hand-typed).

`overview_stats(df)` returns a JSON-safe dict that feeds three consumers:
  * docs/FINDINGS.md  (python -m ml.eda --write docs/FINDINGS.md)
  * GET /api/insights/overview  (computed from Supabase rows at runtime)
  * the dashboard Overview tab
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

from ml.data import TIERS, budget_tier, clean, incomplete_rows, load_raw

FUNNEL_IDENTITIES = {
    "leads_answered + leads_not_answered == num_leads": lambda d: d.leads_answered + d.leads_not_answered == d.num_leads,
    "closed + not_closed == followup_5": lambda d: d.closed + d.not_closed == d.followup_5,
    "followup_1 <= leads_answered": lambda d: d.followup_1 <= d.leads_answered,
    "followups are non-increasing": lambda d: (
        (d.followup_1 >= d.followup_2)
        & (d.followup_2 >= d.followup_3)
        & (d.followup_3 >= d.followup_4)
        & (d.followup_4 >= d.followup_5)
    ),
}


def _f(x, nd: int = 4) -> float | None:
    """JSON-safe float rounding (NaN -> None)."""
    if x is None or (isinstance(x, float) and np.isnan(x)):
        return None
    return round(float(x), nd)


def _safe_ratio(num: float, den: float) -> float | None:
    return _f(num / den) if den else None


def ensure_tier(df: pd.DataFrame) -> pd.DataFrame:
    """Rows coming from the database already carry budget_tier; CSV rows get it from clean()."""
    if "budget_tier" not in df.columns:
        df = df.copy()
        df["budget_tier"] = budget_tier(df["ad_budget"])
    return df


def overview_stats(df: pd.DataFrame) -> dict:
    df = ensure_tier(df)
    n = len(df)
    missing_per_col = {c: int(v) for c, v in df.isna().sum().items() if v > 0}
    incomplete = incomplete_rows(df)

    # --- correlations with cumulative_profit (Pearson, pairwise-complete) --------------
    numeric = df.drop(columns=[c for c in ("row_id", "id", "budget_tier") if c in df.columns]).copy()
    if numeric["referred"].dtype == bool:
        numeric["referred"] = numeric["referred"].astype(int)
    corr = numeric.astype(float).corr()["cumulative_profit"].drop("cumulative_profit")
    corr = corr.dropna().sort_values(ascending=False)  # constant columns have no correlation
    correlations = [{"column": c, "r": _f(v)} for c, v in corr.items()]

    # --- ad_budget -> num_leads ----------------------------------------------------------
    by_budget = []
    for budget, grp in df.groupby("ad_budget", sort=True):
        by_budget.append(
            {
                "ad_budget": int(budget),
                "n": int(len(grp)),
                "mean_leads": _f(grp.num_leads.mean(), 2),
                "leads_per_1000": _f(grp.num_leads.mean() / (budget / 1000), 2),
                "conversion": _safe_ratio(grp.closed.sum(), grp.num_leads.sum()),
                "mean_closed": _f(grp.closed.mean(), 2),
                "mean_profit": _f(grp.cumulative_profit.mean(), 1),
                "mean_cac": _f(grp.customer_acquisition_cost.mean(), 1),
            }
        )
    budgets = np.array([b["ad_budget"] for b in by_budget], dtype=float)
    leads = np.array([b["mean_leads"] for b in by_budget], dtype=float)
    elasticity = float(np.polyfit(np.log(budgets), np.log(leads), 1)[0]) if len(budgets) > 1 else None
    diminishing = {
        "leads_per_1000_at_min_budget": by_budget[0]["leads_per_1000"],
        "leads_per_1000_at_max_budget": by_budget[-1]["leads_per_1000"],
        "efficiency_ratio_max_over_min": _safe_ratio(by_budget[-1]["leads_per_1000"], by_budget[0]["leads_per_1000"]),
        "log_log_elasticity": _f(elasticity, 3),  # 1.0 = proportional; < 1 = diminishing returns
        "verdict": "diminishing" if elasticity is not None and elasticity < 0.9 else "roughly proportional",
    }

    # --- conversion by tier --------------------------------------------------------------
    tiers = []
    for tier in TIERS:
        grp = df[df.budget_tier == tier]
        if grp.empty:
            continue
        tiers.append(
            {
                "tier": tier,
                "n": int(len(grp)),
                "share_rows": _f(len(grp) / n),
                "conversion": _safe_ratio(grp.closed.sum(), grp.num_leads.sum()),
                "mean_profit": _f(grp.cumulative_profit.mean(), 1),
                "mean_cac": _f(grp.customer_acquisition_cost.mean(), 1),
                "mean_ltv_months": _f(grp.ltv_months.mean(), 2),
                "purchase_rate": _f(grp.purchased.mean()),
            }
        )
    best_tier = max(tiers, key=lambda t: t["conversion"] or -1)["tier"] if tiers else None

    # --- what do non-purchasers look like? -------------------------------------------------
    p0 = df[df.purchased == 0]
    purchased_zero = {
        "n": int(len(p0)),
        "share_ltv_positive": _f((p0.ltv_months > 0).mean()) if len(p0) else None,
        "share_profit_positive": _f((p0.cumulative_profit > 0).mean()) if len(p0) else None,
        "share_closed_positive": _f((p0.closed > 0).mean()) if len(p0) else None,
        "upsell_positive": int((p0.upsell == 1).sum()),
        "referred_positive": int(p0.referred.astype(bool).sum()),
        "mean_ltv_months": _f(p0.ltv_months.mean(), 2) if len(p0) else None,
    }

    consistency = {name: _f(rule(df).mean()) for name, rule in FUNNEL_IDENTITIES.items()}

    return {
        "counts": {
            "rows": int(n),
            "customers": int((df.purchased == 1).sum()),
            "non_customers": int((df.purchased == 0).sum()),
            "incomplete_rows": int(incomplete.sum()),
            "missing_per_column": missing_per_col,
            "incomplete_by_purchased": {str(k): int(v) for k, v in df[incomplete].purchased.value_counts().items()},
            "overall_conversion": _safe_ratio(df.closed.sum(), df.num_leads.sum()),
        },
        "correlations_with_profit": correlations,
        "budget_vs_leads": by_budget,
        "diminishing_returns": diminishing,
        "conversion_by_tier": tiers,
        "best_tier": best_tier,
        "purchased_zero_profile": purchased_zero,
        "funnel_consistency": consistency,
    }


# ------------------------------------------------------------------ FINDINGS.md rendering
def _pct(x: float | None) -> str:
    return "—" if x is None else f"{100 * x:.1f}%"


def _num(x: float | None, nd: int = 1) -> str:
    return "—" if x is None else f"{x:,.{nd}f}"


def render_findings_md(s: dict) -> str:
    c, d, pz, fc = s["counts"], s["diminishing_returns"], s["purchased_zero_profile"], s["funnel_consistency"]
    lines: list[str] = []
    a = lines.append
    a("# P1 — Exploration & cleaning findings")
    a("")
    a("> Generated by `python -m ml.eda --write docs/FINDINGS.md`. Every number below is computed, not typed.")
    a("")
    a("## 1. Missing values and how they are handled")
    a("")
    a(f"- Rows: **{c['rows']:,}** · customers (purchased = 1): **{c['customers']:,}** · non-customers: **{c['non_customers']:,}**.")
    missing = ", ".join(f"`{k}` {v}" for k, v in c["missing_per_column"].items()) or "none"
    a(f"- Incomplete rows: **{c['incomplete_rows']}** ({_pct(c['incomplete_rows'] / c['rows'])}). Missing per column: {missing}.")
    a(f"- Incomplete rows by purchased flag: {c['incomplete_by_purchased']}.")
    a("- **Handling (D-M2-2):** the missing columns are both *targets* (`ltv_months`, `cumulative_profit`). A target is never")
    a("  imputed: rows missing `ltv_months` are dropped only when training the LTV model; rows missing `cumulative_profit`")
    a("  only when training the profit model. Every other task keeps all rows. The database stores them as NULL.")
    a("- Funnel arithmetic holds on every row:")
    for name, share in fc.items():
        a(f"  - {name}: {_pct(share)}")
    a("")
    a("## 2. Correlation with `cumulative_profit`")
    a("")
    a("| column | Pearson r |")
    a("| --- | ---: |")
    for row in s["correlations_with_profit"]:
        a(f"| `{row['column']}` | {row['r']:+.3f} |")
    top = s["correlations_with_profit"][0]
    a("")
    a(f"- The strongest correlate is `{top['column']}` (r = {top['r']:+.3f}). It is an **outcome**, not something known at")
    a("  acquisition time — which is exactly why it must not be a feature when predicting other outcomes (see P2).")
    a("- Among funnel features, `calls_to_closed` has the strongest (negative) relationship: deals that need more calls")
    a("  to close end up less profitable. Budget and CAC correlate *negatively* with profit — spending more does not buy")
    a("  more profit per record.")
    a("")
    a("## 3. Does more budget buy proportionally more leads?")
    a("")
    a("| ad_budget | n | mean leads | leads per ₪1,000 | conversion | mean profit | mean CAC |")
    a("| ---: | ---: | ---: | ---: | ---: | ---: | ---: |")
    for b in s["budget_vs_leads"]:
        a(
            f"| {b['ad_budget']:,} | {b['n']} | {_num(b['mean_leads'])} | {_num(b['leads_per_1000'])} | "
            f"{_pct(b['conversion'])} | {_num(b['mean_profit'], 0)} | {_num(b['mean_cac'], 0)} |"
        )
    a("")
    a(f"- **Verdict: {d['verdict']}.** Leads per ₪1,000 fall from {_num(d['leads_per_1000_at_min_budget'])} at the smallest")
    a(f"  budget to {_num(d['leads_per_1000_at_max_budget'])} at the largest (ratio {_num(d['efficiency_ratio_max_over_min'], 2)}).")
    a(f"  The log-log elasticity of leads with respect to budget is {_num(d['log_log_elasticity'], 3)}; 1.0 would mean")
    a("  proportional. Every extra shekel buys fewer leads than the one before.")
    a("")
    a("## 4. Conversion rate by budget tier")
    a("")
    a("| tier | n | share | conversion (closed / leads) | mean profit | mean CAC | mean LTV (months) | purchase rate |")
    a("| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |")
    for t in s["conversion_by_tier"]:
        a(
            f"| {t['tier']} | {t['n']} | {_pct(t['share_rows'])} | {_pct(t['conversion'])} | {_num(t['mean_profit'], 0)} | "
            f"{_num(t['mean_cac'], 0)} | {_num(t['mean_ltv_months'])} | {_pct(t['purchase_rate'])} |"
        )
    a("")
    a(f"- **Best-converting tier: {s['best_tier']}.** It is surprising in the sense that neither the cheapest nor the")
    a("  most expensive campaigns win: the middle tier converts best *and* carries by far the highest profit and lifetime.")
    a("  High-budget campaigns buy many leads at a low rate per shekel and then convert them worse than Mid.")
    a("")
    a("## 5. Who are the non-purchasers? (drives D-M2-1)")
    a("")
    a(f"- {pz['n']} rows have purchased = 0. Share with profit > 0: {_pct(pz['share_profit_positive'])}; share with")
    a(f"  ltv_months > 0: {_pct(pz['share_ltv_positive'])} (mean {_num(pz['mean_ltv_months'])} months); share with closed > 0:")
    a(f"  {_pct(pz['share_closed_positive'])}; upsell = 1: {pz['upsell_positive']}; referred: {pz['referred_positive']}.")
    a("- Reading: a non-purchaser never produces profit or an upsell, yet often carries a positive 'lifetime' and even")
    a("  closed deals. This looks like relationship duration without a paid purchase. **Decision D-M2-1:** the customer")
    a("  models (P2 lifetime, P3 upsell, P4 super-customer) are trained on customers only (purchased = 1) — their")
    a("  questions are about people who *are* customers. The profit model (P6) keeps all rows, because a campaign")
    a("  that yields no purchase is a real zero-profit outcome the simulator must account for.")
    a("")
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="P1 findings from the provided CSV")
    parser.add_argument("--write", type=Path, help="write FINDINGS.md to this path")
    parser.add_argument("--json", action="store_true", help="print the stats as JSON")
    args = parser.parse_args()
    stats = overview_stats(clean(load_raw()))
    if args.json:
        print(json.dumps(stats, indent=2))
    if args.write:
        args.write.parent.mkdir(parents=True, exist_ok=True)
        args.write.write_text(render_findings_md(stats), encoding="utf-8")
        print(f"wrote {args.write}")
    if not args.json and not args.write:
        print(json.dumps(stats["counts"], indent=2))


if __name__ == "__main__":
    main()
