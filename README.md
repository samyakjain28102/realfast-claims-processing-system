# Claims Processing System

Take-home assignment: a deterministic claims adjudication system for member reimbursement.

## Status

**Design complete; implementation in progress.** See branch `implementation` for application code.

## Documentation

| Document | Purpose |
|---|---|
| [problem-understanding.md](docs/problem-understanding.md) | Domain framing and scope decisions |
| [scope.md](docs/scope.md) | In scope / out of scope / deferred |
| [technical-plan.md](docs/technical-plan.md) | Architecture and build order |
| [domain-model.md](docs/domain-model.md) | Entities, state machines, rules |
| [decisions.md](docs/decisions.md) | Decision register (D1–D25) |
| [design-review-and-test-matrix.md](docs/design-review-and-test-matrix.md) | Pre-implementation QA review and tests |
| [self-review.md](docs/self-review.md) | Honest assessment *(completed before submission)* |

Problem statement: [problem_statement/problem_statement.md](problem_statement/problem_statement.md)

## Setup

*To be added when `app/` is implemented.*

```bash
# Planned:
# python -m venv .venv
# source .venv/bin/activate  # or .venv\Scripts\activate on Windows
# pip install -e ".[dev]"
# python -m app.seed.load
# uvicorn app.api.main:app --reload
# pytest
```

## Submission layout

Per assignment requirements:

```
app/                  # application code (implementation branch)
docs/                 # domain-model, decisions, self-review
ai-artifacts/         # raw JSONL session logs (mandatory)
README.md
.git/                 # commit history
```
