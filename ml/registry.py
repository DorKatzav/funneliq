"""Model registry: loads the committed artifacts in models/ and serves predictions.

Trainers write `models/<name>.joblib` and merge their section into `models/metrics.json`
via `save_metrics`. The API loads everything once at startup through `ModelRegistry.load`.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import joblib
import pandas as pd

from ml.features import FUNNEL_RAW, build_features

MODELS_DIR = Path(__file__).resolve().parent.parent / "models"
METRICS_FILE = "metrics.json"

LTV_MODELS = ("xgboost", "lightgbm", "catboost")


def utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def load_metrics(models_dir: Path = MODELS_DIR) -> dict:
    path = models_dir / METRICS_FILE
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def save_metrics(section: str, payload: dict, models_dir: Path = MODELS_DIR) -> dict:
    """Merge one task's metrics into models/metrics.json and return the full document."""
    models_dir.mkdir(parents=True, exist_ok=True)
    doc = load_metrics(models_dir)
    doc[section] = payload
    text = json.dumps(doc, indent=2, ensure_ascii=False) + "\n"
    (models_dir / METRICS_FILE).write_text(text, encoding="utf-8")
    return doc


def customer_frame(customer: dict) -> pd.DataFrame:
    """One-row frame from the API's CustomerInput dict (extra keys such as ltv_months are kept)."""
    missing = [k for k in FUNNEL_RAW if k not in customer]
    if missing:
        raise ValueError(f"customer is missing fields: {missing}")
    return pd.DataFrame([customer])


class ModelRegistry:
    def __init__(self, models_dir: Path, metrics: dict, ltv_models: dict[str, object]):
        self.models_dir = models_dir
        self.metrics = metrics
        self.ltv_models = ltv_models

    @classmethod
    def load(cls, models_dir: Path = MODELS_DIR) -> ModelRegistry:
        models_dir = Path(models_dir)
        metrics = load_metrics(models_dir)
        ltv_models: dict[str, object] = {}
        for name in LTV_MODELS:
            path = models_dir / f"ltv_{name}.joblib"
            if path.exists():
                ltv_models[name] = joblib.load(path)
        return cls(models_dir, metrics, ltv_models)

    @property
    def loaded(self) -> list[str]:
        return [f"ltv_{n}" for n in self.ltv_models]

    # ------------------------------------------------------------------ P2
    def predict_ltv(self, customer: dict) -> dict:
        if not self.ltv_models:
            raise RuntimeError("LTV models are not loaded")
        X = build_features(customer_frame(customer), "ltv")
        by_model = {name: round(max(float(m.predict(X)[0]), 0.0), 2) for name, m in self.ltv_models.items()}
        served = self.metrics.get("ltv", {}).get("served", "ensemble")
        if served == "ensemble" or served not in by_model:
            months = sum(by_model.values()) / len(by_model)
            served = "ensemble"
        else:
            months = by_model[served]
        return {"months": round(months, 1), "by_model": by_model, "served": served}
