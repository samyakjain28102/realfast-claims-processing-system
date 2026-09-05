# Self-Review

This document covers:

- What is good in the submission
- What is rough or intentionally thin
- Known gaps (with reasoning, not omissions)
- What would change with more time

This was a very interesting problem to solve and since I did not have subject-matter expertise for this, I had to develop it. The key takeaway from this problem statement — and the one the complete architecture is based on — is that we cannot afford to wrongly process a claim. Disputed claims are risky and costly. Underpayment denies a member money they are owed. Overpayment cannot be clawed back. Either way the accumulator is wrong, so one bad decision silently contaminates every later claim for that member.

---

## What's good?

1. If there is any unsurety about any line in a claim, the claim hits the human-in-the-loop state and nothing is assumed when processing it. `NEEDS_REVIEW` is a designed outcome, not a failure or a placeholder. Partial automation with visible gaps is better than full automation with silent errors.

2. Gemini can extract claim facts from unstructured text; already-structured JSON bypasses it. We then apply strict deterministic rules on top of those facts to decide how the claim should be processed. The LLM never decides coverage, pricing, deductible, limits, payment, outcome, or reason codes. Wiring PDF / Excel / TIFF / image ingest as an HTTP path is still deferred — the extractor exists; the file-upload surface does not.

3. Persistence in SQLite lets us do more than one-shot adjudication: annual limit checks, visit caps, append-only decision history, dispute records, and accumulator inspection across claims for the same member.

4. **Human review and adjudication are deliberately separate jobs.** The engine answers "what do the rules say about these facts?" A reviewer answers "are the facts right?" They never set `plan_paid`, allowed amount, deductible, or outcome by hand — that would produce a number wearing the costume of a rules-derived decision. Review has two modes only: correct facts and re-adjudicate the whole claim against the original plan version, or (on an open dispute) uphold and let the engine confirm the original RULES reason. Decisions and ledger entries are append-only; earlier answers stay as the historical record. Lines still in review post no accumulator consumption, so a pending human cannot corrupt later claims. Claim state is derived from line states, and settlement is a second derived axis — so a member can dispute a denied line on an already-paid claim without forcing the system out of a fake "PAID is terminal" corner.

5. The strongest end-to-end test is **dispute → resolve → re-adjudicate → pay → EOB**: `tests/api/test_demo_flows.py::test_demo_flow_3_dispute_resolve_pay_and_eob`. A denied cosmetic line is disputed; the reviewer maps it to a covered physio code; the whole claim is re-adjudicated (original decision stays, sequence 2 is appended); exact payable is recorded; the member-facing EOB and the physio accumulator both match. That single flow exercises line-level decisions, immutable audit, fact-only review, settlement, explanation, and limit memory.

---

## What's rough?

1. I am not sure on the volume of claims that would hit human-in-the-loop. We have tried to account for as many cases as possible (unknown service codes, suspected cross-claim duplicates, unpriceable lines), but there is no evidence yet on how many real claims would clear the pipeline without a reviewer. The design is biased toward review when unsure; that is safer, and it may also be chatty.

2. I have optimised for correctness, which has in turn made scalability an issue. Two concurrent claims against the same remaining annual limit must never both pay the remainder — that write-skew would overpay quietly and leave the accumulator permanently wrong. The fix is `BEGIN IMMEDIATE` before balances are read, plus a pre-commit invariant that refuses to persist an over-limit ledger (HTTP 409, rollback, not `NEEDS_REVIEW`). SQLite allows one writer database-wide, so **every adjudication serialises against every other**, even for unrelated members and benefits. The contention is artificial — it comes from lock granularity, not from a real conflict. An adjudication here is a few milliseconds, so the ceiling is likely low hundreds of claims per second and may never bind for a demo-scale payer. What we would change with more time is the lock, not the design: measure first, then row-level locks (or optimistic version columns) on the accumulator keys a claim actually touches, optionally partition by `member_id`. The ledger, the invariant, and the pure engine stay.

3. **Intentionally deferred** (designed for, not forgotten):

   | Item | Why it is not in this build |
   |---|---|
   | **Submit idempotency** | A client retry after an unknown server outcome can create a second claim. Valuable, not load-bearing for the domain story. |
   | **Unstructured HTTP / Gemini ingestion** | Extractor is built; `POST /claims` is structured JSON and bypasses Gemini. New field vs new endpoint, plus PHI redaction of the Gemini payload and persistence of the raw blob, were left for later. |
   | **Clawbacks / payment reversals** | Payments are append-only and never negative. If an appeal reduces an already-paid amount, settlement becomes `OVERPAID` and a human recovers the money — we do not invent a reversal transaction. |
   | **Manual financial overrides** | Reviewers correct facts only. Setting `plan_paid` by hand is non-deterministic and would lie about what the rules concluded. |
   | **Retroactive policy automation** | Every decision stamps `plan_version`. Ordinary re-adjudication always uses that original version. Detecting that a later rule change would have paid differently, and routing those claims to review, is a separate workflow — never silent auto-reverse. |
   | **Scalable / distributed locking** | Correctness is handled (global write lock + closing invariant). Per-accumulator row locks, optimistic concurrency, and member-partitioned queues are the productionisation path, not this take-home. |

   Also deferred: closing a review as "permanently undecidable" without a rules-derived terminal outcome. A line can stay in `NEEDS_REVIEW` until facts suffice.

4. **Known limitation at the HTTP submission boundary:** the domain engine adjudicates eligibility **per line**. A claim with one line before policy termination and one after is a mixed claim in the engine (`APPROVED` + `DEN_NOT_ELIGIBLE`). `POST /claims` does not reach that path. Submit loads **exactly one policy that covers every service date on the claim**; if lines span eligibility windows, the API returns a policy-not-found error instead of adjudicating the mixed case. That is a shell limitation, not a rules gap. Plan-year spans on the same policy are fine — service date lives on the line, so each line keys its own accumulator year.

---

## What I'd flag?

1. I am fairly confident in the solution's ability to deal with the claims and have tried to account for many edge cases: partial approval at a limit boundary, deductible vs denial as separate ideas, confirmed vs suspected duplicates, whole-claim re-adjudication with ledger reversal, exact-amount payment, and PHI not echoed in validation errors.

2. I have documented the assumptions and design trade-offs in `docs/decisions.md` and `docs/scope.md`. The short version: one member per policy; one active policy per member; plan year = calendar year; no coinsurance or copay (deductible met ⇒ plan pays 100% of allowed); no `units` on lines so there is no rounding; typed coverage rules seeded from data rather than a DSL; claim state derived, never assigned; Gemini extracts facts only. The departures from real payer practice are named on purpose — cross-claim duplicates go to review rather than auto-deny; `above_allowed` is the member's cost because this is reimbursement, not a contracted write-off; reason codes are a compact CARC-informed taxonomy, not X12 copied verbatim.

3. The biggest learning from this project as a whole was how to use LLMs to do things. I was so tempted to make this process fully agentic but decided against it to honor the requirement of deterministic outputs. Same claim, same system state, same decision — every time, traceable to a specific rule.

4. One thing I would have done differently was focus a bit more on the technical aspects of implementation while learning the non-technicalities of this project. That led to some back and forth on design decisions which otherwise would not have happened. Going forward I would try to have a mental map of which component of the use case is handled by what technology a bit earlier.
