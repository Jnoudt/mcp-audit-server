"""Deterministic, review-oriented CAATs for the local ReconFlow demo."""

from __future__ import annotations

from collections import defaultdict
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

RULE_VERSION = "reconflow-caats-1"
SERVICE_LEDGER_TYPES: dict[str, frozenset[str]] = {
    "journal-entry-analytics": frozenset({"general_ledger"}),
    "invoice-integrity-review": frozenset({"accounts_payable", "accounts_receivable"}),
    "inventory-asset-controls": frozenset({"inventory", "fixed_assets"}),
}


def analyze_sources(
    service_id: str,
    sources: list[dict[str, Any]],
    assessment: dict[str, Any],
) -> list[dict[str, Any]]:
    """Run only rules applicable to the selected service and imported ledger types."""
    allowed_types = SERVICE_LEDGER_TYPES.get(service_id)
    if allowed_types is None:
        raise ValueError("This service is not available in the local demo.")

    applicable = [source for source in sources if source["ledger_type"] in allowed_types]
    if not applicable:
        expected = ", ".join(sorted(allowed_types))
        raise ValueError(f"Upload at least one supported ledger for this service ({expected}).")

    findings: list[dict[str, Any]] = []
    for source in applicable:
        ledger_type = source["ledger_type"]
        rows = source["rows"]
        rows = _filter_to_period(rows, _period_field(ledger_type), assessment)
        if ledger_type == "general_ledger":
            findings.extend(_analyze_general_ledger(source, rows, assessment))
        elif ledger_type in {"accounts_payable", "accounts_receivable"}:
            findings.extend(_analyze_invoices(source, rows, ledger_type, assessment))
        elif ledger_type == "inventory":
            findings.extend(_analyze_inventory(source, rows))
        elif ledger_type == "fixed_assets":
            findings.extend(_analyze_fixed_assets(source, rows))
    return findings


def summarize_findings(findings: list[dict[str, Any]], source_count: int) -> dict[str, Any]:
    by_rule: dict[str, int] = defaultdict(int)
    by_severity: dict[str, int] = defaultdict(int)
    for finding in findings:
        by_rule[finding["rule_code"]] += 1
        by_severity[finding["severity"]] += 1
    return {
        "source_count": source_count,
        "finding_count": len(findings),
        "by_rule": dict(sorted(by_rule.items())),
        "by_severity": dict(sorted(by_severity.items())),
        "limitations": [
            "Flags are screening candidates and require auditor review.",
            "Posting-date patterns alone do not establish revenue cutoff errors.",
            "AP purchase-order references do not establish three-way matching without PO-line and GRN evidence.",
            "Negative inventory movements do not establish negative on-hand stock without a balance snapshot.",
        ],
    }


def count_rows_in_scope(
    service_id: str,
    sources: list[dict[str, Any]],
    assessment: dict[str, Any],
) -> int:
    allowed_types = SERVICE_LEDGER_TYPES.get(service_id)
    if allowed_types is None:
        raise ValueError("This service is not available in the local demo.")
    return sum(
        len(_filter_to_period(source["rows"], _period_field(source["ledger_type"]), assessment))
        for source in sources
        if source["ledger_type"] in allowed_types
    )


def _analyze_general_ledger(
    source: dict[str, Any],
    rows: list[dict[str, Any]],
    assessment: dict[str, Any],
) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    weekend_rows: list[dict[str, Any]] = []
    round_sum_rows: list[dict[str, Any]] = []
    split_groups: dict[tuple[Any, ...], list[dict[str, Any]]] = defaultdict(list)

    round_quantum = _positive_decimal(assessment.get("round_amount_quantum"), Decimal("10000"))
    round_minimum = _positive_decimal(assessment.get("round_amount_minimum"), Decimal("100000"))
    approval_threshold = _positive_decimal(assessment.get("approval_threshold"), Decimal("50000"))

    for row in rows:
        posting_date = _as_date(row.get("posting_date"))
        amount = _as_decimal(row.get("amount"))
        if posting_date and posting_date.weekday() >= 5:
            weekend_rows.append(row)
        if amount is not None and abs(amount) >= round_minimum and amount % round_quantum == 0:
            round_sum_rows.append(row)
        if amount is not None and abs(amount) < approval_threshold:
            split_groups[
                (row.get("company_code"), row.get("cost_center"), row.get("account_code"), posting_date)
            ].append(row)

    for row in weekend_rows:
        findings.append(
            _finding(
                source,
                row,
                "GL_WEEKEND_POSTING",
                "review",
                "Weekend-dated journal entry",
                "The posting date falls on a Saturday or Sunday. This identifies timing for review; it does not establish that the entry was manual or unauthorized.",
                "Inspect the source journal, approval evidence, and business-calendar context.",
            )
        )
    for row in round_sum_rows:
        findings.append(
            _finding(
                source,
                row,
                "GL_ROUND_AMOUNT",
                "review",
                "Large round-amount journal entry",
                "The absolute amount meets the configured round-amount quantum and minimum. This is a screening indicator, not evidence of misstatement.",
                "Compare the amount with supporting schedules, approval limits, and similar entries.",
                {"quantum": str(round_quantum), "minimum": str(round_minimum)},
            )
        )

    for group in split_groups.values():
        if len(group) < 2:
            continue
        total = sum(
            (abs(amount) for row in group if (amount := _as_decimal(row.get("amount"))) is not None),
            Decimal("0"),
        )
        if total < approval_threshold:
            continue
        for row in group:
            findings.append(
                _finding(
                    source,
                    row,
                    "GL_POSSIBLE_THRESHOLD_SPLIT",
                    "review",
                    "Potential approval-threshold split",
                    "Multiple same-day postings in one cost-center grouping are individually below the configured approval threshold and collectively meet or exceed it.",
                    "Check approvals, business purpose, and whether the entries are independent transactions.",
                    {"group_entry_count": len(group), "group_total": str(total), "threshold": str(approval_threshold)},
                )
            )

    benford = _benford_finding(source, rows)
    if benford:
        findings.append(benford)
    return findings


def _analyze_invoices(
    source: dict[str, Any],
    rows: list[dict[str, Any]],
    ledger_type: str,
    assessment: dict[str, Any],
) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    party_field = "vendor_id" if ledger_type == "accounts_payable" else "customer_id"
    duplicate_groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    split_groups: dict[tuple[Any, ...], list[dict[str, Any]]] = defaultdict(list)
    threshold = _positive_decimal(assessment.get("approval_threshold"), Decimal("50000"))

    for row in rows:
        invoice_number = str(row.get("invoice_number") or "").strip().casefold()
        party_id = str(row.get(party_field) or "").strip().casefold()
        if invoice_number:
            duplicate_groups[(party_id, invoice_number)].append(row)
        amount = _as_decimal(row.get("amount"))
        invoice_date = _as_date(row.get("invoice_date"))
        if amount is not None and abs(amount) < threshold:
            split_groups[(row.get("company_code"), row.get(party_field), invoice_date)].append(row)

    for group in duplicate_groups.values():
        if len(group) < 2:
            continue
        for row in group:
            findings.append(
                _finding(
                    source,
                    row,
                    "INVOICE_DUPLICATE_REFERENCE",
                    "high",
                    "Repeated invoice reference for the same counterparty",
                    "The normalized invoice reference occurs more than once for the same counterparty in this ledger import.",
                    "Compare source documents, credit notes, legal entities, and payment status before concluding duplication.",
                    {"matching_rows": len(group)},
                )
            )

    for group in split_groups.values():
        if len(group) < 2:
            continue
        total = sum(
            (abs(amount) for row in group if (amount := _as_decimal(row.get("amount"))) is not None),
            Decimal("0"),
        )
        if total < threshold:
            continue
        for row in group:
            findings.append(
                _finding(
                    source,
                    row,
                    "INVOICE_POSSIBLE_THRESHOLD_SPLIT",
                    "review",
                    "Potential invoice approval-threshold split",
                    "Multiple same-day invoices for one counterparty are individually below the configured threshold and collectively meet or exceed it.",
                    "Review approval history, supporting documents, and whether the invoices represent separate obligations.",
                    {"group_invoice_count": len(group), "group_total": str(total), "threshold": str(threshold)},
                )
            )

    if ledger_type == "accounts_payable":
        for row in rows:
            if not str(row.get("purchase_order") or "").strip():
                findings.append(
                    _finding(
                        source,
                        row,
                        "AP_MISSING_PO_REFERENCE",
                        "review",
                        "Payable has no purchase-order reference",
                        "The imported payable row has no mapped purchase-order reference. A missing reference alone does not establish a control failure.",
                        "Confirm whether a PO is required and inspect the approved purchasing evidence.",
                    )
                )
    return findings


def _analyze_inventory(
    source: dict[str, Any],
    rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    return [
        _finding(
            source,
            row,
            "INVENTORY_NEGATIVE_MOVEMENT",
            "review",
            "Negative inventory movement quantity",
            "The row records a negative movement quantity. Movement data alone cannot establish negative on-hand stock.",
            "Reconcile movement signs and quantities to a dated inventory-balance snapshot.",
        )
        for row in rows
        if (quantity := _as_decimal(row.get("quantity"))) is not None and quantity < 0
    ]


def _analyze_fixed_assets(
    source: dict[str, Any],
    rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    findings = []
    for row in rows:
        cost = _as_decimal(row.get("acquisition_cost"))
        depreciation = _as_decimal(row.get("accumulated_depreciation"))
        if cost is not None and depreciation is not None and depreciation > cost:
            findings.append(
                _finding(
                    source,
                    row,
                    "FA_DEPRECIATION_EXCEEDS_COST",
                    "high",
                    "Accumulated depreciation exceeds acquisition cost",
                    "The imported accumulated-depreciation amount exceeds the asset's acquisition cost.",
                    "Reconcile to the fixed-asset subledger, useful life, disposal history, and depreciation policy.",
                )
            )
    return findings


def _benford_finding(
    source: dict[str, Any],
    rows: list[dict[str, Any]],
) -> dict[str, Any] | None:
    first_digits = [digit for row in rows if (digit := _first_significant_digit(row.get("amount"))) is not None]
    if len(first_digits) < 100:
        return None
    observed = [first_digits.count(digit) for digit in range(1, 10)]
    expected = [
        len(first_digits) * (Decimal(1) + Decimal(1) / Decimal(digit)).ln() / Decimal(10).ln()
        for digit in range(1, 10)
    ]
    chi_square = sum(
        (
            ((Decimal(actual) - expected_count) ** 2) / expected_count
            for actual, expected_count in zip(observed, expected, strict=True)
        ),
        start=Decimal(0),
    )
    threshold = Decimal("15.507")
    if chi_square <= threshold:
        return None
    return _finding(
        source,
        None,
        "GL_BENFORD_FIRST_DIGIT_SCREEN",
        "review",
        "First-digit distribution differs from Benford screening threshold",
        "The population's first-significant-digit distribution exceeds the configured chi-square screening threshold. Suitability depends on the population and this is not evidence of fraud.",
        "Confirm the population is suitable for Benford analysis and investigate with independent supporting evidence.",
        {
            "sample_size": len(first_digits),
            "chi_square": str(chi_square.quantize(Decimal("0.001"))),
            "threshold": str(threshold),
        },
    )


def _first_significant_digit(value: Any) -> int | None:
    amount = _as_decimal(value)
    if amount is None or amount == 0:
        return None
    digits = str(abs(amount)).replace(".", "").lstrip("0")
    if not digits or not digits[0].isdigit():
        return None
    return int(digits[0])


def _finding(
    source: dict[str, Any],
    row: dict[str, Any] | None,
    rule_code: str,
    severity: str,
    title: str,
    description: str,
    recommendation: str,
    evidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "import_id": source["import_id"],
        "document_id": source["document_id"],
        "source_row_number": row.get("row_number") if row else None,
        "rule_code": rule_code,
        "severity": severity,
        "title": title,
        "description": description,
        "recommendation": recommendation,
        "evidence": evidence or {},
    }


def _as_decimal(value: Any) -> Decimal | None:
    if value is None:
        return None
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    return result if result.is_finite() else None


def _positive_decimal(value: Any, default: Decimal) -> Decimal:
    result = _as_decimal(value)
    return result if result is not None and result > 0 else default


def _as_date(value: Any) -> date | None:
    if isinstance(value, date):
        return value
    return None


def _period_field(ledger_type: str) -> str | None:
    if ledger_type in {"general_ledger", "inventory"}:
        return "posting_date"
    if ledger_type in {"accounts_payable", "accounts_receivable"}:
        return "invoice_date"
    return None


def _filter_to_period(
    rows: list[dict[str, Any]],
    date_field: str | None,
    assessment: dict[str, Any],
) -> list[dict[str, Any]]:
    if not date_field:
        return rows
    start = _as_iso_date(assessment.get("period_start"))
    end = _as_iso_date(assessment.get("period_end"))
    return [
        row
        for row in rows
        if (row_date := _as_date(row.get(date_field))) is not None
        and (start is None or row_date >= start)
        and (end is None or row_date <= end)
    ]


def _as_iso_date(value: Any) -> date | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None
