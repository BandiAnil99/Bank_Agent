from __future__ import annotations

from contextvars import ContextVar

from fastapi import Header, HTTPException, status

from app import config, repository

authenticated_customer: ContextVar[str | None] = ContextVar(
    "authenticated_customer", default=None
)
chat_artifacts: ContextVar[dict[str, object] | None] = ContextVar(
    "chat_artifacts", default=None
)
trusted_confirmation: ContextVar[dict[str, object] | None] = ContextVar(
    "trusted_confirmation", default=None
)


async def require_customer(
    x_mock_customer_id: str | None = Header(default=None, alias="X-Mock-Customer-ID"),
) -> str:
    if not config.MOCK_AUTH_ENABLED:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Development mock authentication is disabled; configure production authentication.",
        )
    if not x_mock_customer_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Provide the development-only X-Mock-Customer-ID header.",
        )
    if not repository.customer_exists(x_mock_customer_id):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unknown development mock customer.",
        )
    return x_mock_customer_id
