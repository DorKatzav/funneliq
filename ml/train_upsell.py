"""P3 — predict upsell (bought additional services) with three gradient-boosting classifiers.

    python -m ml.train_upsell

Two feature variants:
  * early  — FUNNEL only (what is known the day the customer signs)
  * tenure — FUNNEL + ltv_months (an existing customer's known tenure; the only sanctioned
             outcome-as-feature, see ml/features.ALLOWED_OUTCOMES and docs/REPORT.md §P3)

Also: class-balance check + scale_pos_weight decision, majority-class baseline, and the
brief's business rule ("LTV > X and CAC < Y") tuned and scored on the same folds as the models.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from catboost import CatBoostClassifier
from lightgbm import LGBMClassifier
from sklearn.model_selection import StratifiedKFold
from xgboost import XGBClassifier

from ml.data import clean, customers_only, load_raw
from ml.evaluate import classification_scores, cv_classification, importances, majority_baseline, oof_proba
from ml.features import assert_no_leakage, build_features
from ml.registry import MODELS_DIR, save_metrics, utc_now

SEED = 42
VARIANTS = ("early", "tenure")
LTV_GRID = list(range(6, 42, 3))  # months
CAC_GRID = list(range(500, 3501, 250))  # ₪


def make_models(seed: int = SEED, scale_pos_weight: float = 1.0) -> dict[str, object]:
    return {
        "xgboost": XGBClassifier(
            n_estimators=400,
            learning_rate=0.05,
            max_depth=4,
            subsample=0.9,
            colsample_bytree=0.9,
            scale_pos_weight=scale_pos_weight,
            eval_metric="logloss",
            random_state=seed,
            n_jobs=4,
        ),
        "lightgbm": LGBMClassifier(
            n_estimators=400,
            learning_rate=0.05,
            num_leaves=15,
            subsample=0.9,
            subsample_freq=1,
            colsample_bytree=0.9,
            scale_pos_weight=scale_pos_weight,
            random_state=seed,
            verbose=-1,
            n_jobs=4,
            importance_type="gain",
        ),
        "catboost": CatBoostClassifier(
            iterations=600,
            learning_rate=0.05,
            depth=4,
            scale_pos_weight=scale_pos_weight,
            random_seed=seed,
            verbose=0,
            thread_count=4,
        ),
    }


def training_frame() -> pd.DataFrame:
    df = customers_only(clean(load_raw()))
    return df[df["ltv_months"].notna()].reset_index(drop=True)  # tenure variant needs it; same rows for both


# ------------------------------------------------------------------ business rule
def rule_predict(ltv: pd.Series, cac: pd.Series, ltv_threshold: float, cac_threshold: float) -> np.ndarray:
    return ((ltv > ltv_threshold) & (cac < cac_threshold)).astype(int).to_numpy()


def best_rule(df: pd.DataFrame, y: pd.Series) -> tuple[float, float, float]:
    """Grid-search the two thresholds for the best F1 on the given rows."""
    best = (LTV_GRID[0], CAC_GRID[0], -1.0)
    for lt in LTV_GRID:
        for ct in CAC_GRID:
            pred = rule_predict(df["ltv_months"], df["customer_acquisition_cost"], lt, ct)
            f1 = classification_scores(y, pred)["f1"]
            if f1 > best[2]:
                best = (lt, ct, f1)
    return best


def cv_rule(df: pd.DataFrame, y: pd.Series, n_splits: int = 5, seed: int = SEED) -> tuple[dict, np.ndarray]:
    """Tune thresholds on the train folds, score on the test folds (same folds as the models)."""
    skf = StratifiedKFold(n_splits=n_splits, shuffle=True, random_state=seed)
    oof = np.zeros(len(df), dtype=int)
    folds = []
    for tr, te in skf.split(df, y):
        lt, ct, _ = best_rule(df.iloc[tr], y.iloc[tr])
        oof[te] = rule_predict(df.iloc[te]["ltv_months"], df.iloc[te]["customer_acquisition_cost"], lt, ct)
        folds.append(classification_scores(y.iloc[te], oof[te]))
    summary = {k: round(float(np.mean([f[k] for f in folds])), 4) for k in ("accuracy", "precision", "recall", "f1")}
    return summary, oof


def by_tier_comparison(df: pd.DataFrame, y: pd.Series, model_pred: np.ndarray, rule_pred: np.ndarray) -> list[dict]:
    rows = []
    for tier in ("Low", "Mid", "High"):
        m = (df["budget_tier"] == tier).to_numpy()
        if m.sum() == 0:
            continue
        rows.append(
            {
                "tier": tier,
                "n": int(m.sum()),
                "positive_rate": round(float(y[m].mean()), 4),
                "model": classification_scores(y[m], model_pred[m]),
                "rule": classification_scores(y[m], rule_pred[m]),
            }
        )
    return rows


# ------------------------------------------------------------------ main
def train(models_dir: Path = MODELS_DIR, n_splits: int = 5) -> dict:
    df = training_frame()
    y = df["upsell"].astype(int)
    balance = {str(k): int(v) for k, v in y.value_counts().sort_index().items()}
    pos_share = float(y.mean())
    baseline = majority_baseline(y)
    print(f"class balance: {balance} (positive share {pos_share:.3f}) | baseline acc {baseline['accuracy']:.3f}")

    # --- imbalance decision: does scale_pos_weight help F1 on the early variant? --------------
    X_early = build_features(df, "upsell_early")
    neg_pos = (1 - pos_share) / pos_share
    plain = cv_classification(make_models()["xgboost"], X_early, y, n_splits=n_splits, seed=SEED)
    weighted = cv_classification(make_models(scale_pos_weight=neg_pos)["xgboost"], X_early, y, n_splits=n_splits, seed=SEED)
    use_weight = weighted["f1"] > plain["f1"] + 0.005
    spw = neg_pos if use_weight else 1.0
    imbalance = {
        "positive_share": round(pos_share, 4),
        "neg_pos_ratio": round(neg_pos, 4),
        "xgboost_plain": plain,
        "xgboost_weighted": weighted,
        "use_scale_pos_weight": bool(use_weight),
        "scale_pos_weight_used": round(spw, 4),
        "reason": (
            "classes are close to balanced; weighting is kept only if it improves F1 by > 0.005 on the early variant"
        ),
    }
    print(f"scale_pos_weight {neg_pos:.3f}: F1 {plain['f1']:.3f} plain vs {weighted['f1']:.3f} weighted -> use={use_weight}")

    # --- three classifiers × two variants ----------------------------------------------------
    cv: dict[str, dict] = {}
    imps: dict[str, dict] = {}
    oof: dict[str, np.ndarray] = {}
    for variant in VARIANTS:
        task = f"upsell_{variant}"
        X = build_features(df, task)
        assert_no_leakage(list(X.columns), task)
        cv[variant], imps[variant] = {}, {}
        for name, model in make_models(scale_pos_weight=spw).items():
            cv[variant][name] = cv_classification(model, X, y, n_splits=n_splits, seed=SEED)
            model.fit(X, y)
            joblib.dump(model, models_dir / f"upsell_{variant}_{name}.joblib")
            imps[variant][name] = importances(model, list(X.columns))
            m = cv[variant][name]
            print(f"{variant:6s} {name:9s} acc {m['accuracy']:.3f} P {m['precision']:.3f} R {m['recall']:.3f} F1 {m['f1']:.3f} AUC {m['roc_auc']:.3f}")
        best_name = max(cv[variant], key=lambda k: cv[variant][k]["roc_auc"])
        oof[variant] = oof_proba(make_models(scale_pos_weight=spw)[best_name], X, y, n_splits=n_splits, seed=SEED)
        cv[variant]["best"] = best_name

    # --- variant to serve: best ROC-AUC; the tenure allowance is justified in REPORT.md §P3 ------
    best_auc = {v: cv[v][cv[v]["best"]]["roc_auc"] for v in VARIANTS}
    variant_served = max(best_auc, key=best_auc.get)
    model_served = cv[variant_served]["best"]

    # --- the brief's business rule vs the served model, on the same folds ----------------------
    rule_cv, rule_oof = cv_rule(df, y, n_splits=n_splits, seed=SEED)
    lt, ct, f1_all = best_rule(df, y)
    model_oof_pred = (oof[variant_served] >= 0.5).astype(int)
    business_rule = {
        "definition": "flag for outreach if ltv_months > ltv_threshold and customer_acquisition_cost < cac_threshold",
        "ltv_threshold": lt,
        "cac_threshold": ct,
        "f1_on_all_rows": f1_all,
        "cv": rule_cv,
        "model_cv_oof": classification_scores(y, model_oof_pred, oof[variant_served]),
        "by_tier": by_tier_comparison(df, y, model_oof_pred, rule_oof),
        "positives_flagged": {"rule": int(rule_oof.sum()), "model": int(model_oof_pred.sum()), "actual": int(y.sum())},
    }
    print(f"rule: LTV > {lt} and CAC < {ct} -> CV F1 {rule_cv['f1']:.3f} | model OOF F1 {business_rule['model_cv_oof']['f1']:.3f}")

    payload = {
        "trained_at": utc_now(),
        "target": "upsell",
        "training_policy": "customers only (purchased = 1); rows without ltv_months dropped so both variants share rows",
        "n_train": int(len(df)),
        "class_balance": balance,
        "baseline": baseline,
        "imbalance": imbalance,
        "variants": {v: {"features": list(build_features(df.head(1), f"upsell_{v}").columns)} for v in VARIANTS},
        "variant_served": variant_served,
        "model_served": model_served,
        "cv": cv,
        "importances": imps,
        "business_rule": business_rule,
    }
    save_metrics("upsell", payload, models_dir)
    print(f"served: {variant_served}/{model_served} | wrote {models_dir / 'metrics.json'}")
    return payload


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--models-dir", type=Path, default=MODELS_DIR)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    args.models_dir.mkdir(parents=True, exist_ok=True)
    result = train(args.models_dir)
    if args.json:
        print(json.dumps(result, indent=2))
