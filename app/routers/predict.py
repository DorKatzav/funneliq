"""Prediction endpoints — models from ml/registry.py, every call logged to prediction_log."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from supabase import Client

from app.auth import UserContext, get_current_user
from app.db import get_user_client
from app.schemas import CustomerInput, LtvPrediction, SuperScore, UpsellPrediction
from ml.registry import ModelRegistry

log = logging.getLogger("funneliq.predict")
router = APIRouter(prefix="/api", tags=["predict"])


def get_registry(request: Request) -> ModelRegistry:
    registry = getattr(request.app.state, "registry", None)
    if registry is None or not registry.loaded:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "models are not loaded on this server")
    return registry


def log_prediction(client: Client, model: str, payload: dict, output: dict) -> None:
    """Best effort: a logging failure must never fail the prediction."""
    try:
        client.table("prediction_log").insert({"model": model, "input": payload, "output": output}).execute()
    except Exception as exc:  # noqa: BLE001
        log.warning("prediction_log insert failed: %s", exc)


@router.post("/predict/ltv", response_model=LtvPrediction)
def predict_ltv(
    customer: CustomerInput,
    registry: ModelRegistry = Depends(get_registry),
    client: Client = Depends(get_user_client),
) -> LtvPrediction:
    """P2: expected customer lifetime in months from acquisition-time funnel data."""
    result = registry.predict_ltv(customer.funnel_dict())
    served_cv = registry.metrics.get("ltv", {}).get("cv", {}).get(result["served"], {})
    result["rmse_months"] = served_cv.get("rmse_mean")
    result["novelty"] = registry.novelty(customer.funnel_dict())
    log_prediction(client, "ltv", customer.model_dump(), result)
    return LtvPrediction(**result)


@router.post("/predict/upsell", response_model=UpsellPrediction)
def predict_upsell(
    customer: CustomerInput,
    registry: ModelRegistry = Depends(get_registry),
    client: Client = Depends(get_user_client),
) -> UpsellPrediction:
    """P3: probability the customer buys additional services, plus the brief's business-rule verdict."""
    result = registry.predict_upsell(customer.funnel_dict())
    cv = registry.metrics.get("upsell", {}).get("cv", {}).get(result["variant"], {}).get(result["model"], {})
    result["roc_auc"] = cv.get("roc_auc")
    log_prediction(client, "upsell", customer.model_dump(), result)
    return UpsellPrediction(**result)


@router.post("/predict/super-score", response_model=SuperScore)
def predict_super_score(
    customer: CustomerInput,
    registry: ModelRegistry = Depends(get_registry),
    client: Client = Depends(get_user_client),
) -> SuperScore:
    """P4: 0–100 likelihood of becoming a super customer (stays, spends, refers)."""
    result = registry.super_score(customer.funnel_dict())
    result["roc_auc"] = registry.metrics.get("super", {}).get("cv", {}).get("roc_auc")
    log_prediction(client, "super", customer.model_dump(), result)
    return SuperScore(**result)


@router.get("/models")
def models_info(
    registry: ModelRegistry = Depends(get_registry), _: UserContext = Depends(get_current_user)
) -> dict:
    """Training metadata: CV metrics, importances, ablations, form defaults (models/metrics.json)."""
    return {"loaded": registry.loaded, "metrics": registry.metrics}


@router.get("/predictions")
def my_predictions(
    limit: int = Query(20, ge=1, le=100),
    client: Client = Depends(get_user_client),
) -> dict:
    """The signed-in user's recent predictions (RLS: only their own rows)."""
    res = (
        client.table("prediction_log")
        .select("id, model, input, output, created_at")
        .order("created_at", desc=True)
        .limit(limit)
        .execute()
    )
    return {"rows": res.data, "limit": limit}
