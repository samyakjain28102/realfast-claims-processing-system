-- SQLite schema. Domain dataclasses map onto these tables by hand.
-- Claim adjudication_state and settlement_state are never stored.

PRAGMA foreign_keys = ON;

-- ---------------------------------------------------------------------------
-- Reference / seed data
-- ---------------------------------------------------------------------------

CREATE TABLE members (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    date_of_birth TEXT NOT NULL
);

CREATE TABLE providers (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL
);

CREATE TABLE plans (
    id TEXT NOT NULL,
    version INTEGER NOT NULL CHECK (version >= 1),
    deductible_minor INTEGER NOT NULL CHECK (deductible_minor >= 0),
    PRIMARY KEY (id, version)
);

CREATE TABLE benefits (
    plan_id TEXT NOT NULL,
    plan_version INTEGER NOT NULL,
    code TEXT NOT NULL,
    name TEXT NOT NULL,
    covered INTEGER NOT NULL CHECK (covered IN (0, 1)),
    excluded INTEGER NOT NULL CHECK (excluded IN (0, 1)),
    annual_limit_amount_minor INTEGER CHECK (
        annual_limit_amount_minor IS NULL OR annual_limit_amount_minor >= 0
    ),
    annual_visit_limit INTEGER CHECK (
        annual_visit_limit IS NULL OR annual_visit_limit >= 0
    ),
    PRIMARY KEY (plan_id, plan_version, code),
    FOREIGN KEY (plan_id, plan_version) REFERENCES plans (id, version)
);

CREATE TABLE policies (
    id TEXT PRIMARY KEY,
    member_id TEXT NOT NULL REFERENCES members (id),
    plan_id TEXT NOT NULL,
    effective_date TEXT NOT NULL,
    termination_date TEXT
);

CREATE TABLE service_catalogue (
    service_code TEXT PRIMARY KEY,
    description TEXT NOT NULL,
    benefit_code TEXT NOT NULL,
    scheduled_amount_minor INTEGER CHECK (
        scheduled_amount_minor IS NULL OR scheduled_amount_minor >= 0
    )
);

-- ---------------------------------------------------------------------------
-- Claim envelope. rejected is the gate-0 fact, not a stored lifecycle state.
-- ---------------------------------------------------------------------------

CREATE TABLE claims (
    id TEXT PRIMARY KEY,
    member_id TEXT NOT NULL REFERENCES members (id),
    submitted_at TEXT NOT NULL,
    rejected INTEGER NOT NULL DEFAULT 0 CHECK (rejected IN (0, 1))
);

CREATE TABLE claim_lines (
    id TEXT PRIMARY KEY,
    claim_id TEXT NOT NULL REFERENCES claims (id),
    line_number INTEGER NOT NULL CHECK (line_number >= 1),
    provider_id TEXT NOT NULL REFERENCES providers (id),
    service_code TEXT NOT NULL,
    service_date TEXT NOT NULL,
    billed_amount_minor INTEGER NOT NULL CHECK (billed_amount_minor >= 0),
    diagnosis_code TEXT NOT NULL,
    UNIQUE (claim_id, line_number)
);

-- ---------------------------------------------------------------------------
-- Append-only: LineDecision. Current decision = MAX(sequence) per line.
-- Amount columns are all-null when the decision never reached pricing (D27).
-- ---------------------------------------------------------------------------

CREATE TABLE line_decisions (
    id TEXT PRIMARY KEY,
    line_id TEXT NOT NULL REFERENCES claim_lines (id),
    sequence INTEGER NOT NULL CHECK (sequence >= 1),
    source TEXT NOT NULL,
    outcome TEXT NOT NULL,
    allowed_minor INTEGER,
    above_allowed_minor INTEGER,
    deductible_applied_minor INTEGER,
    plan_paid_minor INTEGER,
    denied_amount_minor INTEGER,
    reasons_json TEXT NOT NULL,
    trace_json TEXT NOT NULL,
    plan_version INTEGER NOT NULL CHECK (plan_version >= 1),
    decided_at TEXT NOT NULL,
    decided_by TEXT NOT NULL,
    UNIQUE (line_id, sequence),
    CHECK (
        (
            allowed_minor IS NULL
            AND above_allowed_minor IS NULL
            AND deductible_applied_minor IS NULL
            AND plan_paid_minor IS NULL
            AND denied_amount_minor IS NULL
        )
        OR (
            allowed_minor IS NOT NULL
            AND above_allowed_minor IS NOT NULL
            AND deductible_applied_minor IS NOT NULL
            AND plan_paid_minor IS NOT NULL
            AND denied_amount_minor IS NOT NULL
        )
    )
);

-- ---------------------------------------------------------------------------
-- Append-only ledger. Balance for a key is SUM(quantity). Never UPDATE/DELETE.
-- ---------------------------------------------------------------------------

CREATE TABLE accumulator_entries (
    id TEXT PRIMARY KEY,
    member_id TEXT NOT NULL REFERENCES members (id),
    plan_year INTEGER NOT NULL,
    scope TEXT NOT NULL,
    benefit_code TEXT,
    quantity INTEGER NOT NULL CHECK (quantity != 0),
    decision_id TEXT NOT NULL REFERENCES line_decisions (id),
    reverses_entry_id TEXT REFERENCES accumulator_entries (id),
    CHECK (
        (scope = 'DEDUCTIBLE' AND benefit_code IS NULL)
        OR (
            scope IN ('BENEFIT_AMOUNT', 'BENEFIT_VISITS')
            AND benefit_code IS NOT NULL
        )
    )
);

-- ---------------------------------------------------------------------------
-- Append-only payments. Never negative. Settlement state is derived.
-- ---------------------------------------------------------------------------

CREATE TABLE payments (
    id TEXT PRIMARY KEY,
    claim_id TEXT NOT NULL REFERENCES claims (id),
    amount_minor INTEGER NOT NULL CHECK (amount_minor > 0),
    paid_at TEXT NOT NULL,
    reference TEXT NOT NULL
);

-- Dispute.state is the one mutable lifecycle on this table (OPEN → CLOSED).
CREATE TABLE disputes (
    id TEXT PRIMARY KEY,
    line_id TEXT NOT NULL REFERENCES claim_lines (id),
    disputed_decision_id TEXT NOT NULL REFERENCES line_decisions (id),
    member_reason TEXT NOT NULL,
    state TEXT NOT NULL
);

-- Append-only: each review attempt is a new row (D23, D24).
CREATE TABLE review_resolutions (
    id TEXT PRIMARY KEY,
    line_id TEXT NOT NULL REFERENCES claim_lines (id),
    dispute_id TEXT REFERENCES disputes (id),
    mode TEXT NOT NULL,
    reviewer_id TEXT NOT NULL,
    note TEXT NOT NULL,
    resulting_decision_id TEXT NOT NULL REFERENCES line_decisions (id),
    correction_service_code TEXT,
    correction_service_date TEXT,
    correction_provider_id TEXT,
    correction_billed_amount_minor INTEGER,
    correction_diagnosis_code TEXT
);

CREATE INDEX idx_policies_member ON policies (member_id);
CREATE INDEX idx_claims_member ON claims (member_id);
CREATE INDEX idx_claim_lines_claim ON claim_lines (claim_id);
CREATE INDEX idx_line_decisions_line_seq ON line_decisions (line_id, sequence);
CREATE INDEX idx_accumulator_key ON accumulator_entries (
    member_id, plan_year, scope, benefit_code
);
CREATE INDEX idx_payments_claim ON payments (claim_id);
CREATE INDEX idx_disputes_line ON disputes (line_id);
CREATE INDEX idx_review_resolutions_line ON review_resolutions (line_id);

CREATE TRIGGER line_decisions_no_update
BEFORE UPDATE ON line_decisions
BEGIN
    SELECT RAISE(ABORT, 'line_decisions are append-only');
END;

CREATE TRIGGER line_decisions_no_delete
BEFORE DELETE ON line_decisions
BEGIN
    SELECT RAISE(ABORT, 'line_decisions are append-only');
END;

CREATE TRIGGER accumulator_entries_no_update
BEFORE UPDATE ON accumulator_entries
BEGIN
    SELECT RAISE(ABORT, 'accumulator_entries are append-only');
END;

CREATE TRIGGER accumulator_entries_no_delete
BEFORE DELETE ON accumulator_entries
BEGIN
    SELECT RAISE(ABORT, 'accumulator_entries are append-only');
END;

CREATE TRIGGER payments_no_update
BEFORE UPDATE ON payments
BEGIN
    SELECT RAISE(ABORT, 'payments are append-only');
END;

CREATE TRIGGER payments_no_delete
BEFORE DELETE ON payments
BEGIN
    SELECT RAISE(ABORT, 'payments are append-only');
END;

CREATE TRIGGER review_resolutions_no_update
BEFORE UPDATE ON review_resolutions
BEGIN
    SELECT RAISE(ABORT, 'review_resolutions are append-only');
END;

CREATE TRIGGER review_resolutions_no_delete
BEFORE DELETE ON review_resolutions
BEGIN
    SELECT RAISE(ABORT, 'review_resolutions are append-only');
END;

-- Policy plan_id must name a plan that exists (version is stamped on decisions).
CREATE TRIGGER policies_plan_exists_insert
BEFORE INSERT ON policies
BEGIN
    SELECT RAISE(ABORT, 'policy plan_id must reference an existing plan')
    WHERE NOT EXISTS (SELECT 1 FROM plans WHERE id = NEW.plan_id);
END;

CREATE TRIGGER policies_plan_exists_update
BEFORE UPDATE OF plan_id ON policies
BEGIN
    SELECT RAISE(ABORT, 'policy plan_id must reference an existing plan')
    WHERE NOT EXISTS (SELECT 1 FROM plans WHERE id = NEW.plan_id);
END;

-- Gate-0 rejected flag is set at insert and never rewritten.
CREATE TRIGGER claims_rejected_immutable
BEFORE UPDATE OF rejected ON claims
BEGIN
    SELECT RAISE(ABORT, 'claims.rejected is immutable')
    WHERE OLD.rejected != NEW.rejected;
END;

-- Dispute and review pointers must stay on the same line.
CREATE TRIGGER disputes_decision_same_line_insert
BEFORE INSERT ON disputes
BEGIN
    SELECT RAISE(ABORT, 'disputed decision must belong to dispute line')
    WHERE NOT EXISTS (
        SELECT 1 FROM line_decisions
        WHERE id = NEW.disputed_decision_id AND line_id = NEW.line_id
    );
END;

CREATE TRIGGER disputes_decision_same_line_update
BEFORE UPDATE OF disputed_decision_id, line_id ON disputes
BEGIN
    SELECT RAISE(ABORT, 'disputed decision must belong to dispute line')
    WHERE NOT EXISTS (
        SELECT 1 FROM line_decisions
        WHERE id = NEW.disputed_decision_id AND line_id = NEW.line_id
    );
END;

CREATE TRIGGER review_resolutions_decision_same_line_insert
BEFORE INSERT ON review_resolutions
BEGIN
    SELECT RAISE(ABORT, 'resulting decision must belong to resolution line')
    WHERE NOT EXISTS (
        SELECT 1 FROM line_decisions
        WHERE id = NEW.resulting_decision_id AND line_id = NEW.line_id
    );
END;

CREATE TRIGGER review_resolutions_dispute_same_line_insert
BEFORE INSERT ON review_resolutions
WHEN NEW.dispute_id IS NOT NULL
BEGIN
    SELECT RAISE(ABORT, 'dispute must belong to resolution line')
    WHERE NOT EXISTS (
        SELECT 1 FROM disputes
        WHERE id = NEW.dispute_id AND line_id = NEW.line_id
    );
END;
