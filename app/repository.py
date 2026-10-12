from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Any

from app.database import connect

CONFIRMATION_TTL_MINUTES = 15


def get_account_for_customer(customer_id: str) -> sqlite3.Row | None:
    with connect() as connection:
        return connection.execute(
            """
            SELECT account_number, account_type, status
            FROM accounts WHERE customer_id = ?
            ORDER BY account_id LIMIT 1
            """,
            (customer_id,),
        ).fetchone()


def customer_exists(customer_id: str) -> bool:
    with connect() as connection:
        return (
            connection.execute(
                "SELECT 1 FROM customers WHERE customer_id = ?", (customer_id,)
            ).fetchone()
            is not None
        )


def _application_response(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "application_id": row["application_id"],
        "status": row["status"],
        "loan_amount": row["loan_amount"],
        "tenure_months": row["tenure_months"],
        "annual_interest_rate": row["annual_interest_rate"],
        "monthly_salary": row["monthly_salary"],
        "existing_monthly_emi": row["existing_monthly_emi"],
        "calculated_emi": row["calculated_emi"],
        "eligibility": json.loads(row["eligibility_json"]),
        "confirmation_expires_at": row["confirmation_expires_at"],
    }


def prepare_application(
    *,
    application_id: str,
    customer_id: str,
    loan_amount: float,
    tenure_months: int,
    annual_interest_rate: float,
    monthly_salary: float,
    existing_monthly_emi: float,
    calculated_emi: float,
    eligibility: dict[str, Any],
    idempotency_key: str,
    token_hash: str,
) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    expires = now + timedelta(minutes=CONFIRMATION_TTL_MINUTES)
    with connect() as connection:
        existing = connection.execute(
            """
            SELECT * FROM loan_applications
            WHERE customer_id = ? AND idempotency_key = ?
            """,
            (customer_id, idempotency_key),
        ).fetchone()
        if existing:
            same_details = (
                existing["loan_amount"] == loan_amount
                and existing["tenure_months"] == tenure_months
                and existing["annual_interest_rate"] == annual_interest_rate
                and existing["monthly_salary"] == monthly_salary
                and existing["existing_monthly_emi"] == existing_monthly_emi
            )
            if not same_details:
                raise ValueError("This idempotency key was already used for different details.")
            if existing["status"] == "pending_confirmation":
                connection.execute(
                    """
                    UPDATE loan_applications
                    SET confirmation_token_hash = ?, confirmation_expires_at = ?,
                        updated_at = ?
                    WHERE application_id = ?
                    """,
                    (token_hash, expires.isoformat(), now.isoformat(), existing["application_id"]),
                )
                existing = connection.execute(
                    "SELECT * FROM loan_applications WHERE application_id = ?",
                    (existing["application_id"],),
                ).fetchone()
                return _application_response(existing)
            return _application_response(existing)

        connection.execute(
            """
            INSERT INTO loan_applications (
                application_id, customer_id, loan_amount, tenure_months,
                annual_interest_rate, monthly_salary, existing_monthly_emi,
                calculated_emi, eligibility_json, status, idempotency_key,
                confirmation_token_hash, confirmation_expires_at, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending_confirmation', ?, ?, ?, ?, ?)
            """,
            (
                application_id,
                customer_id,
                loan_amount,
                tenure_months,
                annual_interest_rate,
                monthly_salary,
                existing_monthly_emi,
                calculated_emi,
                json.dumps(eligibility),
                idempotency_key,
                token_hash,
                expires.isoformat(),
                now.isoformat(),
                now.isoformat(),
            ),
        )
        row = connection.execute(
            "SELECT * FROM loan_applications WHERE application_id = ?", (application_id,)
        ).fetchone()
        return _application_response(row)


def get_application(application_id: str, customer_id: str) -> sqlite3.Row | None:
    with connect() as connection:
        return connection.execute(
            "SELECT * FROM loan_applications WHERE application_id = ? AND customer_id = ?",
            (application_id, customer_id),
        ).fetchone()


def mark_application_submitted(application_id: str) -> None:
    with connect() as connection:
        connection.execute(
            """
            UPDATE loan_applications
            SET status = 'submitted', updated_at = ?
            WHERE application_id = ? AND status = 'pending_confirmation'
            """,
            (datetime.now(timezone.utc).isoformat(), application_id),
        )
