from __future__ import annotations

import uuid
from typing import Any

import httpx
from langchain_core.tools import tool

from app import config
from app.auth import (
    authenticated_customer,
    chat_artifacts,
    trusted_confirmation,
)


async def _post(
    path: str,
    payload: dict[str, Any],
    extra_headers: dict[str, str] | None = None,
) -> dict[str, Any]:
    customer_id = authenticated_customer.get()
    headers = {"X-Mock-Customer-ID": customer_id} if customer_id else {}
    if extra_headers:
        headers.update(extra_headers)
    async with httpx.AsyncClient(base_url=config.API_BASE_URL, timeout=15) as client:
        response = await client.post(path, json=payload, headers=headers)
        response.raise_for_status()
        return response.json()


async def _get(path: str) -> dict[str, Any]:
    customer_id = authenticated_customer.get()
    headers = {"X-Mock-Customer-ID": customer_id} if customer_id else {}
    async with httpx.AsyncClient(base_url=config.API_BASE_URL, timeout=15) as client:
        response = await client.get(path, headers=headers)
        response.raise_for_status()
        return response.json()


@tool
async def calculate_emi(
    loan_amount: float, tenure_months: int, annual_interest_rate: float | None = None
) -> dict[str, Any]:
    """Calculate reducing-balance EMI, total repayment, and interest. If no rate was given, use and disclose the configured mock rate."""
    rate = annual_interest_rate
    if rate is None:
        rate = config.DEFAULT_ANNUAL_INTEREST_RATE
    if rate is None:
        raise ValueError(
            "An annual interest rate is required because no mock default is configured."
        )
    result = await _post(
        "/emi/calculate",
        {
            "loan_amount": loan_amount,
            "tenure_months": tenure_months,
            "annual_interest_rate": rate,
        },
    )
    return result


@tool
async def check_loan_eligibility(
    monthly_salary: float,
    existing_monthly_emi: float,
    proposed_monthly_emi: float,
    loan_amount: float,
    tenure_months: int,
) -> dict[str, Any]:
    """Check the clearly documented mock EMI-to-income policy; this is not loan approval."""
    return await _post(
        "/loan/eligibility",
        {
            "monthly_salary": monthly_salary,
            "existing_monthly_emi": existing_monthly_emi,
            "proposed_monthly_emi": proposed_monthly_emi,
            "loan_amount": loan_amount,
            "tenure_months": tenure_months,
        },
    )


@tool
async def get_account_details() -> dict[str, Any]:
    """Retrieve only the authenticated customer's masked mock account details."""
    return await _get("/accounts/me")


@tool
async def submit_loan_application(
    loan_amount: float,
    tenure_months: int,
    annual_interest_rate: float,
    monthly_salary: float,
    existing_monthly_emi: float,
    calculated_emi: float,
    eligibility_result: bool,
) -> dict[str, Any]:
    """Prepare an eligible mock application for confirmation, or submit it only inside the server-validated confirmation flow."""
    confirmation = trusted_confirmation.get()
    if confirmation is not None:
        application_id = str(confirmation["application_id"])
        details = dict(confirmation["details"])
        result = await _post(
            f"/loan/applications/{application_id}/confirm",
            details,
        )
        return result

    result = await _post(
        "/loan/applications/prepare",
        {
            "loan_amount": loan_amount,
            "tenure_months": tenure_months,
            "annual_interest_rate": annual_interest_rate,
            "monthly_salary": monthly_salary,
            "existing_monthly_emi": existing_monthly_emi,
            "calculated_emi": calculated_emi,
            "eligibility_result": eligibility_result,
        },
        {"Idempotency-Key": str(uuid.uuid4())},
    )
    artifacts = chat_artifacts.get()
    if artifacts is not None:
        artifacts["pending_confirmation"] = {
            "application_id": result["application_id"],
            "confirmation_token": result["confirmation_token"],
            "confirmation_phrase": result["confirmation_phrase"],
            "loan_amount": result["loan_amount"],
            "tenure_months": result["tenure_months"],
            "annual_interest_rate": result["annual_interest_rate"],
            "calculated_emi": result["calculated_emi"],
            "expires_at": result["confirmation_expires_at"],
        }
    result.pop("confirmation_token", None)
    return result


BUSINESS_TOOLS = [
    calculate_emi,
    check_loan_eligibility,
    get_account_details,
    submit_loan_application,
]
