from __future__ import annotations

from typing import Any

from fastapi import HTTPException, status

from app import config, repository


def calculate_emi(
    loan_amount: float, annual_interest_rate: float, tenure_months: int
) -> dict[str, float]:
    if loan_amount <= 0:
        raise HTTPException(status_code=422, detail="Loan amount must be greater than zero.")
    if annual_interest_rate < 0:
        raise HTTPException(status_code=422, detail="Interest rate cannot be negative.")
    if tenure_months <= 0:
        raise HTTPException(status_code=422, detail="Tenure must be greater than zero.")

    monthly_rate = annual_interest_rate / 1200
    if monthly_rate == 0:
        emi = loan_amount / tenure_months
    else:
        growth = (1 + monthly_rate) ** tenure_months
        emi = loan_amount * monthly_rate * growth / (growth - 1)
    emi = round(emi, 2)
    total_repayment = round(emi * tenure_months, 2)
    return {
        "monthly_emi": emi,
        "total_repayment": total_repayment,
        "total_interest": round(total_repayment - loan_amount, 2),
    }


def check_eligibility(
    monthly_salary: float,
    existing_monthly_emi: float,
    proposed_monthly_emi: float,
    loan_amount: float,
    tenure_months: int,
) -> dict[str, Any]:
    if monthly_salary <= 0:
        raise HTTPException(status_code=422, detail="Monthly salary must be greater than zero.")
    if min(existing_monthly_emi, proposed_monthly_emi) < 0:
        raise HTTPException(status_code=422, detail="EMI values cannot be negative.")
    if loan_amount <= 0 or tenure_months <= 0:
        raise HTTPException(status_code=422, detail="Loan amount and tenure must be positive.")
    total_emi = round(existing_monthly_emi + proposed_monthly_emi, 2)
    ratio = total_emi / monthly_salary
    max_ratio = config.MAX_EMI_TO_INCOME_RATIO
    reasons = []
    if ratio > max_ratio:
        reasons.append(
            f"Total monthly EMI exceeds the mock policy limit of {max_ratio:.0%} of income."
        )
    else:
        reasons.append(
            f"Total monthly EMI is within the mock policy limit of {max_ratio:.0%} of income."
        )
    return {
        "eligible": ratio <= max_ratio,
        "monthly_income": round(monthly_salary, 2),
        "existing_emi": round(existing_monthly_emi, 2),
        "proposed_emi": round(proposed_monthly_emi, 2),
        "total_monthly_emi": total_emi,
        "emi_to_income_ratio": round(ratio, 4),
        "maximum_emi_to_income_ratio": max_ratio,
        "reasons": reasons,
        "decision_type": "preliminary_mock_policy_only",
    }


def get_account_details(customer_id: str) -> dict[str, str]:
    row = repository.get_account_for_customer(customer_id)
    if row is None:
        raise HTTPException(status_code=404, detail="No mock account found for this customer.")
    account_number = row["account_number"]
    return {
        "masked_account_number": f"****{account_number[-4:]}",
        "account_type": row["account_type"],
        "account_status": row["status"],
    }


def create_application(
    *,
    customer_id: str,
    loan_amount: float,
    tenure_months: int,
    annual_interest_rate: float,
    monthly_salary: float,
    existing_monthly_emi: float,
    calculated_emi: float,
    eligibility_result: bool,
    idempotency_key: str,
    token_hash: str,
    application_id: str,
) -> dict[str, Any]:
    expected_emi = calculate_emi(loan_amount, annual_interest_rate, tenure_months)[
        "monthly_emi"
    ]
    if abs(expected_emi - calculated_emi) > 0.01:
        raise HTTPException(
            status_code=422, detail="Calculated EMI does not match the submitted loan details."
        )
    eligibility = check_eligibility(
        monthly_salary,
        existing_monthly_emi,
        expected_emi,
        loan_amount,
        tenure_months,
    )
    if not eligibility_result or not eligibility["eligible"]:
        raise HTTPException(
            status_code=422,
            detail="Application preparation is unavailable because the mock eligibility policy was not met.",
        )
    try:
        return repository.prepare_application(
            application_id=application_id,
            customer_id=customer_id,
            loan_amount=loan_amount,
            tenure_months=tenure_months,
            annual_interest_rate=annual_interest_rate,
            monthly_salary=monthly_salary,
            existing_monthly_emi=existing_monthly_emi,
            calculated_emi=expected_emi,
            eligibility=eligibility,
            idempotency_key=idempotency_key,
            token_hash=token_hash,
        )
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


def confirmation_phrase(application: dict[str, Any]) -> str:
    return (
        f"CONFIRM {application['application_id']} | INR {application['loan_amount']:,.2f} | "
        f"{application['tenure_months']} months | "
        f"{application['annual_interest_rate']:.2f}% p.a. | "
        f"EMI INR {application['calculated_emi']:,.2f}"
    )


def confirm_application(
    *,
    application_id: str,
    customer_id: str,
    confirmation_token: str,
    phrase: str,
    loan_amount: float,
    tenure_months: int,
    annual_interest_rate: float,
    calculated_emi: float,
) -> dict[str, Any]:
    import hashlib
    import hmac
    from datetime import datetime, timezone

    row = repository.get_application(application_id, customer_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Application not found.")
    application = dict(row)
    if application["status"] not in {"pending_confirmation", "submitted"}:
        raise HTTPException(status_code=409, detail="Application is not awaiting confirmation.")
    if (
        application["loan_amount"] != loan_amount
        or application["tenure_months"] != tenure_months
        or application["annual_interest_rate"] != annual_interest_rate
        or application["calculated_emi"] != calculated_emi
    ):
        raise HTTPException(
            status_code=409, detail="Confirmation details do not match the prepared application."
        )
    expected_phrase = confirmation_phrase(application)
    if not hmac.compare_digest(phrase, expected_phrase):
        raise HTTPException(status_code=400, detail="Confirmation phrase does not match.")
    supplied_hash = hashlib.sha256(confirmation_token.encode("utf-8")).hexdigest()
    if not hmac.compare_digest(supplied_hash, application["confirmation_token_hash"]):
        raise HTTPException(status_code=403, detail="Invalid confirmation token.")
    if application["status"] == "submitted":
        return {
            "application_id": application_id,
            "status": "submitted",
            "message": "Application was already submitted.",
        }
    if datetime.fromisoformat(application["confirmation_expires_at"]) < datetime.now(timezone.utc):
        raise HTTPException(status_code=410, detail="Confirmation has expired; prepare the application again.")

    eligibility = check_eligibility(
        application["monthly_salary"],
        application["existing_monthly_emi"],
        application["calculated_emi"],
        application["loan_amount"],
        application["tenure_months"],
    )
    if not eligibility["eligible"]:
        raise HTTPException(status_code=422, detail="Application no longer meets the mock policy.")
    repository.mark_application_submitted(application_id)
    return {
        "application_id": application_id,
        "status": "submitted",
        "message": "Application submitted under the educational mock workflow; this is not a loan approval.",
    }
