"""Deterministic policy compliance rules."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from src.schemas.models import PolicyComplianceRequest, PolicyComplianceResult


def evaluate_policy_compliance(arguments: dict[str, object]) -> dict[str, object]:
    request = PolicyComplianceRequest.model_validate(arguments)

    violations: list[str] = []
    approval_tier = "none"

    if request.approval_tier is not None:
        approval_tier = request.approval_tier

    if request.amount > request.policy.spend_limit:
        violations.append("spend_limit_exceeded")

    if request.amount > Decimal("1000") and approval_tier not in {"manager", "executive"}:
        violations.append("manager_approval_required")
    if request.amount > Decimal("10000") and approval_tier != "executive":
        violations.append("executive_approval_required")

    if request.policy.require_vat and not request.vat_registered:
        violations.append("vat_registration_required")

    if request.due_date is not None:
        due_date: date = request.due_date
        if due_date < request.as_of_date:
            violations.append("past_due")
        elif (due_date - request.as_of_date).days > request.policy.sla_days:
            violations.append("sla_window_exceeded")

    result = PolicyComplianceResult(
        tenant_id=request.tenantId,
        compliant=not violations,
        violations=violations,
        approval_tier=approval_tier,
    )
    return result.model_dump(mode="json")
