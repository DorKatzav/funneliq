"""Request / response models for the prediction and simulation endpoints."""

from __future__ import annotations

from pydantic import BaseModel, Field, model_validator


class CustomerInput(BaseModel):
    """The 14 acquisition-time funnel fields (exactly ml.features.FUNNEL_RAW), plus optional tenure."""

    ad_budget: float = Field(..., ge=0, description="Monthly ad spend of the campaign (₪)")
    num_leads: int = Field(..., ge=0)
    leads_answered: int = Field(..., ge=0)
    leads_not_answered: int = Field(..., ge=0)
    followup_1: int = Field(..., ge=0)
    followup_2: int = Field(..., ge=0)
    followup_3: int = Field(..., ge=0)
    followup_4: int = Field(..., ge=0)
    followup_5: int = Field(..., ge=0)
    not_closed: int = Field(..., ge=0)
    closed: int = Field(..., ge=0)
    calls_to_closed: int = Field(..., ge=0, description="Calls it took to close this customer")
    calls_to_not_closed: int = Field(..., ge=0)
    customer_acquisition_cost: float = Field(..., ge=0)
    ltv_months: float | None = Field(
        None, ge=0, description="Known tenure — only used by the upsell 'tenure' variant"
    )

    @model_validator(mode="after")
    def _funnel_shape(self) -> CustomerInput:
        if self.leads_answered + self.leads_not_answered != self.num_leads:
            raise ValueError("leads_answered + leads_not_answered must equal num_leads")
        stages = [self.followup_1, self.followup_2, self.followup_3, self.followup_4, self.followup_5]
        if any(a < b for a, b in zip(stages, stages[1:], strict=False)):
            raise ValueError("follow-up counts must be non-increasing (followup_1 >= ... >= followup_5)")
        if self.followup_1 > self.leads_answered:
            raise ValueError("followup_1 cannot exceed leads_answered")
        if self.closed + self.not_closed != self.followup_5:
            raise ValueError("closed + not_closed must equal followup_5")
        return self

    def funnel_dict(self) -> dict:
        return self.model_dump()


class Novelty(BaseModel):
    """How unusual the input is compared with the training customers (M8 'far from training data' warning)."""

    max_z: float | None = None
    feature: str | None = None
    outside_training_range: list[str] = []
    flag: bool = False
    note: str = ""


class LtvPrediction(BaseModel):
    months: float
    by_model: dict[str, float]
    served: str
    rmse_months: float | None = None
    novelty: Novelty | None = None


class UpsellPrediction(BaseModel):
    probability: float
    flag: bool
    rule_flag: bool | None = None
    variant: str
    model: str
    rule: str
    roc_auc: float | None = None


class SuperScore(BaseModel):
    score: int
    probability: float
    band: str
    roc_auc: float | None = None


class ModelsInfo(BaseModel):
    metrics: dict


class AllocationItem(BaseModel):
    budget: int = Field(..., gt=0, description="One of the budget levels seen in the data")
    count: int = Field(..., ge=1, description="How many campaigns at this budget")


class BudgetAllocation(BaseModel):
    allocation: list[AllocationItem] = Field(..., min_length=1)
    total: int = Field(50_000, gt=0)


class CampaignLine(BaseModel):
    budget: int
    count: int
    spend: int
    profile_n: int
    predicted_profit_per_campaign: float
    empirical_profit_per_campaign: float | None = None
    expected_profit: float
    empirical_profit: float | None = None


class SimulationResult(BaseModel):
    total_budget: int
    n_campaigns: int
    expected_profit: float
    empirical_profit: float | None = None
    roi_model: float
    roi_empirical: float | None = None
    per_campaign: list[CampaignLine]
    served_model: str | None = None
    rmse_per_campaign: float | None = None
