"""Member accumulator balances for the accumulators endpoint."""

from __future__ import annotations

from app.application.claim_queries import MemberNotFoundError
from app.application.read_models import AccumulatorBalanceView, MemberAccumulatorsView
from app.domain.accumulators import AccumulatorKey, AccumulatorScope
from app.domain.entities import Plan
from app.domain.rules import Benefit
from app.infrastructure.db import SqliteDatabase


def get_member_accumulators(
    db: SqliteDatabase, member_id: str
) -> MemberAccumulatorsView:
    if db.members.get(member_id) is None:
        raise MemberNotFoundError(member_id)
    plan = _plan_for_member_limits(db, member_id)
    keys = db.accumulators.list_keys_for_member(member_id)
    balances = tuple(
        _balance_view(db, key, plan) for key in sorted(keys, key=_key_sort)
    )
    return MemberAccumulatorsView(member_id=member_id, balances=balances)


def _plan_for_member_limits(db: SqliteDatabase, member_id: str) -> Plan | None:
    policies = db.policies.list_for_member(member_id)
    if len(policies) != 1:
        return None
    return db.plans.get_latest(policies[0].plan_id)


def _benefit_for_code(plan: Plan | None, code: str | None) -> Benefit | None:
    if plan is None or code is None:
        return None
    for benefit in plan.benefits:
        if benefit.code == code:
            return benefit
    return None


def _balance_view(
    db: SqliteDatabase, key: AccumulatorKey, plan: Plan | None
) -> AccumulatorBalanceView:
    consumed = db.accumulators.balance(key)
    limit_minor: int | None = None
    limit_visits: int | None = None
    if key.scope is AccumulatorScope.DEDUCTIBLE and plan is not None:
        limit_minor = plan.deductible.minor_units
    else:
        benefit = _benefit_for_code(plan, key.benefit_code)
        if benefit is not None:
            if key.scope is AccumulatorScope.BENEFIT_AMOUNT:
                limit_minor = (
                    None
                    if benefit.annual_limit_amount is None
                    else benefit.annual_limit_amount.minor_units
                )
            elif key.scope is AccumulatorScope.BENEFIT_VISITS:
                limit_visits = benefit.annual_visit_limit
    return AccumulatorBalanceView(
        plan_year=key.plan_year,
        scope=key.scope.value,
        benefit_code=key.benefit_code,
        consumed=consumed,
        limit_minor=limit_minor,
        limit_visits=limit_visits,
    )


def _key_sort(key: AccumulatorKey) -> tuple[int, str, str | None]:
    return (key.plan_year, key.scope.value, key.benefit_code or "")
