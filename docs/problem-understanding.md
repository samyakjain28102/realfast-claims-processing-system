# Problem Understanding (Non-Technical)

This document captures **what we are being asked to build and why**, in business language,
before any technical design happens. No schemas, no APIs, no code decisions here — those
belong in `docs/domain-model.md` and `docs/decisions.md`.

Everything below is labelled so we can tell the sources apart:

- **[REQ]** — stated in the assignment (`problem_statement.md` / `candidate_assignment_instructions.md`)
- **[RESEARCH]** — how the real insurance domain works, from domain research
- **[ASSUMPTION]** — a simplification I am proposing; **needs your sign-off**
- **[OPEN]** — a decision that is genuinely yours to make, listed at the end

---

## 1. What is actually being asked

**[REQ]** Build a working Claims Processing System for an insurance company. Members submit
claims for reimbursement; the system decides what is covered, how much to pay, and tracks the
claim through its lifecycle.

But read alongside the candidate instructions, the assignment is not really "build a claims app."
It is: **can you research an unfamiliar business domain, decompose it into honest abstractions,
and defend every modelling choice you made?**

**[REQ]** Explicitly stated: *"This isn't about whether you can build a CRUD app."* The five
scoring signals are domain decomposition, rule representation, state management, edge-case
thinking, and explanation capability. Notice that **four of the five are modelling signals**, not
implementation signals. The interface (REST/UI/CLI) exists only so the work can be demonstrated.

The practical consequence: a small system where the coverage rules, the state machines, and the
denial explanations are crisp and well-argued beats a large system with more features and a mushy
domain model. **[REQ]** *"A system that does 3 things well beats one that does 10 things poorly."*

There is also a second, quieter test: **[REQ]** the next round is a 75-minute live pairing session
where this system gets extended. So the model has to be something a human can navigate and change
under pressure — which argues against clever indirection.

---

## 2. The business, in plain language

### 2.1 The cast

| Who / what | What it means in the business |
|---|---|
| **Member** | The insured person. They receive care and want money back or paid on their behalf. |
| **Policy (plan)** | The contract that says what is covered, up to how much, and who pays what share. |
| **Provider** | The clinic, hospital, lab or doctor that delivered the service. |
| **Claim** | One request for payment, covering one visit or episode of care. |
| **Line item** | One billable thing inside that claim — a consultation, an X-ray, a drug, a physio session. **This is where coverage is actually decided.** |
| **Coverage rule** | The plan's promise for a category of service: covered or not, up to a cap, with the member paying some share. |
| **Adjudication** | The act of applying those rules to each line item to produce a payable amount and a reason. |
| **Accumulator** | The running ledger of how much a member has already used up this plan year (deductible met, visits used, dollars spent against an annual cap). |
| **Explanation of Benefits (EOB)** | The member-facing statement: here's what was billed, what we paid, what you owe, and why. |
| **Dispute (appeal)** | The member saying "you got this wrong" and asking for a re-look. |

**[RESEARCH]** A crucial fact that shapes the whole model: **the claim is the envelope, the line
item is the unit of decision.** Real payers adjudicate line by line. One claim can legitimately end
up with three lines paid, one line denied, and one line parked for manual review. That is a normal
Tuesday, not an edge case — which is exactly why the problem statement asks about it directly.

### 2.2 How a claim actually gets decided

**[RESEARCH]** Real adjudication is a **sequence of gates, then arithmetic**. Order matters, because
each gate can stop the claim before money is ever calculated:

1. **Intake / validation** — is the claim well-formed? Duplicate of one we already processed?
2. **Eligibility** — was the member actually covered *on the date the service happened*? (Not today
   — the service date. This distinction causes real denials.)
3. **Benefit / coverage check** — is this type of service covered by this plan at all, or excluded?
4. **Authorisation & necessity checks** — did this service need pre-approval that wasn't obtained?
   Is it clinically justified given the diagnosis? This is the gate that produces "needs human review."
5. **Pricing** — determine the **allowed amount**. The insurer does *not* pay what the provider
   billed; it pays against a negotiated/plan-defined rate. Billed $500, allowed $300 is ordinary.
6. **Cost-sharing arithmetic** — apply, in order: the **deductible** (member pays everything until a
   yearly threshold is met), then **copay** (fixed fee per visit) or **coinsurance** (a percentage
   split), all bounded by limits and the **out-of-pocket maximum**.
7. **Explain and pay** — produce the plan-pays / member-owes split plus a coded reason for every
   adjustment, then move money.

**[RESEARCH]** Two facts from step 6 that a naive model gets wrong:

- **Cost-sharing is computed off the allowed amount, never the billed amount.** The gap between
  billed and allowed is a separate adjustment that the member does not owe.
- **A single line can split.** If the member has $50 of deductible left and the allowed amount is
  $300, that line splits into a $50 deductible portion and a $250 portion that coinsurance applies
  to. So "one line item = one outcome" is too simple; a line has an *amount breakdown*.

**[RESEARCH]** Annual limits work the same way and produce **partial payment at the boundary**:
if physiotherapy is capped at $1,000/year and $900 is already used, a $400 claim pays $100 and
denies $300 as "benefit maximum reached." This is the "limit exhaustion" edge case the assignment
names, and it is the single best test of whether accumulators were modelled properly.

### 2.3 Why decisions have to be explainable

**[RESEARCH]** The industry does not say "denied." It attaches structured reason codes — CARCs
(Claim Adjustment Reason Codes, the *why*, published by X12) plus RARCs (remark codes, the extra
detail) — and a group code saying **who absorbs the amount**: the provider (contractual write-off),
the member (patient responsibility), or the payer. That last distinction matters: "$200 applied to
your deductible" is *not* a denial, it is a coverage determination that shifts cost to the member.
Lumping those together is a modelling mistake.

**[RESEARCH]** Explainability is also what makes disputes possible. A member can only appeal what
they can understand, and appeals are argued *against the stated reason*. Denials rooted in judgement
(medical necessity, missing authorisation, frequency exceeded) are appealable; denials that are just
arithmetic (this is your deductible) generally are not.

**[REQ]** The assignment asks directly: *"How do you explain to a member why something was denied?"*
So explanation is not a logging afterthought — **it is a first-class output of adjudication**, produced
at the same moment as the money, carrying a code, a human-readable reason, and ideally which rule and
which numbers produced it.

### 2.4 Sensitive data

**[REQ]** *"Claims contain member names, diagnosis codes, and provider details. This is sensitive
health data — your design decisions should reflect that."*

Non-technically: this is protected health information. The business expectation is that we are
deliberate about where it lives, who sees it, what ends up in logs and error messages, and that we
can show a defensible trail of who decided what. **[REQ]** Authentication and access control are
explicitly out of scope, so this cannot mean "build security." It means our choices should visibly
acknowledge the sensitivity rather than ignore it, and we should say what we deliberately did *not*
build and why in `docs/decisions.md`.

---

## 3. The lifecycle, in plain words

**[REQ]** Stated states: `submitted → under review → approved/denied → paid`, plus members can dispute.

**[REQ]** And the pointed question: *"What's the state machine of a claim vs. a line item?"* — the
assignment is telling us these are two different lifecycles and it wants us to notice.

The business reading:

- **A line item** is where the real verdict lives. Each line independently ends up covered (fully or
  partially), denied with a reason, or held for a human to look at.
- **A claim** does not have its own opinion — its state is largely **derived from its lines**. A claim
  cannot be settled while any line is still waiting on a human. A claim where some lines paid and some
  denied is **partially approved**, which is a genuine outcome and not a failure.
- **Payment happens at the claim level** even though decisions happen at the line level, because money
  moves as one remittance.

**[ASSUMPTION]** A claim is only "denied" when *every* line is denied; if any line pays, the claim is
approved or partially approved. Simple, but it is a real modelling choice and you should confirm it.

**[OPEN]** What a dispute does to the lifecycle is the most interesting unanswered question, and I do
not want to decide it silently. Two honest options: a dispute **reopens** the original claim (states
cycle backwards), or a dispute is **its own entity** attached to a specific line item, leaving the
original decision immutable as a historical record. The second is closer to how real appeals work and
preserves the audit trail; the first is simpler. Listed again in §7.

---

## 4. The five hard questions, answered non-technically

The problem statement poses five "interesting problems." Here is the business-level answer to each —
these become the spine of the technical plan:

1. **How do you model coverage rules?** A plan is a set of promises, each attached to a *category of
   service* rather than to individual procedure codes: is it covered, what's the cap, what's the
   member's share, what conditions apply. The real question is whether rules are code or data —
   data-driven rules mean a new plan is a new configuration, not a new deployment. **[OPEN]**

2. **How do you track what's been used against limits?** Accumulators, scoped to a member + plan +
   benefit + plan year. They are the system's memory. They are also the hardest correctness problem,
   because they are read *and* written during adjudication, and two claims processed against the same
   remaining balance must not both consume it.

3. **What happens with 5 lines, 3 covered, 1 denied, 1 needing review?** Nothing special — that is the
   normal shape of the domain. It only becomes a problem if the model forces one verdict per claim.
   The claim sits incomplete until the flagged line is resolved by a human.

4. **How do you explain a denial?** Every decision carries a reason code, a plain-English sentence, and
   the evidence behind it (which rule fired, which numbers were used, what the remaining limit was).
   "Denied" alone is a failure of the system, not an outcome of it.

5. **Claim vs line-item state machine?** Covered in §3 — lines decide, claims aggregate.

---

## 5. Scope: what we are and are not building

**[REQ]** In scope: submitting claims with line items; adjudicating each line against coverage rules;
tracking claim and line-item lifecycle states; producing explanations; members disputing decisions.

**[REQ]** Out of scope, and explicitly *"building them will not improve your score"*: registration /
login / auth, policy purchase or enrolment, member and provider account management, notifications,
dashboards and analytics, admin panels, multi-tenant or role-based access.

Reading those two lists together, the message is: **all the effort goes into the decision engine and
the domain model.** Anything that looks like generic SaaS scaffolding is actively a waste of the 24–48
hours. Seed data replaces the enrolment flows we are told not to build.

---

## 6. How the submission is judged

**[REQ]** Hard requirements — missing any one of these means rejection regardless of code quality:

| Deliverable | Note |
|---|---|
| `app/` (or equivalent) | The working system. *"We will clone your submission, set it up from your README, and run the flows you built. If it doesn't run, the tests don't count."* |
| `docs/domain-model.md` | Entities, relationships, state machines, and **why this decomposition**. |
| `docs/decisions.md` | What was built, what was skipped, assumptions made. |
| `docs/self-review.md` | Honest assessment — *"a calibrated gap-list with reasoning earns more credit than polished completeness."* |
| `ai-artifacts/` | **Raw `.jsonl` session logs covering every phase** — framing, research, planning, coding, docs, testing, QA. Markdown summaries and screenshots do not substitute. |
| `README.md` | Setup and run instructions. |
| `.git/` | Full commit history, included in the zip. Not a single-commit dump. |

**[REQ]** Two process requirements that affect *how* we work, not just what we ship:

- **Tests before or alongside code, visible in git history.** *"Git history doesn't lie."* Tests must
  encode domain rules ("when the annual limit is partially exhausted, the line pays the remainder and
  denies the rest") rather than assert HTTP status codes.
- **This conversation is part of the submission.** Every phase — including this framing session — has
  to happen inside an agent that produces `.jsonl` logs, and all of them must be in `ai-artifacts/`.

**[REQ]** Stated rejection patterns worth keeping visible: a domain model that doesn't go beyond what
AI generated without your input; not being able to walk through your own code; tests obviously added at
the end; scattered half-features; a self-review that doesn't match reality.

---

## 7. Scope decisions taken

These are **your** calls, made deliberately at framing time. They belong in `docs/decisions.md` too,
with the reasoning, since the assignment grades justified decisions rather than maximal features.

### 7.1 Decided

| Decision | Choice | Reasoning |
|---|---|---|
| **Rule representation** | Typed rule objects in code, seeded from data | Keeps rules explicit and readable enough to modify live in the round-two pairing session, while still making "a new plan" a data change rather than a code change. Avoids the cost of building and defending a bespoke DSL. |
| **Cost-sharing depth** | Allowed amount vs billed, deductible, annual benefit limits | These three produce the edge cases the assignment names: billed ≠ paid, line splitting at the deductible boundary, and partial payment at limit exhaustion. |
| **Cost-sharing excluded** | Copay, coinsurance, out-of-pocket maximum | Deliberately cut to keep scope coherent. |
| **Disputes** | A separate appeal entity attached to a specific line-item decision; the original decision stays immutable | Matches how real appeals work, preserves the audit trail, and avoids state machines that run backwards. |
| **Interface** | REST API in Python / FastAPI | Fast to demo, and domain tests can be written against the engine directly rather than against HTTP. |
| **Human-in-the-loop** | `NEEDS_REVIEW` is a real line-item outcome; the reviewer's *workflow* is out of implementation scope | Anything the rules cannot decide confidently — or any claim that isn't coherent — routes to a human instead of being guessed at. We model the outcome and the reason it was raised, not the queue, the assignment, or the resolution UI. |
| **Money direction** | Reimbursement paid directly to the member; no payment system | Follows the problem statement's own framing (*"members submit claims for reimbursement"*). Payment is a lifecycle state the claim reaches, not a subsystem we build. |
| **Persistence** | SQLite | Accumulators, duplicate detection and disputes all need durable history — they are questions about *what happened before*, which an in-memory store answers badly. SQLite keeps reviewer setup to zero external dependencies. Schema to be designed later. |
| **Retroactive changes** | Detect and surface, never auto-resolve | The system flags that a decided claim is affected by a later change and routes it to `NEEDS_REVIEW`. It does not silently re-adjudicate, reverse payments, or decide what the change *means*. |

**[ASSUMPTION — follows from the cost-sharing choice]** With a deductible but no coinsurance or copay,
**once the deductible is met the plan pays the full allowed amount** for a covered service, subject to
the annual benefit limit. That is a simplified plan design, not how most real plans work. It must be
stated plainly in `docs/decisions.md` as a conscious simplification, not left for a reviewer to
discover — an unexplained gap reads as an oversight, an explained one reads as judgement.

Member responsibility therefore comes from exactly three sources, and they should be distinguishable
in the output: the billed-minus-allowed gap, the deductible portion, and anything denied.

### 7.2 The governing principle behind those calls

Two of the decisions above — human-in-the-loop and retroactive changes — are the same principle applied
twice, and it is worth naming because it should govern every design choice that follows:

> **Automate everything the rules can decide deterministically. Escalate everything else to a human.
> Never guess.**

A wrongly processed claim is not a bug in the ordinary sense. Underpaying denies a member money they
are owed and gives them a reason to appeal that we generated ourselves; overpaying is money that cannot
easily be clawed back; and both corrupt the accumulators, so the error silently contaminates every
later claim for that member. The blast radius of a bad decision is larger than the claim it was made on.

`NEEDS_REVIEW` is therefore not a failure state or an escape hatch for unfinished work — **it is the
correct, designed outcome whenever the rules do not have a confident answer.** A system that
adjudicates 80% of claims correctly and honestly parks the other 20% is worth more than one that
adjudicates 100% with some percentage silently wrong, because the first one's errors are visible.

The practical test for any design decision from here on: *if this is wrong, does the system produce a
wrong number quietly, or does it stop and say so?* Anything in the first category needs to be
redesigned or escalated. This is now encoded as a standing instruction in `.cursor/rules/project.mdc`.

### 7.3 Still open

None on scope. What remains is design work, not decisions about what to build.

---

## 8. Where this leaves us

The domain is clear enough to design against: **claims are envelopes, line items are decisions,
accumulators are memory, and explanations are output, not logging.** The real risk in this assignment
is not that the code fails — it is building a competent CRUD app with a thin domain underneath, which
the instructions call out by name as a rejection pattern.

Scope is now settled. The next step is the technical plan: entities and their relationships, the two
state machines, how a rule is shaped, how accumulators are read and written during adjudication, what
triggers `NEEDS_REVIEW`, and the domain tests that should be written first.
