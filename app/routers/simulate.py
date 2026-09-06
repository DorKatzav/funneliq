"""Budget simulator endpoints — the profit model on typical campaign profiles, no database needed."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from app.auth import UserContext, get_current_user
from app.routers.predict import get_registry
from app.schemas import BudgetAllocation, SimulationResult
from ml.registry import ModelRegistry
from ml.simulator import rank_presets, simulate

router = APIRouter(prefix="/api/simulate", tags=["simulate"])


def _ready(registry: ModelRegistry) -> ModelRegistry:
    if registry.profit_model is None or registry.profiles is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "profit model or profiles are not loaded")
    return registry


@router.post("/budget", response_model=SimulationResult)
def simulate_budget(
    body: BudgetAllocation,
    registry: ModelRegistry = Depends(get_registry),
    _user: UserContext = Depends(get_current_user),
) -> SimulationResult:
    """P6: expected profit of a custom split of the monthly budget across campaign sizes."""
    try:
        result = simulate([a.model_dump() for a in body.allocation], _ready(registry), body.total)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    return SimulationResult(**result)


@router.get("/presets")
def presets(
    registry: ModelRegistry = Depends(get_registry),
    _user: UserContext = Depends(get_current_user),
) -> dict:
    """P6: the brief's strategies (plus 5 × ₪10,000) ranked by expected profit, plus the profit curve."""
    return rank_presets(_ready(registry))
