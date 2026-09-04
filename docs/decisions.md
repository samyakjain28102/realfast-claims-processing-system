# Decisions, Trade-offs and Assumptions

What was built, what was not, and what was assumed about the domain.

> **Status: written ahead of implementation and reconciled against the code before submission.**
> Working detail lives in `docs/scope.md` and `docs/technical-plan.md`; this is the authoritative
> record of *why*.

---

## 1. Domain research

Neither the assignment nor prior experience supplied the domain, so it was researched before modelling.
Four findings changed the design, and each is visible in the code:

| Finding | What it changed |
|---|---|
| Payers adjudicate **line by line**, not claim by claim | Decisions attach to lines; claim state is derived |
| Cost-sharing is computed off the **allowed amount**, never the billed amount | Pricing is a distinct pipeline stage before any cost-sharing |
| "Applied to your deductible" is a **coverage determination, not a denial** | `outcome` and the amount breakdown are separate concepts |
| Denials carry **structured reason codes** (CARC/RARC) with a group code saying who absorbs the amount | Reason codes carry liability and an appealable flag |

The reason-code catalogue is our own, deliberately. X12 publishes roughly 194 CARCs; implementing them
verbatim would be cargo-culting a standard we cannot honour. A compact taxonomy that cites its
inspiration is more defensible and can be walked through in a live session.

---

## 2. Decision register

Format: decision · alternatives · why · consequence.

### D1 — Line items decide; claims aggregate
**Alternatives:** one decision per claim. **Why:** partial approval is the ordinary case in this domain,
and a claim-level decision cannot express "three paid, one denied, one in review" without inventing a
summary that discards the reasons. **Consequence:** claim state is a pure function of line states,
recomputed after every event and never assigned.

### D2 — `NEEDS_REVIEW` is a designed outcome
**Alternatives:** guess a default; infer intent; deny by default. **Why:** a wrongly processed claim
underpays a member who is owed money, or overpays irrecoverably, and either way corrupts the accumulator
so the error contaminates every later claim for that member. **Consequence:** anything the rules cannot
decide deterministically routes to a human. Partial automation with visible gaps beats full automation
with silent errors. Encoded as a standing rule in `.cursor/rules/project.mdc`.

### D3 — Coverage rules are typed objects seeded from data
**Alternatives:** a DSL; hard-coded conditionals. **Why:** a DSL is more impressive and less defensible —
it needs a parser, an error model, and a debugging story, all to be explained under time pressure. Typed
objects give the same "new plan is a data change" property. **Consequence:** a new *kind* of rule is a
code change, which is honest: it needs new pipeline logic and new tests regardless of storage.

### D4 — Decisions are append-only; appeals never mutate them
**Alternatives:** update the decision in place. **Why:** the audit trail is the product. Without it,
"the original decision stands as a historical record" is unenforceable and we cannot show what a member
was originally told. **Consequence:** the current decision is the highest `sequence` for a line; every
review or appeal appends.

### D5 — Accumulators are an append-only ledger
**Alternatives:** a mutable counter row. **Why:** overturned appeals must reverse prior consumption. On
a counter that is a read-modify-write that can drift or double-apply; on a ledger it is an append that
cannot be half-done. **Consequence:** balance is a `SUM`; before/after values for the explanation exist
by construction.

### D6 — The accumulator is a quantity against a limit, not a money counter
**Alternatives:** money counter with visit counts added later. **Why:** one abstraction serving
deductibles, dollar caps and visit caps proves the model generalises — and retrofitting counts onto a
money counter is the one genuinely expensive rework in this design. **Consequence:** built generic from
the first commit.

### D7 — Reviewers correct facts; they never touch computed values
**Alternatives:** allow editing any field. **Why:** a fact is verifiable against a document; a computed
value is the rules' output. A reviewer setting `plan_paid` through the re-adjudication path would produce
an override wearing the costume of a rules-derived decision, and the audit trail would claim the rules
concluded something they never did. **Consequence:** correctable — service code, service date, provider,
billed amount, diagnosis. Never — allowed, deductible, plan paid, denied, outcome.

**Superseded on manual overrides by D21.** D7 originally allowed financial overrides via a separate Path B;
D21 removes that from implementation scope. All monetary outcomes come from the rules engine after fact
correction, or the original decision stands on uphold.

### D8 — Confirmed and suspected duplicates are different things
**Alternatives:** auto-deny both, as real payers do. **Why:** an exact repeat within one claim is a data
error the system can rule on. The same match across claims may be legitimate repeated care — a bilateral
procedure, two sessions the same day — and auto-denying means confidently refusing to pay for care that
happened. **Consequence:** within-claim → denied; cross-claim → review. **A knowing departure from
industry practice**, recorded here so it is not mistaken for ignorance of the convention.

### D9 — Functional core, imperative shell
**Alternatives:** service classes with injected repositories; an ORM-centric design. **Why:** three
requirements collapse into one choice — determinism becomes structural rather than maintained by
discipline, domain tests need no database (so they are fast enough to write first, which the git history
must show), and there is one file to open when someone asks where the deductible is applied.
**Consequence:** hand-written row mapping, accepted deliberately. It also makes retry-by-re-adjudication
trivially safe, which §4 depends on.

### D10 — Plain `sqlite3`, no ORM
**Alternatives:** SQLAlchemy Core or ORM. **Why:** with a pure dataclass domain, an ORM's main benefit —
not writing mapping code — is precisely what would compromise D9. A hand-written `schema.sql` is also a
readable artifact this documentation can point at. **Consequence:** more plumbing, zero dependencies, no
magic to explain live.

### D11 — No `units` on line items
**Alternatives:** a `units` field. **Why:** with units, a visit limit permitting 2 of 5 must split a
line's allowed amount proportionally — introducing division, rounding, and a rounding policy to defend.
**Consequence:** three physio sessions are three lines. Every amount comes from addition, subtraction or
`min` on integers; **there is no rounding anywhere in the system.**

### D12 — The annual dollar limit caps plan payment, not allowed amount
**Alternatives:** count allowed amount against the limit. **Why:** a benefit maximum limits the insurer's
exposure; the deductible is the member's own money. Charging a member's own spending against the plan's
cap would exhaust the benefit faster than the plan actually promised. **Consequence:** the deductible
portion does not consume the benefit limit.

### D13 — One deductible per policy per plan year
**Alternatives:** per-benefit deductibles. **Why:** the common real design, and it creates cross-benefit
interaction — a physio claim consumes the deductible that changes the outcome of a later diagnostics
claim. Per-benefit deductibles are more machinery demonstrating less, since benefits never affect each
other. **Consequence:** accumulator scope `DEDUCTIBLE` is policy-wide. The **amount** lives on
`Plan.deductible` (D26), not on `Policy`.

### D14 — Correctness over throughput on concurrency
See §4 — the trade-off with the most operational consequence.

### D15 — A claim has two lifecycles: adjudication and settlement
**Alternatives:** the single chain the problem statement sketches (`submitted → under review →
approved/denied → paid`); or making `PAID` non-terminal; or refusing post-payment disputes. **Why:** the
single chain contradicts itself as soon as disputes are real. A member disputing a *denied* line on a
claim already paid for its *approved* lines is the common case, and if that dispute succeeds the plan
owes more money on a claim in a terminal state. The contradiction exists because one field was answering
two independent questions — *what did we decide* and *what have we paid*. **Consequence:** two derived
fields instead of one. The awkward case then needs no special handling: adjudication returns to
`UNDER_REVIEW` while settlement stays `SETTLED`; if the appeal succeeds, `payable` rises and settlement
becomes `DUE` by itself. A supplementary payment is just another payment record. `OVERPAID` exists as an
anomaly the system surfaces rather than corrects, since there are no clawbacks.

This was found while writing the state machines, not while scoping — worth recording as evidence that
drawing the diagrams did work that prose had not.

### D16 — `NEEDS_REVIEW` does not consume accumulators
**Alternatives:** commit partial consumption while a line is in review; block adjudication of sibling
lines until review clears. **Why:** committing consumption before a terminal decision risks corrupting
accumulators if the review outcome changes the facts or keys (see D19). **Consequence:** all lines are evaluated on submit, but a line in `NEEDS_REVIEW` posts **no** ledger
entries. Terminal siblings (`APPROVED`, `PARTIALLY_APPROVED`, `DENIED`) **do** post on initial submit.
`payable` sums `plan_paid` from current decisions that have a financial breakdown (D27) —
review lines and other pre-pricing exits contribute zero until resolved. A claim with any review line stays `UNDER_REVIEW`. When review or appeal resolves, the
**whole claim is re-adjudicated** deterministically. On re-adjudication: ledger entries from **superseded
terminal** decisions are **reversed** (compensating append); entries for **new terminal** outcomes are
**posted** — atomically (D19). Lines in `NEEDS_REVIEW` or `UNDER_APPEAL` never post entries, including
after a re-adjudication pass that leaves them still in review.

### D17 — Duplicate detection key
**Alternatives:** include `billed_amount` in the key; treat unresolved review lines as duplicate anchors.
**Why:** billed amount can legitimately differ on repeat care; unresolved lines have no stable outcome to
anchor against. **Consequence:** suspected duplicate = `member_id + provider_id + service_code +
service_date` (billed amount excluded). Cross-claim match → `NEEDS_REVIEW`. Lines still in `NEEDS_REVIEW`
are **not** used as duplicate anchors.

### D18 — Re-adjudication uses the original policy version
**Alternatives:** always use current plan; silently pick latest on re-run. **Why:** a newer plan version
must not silently change the outcome of an ordinary dispute or review resolution — that would be a
retroactive change without the explicit workflow. **Consequence:** normal re-adjudication (Path A, uphold
re-run) uses the `plan_version` stamped on the original adjudication. Applying a different version is a
**separate deferred workflow** (retroactive policy change detection, `scope.md` §9) and requires an
explicit decision to apply a different version — not in this implementation.

### D19 — Plan-year correction reverses prior accumulator entries
**Alternatives:** leave old entries in place; delete entries. **Why:** append-only ledger (D5); a
`service_date` correction can move a line to a different plan year and therefore a different accumulator
key. **Consequence:** if fact correction changes an accumulator key, previously committed entries for the
superseded decision are reversed via compensating append-only entries; the corrected re-adjudication
posts new entries under the new key. Reversal and repost occur in **one transaction**.

### D20 — Payments must equal exact payable
**Alternatives:** allow partial payments; allow overpayment with change. **Why:** partial pay leaves
settlement state ambiguous; overpay creates `OVERPAID` through API sloppiness rather than a genuine
appeal outcome. **Consequence:** a payment request must equal the claim's current `payable` exactly;
otherwise rejected.

### D21 — No arbitrary human computed-value overrides
**Alternatives:** Path B with reviewer-set `plan_paid` and outcome. **Why:** manual financial overrides
are non-deterministic, bypass the rules engine, and produce decisions the audit trail cannot distinguish
from rule-derived ones unless heavily instrumented — exactly the failure mode D7 was written to prevent.
**Consequence:** reviewers may correct **claim facts only**. Allowed, deductible, benefit utilisation,
member responsibility, plan payment, reason codes, and outcomes are **never** manually set. After fact
correction, the deterministic engine computes the new decision. **Manual financial/computed-value
overrides are outside implementation scope** — future work if needed, with explicit `HUMAN_OVERRIDE`
labelling and separate audit requirements.

Dispute/review resolution therefore has two modes only:
- **Correct facts and re-adjudicate** (whole claim, original plan version) — available for
  `NEEDS_REVIEW` and for disputes
- **Uphold** (dispute-only; re-adjudication confirms original outcome unchanged). Recorded on
  `ReviewResolution`; the `LineDecision` keeps the RULES reason code (D28, D29)

### D22 — Submission idempotency deferred
**Alternatives:** idempotency keys on `POST /claims`. **Why:** correct and valuable, but not load-bearing
for demonstrating domain modelling within the take-home time budget. **Consequence:** a client retry after
an unknown server outcome may create a duplicate claim. Documented as accepted risk; README must not advise
blind retry without checking claim state first.

### D23 — Iterative review resolution on one endpoint
**Alternatives:** one-shot resolve only; separate endpoint per attempt. **Why:** fact correction is
often iterative — a reviewer may supply a service code that is still unknown, then a valid one on a
second attempt. Blocking after the first failed re-adjudication would leave no in-scope path forward
without manual overrides (D21). **Consequence:** `POST /reviews/{line_id}/resolve` is **idempotent in
shape but iterative in use** — the same endpoint accepts repeated fact-correction attempts until
re-adjudication produces terminal outcomes for all lines under review, or the reviewer upholds (on
dispute). Each call is a separate resolution event recorded in `ReviewResolution`.

### D24 — Every re-adjudication pass appends a new `LineDecision`
**Alternatives:** update decision in place when still `NEEDS_REVIEW`; skip append if outcome unchanged.
**Why:** append-only audit trail (D4); a second `NEEDS_REVIEW` after correction is a **different**
decision — different facts, different gate that fired, different reason/trace — even if the outcome
label is the same. **Consequence:** each whole-claim re-adjudication triggered by review resolution
appends new `LineDecision` rows (incrementing `sequence`) for every line re-evaluated. A line that
remains `NEEDS_REVIEW` still gets a new decision record with its **current** reason code, trace, and
corrected inputs. Prior decisions stay immutable.

### D25 — Closing review as "permanently undecidable" is out of scope
**Alternatives:** terminal `DENIED` with `REV_UNRESOLVED`; manual override to force-close. **Why:**
declaring a claim permanently undecidable without a rules-derived terminal outcome is a judgement call
that cannot be expressed as corrected facts — the same class of problem D21 removed from scope. Without
it, a line can remain in `NEEDS_REVIEW` indefinitely if facts never become sufficient. **Consequence:**
**no in-scope action** closes a review as permanently undecidable. The claim stays `UNDER_REVIEW` until
fact correction yields a terminal rules outcome (`APPROVED`, `PARTIALLY_APPROVED`, `DENIED`) or a
dispute is upheld. Uphold cannot close a `NEEDS_REVIEW` line that has no dispute (D28). **Future work:**
explicit "close unresolved" with a terminal denial reason (e.g. `REV_UNRESOLVED`) or a governed manual
disposition path — documented in §6 and `scope.md` §9.

### D26 — `Plan.deductible` is the single source of truth
**Alternatives:** duplicate `deductible` on `Policy`; allow a policy-level override. **Why:** a policy is
an instance of a plan bounded in time; the deductible is a plan promise, not a per-enrolment override.
Two fields would be two sources of truth. **Consequence:** `Policy` holds membership dates only. The
deductible **amount** is `Plan.deductible`. Consumption remains per member per plan year (D13).

### D27 — Money conservation applies only to priced decisions
**Alternatives:** require a four-way amount split on every `LineDecision`, including `REJECTED` and
`NEEDS_REVIEW`. **Why:** pre-pricing exits never compute an allowed amount; inventing
`denied_amount = billed` would dress a validation outcome as financial adjudication. **Consequence:**
the invariant `billed == above_allowed + deductible_applied + plan_paid + denied_amount` is a property
of decisions that reach pricing / financial adjudication (gates 7–9). Claim `REJECTED`, `NEEDS_REVIEW`,
and denials that terminate before pricing have **no** amount breakdown. `payable` sums `plan_paid` only
from current decisions that have a breakdown; others contribute zero.

### D28 — Uphold is dispute-only
**Alternatives:** allow uphold to close a `NEEDS_REVIEW` line with no dispute. **Why:** that would close
review without facts and without a rules-derived terminal outcome — the same class of judgement D25
deferred. A dispute challenges a terminal decision; upholding confirms it. A `NEEDS_REVIEW` line has no
terminal decision to confirm. **Consequence:** `mode=uphold` is valid only when an open dispute exists
on the line. `NEEDS_REVIEW` without a dispute exits only by correcting facts and re-adjudicating.

### D29 — Uphold is not a `LineDecision` reason code
**Alternatives:** `HUM_UPHELD` on the resulting `LineDecision`. **Why:** that would replace the
deterministic rules reason (e.g. `DEN_EXCLUDED`) with a process event, and the audit trail would no
longer say why the plan said no. D21 requires all monetary outcomes `source=RULES`. **Consequence:**
`HUM_UPHELD` is removed from the reason catalogue. `ReviewResolution.mode` records that the reviewer
upheld. The appended `LineDecision` carries the RULES reason the engine produces.

### D30 — Gemini extracts facts; the engine decides
**Alternatives:** let Gemini produce coverage outcomes, amounts, or explanations; put a Gemini client
in the domain layer; skip unstructured intake entirely with no recorded boundary. **Why:** an LLM is
non-deterministic. Using it to decide coverage, pricing, deductible, limits, payment, outcome, or
reason codes would make the same claim pay differently on two runs — the failure mode D2 and
`.cursor/rules/project.mdc` exist to prevent. Extraction/normalization is a bounded, reviewable
mapping into existing `Claim` fields; adjudication stays a pure function of those fields. **Consequence:**

- Pipeline (implemented): raw claim → Gemini extraction → structured / schema validation →
  canonical `Claim` → deterministic adjudication → decision + explanation.
- Gemini must never determine coverage, pricing, deductible, limits, payment, outcome, reason codes,
  or authoritative explanations.
- Gemini lives in infrastructure / application (`gemini_extractor.py`, `claim_extractor.py`).
  `app/domain/` has no Gemini dependency.
- Google Gemini API; `GEMINI_API_KEY` from environment / secrets only; never hard-coded or logged.
- **[PROPOSED]** default model `gemini-2.5-flash`; **[PROPOSED]** temperature `0`.
- `claim_id` and `submitted_at` are supplied by the caller; they are not extracted from Gemini.
- `quantity` is not extracted or mapped — `ClaimLine` has no quantity field (D11). Treating quantity
  as a billed fact would be a future domain-model decision.
- Already-structured claims bypass Gemini.
- Final explanations come from deterministic reason codes / templates, not Gemini.
- Domain tests never require live Gemini; mock the client in extraction / integration tests.
- The extractor currently sends the full raw claim text. PHI minimization / redaction is
  **[DEFERRED]** (see §7). Do not log raw claim text, prompts, responses, or the API key.

Failed extraction and Gemini unavailability are **pre-adjudication errors** (D31), not domain
`NEEDS_REVIEW`. After a canonical `Claim` exists, fact correction + re-adjudication (D7, D21) is
unchanged.

This is a different LLM use from retroactive-change *triage* in §6 / `scope.md` §9.1. Both share the
same rule: the LLM never computes a number the member is paid.

### D31 — Failed Gemini extraction is a pre-adjudication error
**Alternatives:** create a `Claim` and route to `NEEDS_REVIEW`; invent an extraction reason code
(e.g. `REV_EXTRACTION_FAILED`); treat failure as claim `REJECTED`. **Why:** extraction runs before
a canonical `Claim` exists. `NEEDS_REVIEW` and `REJECTED` are engine outcomes on a claim that
already entered adjudication. Inventing a reason code would dress an intake failure as a coverage
decision. Gemini being down is an infrastructure failure, not a coverage question. **Consequence:**
invalid / insufficient Gemini output raises `ClaimExtractionValidationError`; Gemini / API
unavailability raises `ClaimExtractionApiError`. No canonical `Claim` is created. No
`LineDecision` is written. No new adjudication reason code is added. Callers see an application /
infrastructure error — not a domain review state.

---

## 3. Deliberate departures from real-world practice

Places where we knowingly differ from how a real payer behaves. Each is a choice, not a gap.

| Departure | Reasoning |
|---|---|
| Cross-claim duplicates go to review rather than auto-denial (D8) | Escalating ambiguity beats confidently refusing to pay for care that may have happened |
| `above_allowed` is the **member's** cost, not a provider write-off | With a provider contract the provider absorbs it and the member never sees it. We reimburse members directly, so there is no contract to absorb it — same arithmetic, different liability party, and the explanation says so honestly |
| No coinsurance or copay; deductible met ⇒ plan pays 100% of allowed | A simplified plan design, chosen to keep scope coherent. Named plainly here because an unexplained gap reads as an oversight |
| Our own reason-code taxonomy rather than X12 CARCs | See §1 |

---

## 4. The trade-off with operational consequences: correctness over throughput

**The assumption, stated plainly: we prioritised never overspending a limit over the ability to
adjudicate claims in parallel. Every adjudication in the system serialises against every other — even
when the claims concern unrelated members and unrelated benefits.**

### 4.1 What we did

Two claims for the same benefit, adjudicated simultaneously against ₹2,000 of remaining annual limit,
will each read ₹8,000 consumed, each conclude ₹2,000 is available, and each pay it. The plan pays
₹12,000 against a ₹10,000 limit, and the member's accumulator is permanently wrong from then on. This
write-skew race is the most damaging bug this system could ship, because it produces a wrong number
*quietly*.

Three layers prevent it:

1. **The write lock is taken before the balances are read** (`BEGIN IMMEDIATE`). SQLite permits one
   write transaction database-wide and guarantees that once `BEGIN IMMEDIATE` succeeds, nothing later in
   that transaction fails with `SQLITE_BUSY`. The second claim cannot begin until the first commits, so
   it reads ₹10,000 consumed and denies correctly.
2. **A closing invariant** refuses to commit any decision that would push a balance past its limit,
   routing to `NEEDS_REVIEW` instead. This is the safety rule turned on our own concurrency control: if
   the locking is ever wrong, the system stops rather than paying wrong.
3. **Retry by full re-adjudication**, never by patching the earlier result — the correct answer genuinely
   differs once the other claim has committed. Safe because the engine is pure (D9).

This was originally scoped as a documented limitation. That was wrong: it assumed the fix required row
locking or optimistic version columns, when SQLite's single-writer model makes it about thirty lines.
A correctness bug does not get documented away when the fix is that cheap.

### 4.2 What we gave up

Throughput. The lock is database-wide, so two claims for two different members with no shared
accumulator still queue behind each other. The contention is *entirely artificial* — it comes from
SQLite's locking granularity, not from any real conflict between the claims.

Worth sizing honestly rather than assuming: an adjudication transaction here is a few milliseconds, so
this ceiling sits in the low hundreds of claims per second. That is above what many mid-size payers
process in real time, so **the limitation may never actually bind.** The first production step is to
measure, not to optimise.

### 4.3 How we would productionise it

The correctness mechanism is already production-grade and portable — an append-only ledger, an
invariant checked before commit, and a pure engine that is safe to retry. **What changes is the locking
granularity, not the design.** In order of what we would actually do:

1. **Measure first.** Establish whether global serialisation binds at real volumes. Optimising an
   unmeasured bottleneck is how correctness gets traded away for nothing.
2. **Move to a database with row-level locking** (Postgres) and lock only the accumulator keys a claim
   actually touches: `SELECT ... FROM accumulators WHERE key = ANY(...) FOR UPDATE`. Contention then
   scopes to member + benefit + plan year. Since two claims for the *same member and same benefit* at
   the *same instant* are rare, this yields close to full parallelism with no change to the domain layer.
3. **Or use optimistic concurrency** — a version column on a materialised balance, updated with
   `WHERE version = :read_version`; zero rows affected means conflict, so roll back and re-adjudicate.
   Preferable under low contention because no lock is held across the adjudication. Made cheap by the
   pure engine (D9), which is safe to re-run.
4. **Materialise the balance** alongside the ledger, updated in the same transaction. The ledger stays
   the source of truth for audit; the materialised row is what gets locked or version-checked, so we stop
   summing a growing ledger on every claim.
5. **Idempotency keys on submission**, so a client retry after a timeout cannot adjudicate twice.
6. **Partition by member** if a single database ever stops being enough — route claims through a queue
   partitioned on `member_id`. That gives strict per-member ordering with full cross-member parallelism,
   because the accumulator key always contains the member.
7. **Keep the invariant, and add reconciliation.** The pre-commit check stays regardless of locking
   strategy — it is what converts a future concurrency bug into a refusal to pay rather than an
   overpayment. Add a periodic job recomputing balances from the ledger and alerting on drift.

What would *not* change: the ledger, the invariant, the pure engine, the domain model. That is the point
of the trade — the thing we gave up is swappable infrastructure, and the thing we protected is the part
that would be expensive to get wrong.

---

## 5. Assumptions about the domain

Real-world complexity deliberately flattened. Each is a modelling choice, not an oversight.

1. **One member per policy.** No dependents, no family plans, no aggregate family accumulators.
2. **One active policy per member.** No coordination of benefits, no secondary payer.
3. **Plan year = calendar year**, uniform across policies.
4. **All providers are equivalent.** No network status, no per-provider negotiated rates; the fee
   schedule is plan-level.
5. **Single currency, integer minor units.** No rounding policy is needed because no division occurs (D11).
6. **Concurrent submissions are safe but fully serialised** (§4).
7. **Members, policies, providers and fee schedules arrive via seed fixtures**, since enrolment and
   account management are out of scope.
8. **Deductible met ⇒ the plan pays 100% of the allowed amount.** No coinsurance, no copay, no
   out-of-pocket maximum.
9. **The claim is the unit of submission and payment; the line item is the unit of decision.**
10. **A dispute concerns one line-item decision**, not a whole claim.
11. **Payments are recorded, not made.** A `Payment` row is a fact that money moved — there is no
    gateway, no reconciliation, no reversal. Payments are append-only and never negative.
12. **A payment must equal payable exactly** (D20). No partial or excess payments via the API.
13. **Review/dispute resolution never manually sets monetary outcomes** (D21). Facts in; rules decide.
14. **Submit idempotency is not implemented** (D22). Retries after unknown outcomes may duplicate claims.
15. **Review resolution is iterative** (D23) — same endpoint, multiple fact-correction attempts.
16. **No permanent "close as undecidable"** (D25) — future work; claims may stay `UNDER_REVIEW` until
    facts yield a terminal rules outcome.
17. **Deductible amount lives on `Plan`** (D26), not on `Policy`.
18. **Money conservation applies only to priced decisions** (D27). Pre-pricing exits have no amount
    breakdown.
19. **Uphold is dispute-only** (D28). `NEEDS_REVIEW` without a dispute is resolved by fact correction.
20. **Uphold is recorded on `ReviewResolution`**, not as a `LineDecision` reason (D29).
21. **Gemini extracts and normalizes facts only** (D30). The engine remains the source of truth.
    Domain has no Gemini dependency. Unstructured HTTP submit is still deferred.
22. **Failed or unavailable Gemini extraction is a pre-adjudication error** (D31) — not
    `NEEDS_REVIEW`, not a new reason code.
23. **`claim_id` and `submitted_at` are caller-supplied**, not extracted. **`quantity` is not
    extracted** (D11).
24. **Full raw claim text is sent to Gemini today.** PHI minimization / redaction is deferred.

---

## 6. What we did not build

Excluded by the assignment: authentication, enrolment, account management, notifications, dashboards,
admin panels, multi-tenancy and role-based access.

Excluded by us, with reasons in `scope.md` §5: coordination of benefits, corrected-claim resubmission,
EDI X12 / CMS-1500 formats, real ICD-10 / CPT validation, fraud detection, family plans, balance billing
and tiered networks, multi-currency, review work queues and SLAs, refunds and clawbacks, provider-submitted
claims.

Coverage rules considered and cut, in `scope.md` §3.2: prior authorisation, network-status pricing,
timely-filing and appeal-filing windows, waiting periods, per-visit caps, lifetime maximums. Each tests a
rule shape the model already demonstrates.

**Deferred rather than cut** (`scope.md` §9):

| Item | What we kept | Why deferred |
|---|---|---|
| Retroactive change detection (D18) | `plan_version` on every decision | Needs explicit version-apply workflow; must not silently change ordinary re-adjudication |
| Manual financial/computed-value overrides (D21) | Fact correction + rules engine | Non-deterministic; needs `HUMAN_OVERRIDE` audit model — future scope |
| Close review as permanently undecidable (D25) | Lines can remain in `NEEDS_REVIEW` indefinitely | Judgement without facts; needs terminal disposition reason or governed override — future scope |
| Submission idempotency (D22) | — | Retry may duplicate claims — future scope |
| Unstructured HTTP submit shape | Gemini extractor (D30) | New field vs new endpoint — not built |
| PHI minimization / redaction of Gemini payload | Full raw text currently sent; no logging of text/key | Field-list redaction is future work |
| Persistence of raw text / extraction artifacts | Canonical `Claim` only | Audit of the raw blob is future work |

Retroactive policy changes: detect, surface, route to review; never auto-reverse. If an LLM is ever used
there, it may triage and propose; a human approves; deterministic rules compute every number.

Unstructured intake uses Gemini the same way: **extract facts, never decide**. That is D30, not a
second adjudication engine. Failed extraction is a pre-adjudication error (D31).

---

## 7. Sensitive data posture

**[REQ]** *"This is sensitive health data — your design decisions should reflect that."* Authentication
and access control are explicitly out of scope, so this cannot mean building security. What we did:

- **Member identity and clinical data are separate entities.** Diagnosis codes live on `ClaimLine`, never
  on `Member`, so the join between "who this is" and "what is wrong with them" is explicit.
- **No PHI in logs or error messages** — identifiers only. The most common real leak, and nearly free
  to avoid. **[DECIDED]** The same rule applies to Gemini (D30): do not log raw claim text, prompts,
  Gemini responses, or `GEMINI_API_KEY`. The extractor currently sends the **full raw claim text**.
  A minimization / redaction strategy is **[DEFERRED]** and is not implemented.
- **Every decision and state transition is audited**, with the actor recorded. Review resolutions
  (fact corrections, uphold) are distinguishable from rules-derived decisions via `ReviewResolution` and
  `LineDecision.source=RULES` on all monetary outcomes.

Not built, and named so it is not mistaken for an oversight: encryption at rest, field-level encryption,
access control, consent management, data retention and deletion, and de-identification for non-production
use. In a real deployment these would matter more than anything in §4.

---

## 8. Open

No open *adjudication* design decisions from D1–D31. Remaining items from the pre-implementation
review are **deferred to the implementation slice that needs them**, not product-scope questions:

- Future service date — gate 0
- Zero billed amount — validation / financial adjudication
- Double dispute and dispute of a superseded sequence — dispute use case (recommended: reject both)
- `Dispute.state` values — dispute domain
- Line state vs decision outcome — state derivation slice
- Unknown provider / unmapped benefit — validation / catalogue lookup; do not invent a rule in advance
- `INFO_COVERED` appealability — dispute use case
- `OVERPAID` vs limit invariant I2 — still a documented gap; pick a reconciliation stance when
  implementing settlement after appeal

D30 / D31 closed the extraction-slice questions (pre-adjudication failure, no quantity, caller
identity fields, Gemini-unavailable as an API error). Still **[DEFERRED]**:

- Unstructured HTTP shape
- Persistence of raw unstructured text and extraction artifacts
- PHI minimization / redaction of the Gemini payload
- Retries / timeouts beyond the current client call

**[PROPOSED]** (not elevated): default model `gemini-2.5-flash`; temperature `0`.

This document and `docs/domain-model.md` were written before implementation, and every claim in them is
re-verified against `app/` before submission. Anything the code does differently gets corrected here
rather than quietly tolerated.
