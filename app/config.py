from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


def _optional_float(value: str | None) -> float | None:
    if value is None or not value.strip():
        return None
    return float(value)


DATABASE_PATH = Path(os.getenv("DATABASE_PATH", "banking.db"))
API_BASE_URL = os.getenv("API_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
LLM_MODEL = os.getenv("LLM_MODEL", "gemini-3.5-flash-lite")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
DEFAULT_ANNUAL_INTEREST_RATE = _optional_float(
    os.getenv("DEFAULT_ANNUAL_INTEREST_RATE", "12.0")
)
MAX_EMI_TO_INCOME_RATIO = float(os.getenv("MAX_EMI_TO_INCOME_RATIO", "0.40"))
MOCK_AUTH_ENABLED = os.getenv("MOCK_AUTH_ENABLED", "true").lower() == "true"

if DEFAULT_ANNUAL_INTEREST_RATE is not None and not 0 <= DEFAULT_ANNUAL_INTEREST_RATE <= 100:
    raise ValueError("DEFAULT_ANNUAL_INTEREST_RATE must be between 0 and 100.")
if not 0 < MAX_EMI_TO_INCOME_RATIO <= 1:
    raise ValueError("MAX_EMI_TO_INCOME_RATIO must be greater than 0 and at most 1.")
