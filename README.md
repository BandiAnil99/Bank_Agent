# Smart Banking Support Agent

An educational, mock-data banking support prototype built with FastAPI, SQLite,
LangChain's single `create_agent` tool-calling agent, HTTPX, and Pydantic. It
does not connect to a bank, make payments, or approve loans.

## Project structure

```text
app/
  agent.py       Single agent and safety-focused system prompt
  auth.py        Development mock identity and request-scoped server context
  config.py      Environment configuration
  database.py    SQLite schema initialization and mock seed data
  logic.py       EMI, mock eligibility, and application workflow validation
  main.py        FastAPI routes and agent/chat orchestration
  repository.py  Parameterized SQLite access
  schemas.py     Pydantic request/response models
  tools.py       Four HTTPX-backed LangChain business tools
tests/
  test_api.py    API, privacy, and confirmation workflow tests
```

## Setup and run

Python 3.11+ is required.

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
# Edit .env and set GEMINI_API_KEY from Google AI Studio for agent chat.
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --env-file .env --port 8767
```

Open the customer-facing demo at <http://127.0.0.1:8767/>. The API explorer is
at <http://127.0.0.1:8767/docs>. `API_BASE_URL` in `.env` must use the same
port as the server so the agent's HTTPX tools reach this app. Core API
endpoints and tests work without an LLM key; `/agent/chat` requires a Gemini
API key in `GEMINI_API_KEY`. Get a key from
<https://aistudio.google.com/app/apikey>. From another shell, run `pytest -q`.

`X-Mock-Customer-ID: customer-001` and `customer-002` are development-only
identities. Anyone able to reach this prototype can choose either identity.
Replace this header with production authentication (for example OIDC/JWT
verification), server-derived subject identity, authorization policies,
CSRF protections where applicable, rate limits, audit controls, secrets
management, and secure deployment before any real use. Never use this mock
auth mode or seed data with real customer information.

## Deploy to Render

The `render.yaml` Blueprint deploys a free web service with the mock identities
and seed data enabled. It is a public educational demo, not a production banking
service: anyone can act as either mock customer. Its SQLite database is stored
in `/tmp` and is ephemeral, so data can reset when the service restarts.

Create a new Blueprint in Render and select this GitHub repository. Agent chat
is unavailable until `GEMINI_API_KEY` is added as a secret environment variable
in the Render Dashboard. Do not put API keys in this repository.

## API examples

Use `X-Mock-Customer-ID: customer-001` where the endpoint requires auth.

### EMI

```http
POST /emi/calculate
Content-Type: application/json

{"loan_amount":500000,"annual_interest_rate":12,"tenure_months":36}
```

Example result (rounded to paise):

```json
{
  "loan_amount": 500000,
  "annual_interest_rate": 12,
  "interest_rate_assumed": false,
  "tenure_months": 36,
  "monthly_emi": 16607.15,
  "total_repayment": 597857.4,
  "total_interest": 97857.4
}
```

If `annual_interest_rate` is omitted, the configured `DEFAULT_ANNUAL_INTEREST_RATE`
is disclosed by `interest_rate_assumed`. Set it blank to require a rate in the
request. Zero-interest loans use principal divided by months.

### Eligibility

```http
POST /loan/eligibility

{"monthly_salary":80000,"existing_monthly_emi":5000,
 "proposed_monthly_emi":16607.15,"loan_amount":500000,"tenure_months":36}
```

The mock policy permits eligibility only when `(existing EMI + proposed EMI) /
monthly salary <= MAX_EMI_TO_INCOME_RATIO` (default 0.40). This is not an
underwriting decision, credit-score assessment, or loan approval.

Example response:

```json
{
  "eligible": true,
  "monthly_income": 80000,
  "existing_emi": 5000,
  "proposed_emi": 16607.15,
  "total_monthly_emi": 21607.15,
  "emi_to_income_ratio": 0.2701,
  "maximum_emi_to_income_ratio": 0.4,
  "reasons": ["Total monthly EMI is within the mock policy limit of 40% of income."],
  "decision_type": "preliminary_mock_policy_only"
}
```

### Account

```http
GET /accounts/me
X-Mock-Customer-ID: customer-001
```

Example response: `{"masked_account_number":"****5678","account_type":"savings","account_status":"active"}`.
The API does not accept a customer ID in the URL or query for this operation.

### Prepare, explicitly confirm, and check status

Preparation verifies the EMI and eligibility again on the server. It returns
a 15-minute confirmation token and exact detail-bound phrase. The client must
keep the token and call the separate confirmation endpoint after the customer
reviews the exact terms. A chat message saying "yes" does not call this
endpoint and cannot confirm an application. The confirmation route validates
the mock-authenticated owner, token, expiry, exact details, phrase, and
eligibility again. The application row is updated once; retries return the
same submitted result. Use the same `Idempotency-Key` to safely retry prepare.

```http
POST /loan/applications/prepare
X-Mock-Customer-ID: customer-001
Idempotency-Key: demo-loan-001
Content-Type: application/json

{"loan_amount":500000,"tenure_months":36,"annual_interest_rate":12,
 "monthly_salary":80000,"existing_monthly_emi":5000,
 "calculated_emi":16607.15,"eligibility_result":true}
```

Copy the returned `application_id`, `confirmation_token`,
`confirmation_phrase`, and exact loan fields into:

```http
POST /loan/applications/APP-.../confirm
X-Mock-Customer-ID: customer-001
Content-Type: application/json

{
  "confirmation_token":"<returned token>",
  "confirmation_phrase":"<returned phrase>",
  "loan_amount":500000,
  "tenure_months":36,
  "annual_interest_rate":12,
  "calculated_emi":16607.15
}
```

Then `GET /loan/applications/{application_id}` returns status and the
preliminary mock eligibility outcome. `POST /agent/confirm?application_id=...`
is the optional API-backed submission-tool path; like the direct endpoint, it
needs the same token, phrase, exact terms, and authenticated identity. It calls
the same guarded business-tool implementation without an additional LLM call.

A successful preparation response has this shape (the token is randomly
generated and unique for each prepared draft):

```json
{
  "application_id": "APP-0123456789AB",
  "status": "pending_confirmation",
  "loan_amount": 500000,
  "tenure_months": 36,
  "annual_interest_rate": 12,
  "monthly_salary": 80000,
  "existing_monthly_emi": 5000,
  "calculated_emi": 16607.15,
  "eligibility": {"eligible": true, "decision_type": "preliminary_mock_policy_only"},
  "confirmation_token": "<opaque random token>",
  "confirmation_phrase": "CONFIRM APP-0123456789AB | INR 500,000.00 | 36 months | 12.00% p.a. | EMI INR 16,607.15",
  "confirmation_expires_at": "<UTC timestamp>"
}
```

Confirmation returns `{"application_id":"APP-...","status":"submitted", ...}`.
This status means only that the mock application record was submitted; it is
not a loan approval.

## Sample end-to-end conversation

Example assumptions: customer-001, configured mock rate 12%, monthly salary
INR 80,000, existing monthly EMI INR 5,000. If the customer has not supplied
income or existing EMI, the agent must ask rather than invent them.

```text
Customer: I want a personal loan of INR 5,00,000 for three years.
Agent: I can estimate it using the configured mock rate of 12% per year.
       What is your monthly salary and existing monthly EMI?
Customer: Salary is INR 80,000 and my existing EMI is INR 5,000.
Agent: At the assumed 12% rate, the estimated EMI is INR 16,607.15 for
       36 months. Total repayment is INR 5,97,857.40, including
       INR 97,857.40 estimated interest. Existing plus proposed EMIs are
       27.0% of monthly income, within this prototype's 40% mock threshold.
       This is preliminary mock eligibility, not an approval. Your
       authenticated mock account is ****5678 (savings, active). I prepared
       application APP-...; it is pending confirmation, not submitted.
       Review the exact terms and confirm using the separate authenticated
       confirmation action before the 15-minute challenge expires.
```

The `/agent/chat` JSON response carries the confirmation credential separately
from the model's text. A client should present the terms and an explicit
confirmation control, keep that credential out of chat messages/logs, and
call `/agent/confirm` or the direct confirmation endpoint only after the
customer activates that control.

## Execution flow and limitations

The FastAPI layer derives a development identity from the mock auth header.
During `/agent/chat`, that identity is set in request-local context, and a
single shared LangChain agent invokes the four HTTPX tools. Those tools call
the FastAPI business endpoints, not SQLite directly. The server masks account
numbers and scopes all account/application reads by authenticated customer.

For loan requests the agent gathers missing terms, calls the EMI endpoint,
then eligibility, and only then prepares an eligible pending application.
The client receives the generated confirmation token as a separate structured
response field, not in the agent's tool output. On a distinct confirmation
request, the submission tool forwards that credential; the API validates it
against the customer- and details-bound SQLite draft before changing status.
SQLite uses parameterized queries and a per-customer idempotency key for
preparation.

The mock salary is customer-provided and not verified; customer identity is
spoofable by design; data is seeded locally; persistence and concurrency
controls are suitable only for a small demo; and no production-grade
authentication, underwriting, lending decision, encryption-at-rest policy,
or real banking integration is provided. The agent depends on the configured
LLM provider and network access. Do not use this prototype to handle real
financial or personal data.
