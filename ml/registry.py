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
UPSELL_VARIANTS = ("early", "tenure")


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
    def __init__(
        self,
        models_dir: Path,
        metrics: dict,
        ltv_models: dict[str, object],
        upsell_models: dict[str, object] | None = None,
    ):
        self.models_dir = models_dir
        self.metrics = metrics
        self.ltv_models = ltv_models
        self.upsell_models = upsell_models or {}  # key: "<variant>_<name>"

    @classmethod
    def load(cls, models_dir: Path = MODELS_DIR) -> ModelRegistry:
        models_dir = Path(models_dir)
        metrics = load_metrics(models_dir)
        ltv_models: dict[str, object] = {}
        for name in LTV_MODELS:
            path = models_dir / f"ltv_{name}.joblib"
            if path.exists():
                ltv_models[name] = joblib.load(path)
        upsell_models: dict[str, object] = {}
        for variant in UPSELL_VARIANTS:
            for name in LTV_MODELS:
                path = models_dir / f"upsell_{variant}_{name}.joblib"
                if path.exists():
                    upsell_models[f"{variant}_{name}"] = joblib.load(path)
        return cls(models_dir, metrics, ltv_models, upsell_models)

    @property
    def loaded(self) -> list[str]:
        return [f"ltv_{n}" for n in self.ltv_models] + [f"upsell_{k}" for k in self.upsell_models]

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

    # ------------------------------------------------------------------ P3
    def upsell_config(self) -> dict:
        m = self.metrics.get("upsell", {})
        return {
            "variant": m.get("variant_served", "early"),
            "model": m.get("model_served", "catboost"),
            "ltv_threshold": m.get("business_rule", {}).get("ltv_threshold"),
            "cac_threshold": m.get("business_rule", {}).get("cac_threshold"),
        }

    def predict_upsell(self, customer: dict) -> dict:
        """Probability of buying more. The served variant may need ltv_months (tenure); if it is
        missing, fall back to the early variant and say so."""
        if not self.upsell_models:
            raise RuntimeError("upsell models are not loaded")
        cfg = self.upsell_config()
        variant, name = cfg["variant"], cfg["model"]
        has_tenure = customer.get("ltv_months") is not None
        if variant == "tenure" and not has_tenure:
            variant = "early"
        key = f"{variant}_{name}"
        if key not in self.upsell_models:
            key = next(iter(self.upsell_models))
            variant, name = key.split("_", 1)
        X = build_features(customer_frame(customer), f"upsell_{variant}")
        proba = float(self.upsell_models[key].predict_proba(X)[0][1])
        rule_flag = None
        if has_tenure and cfg["ltv_threshold"] is not None:
            rule_flag = bool(
                customer["ltv_months"] > cfg["ltv_threshold"]
                and customer["customer_acquisition_cost"] < cfg["cac_threshold"]
            )
        return {
            "probability": round(proba, 4),
            "flag": proba >= 0.5,
            "rule_flag": rule_flag,
            "variant": variant,
            "model": name,
            "rule": (
                f"ltv_months > {cfg['ltv_threshold']} and customer_acquisition_cost < {cfg['cac_threshold']}"
            ),
        }
