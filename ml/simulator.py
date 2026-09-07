"""P6 — the ₪50,000 budget simulator.

`typical_profile(df)` summarises what a campaign at each distinct ad budget looks like (median of
every FUNNEL_RAW feature per level) and is written to `models/profiles.json` at training time, so the
API can simulate without touching the database. `simulate()` multiplies the served model's expected
profit per campaign at each level (its predictions averaged over the real campaigns at that level, stored in
the same file) by the number of campaigns, and reports the observed mean profit next to the model's number. `preset_strategies()` are the brief's four splits plus 5 × ₪10,000.

    python -m ml.simulator                 # rank the presets with the committed model
    python -m ml.simulator --write-report  # also write docs/REPORT.md §P6
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from ml.features import FUNNEL_RAW

TOTAL_BUDGET = 50_000
PROFILES_FILE = "profiles.json"
REPORT_PATH = Path(__file__).resolve().parent.parent / "docs" / "REPORT.md"


# ------------------------------------------------------------------ profiles
def typical_profile(df: pd.DataFrame) -> dict:
    """Per distinct ad_budget: median funnel features, campaign count, and observed profit stats.

    Medians are taken column by column, so the profile is a *typical* campaign rather than a real
    one (the funnel identities need not hold exactly); the profit model does not require them to.
    """
    profiles: dict[str, dict] = {}
    for budget, grp in df.groupby("ad_budget", sort=True):
        feats = {c: float(grp[c].median()) for c in FUNNEL_RAW}
        feats["ad_budget"] = float(budget)
        with_profit = grp["cumulative_profit"].dropna()
        profiles[str(int(budget))] = {
            "n": int(len(grp)),
            "n_with_profit": int(len(with_profit)),
            "mean_profit": round(float(with_profit.mean()), 1) if len(with_profit) else None,
            "median_profit": round(float(with_profit.median()), 1) if len(with_profit) else None,
            "purchase_rate": round(float(grp["purchased"].mean()), 4),
            "features": feats,
        }
    return {"levels": [int(k) for k in profiles], "profiles": profiles}


def save_profiles(profiles: dict, models_dir: Path) -> Path:
    path = Path(models_dir) / PROFILES_FILE
    path.write_text(json.dumps(profiles, indent=2) + "\n", encoding="utf-8")
    return path


def load_profiles(models_dir: Path) -> dict | None:
    path = Path(models_dir) / PROFILES_FILE
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


# ------------------------------------------------------------------ strategies
def preset_strategies() -> list[dict]:
    """The brief's four ways to split ₪50,000, plus 5 × ₪10,000 (a mid-sized concentration)."""
    return [
        {
            "name": "2 × ₪20,000 + 1 × ₪10,000",
            "allocation": [{"budget": 20000, "count": 2}, {"budget": 10000, "count": 1}],
        },
        {"name": "5 × ₪10,000", "allocation": [{"budget": 10000, "count": 5}]},
        {"name": "10 × ₪5,000", "allocation": [{"budget": 5000, "count": 10}]},
        {"name": "25 × ₪2,000", "allocation": [{"budget": 2000, "count": 25}]},
        {"name": "100 × ₪500", "allocation": [{"budget": 500, "count": 100}]},
    ]


def validate_allocation(allocation: list[dict], profiles: dict, total: int = TOTAL_BUDGET) -> None:
    """Raise ValueError (→ HTTP 422) unless every level is known and the spend equals the total."""
    if not allocation:
        raise ValueError("allocation is empty")
    levels = set(profiles["levels"])
    spend = 0
    for item in allocation:
        budget, count = int(item["budget"]), int(item["count"])
        if budget not in levels:
            raise ValueError(f"unknown budget level {budget}; choose one of {sorted(levels)}")
        if count < 1:
            raise ValueError("count must be at least 1")
        spend += budget * count
    if spend != total:
        raise ValueError(f"allocation totals ₪{spend:,} but must equal ₪{total:,}")


# ------------------------------------------------------------------ simulation
def expected_profit_per_campaign(profile: dict, registry) -> float:
    """The served model averaged over the real campaigns at this level (stored at training time, D-M7-1);
    falls back to predicting on the typical profile when the stored value is absent."""
    stored = profile.get("model_mean_profit")
    return float(stored) if stored is not None else registry.predict_profit(profile["features"])


def simulate(allocation: list[dict], registry, total: int = TOTAL_BUDGET) -> dict:
    """Expected profit of an allocation: model prediction on the typical profile × campaigns per level."""
    profiles = registry.profiles
    if profiles is None or registry.profit_model is None:
        raise RuntimeError("profit model or profiles are not loaded")
    validate_allocation(allocation, profiles, total)
    lines = []
    expected = 0.0
    empirical: float | None = 0.0
    n_campaigns = 0
    for item in allocation:
        budget, count = int(item["budget"]), int(item["count"])
        prof = profiles["profiles"][str(budget)]
        pred = expected_profit_per_campaign(prof, registry)
        emp = prof["mean_profit"]
        line = {
            "budget": budget,
            "count": count,
            "spend": budget * count,
            "profile_n": prof["n_with_profit"],
            "predicted_profit_per_campaign": round(pred, 1),
            "empirical_profit_per_campaign": emp,
            "expected_profit": round(pred * count, 1),
            "empirical_profit": round(emp * count, 1) if emp is not None else None,
        }
        lines.append(line)
        expected += pred * count
        n_campaigns += count
        empirical = None if (empirical is None or emp is None) else empirical + emp * count
    served = registry.metrics.get("profit", {}).get("served")
    rmse = (
        registry.metrics.get("profit", {}).get("cv", {}).get(served, {}).get("rmse_mean") if served else None
    )
    return {
        "total_budget": total,
        "n_campaigns": n_campaigns,
        "expected_profit": round(expected, 1),
        "empirical_profit": round(empirical, 1) if empirical is not None else None,
        "roi_model": round(expected / total, 3),
        "roi_empirical": round(empirical / total, 3) if empirical is not None else None,
        "per_campaign": lines,
        "served_model": served,
        "rmse_per_campaign": rmse,
    }


def profit_curve(registry) -> list[dict]:
    """Model vs observed profit for one typical campaign at every budget level."""
    profiles = registry.profiles
    curve = []
    for level in profiles["levels"]:
        prof = profiles["profiles"][str(level)]
        pred = expected_profit_per_campaign(prof, registry)
        curve.append(
            {
                "budget": level,
                "n": prof["n_with_profit"],
                "predicted_profit": round(pred, 1),
                "typical_profile_profit": prof.get("model_typical_profit"),
                "empirical_mean_profit": prof["mean_profit"],
                "predicted_per_1000": round(pred / (level / 1000), 1),
                "empirical_per_1000": round(prof["mean_profit"] / (level / 1000), 1)
                if prof["mean_profit"] is not None
                else None,
            }
        )
    return curve


def rank_presets(registry, total: int = TOTAL_BUDGET) -> dict:
    """All presets simulated and ranked by expected profit; says whether model and data agree on the winner."""
    strategies = []
    for preset in preset_strategies():
        res = simulate(preset["allocation"], registry, total)
        strategies.append(
            {
                "name": preset["name"],
                "allocation": preset["allocation"],
                "n_campaigns": res["n_campaigns"],
                "expected_profit": res["expected_profit"],
                "empirical_profit": res["empirical_profit"],
                "roi_model": res["roi_model"],
                "roi_empirical": res["roi_empirical"],
            }
        )
    strategies.sort(key=lambda s: s["expected_profit"], reverse=True)
    for i, s in enumerate(strategies, 1):
        s["rank"] = i
    winner_model = strategies[0]["name"]
    with_emp = [s for s in strategies if s["empirical_profit"] is not None]
    winner_empirical = max(with_emp, key=lambda s: s["empirical_profit"])["name"] if with_emp else None
    curve = profit_curve(registry)
    best_level = max(curve, key=lambda c: c["predicted_per_1000"])
    most_concentrated = min(strategies, key=lambda s: s["n_campaigns"])["name"]
    return {
        "total_budget": total,
        "levels": registry.profiles["levels"],
        "strategies": strategies,
        "winner_model": winner_model,
        "winner_empirical": winner_empirical,
        "agree": winner_model == winner_empirical,
        "verdict": "concentrate" if winner_model == most_concentrated else "spread",
        "best_level_per_1000": best_level["budget"],
        "curve": curve,
        "served_model": registry.metrics.get("profit", {}).get("served"),
    }


# ------------------------------------------------------------------ REPORT.md §P6
def render_report_md(ranking: dict, profit_metrics: dict) -> str:
    cv = profit_metrics["cv"]
    served = profit_metrics["served"]
    s = ranking["strategies"]
    win = s[0]
    conc = next(x for x in s if x["n_campaigns"] == min(y["n_campaigns"] for y in s))
    curve = ranking["curve"]
    best = next(c for c in curve if c["budget"] == ranking["best_level_per_1000"])
    lines = [
        "## P6 — Where should ₪50,000 go? (profit model + budget simulator)",
        "",
        f"**Setup.** Profit model on every campaign with a recorded profit (n = {profit_metrics['n_train']:,}, "
        "non-purchasers included at ₪0 — D-M2-1), FUNNEL features only. Three regressors, 5-fold CV:",
        "",
        "| model | RMSE (₪) | R² |",
        "| --- | ---: | ---: |",
    ]
    for name in ("xgboost", "lightgbm", "catboost"):
        m = cv[name]
        star = " ★ served" if name == served else ""
        lines.append(f"| {name}{star} | {m['rmse_mean']:,.0f} ± {m['rmse_std']:,.0f} | {m['r2_mean']:.3f} |")
    lines += [
        "",
        f"Target std ₪{profit_metrics['target_stats']['std']:,.0f}. For each budget level the simulator uses the served "
        "model's expected profit per campaign — its predictions averaged over the real campaigns at that level, stored "
        "in `models/profiles.json` next to the median funnel profile — and multiplies by the number of campaigns; the "
        "empirical column is the observed mean profit at that level × campaigns.",
        "",
        "### The model's curve: profit per campaign by budget level",
        "",
        "| budget | campaigns in data | model profit / campaign | observed mean | model profit per ₪1,000 |",
        "| ---: | ---: | ---: | ---: | ---: |",
    ]
    for c in curve:
        lines.append(
            f"| ₪{c['budget']:,} | {c['n']} | ₪{c['predicted_profit']:,.0f} | ₪{c['empirical_mean_profit']:,.0f} "
            f"| ₪{c['predicted_per_1000']:,.0f} |"
        )
    lines += [
        "",
        f"The curve is a staircase, not a slope: the Mid tier (₪2,000–5,000) returns ₪{best['predicted_profit']:,.0f} per "
        f"campaign, while a ₪20,000 campaign returns about ₪{curve[-1]['predicted_profit']:,.0f} and a ₪500 one about "
        f"₪{curve[0]['predicted_profit']:,.0f}. Per ₪1,000 spent the best level is **₪{best['budget']:,}** "
        f"(₪{best['predicted_per_1000']:,.0f}). More budget buys more leads (P1) but not more profit per campaign.",
        "",
        "### The five strategies, ranked",
        "",
        "| rank | strategy | campaigns | expected profit (model) | observed-mean profit | ROI (model) |",
        "| ---: | --- | ---: | ---: | ---: | ---: |",
    ]
    for x in s:
        lines.append(
            f"| {x['rank']} | {x['name']} | {x['n_campaigns']} | ₪{x['expected_profit']:,.0f} | ₪{x['empirical_profit']:,.0f} "
            f"| {x['roi_model']:.1f}× |"
        )
    agree_text = (
        "The model and the raw data agree on the winner."
        if ranking["agree"]
        else f"The model and the raw data disagree on the winner (model: {ranking['winner_model']}; "
        f"data: {ranking['winner_empirical']}) — see the caveats."
    )
    verdict_word = "Concentrate" if ranking["verdict"] == "concentrate" else "Spread"
    lines += [
        "",
        "### Verdict: concentrate or spread?",
        "",
        f"**{verdict_word}.** {win['name']} is expected to return ₪{win['expected_profit']:,.0f} on ₪50,000 "
        f"({win['roi_model']:.1f}×), against ₪{conc['expected_profit']:,.0f} for the most concentrated split "
        f"({conc['name']}). {agree_text} The gap is not a modelling artefact: it is the tier staircase in the data, "
        "where a Mid-tier campaign earns roughly four times a High-tier one at a fraction of the cost.",
        "",
        "### Caveats",
        "",
        f"- **Capacity.** {win['n_campaigns']} campaigns a month is a different operation from three: each needs "
        "creative, a landing page and a sales team to work its leads (P5: a sale takes a median of 3 calls). If the "
        "team cannot run that many, the next-best Mid-tier split still beats concentration.",
        f"- **Small levels are noisy.** The ₪500 level has {curve[0]['n']} campaigns with median profit well below its "
        "mean; 100 × ₪500 leans on the least reliable part of the curve. Predicting on the *median* campaign alone "
        f"would put a ₪500 campaign at ₪{curve[0]['typical_profile_profit']:,.0f} (the plan's failure signal), which is "
        "why the simulator uses the model averaged over the real campaigns at each level (D-M7-1).",
        "- **Extrapolation.** The simulator only knows the 16 budget levels in the data and assumes campaigns are "
        "independent (no audience saturation from 25 parallel campaigns). Mixed allocations are fine; new levels are not.",
        "- **This is the practice dataset's structure.** Profit here is almost a function of tier; in production the "
        "curve must be re-estimated from real campaigns before the split is trusted.",
        "",
        "### What to tell the founder next month",
        "",
        f"Put the ₪50,000 into Mid-tier campaigns — {win['name']} if the team can run them, otherwise 10 × ₪5,000 — and "
        "stop buying ₪10,000+ campaigns until the data shows they earn more than ₪5,000 each. Track profit per campaign "
        "by level as the months come in; the simulator re-ranks automatically when the model is retrained.",
        "",
    ]
    return "\n".join(lines)


def write_report(ranking: dict, profit_metrics: dict, path: Path = REPORT_PATH) -> None:
    text = path.read_text(encoding="utf-8")
    block = render_report_md(ranking, profit_metrics)
    start = text.find("## P6")
    if start == -1:
        text = text.rstrip("\n") + "\n\n" + block
    else:
        end = text.find("\n## ", start + 1)
        text = text[:start] + block + (text[end:] if end != -1 else "")
    path.write_text(text.rstrip("\n") + "\n", encoding="utf-8")


def main() -> None:
    from ml.registry import MODELS_DIR, ModelRegistry

    parser = argparse.ArgumentParser(description="rank the ₪50,000 presets with the committed profit model")
    parser.add_argument("--write-report", action="store_true", help="write docs/REPORT.md §P6")
    args = parser.parse_args()
    reg = ModelRegistry.load(MODELS_DIR)
    ranking = rank_presets(reg)
    for s in ranking["strategies"]:
        print(
            f"{s['rank']}. {s['name']:28s} model ₪{s['expected_profit']:>12,.0f}   data ₪{s['empirical_profit']:>12,.0f}"
        )
    print(
        f"verdict: {ranking['verdict']} | agree: {ranking['agree']} | best per ₪1,000: ₪{ranking['best_level_per_1000']:,}"
    )
    if args.write_report:
        write_report(ranking, reg.metrics["profit"])
        print(f"wrote §P6 to {REPORT_PATH}")


if __name__ == "__main__":
    main()
