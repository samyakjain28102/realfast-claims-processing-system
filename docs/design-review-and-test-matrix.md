# Design Review & Test Matrix

Skeptical QA/domain review of the current design **before implementation**. This document does not
expand scope; it stress-tests what we have already decided.

**Legend**

| Tag | Meaning |
|---|---|
| **[DECIDED]** | Explicit decision in `decisions.md` / `scope.md` |
| **[PROPOSED]** | Adopted in `technical-plan.md` unless you object |
| **[DEFERRED]** | Designed for, not built (`scope.md` §9) |
| **[GAP]** | Not yet specified — must be resolved during implementation or documented as accepted risk |

---

## 1. Test matrix

Each row is a test case. **Validates** names the invariant or decision under test.

### 1.1 Happy paths & boundaries

| ID | Given | When | Then | Validates |
|---|---|---|---|---|
| H1 | Member eligible; benefit covered; deductible ₹0; limit ample; billed ₹500, scheduled ₹400 | Submit 1-line claim | `allowed=400`, `above_allowed=100`, `plan_paid=400`, outcome `APPROVED`, `INFO_COVERED` | Pricing + money conservation **[PROPOSED]** |
| H2 | Same as H1 but deductible ₹10,000 unmet, allowed ₹400 | Submit | `deductible_applied=400`, `plan_paid=0`, outcome **`APPROVED`** (not denied), `MEM_DEDUCTIBLE` | D2: deductible ≠ denial **[DECIDED]** |
| H3 | Deductible ₹1,000 remaining; allowed ₹400 | Submit | `deductible_applied=400`, `plan_paid=0`, outcome `APPROVED` | D13 policy-wide deductible **[DECIDED]** |
| H4 | Deductible fully met; allowed ₹400 | Submit | `deductible_applied=0`, `plan_paid=400` | D8 assumption: no coinsurance **[DECIDED]** |
| H5 | Annual plan-pay limit ₹10,000; ₹9,000 consumed; allowed ₹400 after deductible | Submit | `plan_paid=100`, `denied_amount=300`, outcome `PARTIALLY_APPROVED`, `DEN_ANNUAL_LIMIT` | D12 limit caps plan pay **[DECIDED]** |
| H6 | Visit limit 12; 11 used; 1-line claim | Submit | Line `APPROVED`, visit accumulator +1 | Generic accumulator (D6) **[DECIDED]** |
| H7 | Visit limit 12; 12 used; 1-line claim | Submit | Line `DENIED`, `DEN_VISIT_LIMIT`, no visit consumption | Whole-line denial (D11 no units) **[DECIDED]** |
| H8 | 3 covered lines; mixed amounts; all gates pass | Submit | Claim adjudication `PARTIALLY_APPROVED` or `APPROVED`; each line has reason + trace | Explanation capability **[REQ]** |
| H9 | All lines `APPROVED`; `payable > 0` | Record payment = payable | Settlement `SETTLED`; adjudication unchanged | D15 settlement axis **[DECIDED]** |
| H10 | Claim `SETTLED` | Fetch EOB | Member-facing summary matches line breakdowns | EOB in scope **[DECIDED]** |

### 1.2 Coverage, limits, deductible, allowed amount

| ID | Given | When | Then | Validates |
|---|---|---|---|---|
| C1 | Policy inactive on service date | Submit | Line `DENIED`, `DEN_NOT_ELIGIBLE`; claim not `REJECTED` | Eligibility on service date **[DECIDED]** |
| C2 | Benefit `covered=false` | Submit | `DEN_NOT_COVERED` before exclusion gate runs | Pipeline ordering **[PROPOSED]** |
| C3 | Benefit `covered=true`, `excluded=true` | Submit | `DEN_EXCLUDED` (not `NOT_COVERED`) | Separate reason codes **[DECIDED]** |
| C4 | Billed ₹800, scheduled ₹500 | Submit | `allowed=500`, `above_allowed=300` → member owes | Allowed ≠ billed **[DECIDED]** |
| C5 | Billed ₹300, scheduled ₹500 | Submit | `allowed=300`, `above_allowed=0` | `min(billed, scheduled)` **[PROPOSED]** |
| C6 | Physio consumes ₹400 of ₹1,000 deductible; later diagnostics line | Submit second claim | Diagnostics line sees ₹600 deductible remaining | D13 cross-benefit deductible **[DECIDED]** |
| C7 | Annual limit exhausted (`plan_paid` cap hit) | Submit | `plan_paid=0`, `denied_amount=after_deductible`, outcome `DENIED` | Limit boundary — fully denied |
| C8 | Deductible does not consume benefit dollar limit | Line with ₹400 to deductible + separate benefit limit | Benefit limit reduced only by `plan_paid`, not `deductible_applied` | D12 **[DECIDED]** |
| C9 | Line A service_date 2025-12-31; Line B 2026-01-01; same claim | Submit | Each line uses its own plan-year accumulators | Service date on line **[PROPOSED]** |
| C10 | Benefit has visit limit but no dollar limit | Submit | Visit count enforced; `plan_paid=after_deductible` | Generic accumulator scopes **[DECIDED]** |

### 1.3 Mixed line-item outcomes

| ID | Given | When | Then | Validates |
|---|---|---|---|---|
| M1 | 5 lines: 3 covered, 1 excluded, 1 unknown service code | Submit | 3 adjudicated normally; 1 `DEN_EXCLUDED`; 1 `NEEDS_REVIEW`; claim `UNDER_REVIEW` | D1 line decides, claim derives **[DECIDED]** |
| M2 | 2 lines: line 1 `APPROVED`, line 2 `DENIED` | Submit | Claim `PARTIALLY_APPROVED` (not `DENIED`) | Derivation rule **[PROPOSED]** |
| M3 | All lines `DENIED` | Submit | Claim `DENIED`; `payable=0` → settlement `NOTHING_DUE` | Both state axes **[DECIDED]** |
| M4 | ₹2,000 limit remaining; line 1 allowed ₹4,000; line 2 allowed ₹4,000 (same claim) | Submit | Line 1 partial/full per math; line 2 sees **updated** working balance; total `plan_paid` ≤ ₹2,000 | Working balance threading **[PROPOSED]** — **critical** |
| M5 | Line 1 `NEEDS_REVIEW`; line 2 would otherwise `APPROVED` | Submit | Claim `UNDER_REVIEW`; line 2 terminal → **posts ledger**; line 1 posts **nothing**; `payable` includes line 2 only | D16 **[DECIDED]** |
| M6 | One line `UNDER_APPEAL`; others terminal | File dispute | Claim `UNDER_REVIEW`; payment blocked | D15 + dispute blocks settlement **[DECIDED]** |

### 1.4 Duplicate detection

| ID | Given | When | Then | Validates |
|---|---|---|---|---|
| D1 | Two identical lines (same service, date, provider) on **one** claim | Submit | Second line `DENIED`, `DEN_DUPLICATE`; first line unaffected | D8 confirmed duplicate **[DECIDED]** |
| D2 | New claim line matches a line on a **prior** adjudicated claim | Submit | `NEEDS_REVIEW`, `REV_SUSPECTED_DUPLICATE` (not auto-deny) | D8 suspected duplicate **[DECIDED]** |
| D3 | Same service/date/provider but **different billed amount** on a prior terminal line | Submit | Suspected-duplicate **key still matches** (member + provider + service + date); if the application supplies the key → `NEEDS_REVIEW`, `REV_SUSPECTED_DUPLICATE`. Billed amount is **not** part of the key. | D17 **[DECIDED]** — engine does not compare billed amounts; application must not omit keys solely because billed amounts differ |
| D4 | Suspected duplicate resolved via fact correction (legitimate repeat) | Reviewer confirms; re-adjudicate | Line `APPROVED`; accumulators consume on resolution | D16 + D21 **[DECIDED]** |
| D5 | Prior claim line still `NEEDS_REVIEW` | Submit matching line | **Not** flagged as suspected duplicate | D17 **[DECIDED]** |

### 1.5 State transitions & disputes

| ID | Given | When | Then | Validates |
|---|---|---|---|---|
| S1 | Line `DENIED` with appealable reason | Member files dispute | Line `UNDER_APPEAL`; original decision immutable (new sequence only after resolution) | D4 append-only **[DECIDED]** |
| S2 | Line `APPROVED` with only `MEM_DEDUCTIBLE` | Member files dispute | **Rejected** — non-appealable | Reason-code appealable flag **[DECIDED]** |
| S3 | Claim `SETTLED`; denied line disputed | File dispute | Adjudication → `UNDER_REVIEW`; settlement stays `SETTLED` | D15 split axes **[DECIDED]** |
| S4 | Dispute upheld | Reviewer upholds | Whole claim re-adjudicated; original denial stands with RULES reason (e.g. `DEN_EXCLUDED`); `ReviewResolution` records uphold; dispute closed; ledger unchanged | D21 + D28 + D29 **[DECIDED]** |
| S5 | Dispute overturned via **corrected facts** | Reviewer supplies facts; re-adjudicate | New `LineDecision` `source=RULES`; ledger posts if terminal approval | D21 + D18 **[DECIDED]** |
| S6 | Post-payment dispute succeeds; `payable` > `paid` | (no new payment yet) | Settlement → `DUE`; supplementary payment allowed | D15 supplementary payment **[DECIDED]** |
| S7 | Appeal **reduces** `plan_paid` after claim `SETTLED` | Overturn partial approval downward | Settlement → `OVERPAID`; no clawback | D15 OVERPAID surfaced **[DECIDED]** |
| S8 | Second dispute on same line while first open | File again | **[GAP]** — reject? queue? must decide |
| S9 | Dispute on superseded decision (after Path A re-adjudication) | File against old `sequence` | **[GAP]** — should reject; not yet specified |

### 1.6 Human review, fact correction, re-adjudication

| ID | Given | When | Then | Validates |
|---|---|---|---|---|
| R1 | Unknown service code | Submit | `NEEDS_REVIEW`, `REV_UNKNOWN_SERVICE`; **no accumulator consumption** | D16 **[DECIDED]** |
| R2 | Reviewer supplies valid `service_code` | Resolve review | Whole claim re-adjudicated; new `LineDecision` `source=RULES`; accumulators post on terminal approval | D16 + D7 **[DECIDED]** |
| R3 | Corrected facts unchanged from original | Re-adjudicate | **Identical** decision to first run | Determinism invariant **[PROPOSED]** |
| R4 | Reviewer tries to set `plan_paid` | API call | **Rejected** — not a correctable field; out of scope (D21) | D21 **[DECIDED]** |
| R6 | Correction changes `service_date` across plan year | Re-adjudicate | Old ledger entries reversed; new entries under new plan-year key | D19 **[DECIDED]** |
| R7 | `NEEDS_REVIEW` resolved to `DENIED` via rules | Re-adjudicate | No consumption while in review; none posted if denied | D16 **[DECIDED]** |
| R8 | First correction still `NEEDS_REVIEW`; second correction succeeds | Two resolve calls, same endpoint | Claim stays `UNDER_REVIEW` after first; terminal after second; **two** `LineDecision` sequences for affected line | D23 **[DECIDED]** |
| R9 | Re-adjudication still `NEEDS_REVIEW` after correction | Resolve once | New `LineDecision` appended with **updated** reason/trace/inputs; `sequence` incremented; prior decision immutable | D24 **[DECIDED]** |
| R10 | Reviewer attempts "close as undecidable" | Resolve API | **Not supported** — no terminal outcome without rules; claim stays `UNDER_REVIEW` | D25 **[DECIDED]** deferred |
| R11 | Line `NEEDS_REVIEW`, no dispute | Resolve with `mode=uphold` | **Rejected** — uphold is dispute-only | D28 **[DECIDED]** |

### 1.7 Retroactive policy changes

| ID | Given | When | Then | Validates |
|---|---|---|---|---|
| P1 | Claim adjudicated under plan `version=2` | Inspect decision | `plan_version=2` on `LineDecision` | Version stamp kept for deferred feature **[DECIDED]** |
| P2 | Plan updated to `version=3` after claim settled | (no detection built) | **No automatic action** | **[DEFERRED]** scope §9 |
| P3 | **[DEFERRED]** Settled claim would differ under v3 | Rule change trigger | Route affected claims to `NEEDS_REVIEW`; no auto-reversal | Intended future design **[DEFERRED]** |
| P4 | Re-adjudication after ordinary review/dispute | Resolve | Uses **original** `plan_version`, not current plan | D18 **[DECIDED]** |

### 1.8 Accumulator / ledger behaviour

| ID | Given | When | Then | Validates |
|---|---|---|---|---|
| A1 | Line approved with `plan_paid` and deductible | Commit decision | Ledger entries for `BENEFIT_AMOUNT`, `DEDUCTIBLE`, `BENEFIT_VISITS` as applicable; each references `decision_id` | D5 append-only **[DECIDED]** |
| A2 | Appeal overturns prior approval | Resolve dispute | Compensating entries (`reverses_entry_id` set); net balance restored then new consumption posted | D5 reversal **[DECIDED]** |
| A3 | Sum of ledger entries for key | Any time | Equals reported balance in trace before/after | Trace + ledger consistency **[DECIDED]** |
| A4 | Decision `DENIED` at gate 5 (not covered) | Submit | **No** benefit/deductible consumption | Gates before arithmetic **[PROPOSED]** |
| A5 | Decision `NEEDS_REVIEW` at gate 1 | Submit | **No** consumption | D16 **[DECIDED]** |
| A6 | Terminal approval after review resolution | Resolve | Ledger posts per rules engine output only | D21 **[DECIDED]** |
| A7 | `OVERPAID` after payable drops | Appeal reduces plan pay | Ledger **is** reversed/reposted on re-adjudication (D19); payments stay append-only; `OVERPAID` is settlement visibility only | D15, D19 **[DECIDED]** |

### 1.9 Concurrency & transaction safety

| ID | Given | When | Then | Validates |
|---|---|---|---|---|
| X1 | Limit ₹10,000; ₹8,000 consumed; Claim A wants ₹4,000; Claim B wants ₹4,000 | Submit **concurrently** | Total `plan_paid` across both ≤ ₹10,000; one partial/one denied; no silent overspend | D14 BEGIN IMMEDIATE **[DECIDED]** |
| X2 | Same as X1 but sequential | Submit B after A commits | B reads ₹10,000 consumed; fully denied | Deterministic ordering given same inputs **[PROPOSED]** |
| X3 | Closing invariant triggered (bug injected) | Commit | Transaction **rolled back**; submit fails with **409**; no partial ledger; not routed to `NEEDS_REVIEW` | Safety net **[DECIDED]** |
| X4 | `BEGIN IMMEDIATE` busy | Retry | Full re-adjudication with fresh balances; no patch of stale result | D9 pure engine **[DECIDED]** |
| X5 | Two threads, **different members**, unrelated benefits | Concurrent submit | Both succeed but **serialised** (throughput cost only) | D14 throughput trade-off **[DECIDED]** |

### 1.10 Persistence & failure scenarios

| ID | Given | When | Then | Validates |
|---|---|---|---|---|
| F1 | Valid claim | Submit succeeds | Decision + ledger + claim state committed **atomically** | Transaction boundary **[PROPOSED]** |
| F2 | DB error mid-commit | Submit | No orphan decisions; no orphan ledger rows; claim absent or unchanged | Atomicity **[PROPOSED]** |
| F3 | Client timeout after server committed | Client retries same submit | **Duplicate claim may be created** — documented accepted risk | D22 **[DECIDED]** |
| F4 | Process crash after adjudicate(), before commit | Restart | No persisted state; safe to retry (may hit F3) | Pure engine + txn **[PROPOSED]** |
| F5 | Fetch claim after submit | GET | Returns persisted decisions, traces, derived states | Read-your-writes **[PROPOSED]** |
| F6 | Payment recorded | DB inspect | `Payment` row append-only; sum matches recorded amount | D15 payments **[DECIDED]** |
| F7 | Payment attempted while `UNDER_REVIEW` | POST payment | **Rejected** | D15 guard **[DECIDED]** |
| F8 | Payment amount ≠ payable | POST payment | **Rejected** | D20 **[DECIDED]** |

### 1.12 LLM extraction boundary

Protects D30 / D31 — Gemini must not become a second adjudicator. Extraction is implemented before
pricing (`technical-plan.md` step 2a).

| ID | Given | When | Then | Validates |
|---|---|---|---|---|
| L1 | Unstructured input; extraction + Pydantic validation succeed | Intake via Gemini path | Canonical `Claim` is passed to `adjudicate()`; Gemini is **not** asked for coverage, amounts, outcome, or reason codes | D30 **[DECIDED]** |
| L2 | Extraction missing/ambiguous/invalid (fails schema) | Intake via Gemini path | **No invented facts.** Pre-adjudication `ClaimExtractionValidationError`. No `Claim`. No `NEEDS_REVIEW`. No new reason code | D31 **[DECIDED]** |
| L3 | Structured `POST /claims` with line items | Submit | Gemini is **bypassed**; engine runs on the submitted `Claim` | D30 **[DECIDED]** |
| L4 | `tests/domain/` | `adjudicate(claim, ctx)` | No network, no `GEMINI_API_KEY`, no Gemini SDK | D9 + D30 **[DECIDED]** |
| L5 | Extracted `service_code` was wrong | Reviewer corrects facts; resolve | Whole-claim re-adjudication; new `LineDecision` `source=RULES` | D7 + D21 + D30 **[DECIDED]** |
| L6 | Terminal decision after extracted intake | Fetch claim / EOB | Explanation is reason-code template + engine trace, **not** Gemini prose | D30 **[DECIDED]** |
| L7 | Gemini client | Logs / error handler | No API key; no raw claim text, prompts, or responses | D30 + I16 **[DECIDED]** |
| L8 | Gemini / API unavailable | Intake via Gemini path | `ClaimExtractionApiError`. No `Claim`. Not `NEEDS_REVIEW` | D31 **[DECIDED]** |

### 1.11 Structural validation & rejection

| ID | Given | When | Then | Validates |
|---|---|---|---|---|
| V1 | Negative billed amount | Submit | Claim `REJECTED`; no line decisions | Gate 0 **[PROPOSED]** |
| V2 | Future service date | Submit | `REJECTED` or line `NEEDS_REVIEW` | **[GAP]** — docs say "reject or review" |
| V3 | Empty claim (0 lines) | Submit | `REJECTED` | Structural validation **[PROPOSED]** |
| V4 | Duplicate `line_number` | Submit | `REJECTED` | Structural validation **[GAP]** |
| V5 | `REJECTED` claim | Member disputes | Not allowed — nothing to dispute | REJECTED ≠ DENIED **[DECIDED]** |

---

## 2. Contradictions & ambiguities

Updated after D16–D31. Resolved items marked ✅; remaining items are deferred to a named implementation slice.

### 2.1 Resolved (D16–D31)

| # | Was | Resolution |
|---|---|---|
| **A** | NEEDS_REVIEW accumulator consumption | ✅ **D16** — review/appeal lines post nothing; terminal siblings post on submit; re-adjudication reverses superseded + posts new terminal atomically |
| **B** | Re-adjudication plan version | ✅ **D18** — original `plan_version`; retroactive apply is separate deferred workflow |
| **C** | Plan-year correction ledger | ✅ **D19** — compensating reversals + repost atomically |
| **D** | Submit idempotency | ✅ **D22** — deferred; documented accepted risk |
| **F** | Duplicate match key | ✅ **D17** — member + provider + service_code + service_date |
| **G** | Unresolved lines as duplicate anchors | ✅ **D17** — not used |
| **H** | Payment amount rules | ✅ **D20** — exact payable only |
| **Path B** | Manual monetary overrides | ✅ **D21** — out of scope; rules-only outcomes |
| **Review loop** | Iterative resolve; append on each attempt; no permanent undecidable close | ✅ **D23, D24, D25** |
| **Deductible field** | `Policy.deductible` vs `Plan.deductible` | ✅ **D26** — `Plan.deductible` is the single source of truth |
| **Conservation scope** | Invariant on every decision vs pre-pricing exits | ✅ **D27** — priced decisions only; pre-pricing exits have no amount breakdown; `payable` sums priced `plan_paid` only |
| **Uphold target** | Close review or dispute | ✅ **D28** — dispute-only |
| **HUM_UPHELD** | Reason code on `LineDecision` | ✅ **D29** — removed; `ReviewResolution.mode` records uphold; `LineDecision` keeps RULES reasons |
| **Gemini failure mode** | `REJECTED` vs `NEEDS_REVIEW` vs invent a reason | ✅ **D31** — pre-adjudication error; no Claim; no new reason code |

### 2.2 Deferred to the implementation slice that needs them

Not product-scope reopenings. Call them in the named slice; recommended behaviour is recorded so
slice 1 does not invent a default.

| # | Issue | Slice | Recommendation |
|---|---|---|---|
| **E** | **`OVERPAID` ledger drift** A7 / S7 | Settlement after appeal | **Resolved:** ledger reverses/reposts on re-adjudication (D19); payments stay append-only; `OVERPAID` is settlement visibility only |
| **I** | **Future service date** V2 | Gate 0 | Recommend **`REJECTED`** at claim level (deterministic). |
| **J** | **Double dispute** S8 | Dispute use case | Recommend **reject if dispute already open**. |
| **K** | **Dispute targets old sequence** S9 | Dispute use case | Recommend **reject; dispute current decision only**. |
| **L** | **`covered=false` AND `excluded=true` in seed** | Seed data | Seed discipline only — don't seed contradictory benefits. |
| **M5-detail** | **Terminal sibling lines while one line in review** | Accumulator posting | ✅ Documented in `technical-plan.md` §2.5 — **needs explicit test (M5)** |
| **N** | **Judgement-only disputes without correctable facts** | Disputes | ✅ D21 + D25 + D28 — only uphold (on dispute) or better facts; no permanent close |
| **Zero billed** | Approve-with-zeros vs structural reject | Validation / financial adjudication | Pick in that slice; do not invent in slice 1. |
| **Dispute.state** | Values unnamed | Dispute domain | Define with the dispute use case. |
| **Line state vs outcome** | `UNDER_APPEAL` is not a decision outcome | State derivation | Derived from current decision + open dispute. |
| **Unknown provider / benefit** | No gate specified | Validation / catalogue lookup | Do not invent a rule in advance; surface when implementing lookup. |
| **INFO_COVERED appealability** | Catalogue shows "—" | Dispute use case | Resolve when implementing disputes. |
| **Gemini remaining intake plumbing** | HTTP shape, raw-text persistence, PHI redaction | Later intake / API | Extractor is built (D30, D31). Do not invent an HTTP shape in pricing. |

### 2.3 Documentation drift (cosmetic)

| # | Issue | Notes |
|---|---|---|
| **N** | `mark_paid.py` vs record payment | Rename to `record_payment.py` when coding |
| **O** | D18 + deferred retroactive | Resolved — ordinary re-adjudication pinned to original version |

---

## 3. Missing high-risk edge cases

Still worth explicit tests even after D16–D29:

1. **Fact-based overturn when limit now exhausted** — corrected facts re-adjudicate to partial/zero pay; rules decide, not human (D21).
2. **Terminal sibling consumes while sibling in review** — line 2 `APPROVED` posts ledger; line 1 in `NEEDS_REVIEW` does not; `payable` sums priced `plan_paid` only (D27).
3. **Whole-claim re-adjudication changes earlier terminal line** — rare but possible if working balance order shifts; ledger reversal on all superseded terminal decisions (D16, D19).
4. **Zero billed amount** — allowed 0; outcome `APPROVED` with zeros vs structural `REJECTED` — pick one.
5. **Policy terminates mid-claim** — line 1 eligible, line 2 after termination → mixed claim.
6. **All lines `NEEDS_REVIEW`** — payable = 0; settlement `NOTHING_DUE`; payment blocked.
7. **Ledger reversal when re-adjudication changes only deductible portion** — partial compensating entries.
8. **Confirmed duplicate: line 1 still consumes visit count** — yes, if approved.
9. **Dispute with no correctable facts** — only uphold available (D21).
10. **Thread A commits, Thread B retries** — B re-adjudicates fresh (X4).
11. **Client retry duplicate submit** — second claim created (D22); document in README.
12. **Payment partial/excess rejected** — D20 API validation.

---

## 4. Invariants the implementation must never violate

Non-negotiable. Violation = bug, not edge case.

| ID | Invariant | Enforcement |
|---|---|---|
| I1 | **Money conservation:** `billed == above_allowed + deductible_applied + plan_paid + denied_amount` on decisions that reached pricing | Property test on priced decisions only (D27). Pre-pricing exits have no breakdown. |
| I2 | **No silent limit breach:** sum of `plan_paid` ledger for benefit key in plan year ≤ annual limit | Pre-commit check; abort → **409** on invariant failure |
| I3 | **No silent deductible breach:** deductible ledger ≤ plan deductible | Pre-commit check |
| I4 | **Visit count ≤ annual visit limit** after commit | Pre-commit check |
| I5 | **Determinism:** same `(claim, context snapshot)` → same decisions and traces | Domain test |
| I6 | **Append-only decisions:** no UPDATE/DELETE on `LineDecision`; current = max sequence | Schema + repository |
| I7 | **Append-only ledger:** reversal = compensating entry with `reverses_entry_id` | Repository |
| I8 | **No orphan ledger entries:** every entry has valid `decision_id` | FK + tests |
| I9 | **Derived claim states:** adjudication and settlement never stored as authoritative source of truth without recomputation | `states.py` single derivation function |
| I10 | **Review/appeal immutability:** disputed decision row unchanged; new decision appended | Application layer |
| I11 | **Facts-only review resolution:** API rejects computed-field corrections | API validation test |
| I12 | **All monetary outcomes `source=RULES`** in this implementation | Domain + API test |
| I19 | **`NEEDS_REVIEW` / `UNDER_APPEAL` post no ledger entries** | D16 domain test |
| I20 | **Re-adjudication uses original `plan_version`** | D18 domain/application test |
| I21 | **Payment amount == payable exactly** | D20 API test |
| I13 | **Non-appealable disputes rejected** | API test |
| I14 | **No payment while `UNDER_REVIEW`** | API test |
| I15 | **Payments append-only, non-negative** | Schema |
| I16 | **PHI not in logs** | Manual/checklist + test on error handler |
| I17 | **Working balance monotonicity within claim:** later lines see cumulative consumption from earlier lines on same keys | Domain test M4 |
| I18 | **Concurrent safety:** total plan pay for a benefit key never exceeds limit after any commit sequence | Threaded test X1 |
| I22 | **Gemini never decides:** coverage, pricing, deductible, limits, payment, outcome, and reason codes come only from the engine | Extraction tests L1, L6 |
| I23 | **Domain has no Gemini dependency:** `adjudicate()` and `tests/domain/` do not call an LLM or require `GEMINI_API_KEY` | Import/architecture test + L4 |

**Clarification on I2 vs OVERPAID:** Ledger reflects **current** adjudication after re-adjudication (D19).
Payments are not clawed back. `OVERPAID` means `paid > payable` on the settlement axis only; later claims
are limited by the ledger balance, not historical payment totals (D15).

---

## 5. Minimal test set to write first

Ordered for TDD and maximum risk reduction per test. **Write these before infrastructure** (domain-only unless noted).

### Tier 0 — Foundation (day 1, `tests/domain/`)

| Priority | Test | IDs | Why first |
|---|---|---|---|
| 1 | Money conservation property on random/simple **priced** lines | I1, D27 | Catches every arithmetic bug |
| 2 | Deductible-only line → `APPROVED`, `plan_paid=0` | H2 | Most common modelling mistake |
| 3 | Limit boundary partial approval | H5 | Core scored edge case |
| 4 | Two lines, one limit — working balance | M4, I17 | Silent overspend without DB |
| 5 | Visit limit 12th vs 13th | H6, H7 | Proves generic accumulator |
| 6 | Cross-benefit deductible | C6 | D13 interaction |
| 7 | Determinism — same inputs twice | I5 | Safety rule executable |
| 8 | Outcome vs denial at gate 5/6 | C2, C3 | Pipeline ordering |

### Tier 1 — Gates & duplicates (day 1–2, domain)

| Priority | Test | IDs |
|---|---|---|
| 9 | Ineligible service date | C1 |
| 10 | Confirmed duplicate in-claim | D1 |
| 11 | Unknown service → NEEDS_REVIEW, no consumption | R1, A5 |
| 12 | Excluded vs not covered | C3 |

### Tier 2 — State derivation (day 2, domain)

| Priority | Test | IDs |
|---|---|---|
| 13 | Mixed line outcomes → claim `PARTIALLY_APPROVED` | M1, M2 |
| 14 | Any NEEDS_REVIEW → claim `UNDER_REVIEW` | M1 |
| 15 | Settlement `payable` / `DUE` / `SETTLED` derivation | H9, M3 |

### Tier 3 — Ledger & appeals (day 2–3, domain then application)

| Priority | Test | IDs |
|---|---|---|
| 16 | Approval posts ledger; denial at gate 5 does not | A1, A4 |
| 17 | Fact-based dispute overturn reverses + reposts ledger | A2, S5, D19 |
| 18 | NEEDS_REVIEW line posts no ledger; terminal sibling does | M5, D16 |
| 19 | Post-payment dispute → settlement stays SETTLED, adjudication reopens | S3 |
| 20 | Re-adjudication uses original plan_version | P4, D18 |
| 21 | Exact payable payment; reject partial/over | F8, D20 |
| 22 | Iterative resolve — second attempt succeeds | R8, D23 |
| 23 | Still NEEDS_REVIEW appends new decision with distinct trace | R9, D24 |

### Tier 4 — Infrastructure (day 3, `tests/application/`)

| Priority | Test | IDs |
|---|---|---|
| 20 | Atomic commit / rollback on failure | F1, F2 |
| 21 | **Threaded concurrent limit test** | X1, I18 |
| 22 | BEGIN IMMEDIATE retry re-adjudicates | X4 |
| 23 | Payment blocked while UNDER_REVIEW | F7 |
| 24 | Plan-year correction reverses ledger | R6, D19 |

### Tier 5 — API smoke (day 3–4, `tests/api/`)

| Priority | Test | IDs |
|---|---|---|
| 24 | Demo flow 1 — clean claim | scope §8 |
| 25 | Demo flow 2 — mixed claim | scope §8 |
| 26 | Demo flow 3 — dispute + fact correction | scope §8 |
| 27 | Dispute rejected on deductible | S2 |
| 28 | Payment rejected when amount ≠ payable | F8 |

**Stop rule:** If Tier 0–3 pass, the domain is trustworthy. Tier 4 proves persistence/concurrency. Tier 5 proves the demo.

---

## 6. Challenges to current decisions

Not proposals to reopen scope — places a skeptical reviewer would push back.

| Decision | Challenge | Recommended response |
|---|---|---|
| D8 suspected duplicate → review | Review queue fills with legitimate same-day care | Keep decision; document in demo; optional seed avoids noisy matches |
| D14 global serialisation | Unrelated members wait on each other | Keep for take-home; §4.3 production path already written |
| D15 no clawbacks + OVERPAID | Member/plan out of sync forever | Keep; add visible `OVERPAID` in API/EOB; document manual recovery |
| D11 no units | "3 sessions" = 3 lines burdens submitter | Keep; matches assignment (member submits) |
| D21 no manual overrides | Some real appeals need judgement without new facts | Keep; uphold only; document as intentional scope cut |
| D22 no idempotency | Retry = duplicate claim | **Documented** in D22; README must not advise blind retry |
| Deferred retroactive detection | Version stamp without behaviour | Accept; test P1 only |
| D30 Gemini extraction | Unstructured HTTP not in the demo | Keep; structured submit is in-scope intake. Domain has no Gemini dependency |
| D31 pre-adjudication extraction error | Failed extract never becomes a reviewable claim | Keep; do not invent `REV_EXTRACTION_FAILED` |

---

## 7. Remaining gaps before step 1 coding

D26–D31 closed the blockers for slice 1 plus the extraction slice (deductible source, conservation
scope, uphold, `HUM_UPHELD`, Gemini-as-extractor, pre-adjudication extraction failure). Gemini
extraction is complete **before pricing**.

Still deferred to later slices — do **not** invent defaults in pricing:

1. **`OVERPAID` vs accumulator invariant I2** (§2.2 E) — pick reconciliation stance when implementing settlement after appeal.
2. **Future service date** (§2.2 I) — gate 0; recommend `REJECTED`.
3. **Double dispute / dispute old sequence** (§2.2 J, K) — dispute use case; recommend reject both.
4. **Zero billed amount** (§3 item 4) — validation / financial adjudication.
5. **`Dispute.state` values, line-state derivation, unknown provider/benefit, `INFO_COVERED` appealability** — named slices in §2.2.
6. **Gemini intake plumbing** — unstructured HTTP shape, raw-text persistence, PHI redaction of the Gemini payload. Not pricing.

`payable` with mixed review + terminal lines is **resolved** (D27): sum `plan_paid` of current decisions that have a financial breakdown; pre-pricing / review lines contribute zero.

None expand feature scope.
