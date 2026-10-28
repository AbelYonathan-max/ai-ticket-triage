"""Build the triage service from settings: the model, knowledge base, SLA policy and AI assistant."""

from __future__ import annotations

from triage.domain.itil import load_policy
from triage.kb.retrieve import default_knowledge_base
from triage.llm.assistant import Assistant
from triage.llm.base import LlmProvider
from triage.llm.guard import CircuitBreaker, DailyTokenBudget
from triage.ml.model import TriageModel
from triage.service import TriageService
from triage.settings import Settings


def build_assistant(settings: Settings) -> Assistant | None:
    provider: LlmProvider
    if settings.llm_provider == "disabled":
        return None
    if settings.llm_provider == "stub":
        from triage.llm.stub import StubProvider

        provider = StubProvider()
    else:
        from triage.llm.azure_openai import AzureOpenAIProvider

        if not (settings.openai_endpoint and settings.openai_deployment):  # also checked by Settings
            raise ValueError("azure_openai needs an endpoint and a deployment")
        provider = AzureOpenAIProvider(
            endpoint=settings.openai_endpoint,
            deployment=settings.openai_deployment,
            api_version=settings.openai_api_version,
            client_id=settings.azure_client_id,
            timeout=settings.llm_timeout_seconds,
            max_output_tokens=settings.llm_max_output_tokens,
            reasoning_effort=settings.openai_reasoning_effort or None,
        )
    return Assistant(provider, DailyTokenBudget(settings.llm_daily_token_budget), CircuitBreaker())


def build_service(
    settings: Settings, with_llm: bool = True, model: TriageModel | None = None
) -> TriageService:
    return TriageService(
        model=model or TriageModel.load(settings.model_dir),
        kb=default_knowledge_base(),
        policy=load_policy(settings.sla_policy_path),
        assistant=build_assistant(settings) if with_llm else None,
    )
