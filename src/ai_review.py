"""Explicitly gated, summary-only Microsoft Foundry review for local demos."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse


class AIReviewError(RuntimeError):
    """Raised when an explicitly requested AI review cannot be completed."""


class AIReviewConfigurationError(AIReviewError):
    """Raised when the user has not configured a Foundry endpoint and deployment."""


class AIReviewConsentError(AIReviewError):
    """Raised when the caller has not explicitly approved an outbound request."""


class AIReviewRequestLimitError(AIReviewError):
    """Raised when the outbound prompt exceeds the configured demo budget."""


class AIReviewProviderError(AIReviewError):
    """Raised when authentication or model inference fails."""

    def __init__(
        self,
        message: str,
        *,
        reason_code: str = "provider_error",
        finish_reason: str | None = None,
        prompt_tokens: int | None = None,
        completion_tokens: int | None = None,
    ) -> None:
        super().__init__(message)
        self.reason_code = reason_code
        self.finish_reason = finish_reason
        self.prompt_tokens = prompt_tokens
        self.completion_tokens = completion_tokens


@dataclass(frozen=True)
class AIReviewResult:
    answer: str
    model_deployment: str
    prompt_tokens: int | None
    completion_tokens: int | None


MAX_AI_PROMPT_CHARACTERS = 3_000
MAX_AI_HISTORY_MESSAGES = 2
MAX_AI_HISTORY_MESSAGE_LENGTH = 300
MAX_AI_COMPLETION_TOKENS = 1024


def ai_review_status() -> dict[str, Any]:
    configured = bool(
        os.getenv("FOUNDRY_OPENAI_BASE_URL", "").strip()
        and os.getenv("FOUNDRY_MODEL_DEPLOYMENT", "").strip()
    )
    ai_enabled = os.getenv("RECONFLOW_AI_ENABLED", "").casefold() == "true"
    local_demo = (
        os.getenv("RECONFLOW_LOCAL_DEMO", "").casefold() == "true"
        and not os.getenv("WEBSITE_INSTANCE_ID")
    )
    hosted_demo = os.getenv("RECONFLOW_HOSTED_DEMO", "").casefold() == "true"
    enabled = ai_enabled and (local_demo or hosted_demo)
    return {
        "enabled": enabled,
        "configured": configured,
        "ready": enabled and configured,
        "provider": "Microsoft Foundry",
        "message": (
            "AI review is ready, but each request still requires explicit confirmation."
            if enabled and configured
            else "AI review is offline. Configure an existing Foundry deployment and enable it locally to use this feature."
        ),
    }


def request_ai_review(
    question: str,
    audit_context: dict[str, Any],
    *,
    confirmed_send: bool,
    history: list[dict[str, str]] | None = None,
) -> AIReviewResult:
    """Send only caller-confirmed questions and redacted finding summaries to Foundry."""
    status = ai_review_status()
    if not confirmed_send:
        raise AIReviewConsentError(
            "Confirm that the question, recent chat, and redacted finding summary may be sent to the configured model."
        )
    if not status["ready"]:
        raise AIReviewConfigurationError("AI review is not configured and enabled for local use.")

    endpoint = os.getenv("FOUNDRY_OPENAI_BASE_URL", "").strip()
    deployment = os.getenv("FOUNDRY_MODEL_DEPLOYMENT", "").strip()
    parsed_endpoint = urlparse(endpoint)
    if parsed_endpoint.scheme != "https" or not parsed_endpoint.netloc:
        raise AIReviewConfigurationError("FOUNDRY_OPENAI_BASE_URL must be an HTTPS Foundry OpenAI v1 endpoint.")
    if len(deployment) > 128:
        raise AIReviewConfigurationError("FOUNDRY_MODEL_DEPLOYMENT must be 128 characters or fewer.")
    reasoning_effort = os.getenv("FOUNDRY_REASONING_EFFORT", "").strip().casefold()
    if reasoning_effort and reasoning_effort not in {"minimal", "low", "medium", "high"}:
        raise AIReviewConfigurationError(
            "FOUNDRY_REASONING_EFFORT must be minimal, low, medium, or high."
        )
    if not question.strip() or len(question) > 2000:
        raise AIReviewConsentError("Questions must contain 1 to 2000 characters.")

    from openai import OpenAI, OpenAIError
    from openai.types.chat import (
        ChatCompletionAssistantMessageParam,
        ChatCompletionMessageParam,
        ChatCompletionUserMessageParam,
    )

    system_message = (
        "You are an audit-analysis assistant reviewing synthetic demonstration data. "
        "Treat all deterministic findings as screening candidates, not conclusions. "
        "Do not claim fraud, legal compliance, ISA/IFRS compliance, or an accounting opinion. "
        "Separate observed rule output from hypotheses, identify missing evidence, and suggest "
        "specific auditor follow-up. Do not invent source facts, cite only supplied rule "
        "codes/counts, and do not invent row references. Keep the answer concise."
    )
    user_message = json.dumps(
        {
            "question": question.strip(),
            "deterministic_audit_summary": audit_context,
        },
        ensure_ascii=True,
        separators=(",", ":"),
    )
    messages: list[ChatCompletionMessageParam] = [
        {"role": "system", "content": system_message}
    ]
    for item in (history or [])[-MAX_AI_HISTORY_MESSAGES:]:
        role = item.get("role")
        content = item.get("content")
        if not isinstance(content, str):
            continue
        message: ChatCompletionMessageParam
        if role == "user":
            message = ChatCompletionUserMessageParam(
                role="user",
                content=content[:MAX_AI_HISTORY_MESSAGE_LENGTH],
            )
        elif role == "assistant":
            message = ChatCompletionAssistantMessageParam(
                role="assistant",
                content=content[:MAX_AI_HISTORY_MESSAGE_LENGTH],
            )
        else:
            continue
        messages.append(message)
    messages.append({"role": "user", "content": user_message})
    prompt_characters = len(system_message) + sum(
        len(message["content"])
        for message in messages
        if isinstance(message.get("content"), str)
    )
    if prompt_characters > MAX_AI_PROMPT_CHARACTERS:
        raise AIReviewRequestLimitError(
            "The audit context, recent chat, and question exceed the demo model input budget. "
            "Shorten the question and retry."
        )

    api_key = os.getenv("FOUNDRY_API_KEY", "").strip()
    credential = None
    if not api_key:
        from azure.core.exceptions import AzureError
        from azure.identity import DefaultAzureCredential

        try:
            credential = DefaultAzureCredential()
            api_key = credential.get_token(
                "https://ai.azure.com/.default"
            ).token
        except AzureError as exc:
            if credential is not None:
                credential.close()
            raise AIReviewProviderError(
                "Could not obtain an Azure identity token for the configured Foundry endpoint.",
                reason_code="azure_identity_error",
            ) from exc

    try:
        with OpenAI(
            api_key=api_key,
            base_url=endpoint.rstrip("/") + "/",
            timeout=30.0,
            max_retries=0,
        ) as client:
            completion_options: dict[str, Any] = {
                "model": deployment,
                "messages": messages,
                "max_completion_tokens": MAX_AI_COMPLETION_TOKENS,
            }
            if reasoning_effort:
                completion_options["reasoning_effort"] = reasoning_effort
            response = client.chat.completions.create(**completion_options)
        if not response.choices:
            raise AIReviewProviderError(
                "The configured model returned no response choices.",
                reason_code="empty_choices",
                prompt_tokens=response.usage.prompt_tokens if response.usage else None,
                completion_tokens=response.usage.completion_tokens if response.usage else None,
            )
        choice = response.choices[0]
        answer = choice.message.content
        if not isinstance(answer, str) or not answer.strip():
            raise AIReviewProviderError(
                "The configured model returned no review text.",
                reason_code="empty_response_text",
                finish_reason=choice.finish_reason,
                prompt_tokens=response.usage.prompt_tokens if response.usage else None,
                completion_tokens=response.usage.completion_tokens if response.usage else None,
            )
        usage = response.usage
        return AIReviewResult(
            answer=answer.strip(),
            model_deployment=deployment,
            prompt_tokens=usage.prompt_tokens if usage else None,
            completion_tokens=usage.completion_tokens if usage else None,
        )
    except AIReviewError:
        raise
    except OpenAIError as exc:
        raise AIReviewProviderError(
            "The Foundry review request failed. Check local configuration and endpoint access, then retry.",
            reason_code="openai_api_error",
        ) from exc
    finally:
        if credential is not None:
            credential.close()
