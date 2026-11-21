"""Deterministic invoice reconciliation."""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

from src.schemas.models import (
    InvoiceReconciliationRequest,
    InvoiceReconciliationResult,
)

CENT = Decimal("0.01")


def validate_invoice_math(arguments: dict[str, object]) -> dict[str, object]:
    request = InvoiceReconciliationRequest.model_validate(arguments)

    calculated_lines = sum(
        (line.quantity * line.unit_price for line in request.line_items),
        start=Decimal("0"),
    ).quantize(CENT, rounding=ROUND_HALF_UP)

    line_sum_delta = (calculated_lines - request.reported_subtotal).quantize(
        CENT, rounding=ROUND_HALF_UP
    )

    declared_subtotal = request.reported_subtotal.quantize(CENT, rounding=ROUND_HALF_UP)
    calculated_tax = (declared_subtotal * request.tax_rate).quantize(
        CENT, rounding=ROUND_HALF_UP
    )
    tax_delta = (calculated_tax - request.reported_tax).quantize(
        CENT, rounding=ROUND_HALF_UP
    )

    calculated_total = (declared_subtotal + calculated_tax).quantize(
        CENT, rounding=ROUND_HALF_UP
    )
    total_delta = (calculated_total - request.reported_total).quantize(
        CENT, rounding=ROUND_HALF_UP
    )

    findings: list[str] = []
    if line_sum_delta != Decimal("0.00"):
        findings.append("line_item_total_mismatch")
    if tax_delta != Decimal("0.00"):
        findings.append("tax_amount_mismatch")
    if total_delta != Decimal("0.00"):
        findings.append("total_mismatch")

    result = InvoiceReconciliationResult(
        invoice_id=request.invoice_id,
        calculated_line_sum=calculated_lines,
        reported_subtotal=declared_subtotal,
        subtotal_variance=line_sum_delta,
        calculated_tax=calculated_tax,
        reported_tax=request.reported_tax,
        tax_variance=tax_delta,
        calculated_total=calculated_total,
        reported_total=request.reported_total,
        total_variance=total_delta,
        pass_reconciliation=not findings,
        findings=findings,
    )
    return result.model_dump(mode="json")
