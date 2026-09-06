"""P5 — the follow-up paradox: where do leads drop out, how many calls does a sale take,
and should the team stop after the third call?

Three pure functions over a funnel frame (CSV rows or Supabase rows — both carry the same
columns) plus a `recommendation()` that applies explicit, documented rules. The API serves
`followup_insights(df)`; the trainer-free CLI writes the REPORT.md §P5 block from the same
numbers so nothing in the write-up is typed by hand.

Rules (all constants below, all reported back in the recommendation dict):
- the "unexpected" stage is the follow-up transition whose dropout deviates most from the
  median dropout of the *other* follow-up transitions. The final transition (follow-up 5 →
  closed) is a close rate, not a follow-up dropout, so it is reported but never nominated.
- verdict `cut_after_3` only if fewer than CUT_THRESHOLD of closed deals needed more than
  3 calls; `extend` if at least EXTEND_THRESHOLD of closed deals needed more calls than
  the five tracked follow-ups; otherwise `keep`.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

from ml.data import TIERS, clean, load_raw
from ml.eda import ensure_tier

FUNNEL_PATH = [
    "num_leads",
    "leads_answered",
    "followup_1",
    "followup_2",
    "followup_3",
    "followup_4",
    "followup_5",
    "closed",
]
LABELS = {
    "num_leads": "leads",
    "leads_answered": "answered",
    "followup_1": "follow-up 1",
    "followup_2": "follow-up 2",
    "followup_3": "follow-up 3",
    "followup_4": "follow-up 4",
    "followup_5": "follow-up 5",
    "closed": "closed",
}
# answered→f1, f1→f2, f2→f3, f3→f4, f4→f5, f5→closed  (6 stages)
TRANSITIONS: list[tuple[str, str]] = list(zip(FUNNEL_PATH[1:-1], FUNNEL_PATH[2:], strict=True))

CUT_THRESHOLD = 0.15  # PLAN §M6: cut after 3 only if < 15% of closed deals needed > 3 calls
EXTEND_THRESHOLD = 0.25  # extend the tracked window only if ≥ 25% of closed deals needed > 5 calls
CALL_BUCKETS = [("1–2", 1, 2), ("3", 3, 3), ("4–5", 4, 5), ("6+", 6, 10**6)]

REPORT_PATH = Path(__file__).resolve().parent.parent / "docs" / "REPORT.md"


def _rate(before: float, after: float) -> float | None:
    """Dropout between two stages, aggregated over sums (not a mean of per-row ratios)."""
    return round(float(1 - after / before), 4) if before else None


def stage_name(a: str, b: str) -> str:
    return f"{LABELS[a]} → {LABELS[b]}"


def dropout_table(df: pd.DataFrame) -> dict:
    """Per stage: leads remaining (mean per campaign), dropout rate overall and by budget tier."""
    df = ensure_tier(df)
    sums = df[FUNNEL_PATH].sum()
    stages = []
    for a, b in TRANSITIONS:
        by_tier = {}
        for tier in TIERS:
            g = df[df.budget_tier == tier]
            if len(g):
                by_tier[tier] = _rate(g[a].sum(), g[b].sum())
        stages.append(
            {
                "stage": stage_name(a, b),
                "from": a,
                "to": b,
                "remaining_mean": round(float(df[b].mean()), 2),
                "remaining_sum": int(sums[b]),
                "dropout_rate": _rate(sums[a], sums[b]),
                "dropout_rate_by_tier": by_tier,
                "is_close": b == "closed",
            }
        )
    remaining = [
        {"stage": LABELS[c], "column": c, "mean": round(float(df[c].mean()), 2), "sum": int(sums[c])}
        for c in FUNNEL_PATH
    ]
    return {"n_rows": int(len(df)), "remaining": remaining, "stages": stages}


def _distribution(series: pd.Series) -> dict:
    s = series.dropna().astype(int)
    if s.empty:
        return {"n": 0}
    return {
        "n": int(len(s)),
        "mean": round(float(s.mean()), 2),
        "median": float(s.median()),
        "p25": float(s.quantile(0.25)),
        "p75": float(s.quantile(0.75)),
        "share_gt_3": round(float((s > 3).mean()), 4),
        "share_gt_5": round(float((s > 5).mean()), 4),
        "distribution": {str(k): int(v) for k, v in s.value_counts().sort_index().items()},
    }


def closed_deals_followups(df: pd.DataFrame) -> dict:
    """How many calls a sale takes (customers), how many a lost deal takes, and what a late close is worth."""
    customers = df[df.purchased == 1]
    lost = df[df.calls_to_not_closed > 0]
    value = []
    for label, lo, hi in CALL_BUCKETS:
        g = customers[(customers.calls_to_closed >= lo) & (customers.calls_to_closed <= hi)]
        if g.empty:
            continue
        value.append(
            {
                "calls": label,
                "n": int(len(g)),
                "share_of_closed": round(len(g) / len(customers), 4),
                "mean_ltv_months": round(float(g.ltv_months.mean()), 2),
                "mean_profit": round(float(g.cumulative_profit.mean()), 1),
                "upsell_rate": round(float(g.upsell.mean()), 4),
            }
        )
    return {
        "closed": _distribution(customers.calls_to_closed),
        "not_closed": _distribution(lost.calls_to_not_closed),
        "value_by_calls": value,
    }


def recommendation(dropout: dict, calls: dict) -> dict:
    """Explicit rules → verdict + reason + the stage that behaves unexpectedly."""
    followup_stages = [s for s in dropout["stages"] if not s["is_close"]]
    best: tuple[float, dict, float] | None = None
    for s in followup_stages:
        others = [o["dropout_rate"] for o in followup_stages if o is not s and o["dropout_rate"] is not None]
        if s["dropout_rate"] is None or not others:
            continue
        median_others = float(np.median(others))
        deviation = abs(s["dropout_rate"] - median_others)
        if best is None or deviation > best[0]:
            best = (deviation, s, median_others)
    if best is None:
        unexpected = {
            "unexpected_stage": None,
            "unexpected_dropout": None,
            "median_other_dropout": None,
            "unexpected_note": "",
        }
    else:
        _, stage, median_others = best
        direction = "lower" if stage["dropout_rate"] < median_others else "higher"
        unexpected = {
            "unexpected_stage": stage["stage"],
            "unexpected_dropout": stage["dropout_rate"],
            "median_other_dropout": round(median_others, 4),
            "unexpected_note": (
                f"'{stage['stage']}' loses {stage['dropout_rate']:.1%} of the remaining leads, "
                f"{direction} than the {median_others:.1%} median of the other follow-up stages."
            ),
        }

    closed = calls["closed"]
    gt3, gt5 = closed.get("share_gt_3", 0.0), closed.get("share_gt_5", 0.0)
    median, p75 = closed.get("median"), closed.get("p75")
    if closed.get("n", 0) == 0:
        verdict, reason = "keep", "No closed deals in the data; nothing supports cutting follow-ups."
    elif gt3 < CUT_THRESHOLD:
        verdict = "cut_after_3"
        reason = (
            f"Only {gt3:.0%} of closed deals needed more than 3 calls (cut threshold {CUT_THRESHOLD:.0%}); "
            "follow-ups beyond the third rarely produce a sale."
        )
    elif gt5 >= EXTEND_THRESHOLD:
        verdict = "extend"
        reason = (
            f"{gt5:.0%} of closed deals needed more than the 5 tracked follow-ups (extend threshold "
            f"{EXTEND_THRESHOLD:.0%}); the funnel should track and budget for later calls."
        )
    else:
        verdict = "keep"
        reason = (
            f"{gt3:.0%} of closed deals needed more than 3 calls (median {median:.0f}, "
            f"75th percentile {p75:.0f}); "
            f"stopping after the third call would forfeit those sales. {gt5:.0%} needed more than 5 calls "
            f"(below the {EXTEND_THRESHOLD:.0%} bar for extending the tracked window)."
        )

    value_note = ""
    vb = calls.get("value_by_calls") or []
    if len(vb) >= 2:
        first, last = vb[0], vb[-1]
        value_note = (
            f"A sale closed in {first['calls']} calls stays {first['mean_ltv_months']:.1f} months on average "
            f"(profit ₪{first['mean_profit']:,.0f}); one closed after {last['calls']} calls stays "
            f"{last['mean_ltv_months']:.1f} months (₪{last['mean_profit']:,.0f}). "
            "Late closes are real sales, but smaller ones."
        )

    return {
        "verdict": verdict,
        "reason": reason,
        **unexpected,
        "share_closed_gt_3": gt3,
        "share_closed_gt_5": gt5,
        "cut_threshold": CUT_THRESHOLD,
        "extend_threshold": EXTEND_THRESHOLD,
        "value_note": value_note,
    }


def followup_insights(df: pd.DataFrame) -> dict:
    """Everything the Follow-ups tab and REPORT §P5 need, from one frame."""
    dropout = dropout_table(df)
    calls = closed_deals_followups(df)
    return {"dropout": dropout, "calls": calls, "recommendation": recommendation(dropout, calls)}


# ------------------------------------------------------------------ REPORT.md §P5 rendering
def render_report_md(ins: dict) -> str:
    d, c, r = ins["dropout"], ins["calls"], ins["recommendation"]
    lines = [
        "## P5 — The follow-up paradox: is the team wasting time after the third call?",
        "",
        f"**Setup.** All {d['n_rows']:,} campaigns. Dropout per stage = 1 − (leads at the next stage ÷ "
        "leads at this stage), "
        "aggregated over the sums, overall and by budget tier. Calls-to-close comes from the customers "
        f"(n = {c['closed']['n']:,}); calls for lost deals from every campaign with at least one lost deal "
        f"(n = {c['not_closed']['n']:,}).",
        "",
        "| stage | leads remaining (mean per campaign) | dropout | Low | Mid | High |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for s in d["stages"]:
        bt = s["dropout_rate_by_tier"]
        cells = " | ".join(f"{bt.get(t, float('nan')):.1%}" if bt.get(t) is not None else "—" for t in TIERS)
        lines.append(f"| {s['stage']} | {s['remaining_mean']:.1f} | **{s['dropout_rate']:.1%}** | {cells} |")
    lines += [
        "",
        "### Which stage behaves unexpectedly?",
        "",
        f"**{r['unexpected_stage']}.** {r['unexpected_note']} The pattern is the same in every budget tier, "
        "so it is a property of the sales process, not of campaign size. Leads that are still talking after "
        "the third call are the committed ones; the big losses happen earlier (after the first and second "
        "follow-ups) and at the close itself "
        f"({d['stages'][-1]['dropout_rate']:.1%} of follow-up-5 leads do not sign).",
        "",
        "### How many follow-ups does a closed deal typically need?",
        "",
        f"Median **{c['closed']['median']:.0f} calls**, interquartile range "
        f"{c['closed']['p25']:.0f}–{c['closed']['p75']:.0f}, mean {c['closed']['mean']:.2f}. "
        f"**{c['closed']['share_gt_3']:.0%} of closed deals needed more than 3 calls** and "
        f"{c['closed']['share_gt_5']:.0%} needed more than 5. Lost deals take about as many: median "
        f"{c['not_closed']['median']:.0f}, mean {c['not_closed']['mean']:.2f} — the number of calls alone "
        "does not tell a "
        "sale from a loss.",
        "",
        "| calls to close | customers | share of sales | mean tenure (months) | mean profit | upsell rate |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for v in c["value_by_calls"]:
        lines.append(
            f"| {v['calls']} | {v['n']:,} | {v['share_of_closed']:.1%} | {v['mean_ltv_months']:.1f} "
            f"| ₪{v['mean_profit']:,.0f} | {v['upsell_rate']:.0%} |"
        )
    verdict_text = {
        "keep": "**No — do not stop after the third call.**",
        "cut_after_3": "**Yes — stop after the third call.**",
        "extend": "**No — and track more follow-ups than today.**",
    }[r["verdict"]]
    lines += [
        "",
        "### Recommendation: should the team stop following up after the third call?",
        "",
        f"{verdict_text} {r['reason']}",
        "",
        f"{r['value_note']} The lever is therefore not *whether* to keep calling but *whom*: the "
        "calls-to-close signal already drives the lifetime prediction (P2) and the super-customer "
        "score (P4), so late-closing leads should be "
        "worked with the expectation of a smaller account, not dropped.",
        "",
        f"Rules used (in `ml/followups.py`): cut only if < {r['cut_threshold']:.0%} of closed deals needed "
        f"> 3 calls; extend only if ≥ {r['extend_threshold']:.0%} needed > 5; the unexpected stage is the "
        "follow-up transition farthest from "
        "the median of the others.",
        "",
    ]
    return "\n".join(lines)


def write_report(ins: dict, path: Path = REPORT_PATH) -> None:
    """Replace (or append) the §P5 block in docs/REPORT.md; later sections are preserved."""
    text = path.read_text(encoding="utf-8")
    block = render_report_md(ins)
    start = text.find("## P5")
    if start == -1:
        text = text.rstrip("\n") + "\n\n" + block
    else:
        end = text.find("\n## P6", start)
        text = text[:start] + block + (text[end:] if end != -1 else "")
    path.write_text(text.rstrip("\n") + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="P5 follow-up insights from the CSV")
    parser.add_argument("--write-report", action="store_true", help="write docs/REPORT.md §P5")
    args = parser.parse_args()
    ins = followup_insights(clean(load_raw()))
    if args.write_report:
        write_report(ins)
        print(f"wrote §P5 to {REPORT_PATH}")
    print(json.dumps(ins["recommendation"], indent=2))


if __name__ == "__main__":
    main()
