from __future__ import annotations

import hashlib
import json
import logging
import secrets
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException, Response, status
from fastapi.responses import FileResponse
from langchain_core.messages import HumanMessage

from app import config, logic, repository
from app.agent import agent
from app.auth import (
    authenticated_customer,
    chat_artifacts,
    require_customer,
    trusted_confirmation,
)
from app.database import initialize_database
from app.schemas import (
    AccountResponse,
    ApplicationResponse,
    ApplicationStatusResponse,
    ChatRequest,
    ChatResponse,
    ConfirmApplicationRequest,
    EmiRequest,
    EmiResponse,
    EligibilityRequest,
    EligibilityResponse,
    PrepareApplicationRequest,
)
from app.tools import submit_loan_application

logger = logging.getLogger(__name__)
WEB_ROOT = Path(__file__).parent / "web"


@asynccontextmanager
async def lifespan(_: FastAPI):
    initialize_database()
    yield


app = FastAPI(
    title="Smart Banking Support Agent",
    description="Educational mock banking assistant. No real banking or financial transactions.",
    version="1.0.0",
    lifespan=lifespan,
)


@app.get("/", include_in_schema=False)
async def banking_ui() -> FileResponse:
    return FileResponse(WEB_ROOT / "index.html")


def _require_llm() -> None:
    if not config.GEMINI_API_KEY:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Agent chat is unavailable until GEMINI_API_KEY is configured in .env.",
        )


def _message_content_as_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        text_parts = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                text = block.get("text")
                if isinstance(text, str):
                    text_parts.append(text)
        if text_parts:
            return "\n".join(text_parts)
    raise ValueError("The language model returned no readable text.")


@app.post("/emi/calculate", response_model=EmiResponse)
async def emi_calculate(payload: EmiRequest) -> dict[str, Any]:
    rate = payload.annual_interest_rate
    assumed = rate is None
    if rate is None:
        rate = config.DEFAULT_ANNUAL_INTEREST_RATE
    if rate is None:
        raise HTTPException(
            status_code=422,
            detail="Annual interest rate is required because no default mock rate is configured.",
        )
    return {
        "loan_amount": payload.loan_amount,
        "annual_interest_rate": rate,
        "interest_rate_assumed": assumed,
        "tenure_months": payload.tenure_months,
        **logic.calculate_emi(payload.loan_amount, rate, payload.tenure_months),
    }


@app.post("/loan/eligibility", response_model=EligibilityResponse)
async def loan_eligibility(payload: EligibilityRequest) -> dict[str, Any]:
    return logic.check_eligibility(
        payload.monthly_salary,
        payload.existing_monthly_emi,
        payload.proposed_monthly_emi,
        payload.loan_amount,
        payload.tenure_months,
    )


@app.get("/accounts/me", response_model=AccountResponse)
async def account_me(customer_id: str = Depends(require_customer)) -> dict[str, str]:
    return logic.get_account_details(customer_id)


@app.post(
    "/loan/applications/prepare",
    response_model=ApplicationResponse,
    status_code=status.HTTP_201_CREATED,
)
async def prepare_loan_application(
    payload: PrepareApplicationRequest,
    response: Response,
    customer_id: str = Depends(require_customer),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> dict[str, Any]:
    key = idempotency_key or str(uuid.uuid4())
    token = secrets.token_urlsafe(32)
    application = logic.create_application(
        customer_id=customer_id,
        loan_amount=payload.loan_amount,
        tenure_months=payload.tenure_months,
        annual_interest_rate=payload.annual_interest_rate,
        monthly_salary=payload.monthly_salary,
        existing_monthly_emi=payload.existing_monthly_emi,
        calculated_emi=payload.calculated_emi,
        eligibility_result=payload.eligibility_result,
        idempotency_key=key,
        token_hash=hashlib.sha256(token.encode("utf-8")).hexdigest(),
        application_id=f"APP-{uuid.uuid4().hex[:12].upper()}",
    )
    phrase = logic.confirmation_phrase(application)
    application["confirmation_phrase"] = phrase
    if application["status"] == "pending_confirmation":
        application["confirmation_token"] = token
    else:
        application["confirmation_token"] = None
    response.headers["Idempotency-Key"] = key
    return application


@app.post("/loan/applications/{application_id}/confirm")
async def confirm_loan_application(
    application_id: str,
    payload: ConfirmApplicationRequest,
    customer_id: str = Depends(require_customer),
) -> dict[str, str]:
    return logic.confirm_application(
        application_id=application_id,
        customer_id=customer_id,
        confirmation_token=payload.confirmation_token,
        phrase=payload.confirmation_phrase,
        loan_amount=payload.loan_amount,
        tenure_months=payload.tenure_months,
        annual_interest_rate=payload.annual_interest_rate,
        calculated_emi=payload.calculated_emi,
    )


@app.get(
    "/loan/applications/{application_id}",
    response_model=ApplicationStatusResponse,
)
async def get_loan_application(
    application_id: str, customer_id: str = Depends(require_customer)
) -> dict[str, Any]:
    row = repository.get_application(application_id, customer_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Application not found.")
    return {
        "application_id": row["application_id"],
        "status": row["status"],
        "loan_amount": row["loan_amount"],
        "tenure_months": row["tenure_months"],
        "annual_interest_rate": row["annual_interest_rate"],
        "calculated_emi": row["calculated_emi"],
        "eligibility": json.loads(row["eligibility_json"]),
    }


@app.post("/agent/chat", response_model=ChatResponse)
async def chat(
    payload: ChatRequest,
    customer_id: str = Depends(require_customer),
) -> ChatResponse:
    _require_llm()
    customer_token = authenticated_customer.set(customer_id)
    artifacts: dict[str, object] = {}
    artifacts_token = chat_artifacts.set(artifacts)
    try:
        result = await agent.ainvoke({"messages": [HumanMessage(content=payload.message)]})
        final_message = result["messages"][-1]
        reply = _message_content_as_text(final_message.content)
        pending = artifacts.get("pending_confirmation")
        return ChatResponse(reply=reply, pending_confirmation=pending)
    except Exception as error:
        logger.exception("Agent request failed")
        raise HTTPException(
            status_code=502,
            detail=f"The agent could not complete this request: {type(error).__name__}.",
        ) from error
    finally:
        chat_artifacts.reset(artifacts_token)
        authenticated_customer.reset(customer_token)


@app.post("/agent/confirm")
async def agent_confirm(
    payload: ConfirmApplicationRequest,
    application_id: str,
    customer_id: str = Depends(require_customer),
) -> dict[str, str]:
    """Submit via the same business tool, using confirmation supplied out-of-band by the client."""
    row = repository.get_application(application_id, customer_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Application not found.")
    trusted = {
        "application_id": application_id,
        "details": payload.model_dump(),
    }
    customer_token = authenticated_customer.set(customer_id)
    confirmation_token = trusted_confirmation.set(trusted)
    try:
        output = await submit_loan_application.coroutine(
            loan_amount=payload.loan_amount,
            tenure_months=payload.tenure_months,
            annual_interest_rate=payload.annual_interest_rate,
            monthly_salary=float(row["monthly_salary"]),
            existing_monthly_emi=float(row["existing_monthly_emi"]),
            calculated_emi=payload.calculated_emi,
            eligibility_result=True,
        )
        if output.get("status") != "submitted":
            raise HTTPException(status_code=502, detail="The application submission was not confirmed.")
        return output
    except HTTPException:
        raise
    except Exception as error:
        logger.exception("Confirmed application submission failed")
        raise HTTPException(
            status_code=502,
            detail=f"The application could not be submitted: {type(error).__name__}.",
        ) from error
    finally:
        trusted_confirmation.reset(confirmation_token)
        authenticated_customer.reset(customer_token)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "mode": "educational-mock"}
