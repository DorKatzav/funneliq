"""Shared evaluation helpers: cross-validation, baselines, feature importances.

All trainers use these so the numbers in models/metrics.json are comparable
across models and across milestones.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.base import clone
from sklearn.metrics import (
    accuracy_score,
    f1_score,
    mean_squared_error,
    precision_score,
    r2_score,
    recall_score,
    roc_auc_score,
)
from sklearn.model_selection import KFold, StratifiedKFold


def _mean_std(values: list[float]) -> tuple[float, float]:
    arr = np.asarray(values, dtype=float)
    return float(arr.mean()), float(arr.std(ddof=0))


def cv_regression(model, X: pd.DataFrame, y: pd.Series, n_splits: int = 5, seed: int = 42) -> dict:
    """K-fold CV for a regressor -> RMSE and R² (mean ± std over folds)."""
    kf = KFold(n_splits=n_splits, shuffle=True, random_state=seed)
    rmse, r2 = [], []
    for train_idx, test_idx in kf.split(X):
        est = clone(model)
        est.fit(X.iloc[train_idx], y.iloc[train_idx])
        pred = est.predict(X.iloc[test_idx])
        rmse.append(float(np.sqrt(mean_squared_error(y.iloc[test_idx], pred))))
        r2.append(float(r2_score(y.iloc[test_idx], pred)))
    rmse_m, rmse_s = _mean_std(rmse)
    r2_m, r2_s = _mean_std(r2)
    return {
        "rmse_mean": round(rmse_m, 4),
        "rmse_std": round(rmse_s, 4),
        "r2_mean": round(r2_m, 4),
        "r2_std": round(r2_s, 4),
        "n_splits": n_splits,
        "n_rows": int(len(X)),
    }


def cv_classification(model, X: pd.DataFrame, y: pd.Series, n_splits: int = 5, seed: int = 42) -> dict:
    """Stratified K-fold CV for a binary classifier -> accuracy, precision, recall, F1, ROC-AUC."""
    skf = StratifiedKFold(n_splits=n_splits, shuffle=True, random_state=seed)
    scores: dict[str, list[float]] = {k: [] for k in ("accuracy", "precision", "recall", "f1", "roc_auc")}
    for train_idx, test_idx in skf.split(X, y):
        est = clone(model)
        est.fit(X.iloc[train_idx], y.iloc[train_idx])
        proba = est.predict_proba(X.iloc[test_idx])[:, 1]
        pred = (proba >= 0.5).astype(int)
        yt = y.iloc[test_idx]
        scores["accuracy"].append(accuracy_score(yt, pred))
        scores["precision"].append(precision_score(yt, pred, zero_division=0))
        scores["recall"].append(recall_score(yt, pred, zero_division=0))
        scores["f1"].append(f1_score(yt, pred, zero_division=0))
        scores["roc_auc"].append(roc_auc_score(yt, proba))
    out: dict = {"n_splits": n_splits, "n_rows": int(len(X))}
    for k, vals in scores.items():
        m, s = _mean_std(vals)
        out[k] = round(m, 4)
        out[f"{k}_std"] = round(s, 4)
    return out


def majority_baseline(y: pd.Series) -> dict:
    """Always predict the majority class. ROC-AUC of a constant predictor is 0.5 by definition."""
    y = pd.Series(y).astype(int)
    majority = int(y.mode().iloc[0])
    pred = pd.Series(majority, index=y.index)
    return {
        "majority_class": majority,
        "accuracy": round(float(accuracy_score(y, pred)), 4),
        "precision": round(float(precision_score(y, pred, zero_division=0)), 4),
        "recall": round(float(recall_score(y, pred, zero_division=0)), 4),
        "f1": round(float(f1_score(y, pred, zero_division=0)), 4),
        "roc_auc": 0.5,
    }


def importances(model, feature_names: list[str]) -> dict[str, float]:
    """Importances normalised to sum to 1, sorted descending (xgboost, lightgbm, catboost, sklearn)."""
    if hasattr(model, "get_feature_importance"):  # CatBoost
        raw = np.asarray(model.get_feature_importance(), dtype=float)
    elif hasattr(model, "feature_importances_"):  # XGBoost / LightGBM / sklearn
        raw = np.asarray(model.feature_importances_, dtype=float)
    else:
        raise TypeError(f"{type(model).__name__} exposes no feature importances")
    if len(raw) != len(feature_names):
        raise ValueError(f"{len(raw)} importances for {len(feature_names)} features")
    total = raw.sum()
    norm = raw / total if total > 0 else np.full_like(raw, 1.0 / len(raw))
    pairs = sorted(zip(feature_names, norm, strict=True), key=lambda kv: kv[1], reverse=True)
    return {name: round(float(v), 5) for name, v in pairs}


def oof_proba(model, X: pd.DataFrame, y: pd.Series, n_splits: int = 5, seed: int = 42) -> np.ndarray:
    """Out-of-fold positive-class probabilities (stratified) — for fair model-vs-rule comparisons."""
    skf = StratifiedKFold(n_splits=n_splits, shuffle=True, random_state=seed)
    out = np.zeros(len(X), dtype=float)
    for train_idx, test_idx in skf.split(X, y):
        est = clone(model)
        est.fit(X.iloc[train_idx], y.iloc[train_idx])
        out[test_idx] = est.predict_proba(X.iloc[test_idx])[:, 1]
    return out


def classification_scores(y_true, y_pred, proba=None) -> dict:
    """Accuracy / precision / recall / F1 (and ROC-AUC when probabilities are given) for one split."""
    out = {
        "accuracy": round(float(accuracy_score(y_true, y_pred)), 4),
        "precision": round(float(precision_score(y_true, y_pred, zero_division=0)), 4),
        "recall": round(float(recall_score(y_true, y_pred, zero_division=0)), 4),
        "f1": round(float(f1_score(y_true, y_pred, zero_division=0)), 4),
    }
    if proba is not None and len(set(np.asarray(y_true).tolist())) > 1:
        out["roc_auc"] = round(float(roc_auc_score(y_true, proba)), 4)
    return out
