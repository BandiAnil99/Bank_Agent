from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app import config, logic
from app import tools
from app.database import initialize_database
from app.main import app


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATABASE_PATH", tmp_path / "test.sqlite3")
    initialize_database()
    with TestClient(app) as test_client:
        yield test_client


def auth(customer_id: str = "customer-001") -> dict[str, str]:
    return {"X-Mock-Customer-ID": customer_id}


def test_customer_application_page_is_served(client):
    response = client.get("/")
    assert response.status_code == 200
    assert "Harbor Assist" in response.text
    assert "Quick EMI calculator" in response.text


def test_chat_requires_gemini_api_key(client, monkeypatch):
    monkeypatch.setattr(config, "GEMINI_API_KEY", "")
    response = client.post(
        "/agent/chat",
        json={"message": "Hello"},
        headers=auth(),
    )
    assert response.status_code == 503
    assert "GEMINI_API_KEY" in response.json()["detail"]


def test_chat_extracts_text_from_gemini_content_blocks(client, monkeypatch):
    from app import main

    monkeypatch.setattr(config, "GEMINI_API_KEY", "configured-for-test")

    class TextBlockAgent:
        async def ainvoke(self, _request):
            return {
                "messages": [
                    SimpleNamespace(
                        content=[
                            {
                                "type": "text",
                                "text": "Your estimated EMI is INR 16,607.15.",
                                "extras": {"signature": "must not be shown"},
                            }
                        ]
                    )
                ]
            }

    monkeypatch.setattr(main, "agent", TextBlockAgent())
    response = client.post(
        "/agent/chat",
        json={"message": "Calculate an EMI"},
        headers=auth(),
    )
    assert response.status_code == 200
    assert response.json()["reply"] == "Your estimated EMI is INR 16,607.15."
    assert "signature" not in response.json()["reply"]


def test_emi_calculation_and_zero_interest(client):
    response = client.post(
        "/emi/calculate",
        json={"loan_amount": 500000, "annual_interest_rate": 12, "tenure_months": 36},
    )
    assert response.status_code == 200
    assert response.json()["monthly_emi"] == 16607.15
    zero_rate = client.post(
        "/emi/calculate",
        json={"loan_amount": 1200, "annual_interest_rate": 0, "tenure_months": 12},
    )
    assert zero_rate.json()["monthly_emi"] == 100


def test_account_details_are_authenticated_and_masked(client):
    assert client.get("/accounts/me").status_code == 401
    response = client.get("/accounts/me", headers=auth())
    assert response.status_code == 200
    assert response.json() == {
        "masked_account_number": "****5678",
        "account_type": "savings",
        "account_status": "active",
    }
    assert client.get("/accounts/me", headers=auth("unknown")).status_code == 401


def prepared_payload() -> dict:
    return {
        "loan_amount": 500000,
        "tenure_months": 36,
        "annual_interest_rate": 12,
        "monthly_salary": 80000,
        "existing_monthly_emi": 5000,
        "calculated_emi": 16607.15,
        "eligibility_result": True,
    }


def test_prepare_requires_eligibility_then_confirm_is_bound_and_idempotent(client):
    headers = {**auth(), "Idempotency-Key": "request-001"}
    payload = prepared_payload()
    prepared = client.post("/loan/applications/prepare", json=payload, headers=headers)
    assert prepared.status_code == 201
    draft = prepared.json()
    assert draft["status"] == "pending_confirmation"
    assert draft["confirmation_token"]

    confirm = {
        "confirmation_token": draft["confirmation_token"],
        "confirmation_phrase": draft["confirmation_phrase"],
        "loan_amount": draft["loan_amount"],
        "tenure_months": draft["tenure_months"],
        "annual_interest_rate": draft["annual_interest_rate"],
        "calculated_emi": draft["calculated_emi"],
    }
    without_token = {key: value for key, value in confirm.items() if key != "confirmation_token"}
    assert client.post(
        f"/loan/applications/{draft['application_id']}/confirm",
        json=without_token,
        headers=auth(),
    ).status_code == 422
    assert client.get(
        f"/loan/applications/{draft['application_id']}", headers=auth()
    ).json()["status"] == "pending_confirmation"
    mismatch = {**confirm, "loan_amount": 1}
    assert client.post(
        f"/loan/applications/{draft['application_id']}/confirm",
        json=mismatch,
        headers=auth(),
    ).status_code == 409
    submitted = client.post(
        f"/loan/applications/{draft['application_id']}/confirm",
        json=confirm,
        headers=auth(),
    )
    assert submitted.status_code == 200
    assert submitted.json()["status"] == "submitted"
    assert client.post(
        f"/loan/applications/{draft['application_id']}/confirm",
        json=confirm,
        headers=auth(),
    ).json()["status"] == "submitted"
    assert client.get(
        f"/loan/applications/{draft['application_id']}", headers=auth("customer-002")
    ).status_code == 404


def test_agent_confirmation_uses_the_same_submission_tool(client, monkeypatch):
    payload = prepared_payload()
    prepared = client.post("/loan/applications/prepare", json=payload, headers=auth())
    draft = prepared.json()
    confirmation = {
        "confirmation_token": draft["confirmation_token"],
        "confirmation_phrase": draft["confirmation_phrase"],
        "loan_amount": draft["loan_amount"],
        "tenure_months": draft["tenure_months"],
        "annual_interest_rate": draft["annual_interest_rate"],
        "calculated_emi": draft["calculated_emi"],
    }

    async def in_process_post(path, body, extra_headers=None):
        application_id = path.split("/")[-2]
        return logic.confirm_application(
            application_id=application_id,
            customer_id="customer-001",
            confirmation_token=body["confirmation_token"],
            phrase=body["confirmation_phrase"],
            loan_amount=body["loan_amount"],
            tenure_months=body["tenure_months"],
            annual_interest_rate=body["annual_interest_rate"],
            calculated_emi=body["calculated_emi"],
        )

    monkeypatch.setattr(tools, "_post", in_process_post)
    response = client.post(
        f"/agent/confirm?application_id={draft['application_id']}",
        json=confirmation,
        headers=auth(),
    )
    assert response.status_code == 200
    assert response.json()["status"] == "submitted"


def test_preparation_rejects_ineligible_or_false_emi(client):
    payload = {**prepared_payload(), "monthly_salary": 30000}
    response = client.post("/loan/applications/prepare", json=payload, headers=auth())
    assert response.status_code == 422
    payload = {**prepared_payload(), "calculated_emi": 1}
    response = client.post("/loan/applications/prepare", json=payload, headers=auth())
    assert response.status_code == 422
