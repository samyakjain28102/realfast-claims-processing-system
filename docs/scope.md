# Scope

Companion to `docs/problem-understanding.md`. That document establishes *what the domain is*; this one
establishes *how much of it we are building*.

**[REQ]** *"A system that does 3 things well beats one that does 10 things poorly."* Scope is being
graded here, not just tolerated — every item admitted has to earn its place, and every item cut has to
have a stated reason. An unexplained gap reads as an oversight; an explained one reads as judgement.

## The test applied to every item

> Does this exercise **domain decomposition, rule representation, state management, edge-case thinking,
> or explanation capability** — the five things being scored? If not, it is out, however realistic it is.

A second filter follows from `.cursor/rules/project.mdc`: anything that cannot be decided
**deterministically** is not a feature we automate. It is either a `NEEDS_REVIEW` trigger or it is out.

**Status key:** ✅ in scope · ❌ out of scope · 🕓 deferred to future work (§9)
**Cost:** S = under an hour · M = a few hours · L = half a day or more

All decisions in §3 are resolved. The reasoning is kept alongside each one, including for the items
that were cut — a cut with a reason is evidence of judgement; a cut without one looks like an omission.

---

## 1. Mandated in scope

**[REQ]** Straight from `problem_statement.md`. Not negotiable, not re-litigated here.

| Capability | Status |
|---|---|
| Accept claim submissions with line items | ✅ |
| Adjudicate **each line item** against coverage rules to produce a payable amount | ✅ |
| Track lifecycle states for **both** the claim and the line item | ✅ |
| Produce an explanation for **every** decision | ✅ |
| Members disputing decisions | ✅ |
| An interface to demonstrate it — REST API (decided) | ✅ |

Plus the choices already made in `problem-understanding.md` §7.1: typed rules seeded from data,
allowed-amount + deductible + annual limits, `NEEDS_REVIEW` as a real outcome, separate immutable
appeal entity, reimbursement direct to member, SQLite, retroactive changes detected but never
auto-resolved.

---

## 2. Required to make the mandated flows actually work

These aren't optional additions — the mandated capabilities are incoherent without them. Listed so the
scope is honest about its true size.

| Item | Cost | Why it's structural |
|---|---|---|
| Seed data: members, policies, providers, benefit catalogue, fee schedule | M | Enrolment and account management are out of scope, so seeded fixtures are the *only* way data exists. |
| Service code → benefit category mapping | S | Rules attach to benefit categories, not to individual procedure codes. Without this there is nothing to look rules up by. |
| Fee schedule → allowed amount | S | Cost-sharing is computed off the allowed amount. Without it the money model is wrong at the root. |
| Accumulators (member + benefit + plan year) | M | The system's memory. Deductible and annual limits are meaningless without it. |
| Structural validation of the submitted claim | S | An incoherent claim must never reach the rules engine and produce a confident wrong answer. |
| Reason code taxonomy + human-readable messages | M | Explanation is a scored signal, not logging. |
| Decision trace (which rule, which numbers, accumulator before/after) | M | This *is* the explanation-capability signal. |
| Audit trail of decisions and state transitions | S | Doubles as the PHI-handling answer and the retroactive-change evidence. |
| Domain tests written first | L | **[REQ]** Git history must show tests before or alongside code. |
| `README.md` with runnable setup, seed, and demo walkthrough | M | **[REQ]** *"If it doesn't run, the tests don't count."* |

---

## 3. The actual scoping decisions

Recommendations are mine; the calls are yours.

### 3.1 Pre-adjudication gates

**[RESEARCH]** Real adjudication is a sequence of gates before any arithmetic happens. Each gate is a
cheap, deterministic check that produces a distinct, explainable outcome — which makes this the highest
domain-signal-per-hour area in the whole system.

| Gate | Status | Cost | Reasoning |
|---|---|---|---|
| **Member eligible on the date of service** (policy effective/termination dates) | ✅ | S | One date comparison, and it encodes a real distinction most naive models miss: eligibility is judged on the *service* date, not today. |
| **Duplicate detection** (same member + provider + service + date) | ✅ | M | **[REQ]** The candidate instructions use this as their *example* of a good domain test. SQLite was chosen partly for it. Effectively mandatory. |
| **Unknown / unmapped service code** → `NEEDS_REVIEW` | ✅ | S | Direct application of the safety rule: we cannot price what we cannot classify, so we must not try. |
| **Incoherent claim** (future service date, line totals disagreeing, negative amounts) → reject or `NEEDS_REVIEW` | ✅ | S | Same principle, applied at intake. |
| **Timely filing window** (submitted more than N days after service) | ❌ | S | Cut. Deterministic and realistic, but it is one more instance of a date comparison the eligibility gate already demonstrates. No new structure for the reader to learn from. |

### 3.2 Coverage rule types

This is the **rule representation** signal. The question is how many *shapes* of rule we support —
each new shape tests whether the abstraction actually generalises, which is more valuable than more
instances of the same shape.

| Rule type | Status | Cost | Reasoning |
|---|---|---|---|
| Covered / not covered per benefit category | ✅ | S | The base case. |
| **Explicit exclusion** (e.g. cosmetic procedures) | ✅ | S | Cheap, and "excluded by your plan" is a genuinely different denial reason from "not a listed benefit". Different reason codes, different appeal rights. |
| Annual **dollar** limit per benefit | ✅ | M | Already decided. Produces the limit-exhaustion partial-payment case. |
| Annual **visit count** limit (e.g. 12 physio sessions/year) | ✅ | S–M | Proves the accumulator abstraction generalises beyond money — a *second shape* of limit running against the same machinery. This is why the accumulator must be designed generically from the start rather than as a dollar counter. |
| **Prior authorisation required** | ❌ | M | Cut. Deterministic and realistic, but it is a third gate alongside eligibility and exclusions, testing the same "check a precondition, deny with a reason" shape we already have. |
| **Network status** affecting the allowed amount | ❌ | M–L | Cut. Adds a whole pricing *dimension* (per-provider contracted rates) for a payoff that is realism rather than new domain structure. Every provider is treated identically; the fee schedule is plan-level. |
| **Medical necessity** as an automated rule | ❌ | — | Clinical judgement is not deterministic. The safety rule forbids guessing it. If we model it at all it is only as a `NEEDS_REVIEW` trigger, never as an automated denial. |
| Waiting periods, per-visit caps, lifetime maximums | ❌ | — | More instances of mechanisms annual limits already demonstrate. No new signal. |

### 3.3 Accumulators

| Item | Status | Cost | Reasoning |
|---|---|---|---|
| Dollar accumulator per member + benefit + plan year | ✅ | M | Core. |
| Count accumulator (visits used) | ✅ | S | Follows §3.2. The accumulator is therefore a *quantity* against a limit, where the quantity happens to be money or visits — not a money counter with a count bolted on. |
| Plan year = calendar year | ✅ | S | Simplifying assumption; policy-anniversary years add date maths and no new domain insight. Documented. |
| Correct accumulator movement when an appeal changes an outcome | ✅ | M | **Non-negotiable.** If an overturned denial pays without consuming the limit, accumulators drift and silently corrupt every later claim for that member — exactly the failure the safety rule exists to prevent. |
| Transactional read-modify-write within one adjudication | ✅ | S | A limit must not be consumed twice. The write lock is taken **before** the balances are read — see `technical-plan.md` §4.1. |
| **Correct concurrent adjudication** (two claims racing for the same remaining limit) | ✅ | S | Upgraded from "documented limitation" once it became clear the fix is `BEGIN IMMEDIATE` plus a closing invariant — roughly 30 lines. A limit that can be overspent by two simultaneous claims is a correctness bug, and correctness bugs don't get documented away when the fix is this cheap. |
| Fine-grained concurrency (per-accumulator row locking, optimistic version columns) | ❌ | L | Unnecessary: SQLite permits one writer database-wide, so serialising whole adjudications *is* the correct granularity. The remaining limitation is throughput, not correctness (§9.2). |

### 3.4 Disputes

Mandated, but *how a dispute closes* is undecided and is a real modelling question.

| Item | Status | Cost | Reasoning |
|---|---|---|---|
| Member files a dispute against a specific line-item decision | ✅ | M | Mandated. Disputes attach to the line, because that's where the decision was made. |
| Original decision stays immutable; the appeal is a separate record | ✅ | — | Already decided. Preserves the audit trail. |
| Line enters an "under appeal" state; claim can't settle while an appeal is open | ✅ | S | Consistent with claim state being derived from line state. |
| **Appealable vs non-appealable reason classification** | ✅ | S | **[RESEARCH]** Judgement-based denials (necessity, exclusions, limits) are appealable; pure arithmetic ("this is your deductible") is not. A cheap flag on the reason taxonomy that adds real domain fidelity and lets the dispute endpoint reject incoherent appeals with a proper explanation. |
| Appeal filing window (e.g. 180 days from decision) | ❌ | S | Cut alongside the timely filing window, for the same reason. |
| **Resolution: correct facts and re-adjudicate, or uphold** | ✅ | M | See §3.4.1 — D21 removed manual financial overrides from scope |
| Multiple escalating appeal levels, external review | ❌ | — | One level demonstrates the concept. |

#### 3.4.1 How a review or appeal resolves

Anything in `NEEDS_REVIEW` or `UNDER_APPEAL` exits through one endpoint with **two modes** (D16, D21):

**Correct facts and re-adjudicate (Path A).**
The reviewer supplies corrected facts on the affected line(s) — service code, service date, provider,
billed amount, diagnosis. The system re-adjudicates the **whole claim** deterministically against the
**original policy version** (D18), posting ledger entries only for terminal outcomes. Changed facts +
unchanged rules = new decision; unchanged facts = same decision (not theatre — D19 may reverse ledger
entries if keys changed).

**Uphold (dispute-only, D28).**
The reviewer closes an **open dispute** without fact changes. The claim is re-adjudicated to confirm
the original outcome; `ReviewResolution` records `mode=uphold`; the appended `LineDecision` keeps the
RULES reason code (D29); the dispute record closes; no manual monetary override. Uphold on a
`NEEDS_REVIEW` line with no dispute is rejected — that line exits only by fact correction.

**Not in scope (D21, D25):** reviewers setting `plan_paid`, outcome, or reason codes directly. Judgement
that cannot be expressed as corrected facts remains in `NEEDS_REVIEW` until facts exist — or stays
upheld as denied on dispute. **Closing a review as permanently undecidable** without a terminal rules
outcome is **future work** (D25). Manual financial overrides are also future scope (D21).

**Iterative resolution (D23).** The resolve endpoint accepts **multiple attempts**. A reviewer may call
`POST /reviews/{line_id}/resolve` repeatedly with updated facts until re-adjudication produces terminal
outcomes, or uphold on a dispute. Each attempt is recorded; the claim stays `UNDER_REVIEW` while any line
remains in `NEEDS_REVIEW` or `UNDER_APPEAL`.

**Decision history on each attempt (D24).** Every re-adjudication pass appends new `LineDecision` records
(incrementing `sequence`) — including when a line **remains** `NEEDS_REVIEW`. The new record carries the
**current** reason code, trace, and corrected inputs. Prior decisions are never updated or deleted.

**Correctable fields (D7):** `service_code`, `service_date`, `provider_id`, `billed_amount`,
`diagnosis_code`. Never: allowed amount, deductible, plan paid, denied amount, outcome.

**Accumulator behaviour (D16).** Only `NEEDS_REVIEW` and `UNDER_APPEAL` lines post **no** ledger entries.
Terminal sibling lines **do** post on initial submit. On review/dispute resolution, whole-claim
re-adjudication **reverses** superseded terminal entries and **posts** new ones for new terminal outcomes
— atomically (D19). Lines that remain in review still post nothing.

### 3.5 Explanations

| Item | Status | Cost | Reasoning |
|---|---|---|---|
| Reason code + plain-English message on every decision, including approvals | ✅ | M | *Every* decision — an approval that can't explain its arithmetic is as opaque as an unexplained denial. |
| Our own compact taxonomy, explicitly CARC-informed and documented as such | ✅ | M | **[RESEARCH]** X12 publishes ~194 CARCs. Implementing them verbatim would be cargo-culting; a small honest taxonomy that cites its inspiration is more defensible and easier to walk through live. |
| Who absorbs each amount (member responsibility vs denied vs billed-allowed gap) | ✅ | S | **[RESEARCH]** "Applied to your deductible" is a coverage determination, not a denial. Collapsing them is a modelling error. |
| Decision trace: rule applied, inputs, amounts, accumulator before/after | ✅ | M | The evidence behind the sentence. |
| **Member-facing EOB summary for a claim** | ✅ | S–M | Aggregation over data we already have. Makes *"how do you explain to a member why something was denied"* concrete in one API call, and it is the strongest demo artifact available. |
| Provider remittance advice / 835 output | ❌ | — | We reimburse members directly; no provider payment leg exists. |

### 3.6 Retroactive changes

**Deferred to future work (§9).** Detecting them is the largest self-contained item on the list, and
demonstrating them needs a trigger that drifts toward the admin surface the assignment excludes. Cutting
it buys the time to make everything above solid, which is the trade the assignment explicitly rewards.

| Item | Status | Cost | Reasoning |
|---|---|---|---|
| Detect that a rule or eligibility change affects already-decided claims, and route them to `NEEDS_REVIEW` | 🕓 | M | Deferred. Documented in §9 with the reasoning and the intended design, rather than silently dropped. |
| Automatic re-adjudication, payment reversal, clawback | ❌ | — | Out regardless of the above. The system would surface the conflict; a human decides what it means. |
| **Record which rule/policy version produced each decision** | ✅ | S | **Kept even though detection is deferred.** It costs a field written at decision time and it is what makes the deferred feature possible later; retrofitting it means the history of every already-decided claim is unrecoverable. It also strengthens the audit trail we need anyway — "this claim was decided under version 3 of the plan" is part of a complete explanation. |

### 3.7 Sensitive health data

**[REQ]** *"This is sensitive health data — your design decisions should reflect that."* Authentication
and access control are explicitly out of scope, so this cannot mean building security. It means visible,
cheap, defensible choices — plus an honest statement of what we deliberately didn't build.

| Item | Status | Cost | Reasoning |
|---|---|---|---|
| No PHI in logs or error messages; identifiers only | ✅ | S | The most common real leak, and nearly free to avoid. |
| Audit trail of who/what decided each outcome and when | ✅ | — | Already structural (§2). |
| Model separates member identity from clinical data (diagnosis codes) | ✅ | S | A modelling stance rather than a feature — near-zero cost, and it signals the point was understood rather than merely acknowledged. |
| A short "PHI posture" section in `docs/decisions.md` naming what we skipped and why | ✅ | S | Turns an unbuilt requirement into demonstrated judgement. |
| Encryption at rest, field-level encryption, RBAC, consent management | ❌ | — | Auth and access control are explicitly out of scope. |
| Minimize / redact PHI sent to Gemini (D30) | 🕓 | S | Extractor currently sends full raw claim text. Do not log text, prompts, responses, or the key. Redaction strategy deferred (§9.3). |

### 3.8 Interface surface

Minimal set that exercises every in-scope flow. **[REQ]** They will clone this and run it.

| Endpoint | Status | Purpose |
|---|---|---|
| Submit a claim with line items | ✅ | Entry point; triggers adjudication. |
| Fetch a claim with all line decisions, amounts, and explanations | ✅ | The main demonstration surface. |
| List claims for a member | ✅ | Needed to show accumulator effects across claims. |
| File a dispute on a line-item decision | ✅ | Mandated flow. |
| Resolve a `NEEDS_REVIEW` line (facts only) or an appeal (facts, or uphold) — §3.4.1 | ✅ | The only exit from review. Uphold is dispute-only (D28). |
| Record a payment against a claim | ✅ | Advances the settlement lifecycle; records that money moved, with no payment system behind it. |
| Fetch the EOB for a claim | ✅ | The member-facing explanation, in one call. |
| Inspect a member's accumulators | ✅ | Makes limit exhaustion visible in the demo instead of implied. |
| Auto-generated OpenAPI docs | ✅ | Free with FastAPI. |
| Unstructured / free-text claim submit (HTTP shape) | 🕓 | Extractor exists (D30); new field vs new endpoint is still deferred. Structured `POST /claims` **bypasses Gemini**. |
| Web UI | ❌ | Time spent on what they told us not to build. |

---

## 4. Out of scope — stated by the assignment

**[REQ]** *"Building them will not improve your score."*

User registration / login / authentication · policy purchase or enrolment · member and provider account
management · email notifications and alerts · reporting dashboards and analytics · admin panels for
managing policies, members or providers · multi-tenant or multi-role access control.

---

## 5. Out of scope — our choice

Real parts of the domain we are deliberately not building. Each is a thing a reviewer might ask about,
so each has a reason.

| Excluded | Reason |
|---|---|
| Coordination of benefits (secondary payers) | Assumes a second insurer; multiplies the money model for no new modelling insight. |
| Corrected claims resubmitted as new claims | A whole second intake path with its own duplicate-detection problem. Note this is *not* the same as §3.4.1 Path A: corrections there happen inside an open review, on a bounded set of fields, under a reviewer — not as an unbounded new submission. |
| EDI X12 837 / 835, CMS-1500 / UB-04 formats | Serialisation formats, not domain modelling. Would consume hours and demonstrate nothing being scored. |
| Validation against real ICD-10 / CPT code sets | Requires licensed code sets. A small seeded catalogue proves the same rule-lookup behaviour. |
| Fraud, waste and abuse detection | Probabilistic by nature — directly against the determinism rule. |
| Dependents, family plans, aggregate family deductibles | One member per policy. Family accumulators are a genuinely interesting problem, but they duplicate accumulator machinery we'll already have demonstrated. |
| Balance billing, tiered networks, bundling / NCCI edits | Deep provider-contracting territory, far from the scored signals. |
| Multi-currency | Single currency, integer minor units. |
| Claim ageing / review SLAs / work queues | The reviewer *workflow* is out of implementation scope by decision. |
| Refunds, clawbacks, payment reversal | Money only moves forward — payments are append-only and never negative. If an appeal reduces an already-paid amount, the claim surfaces as `OVERPAID` for a human; recovering the money is a conversation, not a transaction we model. |
| Provider portal, provider-submitted claims | Members submit claims for reimbursement (decided). |

---

## 6. Simplifying assumptions

Each of these is a real-world thing being flattened. **[REQ]** They go in `docs/decisions.md`.

1. One member per policy; no dependents or family accumulators.
2. One active policy per member at a time; no COB, no secondary payer.
3. Plan year = calendar year, uniform for all policies.
4. All providers are treated identically; no network status, no per-provider rates. The fee schedule
   that determines the allowed amount is plan-level.
5. Single currency, amounts stored as integer minor units, rounding rule stated explicitly.
6. Concurrent claim submissions are safe but fully serialised — one adjudication at a time across the
   whole system, not just per member or per benefit.
7. Members, policies, providers and fee schedules arrive via seed fixtures.
8. Deductible met ⇒ plan pays 100% of the allowed amount (no coinsurance or copay) — carried over from `problem-understanding.md` §7.1.

---

## 7. Cut order if time runs short

Scope has already been trimmed hard, so this list is short. Cut from the top.

1. **EOB summary endpoint** (§3.5) — the data behind it still exists on the claim, so nothing is lost
   except the convenient shape.
2. **Accumulator inspection endpoint** (§3.8) — limit exhaustion becomes implied by the numbers rather
   than directly visible.
3. **Visit-count limits** (§3.2) — only if the generic accumulator turns out to be more expensive than
   expected. Cutting this weakens the rule-representation story, so it is a reluctant cut.

— everything else is load-bearing and cannot be cut without breaking the story —

Line-item adjudication · accumulators · allowed amount · deductible · annual dollar limits · exclusions ·
eligibility and duplicate gates · claim and line state machines · explanations with reason codes and
trace · disputes with both resolution paths · `NEEDS_REVIEW` routing.

---

## 8. The demo narrative

Coherence check: the scope above should tell one story end to end, not exhibit disconnected features.

1. **A clean claim** — multiple lines, all covered, deductible partly consumed, allowed amount below
   billed. Shows the money split and a full explanation.
2. **A mixed claim** — some lines paid, one denied by an exclusion, one hitting a limit boundary and
   paying partially, one routed to `NEEDS_REVIEW`. Shows line-level decisions, partial approval, and
   why the claim can't settle yet.
3. **A dispute** — the member appeals the denial. The original decision stays intact. The reviewer
   supplies corrected facts; the rules re-adjudicate the whole claim and the line now pays; or the
   reviewer upholds and the denial stands. Accumulators move correctly; the claim can settle when
   adjudication completes.

If an in-scope item doesn't appear in one of these three flows, it needs a reason to exist.

---

## 9. Deferred — designed for, not built

Not "forgotten" and not "out of scope forever". These are things we understand, have left room for, and
consciously did not build inside the time budget. **[REQ]** They belong in `docs/decisions.md` and
`docs/self-review.md`, where a calibrated gap-list earns more credit than polished completeness.

### 9.1 Retroactive change detection

**The problem.** A policy or coverage rule changes after claims have already been decided under the old
version. Some of those decisions would now come out differently. Real payers face this constantly —
backdated eligibility terminations, corrected plan documents, rules effective from a past date.

**Why it's deferred.** Detection means, on every rule change, evaluating already-settled claims against
the new version to find the ones that would now differ — a second adjudication path with its own
correctness burden. Demonstrating it also needs a way to change a rule at runtime, which drifts toward
the admin surface the assignment explicitly excludes. It is the single largest self-contained item
available to cut, and cutting it buys solidity everywhere else.

**What we kept so it stays possible.** Every decision records the rule/policy version that produced it
(§3.6). That is the expensive-to-retrofit half; without it, the history needed to detect anything is
simply absent.

**Intended design if built.** Detect, surface, route to `NEEDS_REVIEW`. Never auto-reverse, never
re-adjudicate silently, never claw back. The system's job is to say *"these 14 settled claims were
decided under a rule that has since changed"* — a human decides what that means.

**A note on using an LLM here.** This is the one place in the system where an LLM is genuinely
attractive: assessing what a rule change means for a settled claim is interpretive, unstructured, and
exactly the kind of triage that swamps human reviewers. It could summarise the delta between rule
versions, cluster affected claims by why they're affected, and draft the reviewer's summary.

But it has to be said plainly, because it cuts against the project's core rule: **an LLM must never
decide the outcome.** It is non-deterministic by construction — the same claim could be assessed two
different ways on two different runs, and a system that pays differently depending on sampling is
exactly the failure mode `.cursor/rules/project.mdc` exists to prevent. The money would be wrong
sometimes, and worse, wrong *unpredictably*, which is far harder to detect than wrong consistently.

So the boundary, if this is ever built: **an LLM may triage, summarise, cluster and propose. A human
approves. Deterministic rules compute every number.** The LLM's output is an input to a human's
judgement, never a decision the system acts on — the same shape as Path A in §3.4.1, where a human
supplies facts and the rules still do the arithmetic.

This is **not** the same as unstructured *intake* extraction (§9.3). Both uses share the rule: the
LLM never decides coverage, pricing, or payment.

### 9.2 Other deferred items

| Item | Why deferred, not cut |
|---|---|
| Concurrency **throughput** (§3.3) | Correctness is handled, not deferred: two claims can no longer both consume the same remaining limit. What is deferred is granularity — every adjudication serialises against every other, even when they touch unrelated members and benefits. Correct but unscalable. The fix on a real database is per-accumulator row locking or an optimistic version column, and the migration path is written down in `technical-plan.md` §4.1 rather than left to be rediscovered. |
| Family plans and aggregate accumulators (§5) | The accumulator abstraction would extend to it — scoping to member level is a data-shape simplification, not a modelling dead end. |
| **Close review as permanently undecidable** (D25) | A line can stay in `NEEDS_REVIEW` forever if facts never suffice. Future: terminal disposition (e.g. `REV_UNRESOLVED`) or governed manual close — requires an explicit design decision, not a silent default. |
| **Manual financial overrides** (D21) | See §9 deferred table in `decisions.md` §6. |
| **Unstructured HTTP submit / PHI redaction / raw-text persistence** (D30) | Extractor is built (§9.3). Remaining intake plumbing is deferred. |

### 9.3 Unstructured intake via Gemini (D30, D31)

**The problem.** Real claims often arrive as unstructured text, not as a validated `Claim` with
catalogued service codes. Mapping that text into line-item facts is interpretive. Computing coverage
and payment from those facts is not.

**What is built.** An extraction-only slice (`technical-plan.md` §10, build step 2a), completed
**before pricing**:

```
Raw claim
  → Gemini extraction
  → structured / schema validation
  → canonical Claim
  → deterministic adjudication
```

**[DECIDED]** Gemini is used only for extraction / normalization. It must **not** decide coverage,
pricing, deductible, limits, payment, outcome, reason codes, or authoritative explanations. The
domain engine remains the source of truth. The domain layer has no Gemini dependency. Google Gemini
API; `GEMINI_API_KEY` via environment only; never hard-code or log it. **[PROPOSED]** default model
`gemini-2.5-flash`; **[PROPOSED]** temperature `0`. `claim_id` and `submitted_at` are caller-supplied.
`quantity` is not extracted (D11). Failed or ambiguous extraction, and Gemini unavailability, are
**pre-adjudication errors** (D31) — not `NEEDS_REVIEW`, not a new reason code. After a `Claim`
exists, humans may correct facts and the engine re-adjudicates (D7). Final explanations come from
reason-code templates. Already-structured claims bypass Gemini. Domain tests must not require live
Gemini. The extractor currently sends the full raw claim text; do not log that text, prompts,
responses, or the API key.

**Still deferred:** unstructured HTTP shape, persistence of raw text / extraction artifacts, PHI
minimization / redaction of the Gemini payload, retries / timeouts.
