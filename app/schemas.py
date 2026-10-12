from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class EmiRequest(BaseModel):
    loan_amount: float = Field(gt=0, le=100_000_000)
    annual_interest_rate: float | None = Field(default=None, ge=0, le=100)
    tenure_months: int = Field(gt=0, le=600)


class EmiResponse(BaseModel):
    loan_amount: float
    annual_interest_rate: float
    interest_rate_assumed: bool
    tenure_months: int
    monthly_emi: float
    total_repayment: float
    total_interest: float


class EligibilityRequest(BaseModel):
    monthly_salary: float = Field(gt=0, le=100_000_000)
    existing_monthly_emi: float = Field(ge=0, le=100_000_000)
    proposed_monthly_emi: float = Field(ge=0, le=100_000_000)
    loan_amount: float = Field(gt=0, le=100_000_000)
    tenure_months: int = Field(gt=0, le=600)


class EligibilityResponse(BaseModel):
    eligible: bool
    monthly_income: float
    existing_emi: float
    proposed_emi: float
    total_monthly_emi: float
    emi_to_income_ratio: float
    maximum_emi_to_income_ratio: float
    reasons: list[str]
    decision_type: str


class AccountResponse(BaseModel):
    masked_account_number: str
    account_type: str
    account_status: str


class PrepareApplicationRequest(BaseModel):
    loan_amount: float = Field(gt=0, le=100_000_000)
    tenure_months: int = Field(gt=0, le=600)
    annual_interest_rate: float = Field(ge=0, le=100)
    monthly_salary: float = Field(gt=0, le=100_000_000)
    existing_monthly_emi: float = Field(ge=0, le=100_000_000)
    calculated_emi: float = Field(gt=0)
    eligibility_result: bool


class ApplicationResponse(BaseModel):
    application_id: str
    status: str
    loan_amount: float
    tenure_months: int
    annual_interest_rate: float
    monthly_salary: float
    existing_monthly_emi: float
    calculated_emi: float
    eligibility: dict[str, Any]
    confirmation_token: str | None = None
    confirmation_phrase: str | None = None
    confirmation_expires_at: str | None = None


class ConfirmApplicationRequest(BaseModel):
    confirmation_token: str = Field(min_length=32, max_length=256)
    confirmation_phrase: str = Field(min_length=10, max_length=256)
    loan_amount: float = Field(gt=0, le=100_000_000)
    tenure_months: int = Field(gt=0, le=600)
    annual_interest_rate: float = Field(ge=0, le=100)
    calculated_emi: float = Field(gt=0)


class ApplicationStatusResponse(BaseModel):
    application_id: str
    status: str
    loan_amount: float
    tenure_months: int
    annual_interest_rate: float
    calculated_emi: float
    eligibility: dict[str, Any]


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=8000)


class ConfirmationChallenge(BaseModel):
    application_id: str
    confirmation_token: str
    confirmation_phrase: str
    loan_amount: float
    tenure_months: int
    annual_interest_rate: float
    calculated_emi: float
    expires_at: str


class ChatResponse(BaseModel):
    reply: str
    pending_confirmation: ConfirmationChallenge | None = None
