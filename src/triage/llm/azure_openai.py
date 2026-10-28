"""Azure OpenAI provider, authenticated with the container app's managed identity.

There is no API key: the resource has local (key) authentication switched off in Terraform, and the
managed identity holds the "Cognitive Services OpenAI User" role, which can call deployments but
cannot change them. Only redacted ticket text is sent.
"""

from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from triage.llm.base import LlmAssist, LlmError, LlmRequest, LlmResponse, response_schema
from triage.llm.prompts import SYSTEM_PROMPT, user_message

SCOPE = "https://cognitiveservices.azure.com/.default"


class AzureOpenAIProvider:
    name = "azure_openai"

    def __init__(
        self,
        endpoint: str,
        deployment: str,
        api_version: str,
        client_id: str | None = None,
        timeout: float = 20.0,
        max_output_tokens: int = 1500,
        reasoning_effort: str | None = None,
        client: Any | None = None,
    ) -> None:
        self.deployment = deployment
        self.max_output_tokens = max_output_tokens
        # Reasoning models (the gpt-5 family) spend part of max_completion_tokens on thinking. A short
        # triage note needs little of it, and "low" keeps answers quick and cheap.
        self.extra: dict[str, Any] = {"reasoning_effort": reasoning_effort} if reasoning_effort else {}
        if client is None:
            from azure.identity import (
                DefaultAzureCredential,
                ManagedIdentityCredential,
                get_bearer_token_provider,
            )
            from openai import AzureOpenAI

            credential = (
                ManagedIdentityCredential(client_id=client_id) if client_id else DefaultAzureCredential()
            )
            client = AzureOpenAI(
                azure_endpoint=endpoint,
                api_version=api_version,
                azure_ad_token_provider=get_bearer_token_provider(credential, SCOPE),
                timeout=timeout,
                max_retries=1,
            )
        self.client = client

    def assist(self, request: LlmRequest) -> LlmResponse:
        try:
            response = self.client.chat.completions.create(
                model=self.deployment,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_message(request)},
                ],
                response_format={
                    "type": "json_schema",
                    "json_schema": {"name": "triage_assist", "strict": True, "schema": response_schema()},
                },
                max_completion_tokens=self.max_output_tokens,
                **self.extra,
            )
        except Exception as exc:  # the SDK raises many types; all mean "no answer"
            raise LlmError(f"Azure OpenAI call failed: {type(exc).__name__}") from exc

        choice = response.choices[0]
        tokens = int(getattr(response.usage, "total_tokens", 0) or 0)
        if getattr(choice.message, "refusal", None):
            raise LlmError("the model refused to answer")
        if choice.finish_reason not in ("stop", None):
            raise LlmError(f"the model stopped early ({choice.finish_reason})")
        try:
            assist = LlmAssist.model_validate_json(choice.message.content or "")
        except ValidationError as exc:
            raise LlmError("the model's answer did not match the schema") from exc
        return LlmResponse(assist=assist, tokens=tokens)
