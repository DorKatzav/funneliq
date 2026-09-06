"""P4 — the "super customer" score: a tuned CatBoost classifier on `referred`, served as 0–100.

    python -m ml.train_super

budget_tier is passed to CatBoost as a native categorical feature. The grid
(learning_rate × depth × iterations = 18 configs) is scored by stratified-CV ROC-AUC;
the whole search table is kept in metrics.json. `super_customer_profile` describes the
customers who actually stayed, bought more and referred — reused at runtime by
GET /api/insights/super-customers on the rows in Supabase.
"""

from __future__ import annotations

import argparse
import itertools
import json
import time
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from catboost import CatBoostClassifier

from ml.data import clean, customers_only, load_raw
from ml.evaluate import cv_classification, importances, majority_baseline
from ml.features import assert_no_leakage, build_features
from ml.registry import MODELS_DIR, save_metrics, utc_now

SEED = 42
CAT_FEATURES = ["budget_tier"]
GRID = {"learning_rate": [0.03, 0.1], "depth": [4, 6, 8], "iterations": [300, 600, 1000]}
SEARCH_SPLITS = 3  # cheaper for the 18-config search; the final model is scored with 5-fold
FINAL_SPLITS = 5
BANDS = [(0, 40, "Low"), (40, 70, "Medium"), (70, 101, "High")]


def make_model(learning_rate: float, depth: int, iterations: int, seed: int = SEED) -> CatBoostClassifier:
    return CatBoostClassifier(
        learning_rate=learning_rate,
        depth=depth,
        iterations=iterations,
        cat_features=CAT_FEATURES,
        random_seed=seed,
        verbose=0,
        thread_count=4,
    )


def training_frame() -> pd.DataFrame:
    return customers_only(clean(load_raw())).reset_index(drop=True)


def score_band(score: int) -> str:
    for lo, hi, name in BANDS:
        if lo <= score < hi:
            return name
    return "High"


# ------------------------------------------------------------------ profile
def super_customer_profile(df: pd.DataFrame, ltv_quantile: float = 0.75) -> dict:
    """Who are the super customers (referred AND upsell AND long tenure) and how do they differ?"""
    df = df.copy()
    if df["referred"].dtype != bool:
        df["referred"] = df["referred"].astype(bool)
    customers = df[df["purchased"] == 1]
    ltv_cut = float(customers["ltv_months"].quantile(ltv_quantile))
    is_super = customers["referred"] & (customers["upsell"] == 1) & (customers["ltv_months"] >= ltv_cut)
    sup, rest = customers[is_super], customers[~is_super]
    total_profit = float(customers["cumulative_profit"].sum())

    def dist(series: pd.Series) -> dict:
        return {str(k): int(v) for k, v in series.value_counts().sort_index().items()}

    early_signal = {
        "share_mid_tier": round(float((sup["budget_tier"] == "Mid").mean()), 4) if len(sup) else None,
        "share_closed_in_2_calls": round(float((sup["calls_to_closed"] <= 2).mean()), 4) if len(sup) else None,
        "rest_share_mid_tier": round(float((rest["budget_tier"] == "Mid").mean()), 4) if len(rest) else None,
        "rest_share_closed_in_2_calls": round(float((rest["calls_to_closed"] <= 2).mean()), 4) if len(rest) else None,
    }
    return {
        "definition": f"referred = Yes AND upsell = 1 AND ltv_months >= {ltv_cut:g} (75th percentile of customers)",
        "ltv_cutoff_months": ltv_cut,
        "n_customers": int(len(customers)),
        "n_super": int(len(sup)),
        "share_of_customers": round(float(len(sup) / len(customers)), 4) if len(customers) else None,
        "share_of_total_profit": round(float(sup["cumulative_profit"].sum() / total_profit), 4) if total_profit else None,
        "avg_profit_super": round(float(sup["cumulative_profit"].mean()), 1) if len(sup) else None,
        "avg_profit_others": round(float(rest["cumulative_profit"].mean()), 1) if len(rest) else None,
        "avg_cac_super": round(float(sup["customer_acquisition_cost"].mean()), 1) if len(sup) else None,
        "avg_cac_others": round(float(rest["customer_acquisition_cost"].mean()), 1) if len(rest) else None,
        "avg_ltv_super": round(float(sup["ltv_months"].mean()), 2) if len(sup) else None,
        "avg_ltv_others": round(float(rest["ltv_months"].mean()), 2) if len(rest) else None,
        "tier_distribution": dist(sup["budget_tier"]),
        "calls_to_closed_distribution": dist(sup["calls_to_closed"]),
        "early_signal": early_signal,
    }


# ------------------------------------------------------------------ training
def train(models_dir: Path = MODELS_DIR) -> dict:
    df = training_frame()
    X = build_features(df, "super", categorical=True)
    y = df["referred"].astype(int)
    assert_no_leakage(list(X.columns), "super")
    baseline = majority_baseline(y)
    print(f"referred rate {y.mean():.3f} | baseline acc {baseline['accuracy']:.3f} | n={len(df)}")

    search: list[dict] = []
    t0 = time.time()
    for lr, depth, iters in itertools.product(GRID["learning_rate"], GRID["depth"], GRID["iterations"]):
        cv = cv_classification(make_model(lr, depth, iters), X, y, n_splits=SEARCH_SPLITS, seed=SEED)
        search.append({"learning_rate": lr, "depth": depth, "iterations": iters, "roc_auc": cv["roc_auc"], "f1": cv["f1"]})
        print(f"lr={lr:<5} depth={depth} iters={iters:<5} AUC {cv['roc_auc']:.4f} F1 {cv['f1']:.4f}")
    best = max(search, key=lambda r: r["roc_auc"])
    best_params = {k: best[k] for k in ("learning_rate", "depth", "iterations")}
    print(f"search done in {time.time() - t0:.0f}s | best {best_params} AUC {best['roc_auc']:.4f}")

    final_cv = cv_classification(make_model(**best_params), X, y, n_splits=FINAL_SPLITS, seed=SEED)
    model = make_model(**best_params)
    model.fit(X, y)
    joblib.dump(model, models_dir / "super.joblib")
    imps = importances(model, list(X.columns))

    scores = np.rint(100 * model.predict_proba(X)[:, 1]).astype(int)
    score_stats = {
        "mean": round(float(scores.mean()), 2),
        "std": round(float(scores.std()), 2),
        "min": int(scores.min()),
        "max": int(scores.max()),
        "band_counts": {name: int(((scores >= lo) & (scores < hi)).sum()) for lo, hi, name in BANDS},
    }
    profile = super_customer_profile(clean(load_raw()))
    payload = {
        "trained_at": utc_now(),
        "target": "referred",
        "training_policy": "customers only (purchased = 1); budget_tier as a native CatBoost categorical",
        "n_train": int(len(df)),
        "features": list(X.columns),
        "cat_features": CAT_FEATURES,
        "baseline": baseline,
        "search": search,
        "search_splits": SEARCH_SPLITS,
        "best_params": best_params,
        "cv": final_cv,
        "importances": imps,
        "score_bands": [{"min": lo, "max": hi - 1, "band": name} for lo, hi, name in BANDS],
        "score_stats_train": score_stats,
        "profile": profile,
    }
    save_metrics("super", payload, models_dir)
    print(f"final 5-fold AUC {final_cv['roc_auc']:.4f} F1 {final_cv['f1']:.4f} | scores mean {score_stats['mean']} std {score_stats['std']}")
    return payload


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--models-dir", type=Path, default=MODELS_DIR)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    args.models_dir.mkdir(parents=True, exist_ok=True)
    result = train(args.models_dir)
    if args.json:
        print(json.dumps(result, indent=2))
