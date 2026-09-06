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


class LtvPrediction(BaseModel):
    months: float
    by_model: dict[str, float]
    served: str
    rmse_months: float | None = None


class UpsellPrediction(BaseModel):
    probability: float
    flag: bool
    rule_flag: bool | None = None
    variant: str
    model: str
    rule: str
    roc_auc: float | None = None


class ModelsInfo(BaseModel):
    metrics: dict
