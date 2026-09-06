import numpy as np
import pandas as pd
import pytest
from sklearn.ensemble import RandomForestClassifier, RandomForestRegressor
from sklearn.linear_model import LinearRegression

from ml.evaluate import cv_classification, cv_regression, importances, majority_baseline


def test_majority_baseline_on_imbalanced_labels():
    b = majority_baseline(pd.Series([0, 0, 0, 1]))
    assert b["majority_class"] == 0
    assert b["accuracy"] == 0.75
    assert b["recall"] == 0.0 and b["f1"] == 0.0 and b["roc_auc"] == 0.5


def test_cv_regression_recovers_a_linear_signal():
    rng = np.random.default_rng(0)
    X = pd.DataFrame({"a": rng.normal(size=200), "b": rng.normal(size=200)})
    y = 3 * X["a"] - 2 * X["b"] + rng.normal(scale=0.1, size=200)
    res = cv_regression(LinearRegression(), X, y, n_splits=4)
    assert res["n_splits"] == 4 and res["n_rows"] == 200
    assert res["r2_mean"] > 0.95
    assert res["rmse_mean"] < 0.2


def test_cv_classification_reports_all_metrics():
    rng = np.random.default_rng(1)
    X = pd.DataFrame({"a": rng.normal(size=300)})
    y = (X["a"] > 0).astype(int)
    res = cv_classification(RandomForestClassifier(n_estimators=20, random_state=0), X, y, n_splits=3)
    for k in ("accuracy", "precision", "recall", "f1", "roc_auc"):
        assert 0 <= res[k] <= 1 and f"{k}_std" in res
    assert res["roc_auc"] > 0.9


def test_importances_normalised_and_sorted():
    rng = np.random.default_rng(2)
    X = pd.DataFrame({"signal": rng.normal(size=300), "noise": rng.normal(size=300)})
    y = X["signal"] * 5 + rng.normal(scale=0.1, size=300)
    model = RandomForestRegressor(n_estimators=30, random_state=0).fit(X, y)
    imp = importances(model, ["signal", "noise"])
    assert list(imp) == ["signal", "noise"]
    assert sum(imp.values()) == pytest.approx(1.0, abs=1e-4)
    assert imp["signal"] > 0.9


def test_importances_length_mismatch_fails():
    X = pd.DataFrame({"a": [1, 2, 3]})
    model = RandomForestRegressor(n_estimators=5, random_state=0).fit(X, [1, 2, 3])
    with pytest.raises(ValueError):
        importances(model, ["a", "b"])
