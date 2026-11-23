from __future__ import annotations

import json
import logging
from pathlib import Path
from types import SimpleNamespace
from typing import Self

import azure.functions as func
import openai
import pytest

import function_app
from src.ai_review import (
    AIReviewConfigurationError,
    AIReviewConsentError,
    AIReviewProviderError,
    AIReviewRequestLimitError,
    request_ai_review,
)
from src.demo_store import DemoStore

SCOPE = {
    "period_start": "1900-01-01",
    "period_end": "2100-12-31",
    "currency": "ZAR",
}
ERP_DIRECTORIES = [
    "01_SAP_S4HANA",
    "02_Oracle_NetSuite",
    "03_Xero_Cloud",
    "04_Sage_Intacct",
    "05_Microsoft_Dynamics_365",
    "06_QuickBooks_Online",
]


@pytest.fixture
def demo_store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> DemoStore:
    monkeypatch.setenv("RECONFLOW_LOCAL_DB_PATH", str(tmp_path / "demo.sqlite3"))
    monkeypatch.setenv("RECONFLOW_LOCAL_STORAGE_DIR", str(tmp_path / "uploads"))
    return DemoStore()


def _process(
    store: DemoStore,
    service_id: str,
    sample_ids: list[str],
    assessment: dict[str, str] | None = None,
) -> dict:
    request = store.create_request(service_id)
    store.save_assessment(request["id"], assessment or SCOPE)
    for sample_id in sample_ids:
        store.upload_sample(request["id"], sample_id)
    return store.run_audit(request["id"])


def _http_request(method: str, payload: dict[str, str]) -> func.HttpRequest:
    return func.HttpRequest(
        method=method,
        url="http://localhost/api/demo/requests",
        headers={"content-type": "application/json"},
        params={},
        route_params={},
        body=json.dumps(payload).encode(),
    )


def test_three_demo_services_process_bundled_samples_and_persist_provenance(
    demo_store: DemoStore,
) -> None:
    cases = [
        (
            "journal-entry-analytics",
            [f"{erp}/01_General_Ledger.csv" for erp in ERP_DIRECTORIES],
            6_300,
        ),
        (
            "invoice-integrity-review",
            [
                f"{erp}/{ledger_file}"
                for erp in ERP_DIRECTORIES
                for ledger_file in (
                    "02_Accounts_Receivable_Ledger.csv",
                    "03_Accounts_Payable_Ledger.csv",
                )
            ],
            12_600,
        ),
        (
            "inventory-asset-controls",
            [
                f"{erp}/{ledger_file}"
                for erp in ERP_DIRECTORIES
                for ledger_file in (
                    "04_Fixed_Assets_Ledger.csv",
                    "05_Inventory_Ledger.csv",
                )
            ],
            12_600,
        ),
    ]

    for service_id, sample_ids, expected_rows in cases:
        result = _process(demo_store, service_id, sample_ids)
        run = result["latestRun"]

        assert result["serviceId"] == service_id
        assert len(result["documents"]) == len(sample_ids)
        assert all(document["columnMap"] for document in result["documents"])
        ground_truth_columns = [
            column
            for document in result["documents"]
            for column in document["columnMap"]
            if "audit" in column["sourceName"].casefold()
            or "injected_anomaly" in column["sourceName"].casefold()
        ]
        assert len(ground_truth_columns) == len(sample_ids)
        assert all(not column["analysisAllowed"] for column in ground_truth_columns)
        assert run is not None
        assert run["summary"]["rows_analyzed"] == expected_rows
        assert run["summary"]["source_count"] == len(sample_ids)
        assert all(
            finding["sourceRowNumber"] is None or finding["sourceRowNumber"] >= 1
            for finding in run["findings"]
        )
        if run["findings"]:
            first_finding = run["findings"][0]
            reviewed = demo_store.save_disposition(
                result["id"],
                run["id"],
                first_finding["id"],
                "needs_follow_up",
                "Inspect supporting evidence.",
            )
            reviewed_finding = next(
                item
                for item in reviewed["latestRun"]["findings"]
                if item["id"] == first_finding["id"]
            )
            assert reviewed_finding["disposition"]["status"] == "needs_follow_up"

        context = demo_store.get_ai_context(result["id"], run["id"])
        serialized_context = json.dumps(context).casefold()
        assert "audit_tag" not in serialized_context
        assert "injected_anomaly_flag" not in serialized_context


@pytest.mark.asyncio
async def test_local_demo_api_creates_request_and_rejects_unsupported_service(
    demo_store: DemoStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("RECONFLOW_LOCAL_DEMO", "true")
    monkeypatch.delenv("WEBSITE_INSTANCE_ID", raising=False)
    monkeypatch.setattr(function_app, "get_demo_store", lambda: demo_store)

    created = await function_app.demo_create_request(
        _http_request("POST", {"serviceId": "journal-entry-analytics"})
    )
    created_payload = json.loads(created.get_body())
    assert created.status_code == 201
    assert created_payload["serviceId"] == "journal-entry-analytics"

    rejected = await function_app.demo_create_request(
        _http_request("POST", {"serviceId": "cash-reconciliation"})
    )
    assert rejected.status_code == 400
    assert "not available" in json.loads(rejected.get_body())["error"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("service_id", "ledger_file"),
    [
        ("journal-entry-analytics", "01_General_Ledger.csv"),
        ("invoice-integrity-review", "02_Accounts_Receivable_Ledger.csv"),
        ("inventory-asset-controls", "04_Fixed_Assets_Ledger.csv"),
    ],
)
async def test_demo_upload_api_parses_files_without_starting_an_audit(
    demo_store: DemoStore,
    monkeypatch: pytest.MonkeyPatch,
    service_id: str,
    ledger_file: str,
) -> None:
    monkeypatch.setenv("RECONFLOW_LOCAL_DEMO", "true")
    monkeypatch.delenv("WEBSITE_INSTANCE_ID", raising=False)
    monkeypatch.setattr(function_app, "get_demo_store", lambda: demo_store)
    request_data = demo_store.create_request(service_id)
    sample_path = (
        Path(__file__).resolve().parents[1]
        / "sample_data"
        / "Enterprise_ERP_Ledgers_and_Audit_CAATs_Pack"
        / "ledgers"
        / "01_SAP_S4HANA"
        / ledger_file
    )
    req = func.HttpRequest(
        method="POST",
        url=f"http://localhost/api/demo/requests/{request_data['id']}/uploads",
        headers={
            "content-type": "text/csv",
            "x-file-name": ledger_file,
            "x-source-system": "SAP S/4HANA",
        },
        params={},
        route_params={"request_id": request_data["id"]},
        body=sample_path.read_bytes(),
    )

    response = await function_app.demo_upload_csv(req)
    uploaded = json.loads(response.get_body())
    saved_request = demo_store.get_request(request_data["id"])

    assert response.status_code == 201
    assert uploaded["fileName"] == ledger_file
    assert uploaded["rowCount"] == 1_050
    assert uploaded["analysisColumns"]
    assert len(saved_request["documents"]) == 1
    assert saved_request["latestRun"] is None


def test_demo_store_rejects_wrong_service_file_and_invalid_assessment(
    demo_store: DemoStore,
) -> None:
    request = demo_store.create_request("journal-entry-analytics")
    with pytest.raises(ValueError, match="does not accept"):
        demo_store.upload_sample(
            request["id"],
            "01_SAP_S4HANA/03_Accounts_Payable_Ledger.csv",
        )

    with pytest.raises(ValueError, match="on or before"):
        demo_store.save_assessment(
            request["id"],
            {
                **SCOPE,
                "period_start": "2026-12-31",
                "period_end": "2026-01-01",
            },
        )


def test_ai_review_is_consent_gated_and_offline_without_configuration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("RECONFLOW_LOCAL_DEMO", "true")
    monkeypatch.setenv("RECONFLOW_AI_ENABLED", "false")
    monkeypatch.delenv("WEBSITE_INSTANCE_ID", raising=False)
    monkeypatch.delenv("FOUNDRY_OPENAI_BASE_URL", raising=False)
    monkeypatch.delenv("FOUNDRY_MODEL_DEPLOYMENT", raising=False)

    with pytest.raises(AIReviewConsentError, match="Confirm"):
        request_ai_review("Explain the summary", {}, confirmed_send=False)

    with pytest.raises(AIReviewConfigurationError, match="not configured"):
        request_ai_review("Explain the summary", {}, confirmed_send=True)


def test_ai_review_prompt_budget_is_checked_before_provider_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("RECONFLOW_LOCAL_DEMO", "true")
    monkeypatch.setenv("RECONFLOW_AI_ENABLED", "true")
    monkeypatch.setenv("FOUNDRY_OPENAI_BASE_URL", "https://example.test/openai/v1")
    monkeypatch.setenv("FOUNDRY_MODEL_DEPLOYMENT", "demo-deployment")
    monkeypatch.setenv("FOUNDRY_API_KEY", "local-test-token")
    monkeypatch.delenv("WEBSITE_INSTANCE_ID", raising=False)
    monkeypatch.setattr(
        openai,
        "OpenAI",
        lambda **_kwargs: pytest.fail("The provider must not be called for an oversized prompt."),
    )

    with pytest.raises(AIReviewRequestLimitError, match="input budget"):
        request_ai_review(
            "Summarize this.",
            {"summary": "x" * 4_000},
            confirmed_send=True,
        )


def test_ai_context_preserves_full_counts_but_limits_finding_samples(
    demo_store: DemoStore,
) -> None:
    request = _process(
        demo_store,
        "journal-entry-analytics",
        ["01_SAP_S4HANA/01_General_Ledger.csv"],
    )
    context = demo_store.get_ai_context(request["id"], request["latestRun"]["id"])

    assert context["summary"]["finding_count"] == sum(context["summary"]["by_rule"].values())
    assert context["finding_sample_count"] == 2
    assert context["findings_are_representative_samples"] is True
    assert len(context["findings"]) == 2
    assert all(
        len(finding[field]) <= 160
        for finding in context["findings"]
        for field in ("title", "description", "recommendation")
    )


def test_ai_provider_error_logs_safe_cause_metadata_only(
    caplog: pytest.LogCaptureFixture,
) -> None:
    class FakeProviderError(Exception):
        status_code = 401

    caplog.set_level(logging.INFO, logger="mcp-audit-server")
    try:
        raise AIReviewProviderError("The Foundry review request failed.") from FakeProviderError(
            "do-not-log-this-provider-message"
        )
    except AIReviewProviderError as exc:
        response = function_app._demo_error(exc, "test-trace")

    assert response.status_code == 502
    assert "FakeProviderError" in caplog.text
    assert '"provider_status":401' in caplog.text
    assert "do-not-log-this-provider-message" not in caplog.text


def test_ai_provider_rate_limit_is_returned_as_http_429() -> None:
    class FakeRateLimitError(Exception):
        status_code = 429

    try:
        raise AIReviewProviderError("The Foundry review request failed.") from FakeRateLimitError(
            "provider response must not be exposed"
        )
    except AIReviewProviderError as exc:
        response = function_app._demo_error(exc, "test-rate-limit")

    assert response.status_code == 429
    assert b"rate-limited" in response.get_body()
    assert b"provider response must not be exposed" not in response.get_body()


def test_ai_review_adapter_uses_configured_client_without_network(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("RECONFLOW_LOCAL_DEMO", "true")
    monkeypatch.setenv("RECONFLOW_AI_ENABLED", "true")
    monkeypatch.setenv("FOUNDRY_OPENAI_BASE_URL", "https://example.test/openai/v1")
    monkeypatch.setenv("FOUNDRY_MODEL_DEPLOYMENT", "demo-deployment")
    monkeypatch.setenv("FOUNDRY_REASONING_EFFORT", "low")
    monkeypatch.setenv("FOUNDRY_API_KEY", "local-test-token")
    monkeypatch.delenv("WEBSITE_INSTANCE_ID", raising=False)
    captured: dict[str, object] = {}

    class FakeClient:
        def __init__(self, **_kwargs: object) -> None:
            self.chat = SimpleNamespace(
                completions=SimpleNamespace(create=self.create_completion)
            )

        def __enter__(self) -> Self:
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def create_completion(self, **kwargs: object) -> SimpleNamespace:
            captured.update(kwargs)
            return SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(content="Review the supporting evidence.")
                    )
                ],
                usage=SimpleNamespace(prompt_tokens=18, completion_tokens=7),
            )

    monkeypatch.setattr(openai, "OpenAI", FakeClient)
    result = request_ai_review(
        "What should the auditor inspect?",
        {
            "summary": {"finding_count": 1, "by_rule": {"GL_WEEKEND_POSTING": 1}},
            "findings": [{"rule_code": "GL_WEEKEND_POSTING", "title": "Weekend posting"}],
        },
        confirmed_send=True,
    )

    assert result.answer == "Review the supporting evidence."
    assert result.prompt_tokens == 18
    assert result.completion_tokens == 7
    assert captured["max_completion_tokens"] == 1024
    assert captured["reasoning_effort"] == "low"
    messages = captured["messages"]
    serialized_messages = json.dumps(messages).casefold()
    assert "gl_weekend_posting" in serialized_messages
    assert "audit_tag" not in serialized_messages
    assert "source_row_number" not in serialized_messages


def test_ai_review_empty_output_keeps_only_safe_finish_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("RECONFLOW_LOCAL_DEMO", "true")
    monkeypatch.setenv("RECONFLOW_AI_ENABLED", "true")
    monkeypatch.setenv("FOUNDRY_OPENAI_BASE_URL", "https://example.test/openai/v1")
    monkeypatch.setenv("FOUNDRY_MODEL_DEPLOYMENT", "demo-deployment")
    monkeypatch.setenv("FOUNDRY_API_KEY", "local-test-token")
    monkeypatch.delenv("WEBSITE_INSTANCE_ID", raising=False)

    class FakeClient:
        def __init__(self, **_kwargs: object) -> None:
            self.chat = SimpleNamespace(
                completions=SimpleNamespace(create=self.create_completion)
            )

        def __enter__(self) -> Self:
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def create_completion(self, **_kwargs: object) -> SimpleNamespace:
            return SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(content=None),
                        finish_reason="length",
                    )
                ],
                usage=SimpleNamespace(prompt_tokens=450, completion_tokens=384),
            )

    monkeypatch.setattr(openai, "OpenAI", FakeClient)
    with pytest.raises(AIReviewProviderError) as error:
        request_ai_review("Review the sample.", {}, confirmed_send=True)

    assert error.value.reason_code == "empty_response_text"
    assert error.value.finish_reason == "length"
    assert error.value.prompt_tokens == 450
    assert error.value.completion_tokens == 384
