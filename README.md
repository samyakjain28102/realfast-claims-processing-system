# Claims Processing System

Deterministic health-claims adjudication for a take-home assignment: each line is priced against seeded
plan rules, accumulators (deductible and annual limits) are updated append-only, every outcome carries
reason codes and a decision trace, and disputes re-run the rules after fact correction or uphold.

## What it does

- Accepts structured claim submissions (member, lines, service codes, billed amounts).
- Adjudicates **each line independently** through pre-pricing gates, pricing, and limit checks.
- Tracks separate **adjudication** and **settlement** state at claim level, and line-level states
  including `NEEDS_REVIEW` and `UNDER_APPEAL`.
- Routes ambiguous or unmapped inputs to `NEEDS_REVIEW` instead of guessing.
- Supports member disputes on appealable denials, reviewer fact correction, and uphold — with full
  claim re-adjudication and ledger reversal/repost (D19).
- Records payments and produces an Explanation of Benefits (EOB) from deterministic data.

Amounts are in **minor currency units** (paise): `5000` = ₹50.00.

## Architecture

```
HTTP (FastAPI)  →  application services  →  domain engine (pure rules)
                         ↓
                  SQLite repositories (append-only decisions, ledger, payments)
```

- **`app/domain/`** — entities, state machines, adjudication engine (no I/O, no Gemini).
- **`app/application/`** — submit, resolve review, file dispute, record payment, read models.
- **`app/infrastructure/`** — SQLite schema, repositories, concurrency (`BEGIN IMMEDIATE`, WAL).
- **`app/api/`** — REST boundary, Pydantic schemas, PHI-safe error handlers.
- **`app/seed/`** — reference fixtures for local runs and API tests.

Design docs: [docs/scope.md](docs/scope.md), [docs/domain-model.md](docs/domain-model.md),
[docs/decisions.md](docs/decisions.md), [docs/technical-plan.md](docs/technical-plan.md).

## Prerequisites

- Python 3.11+
- pip

## Installation

```bash
python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS / Linux
source .venv/bin/activate

pip install -e ".[dev]"
```

## Environment variables

Copy the example file and point the API and seed loader at the **same** database file:

```bash
copy .env.example .env
```

| Variable | Purpose |
|---|---|
| `CLAIMS_DATABASE` | SQLite file path (e.g. `claims.db`). If unset: API uses `:memory:` (empty); seed defaults to `claims.db`. |
| `GEMINI_API_KEY` | Optional. Only for unstructured extraction (`GeminiClaimExtractor`); not used by the REST API or pytest. |

## Database initialization and seed data

Schema is applied automatically on first connection. Load demo reference data:

```bash
python -m app.seed.load
```

This seeds member `m1`, provider `prov1`, plan `plan1` (₹100 deductible, physio annual limit ₹100,
12 visits), policy `pol1` (effective 2026-01-01), and catalogue codes including `PHYSIO-30` and
`COSMETIC-1`.

## Run the API

```bash
uvicorn app.api.main:app --reload
```

With `.env` containing `CLAIMS_DATABASE=claims.db`, the API serves the seeded database.

- **OpenAPI / Swagger UI:** [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)
- **ReDoc:** [http://127.0.0.1:8000/redoc](http://127.0.0.1:8000/redoc)

## Run tests

```bash
python -m pytest
```

Import smoke check:

```bash
python -c "import app; import app.domain; import app.application; import app.infrastructure; import app.api.main; import app.seed.load"
```

## API overview

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/claims` | Submit a claim |
| `GET` | `/claims/{id}` | Claim detail with current decisions |
| `GET` | `/claims?member_id=` | List claims for a member |
| `POST` | `/claims/{id}/lines/{n}/disputes` | File a dispute on a line |
| `POST` | `/reviews/{line_id}/resolve` | Resolve `NEEDS_REVIEW` or appeal (`CORRECT_FACTS` / `UPHOLD`) |
| `POST` | `/claims/{id}/payments` | Record payment (must equal amount due) |
| `GET` | `/claims/{id}/eob` | Explanation of Benefits |
| `GET` | `/members/{id}/accumulators` | Deductible and benefit balances |

### Inspecting decisions, explanations, accumulators, and payments

- **Decisions and explanations:** `GET /claims/{id}` — each line includes `decision.outcome`,
  `decision.reasons` (code + message + appealable flag), and `decision.trace` (rule steps with
  accumulator before/after).
- **EOB:** `GET /claims/{id}/eob` — payable, paid, balance, per-line explanations, payment history.
- **Accumulators:** `GET /members/{id}/accumulators` — consumed amounts by scope (deductible, benefit
  amount, visits) for the plan year.
- **Payments:** listed on the claim view (`paid_minor`, `settlement_state`) and in the EOB
  `payments` array. Payment rows are append-only in SQLite.

Validation and domain errors return generic messages (no diagnosis codes or other PHI echoed). Malformed
JSON bodies return HTTP 422 with field locations only.

---

## Demo flow 1 — clean claim (deductible split)

Two physio lines consume deductible then plan share; explanations include `MEM_DEDUCTIBLE` and
`MEM_ABOVE_ALLOWED`.

```bash
curl -s -X POST http://127.0.0.1:8000/claims -H "Content-Type: application/json" -d "{
  \"id\": \"clean-1\",
  \"member_id\": \"m1\",
  \"submitted_at\": \"2026-03-20T10:00:00\",
  \"lines\": [
    {\"line_number\": 1, \"provider_id\": \"prov1\", \"service_code\": \"PHYSIO-30\",
     \"service_date\": \"2026-03-15\", \"billed_amount_minor\": 5000, \"diagnosis_code\": \"M54.5\"},
    {\"line_number\": 2, \"provider_id\": \"prov1\", \"service_code\": \"PHYSIO-30\",
     \"service_date\": \"2026-03-16\", \"billed_amount_minor\": 5000, \"diagnosis_code\": \"M54.5\"}
  ]
}"

curl -s http://127.0.0.1:8000/claims/clean-1
curl -s http://127.0.0.1:8000/members/m1/accumulators
```

Expected: claim `APPROVED`; line 1 plan paid 0, deductible 4000; line 2 similar; deductible
accumulator consumed 8000 (minor units).

Automated: `tests/api/test_demo_flows.py::test_demo_flow_1_clean_claim_shows_deductible_split_and_explanation`.

## Demo flow 2 — mixed claim (partial approval + review)

**Requires setup claims first** to consume deductible and most of the physio annual limit so line 3
partially approves and line 4 routes to review.

```bash
# Setup: burn deductible (3 lines)
curl -s -X POST http://127.0.0.1:8000/claims -H "Content-Type: application/json" -d "{
  \"id\": \"setup-deduct\", \"member_id\": \"m1\", \"submitted_at\": \"2026-03-20T10:00:00\",
  \"lines\": [
    {\"line_number\": 1, \"provider_id\": \"prov1\", \"service_code\": \"PHYSIO-30\", \"service_date\": \"2026-03-01\", \"billed_amount_minor\": 5000, \"diagnosis_code\": \"M54.5\"},
    {\"line_number\": 2, \"provider_id\": \"prov1\", \"service_code\": \"PHYSIO-30\", \"service_date\": \"2026-03-02\", \"billed_amount_minor\": 5000, \"diagnosis_code\": \"M54.5\"},
    {\"line_number\": 3, \"provider_id\": \"prov1\", \"service_code\": \"PHYSIO-30\", \"service_date\": \"2026-03-03\", \"billed_amount_minor\": 5000, \"diagnosis_code\": \"M54.5\"}
  ]
}"

# Setup: consume limit headroom (1 line, billed above allowed)
curl -s -X POST http://127.0.0.1:8000/claims -H "Content-Type: application/json" -d "{
  \"id\": \"setup-limit\", \"member_id\": \"m1\", \"submitted_at\": \"2026-03-20T10:00:00\",
  \"lines\": [
    {\"line_number\": 1, \"provider_id\": \"prov1\", \"service_code\": \"PHYSIO-30\", \"service_date\": \"2026-03-04\", \"billed_amount_minor\": 3000, \"diagnosis_code\": \"M54.5\"}
  ]
}"

# Mixed claim
curl -s -X POST http://127.0.0.1:8000/claims -H "Content-Type: application/json" -d "{
  \"id\": \"mixed-1\", \"member_id\": \"m1\", \"submitted_at\": \"2026-03-20T10:00:00\",
  \"lines\": [
    {\"line_number\": 1, \"provider_id\": \"prov1\", \"service_code\": \"PHYSIO-30\", \"service_date\": \"2026-03-10\", \"billed_amount_minor\": 5000, \"diagnosis_code\": \"M54.5\"},
    {\"line_number\": 2, \"provider_id\": \"prov1\", \"service_code\": \"COSMETIC-1\", \"service_date\": \"2026-03-11\", \"billed_amount_minor\": 10000, \"diagnosis_code\": \"M54.5\"},
    {\"line_number\": 3, \"provider_id\": \"prov1\", \"service_code\": \"PHYSIO-30\", \"service_date\": \"2026-03-12\", \"billed_amount_minor\": 5000, \"diagnosis_code\": \"M54.5\"},
    {\"line_number\": 4, \"provider_id\": \"prov1\", \"service_code\": \"NOT-IN-CATALOG\", \"service_date\": \"2026-03-13\", \"billed_amount_minor\": 1000, \"diagnosis_code\": \"M54.5\"}
  ]
}"
```

Expected: `UNDER_REVIEW`, payable 5000; line 2 `DENIED` (exclusion); line 3 `PARTIALLY_APPROVED`;
line 4 `NEEDS_REVIEW`.

Automated: `tests/api/test_demo_flows.py::test_demo_flow_2_mixed_claim_partial_approval_and_review`.

## Demo flow 3 — dispute, fact correction, payment, EOB

Denied cosmetic line → dispute → reviewer maps to physio → re-adjudication → payment → inspect EOB and
accumulators.

**Requires two prior physio lines** on the same member so the seeded ₹100 deductible is mostly consumed
and the appealed line has a non-zero plan payment.

```bash
# Setup: consume deductible (2 physio lines)
curl -s -X POST http://127.0.0.1:8000/claims -H "Content-Type: application/json" -d "{
  \"id\": \"dispute-setup-prior\", \"member_id\": \"m1\", \"submitted_at\": \"2026-03-20T10:00:00\",
  \"lines\": [
    {\"line_number\": 1, \"provider_id\": \"prov1\", \"service_code\": \"PHYSIO-30\", \"service_date\": \"2026-03-01\", \"billed_amount_minor\": 5000, \"diagnosis_code\": \"M54.5\"},
    {\"line_number\": 2, \"provider_id\": \"prov1\", \"service_code\": \"PHYSIO-30\", \"service_date\": \"2026-03-02\", \"billed_amount_minor\": 5000, \"diagnosis_code\": \"M54.5\"}
  ]
}"

# 1. Submit denied claim
curl -s -X POST http://127.0.0.1:8000/claims -H "Content-Type: application/json" -d "{
  \"id\": \"dispute-setup\", \"member_id\": \"m1\", \"submitted_at\": \"2026-03-20T10:00:00\",
  \"lines\": [
    {\"line_number\": 1, \"provider_id\": \"prov1\", \"service_code\": \"COSMETIC-1\",
     \"service_date\": \"2026-03-15\", \"billed_amount_minor\": 10000, \"diagnosis_code\": \"M54.5\"}
  ]
}"

# 2. File dispute
curl -s -X POST http://127.0.0.1:8000/claims/dispute-setup/lines/1/disputes \
  -H "Content-Type: application/json" -d "{\"member_reason\": \"Should be covered as physio\"}"

# 3. Resolve with corrected service code (line id is {claim_id}-L{line_number})
curl -s -X POST http://127.0.0.1:8000/reviews/dispute-setup-L1/resolve \
  -H "Content-Type: application/json" -d "{
    \"mode\": \"CORRECT_FACTS\",
    \"reviewer_id\": \"rev1\",
    \"note\": \"Mapped to physio catalogue entry\",
    \"corrections\": {\"service_code\": \"PHYSIO-30\"}
  }"

# 4. Pay (payable is ₹20.00 after partial deductible on the appealed line)
curl -s -X POST http://127.0.0.1:8000/claims/dispute-setup/payments \
  -H "Content-Type: application/json" -d "{\"amount_minor\": 2000, \"reference\": \"NEFT-1\"}"

# 5. Inspect
curl -s http://127.0.0.1:8000/claims/dispute-setup
curl -s http://127.0.0.1:8000/claims/dispute-setup/eob
curl -s http://127.0.0.1:8000/members/m1/accumulators
```

Expected: after resolve — `APPROVED`, payable 2000 (minor units); after payment — `SETTLED`; EOB shows
approved line and payment; physio benefit accumulator reflects plan-paid amounts from setup and appeal.

Automated: `tests/api/test_demo_flows.py::test_demo_flow_3_dispute_resolve_pay_and_eob`.

---

## Known limitations and deferred functionality

These are intentional scope boundaries (see [docs/scope.md](docs/scope.md) §9 and
[docs/decisions.md](docs/decisions.md)):

| Item | Status |
|---|---|
| Submit idempotency (D22) | **Deferred** — retries may duplicate claims |
| Unstructured HTTP / Gemini ingestion | **Deferred** — structured JSON API only in the demo |
| Retroactive policy-change automation | **Deferred** — decisions record plan version; no auto re-adjudication |
| Manual monetary overrides | **Not supported** — reviewers correct facts only; rules compute amounts |
| Clawbacks / payment reversals | **Not supported** — payments append-only; `OVERPAID` surfaces discrepancies |
| SQLite writer serialization | **Limitation** — `BEGIN IMMEDIATE` serialises writers; correct but low throughput |
| Full PHI redaction in logs / Gemini | **Deferred** — API 422 responses strip submitted values; broader redaction not built |

**Closing invariant failures** (internal safety check if ledger would exceed limits after commit) return
HTTP **409 Conflict** and roll back the transaction — not routed to `NEEDS_REVIEW`.

**OVERPAID after appeal:** ledger reflects current adjudication; historical payment rows remain; no
automatic clawback.

## Submission layout

```
app/                  # application code
docs/                 # domain model, decisions, technical plan, self-review
ai-artifacts/         # raw JSONL session logs (mandatory for submission)
problem_statement/    # assignment brief
README.md
```

Problem statement: [problem_statement/problem_statement.md](problem_statement/problem_statement.md)
