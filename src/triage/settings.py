"""Runtime settings, read from environment variables prefixed with TRIAGE_.

Nothing secret has a default. In Azure the container app gets its settings from Terraform, and the
only secret values (the analyst key and the session signing key) come from Key Vault references.
"""

from __future__ import annotations

import secrets
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import AliasChoices, Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="TRIAGE_", env_file=".env", extra="ignore")

    env: Literal["dev", "test", "prod"] = "dev"

    # Database: either a full SQLAlchemy URL (local SQLite or SQL Server with a SQL login), or an
    # Azure SQL server and database reached with a Microsoft Entra token from the managed identity.
    database_url: str | None = None
    sql_server: str | None = None
    sql_database: str | None = None
    azure_client_id: str | None = Field(
        default=None, validation_alias=AliasChoices("TRIAGE_AZURE_CLIENT_ID", "AZURE_CLIENT_ID")
    )

    model_dir: Path = Path("models")
    sla_policy_path: str | None = None

    # Who can review tickets. "none" is for local development only and is refused in prod.
    auth_mode: Literal["none", "easyauth", "apikey"] = "none"
    trust_easy_auth_headers: bool = False
    analyst_ids: str = ""  # comma-separated Microsoft Entra object IDs
    analyst_api_key: SecretStr | None = None
    session_secret: SecretStr = Field(default_factory=lambda: SecretStr(secrets.token_urlsafe(32)))

    # Optional language model assistant.
    llm_provider: Literal["disabled", "stub", "azure_openai"] = "disabled"
    openai_endpoint: str | None = None
    openai_deployment: str | None = None
    openai_api_version: str = "2025-04-01-preview"
    openai_reasoning_effort: Literal["", "minimal", "low", "medium", "high"] = ""
    llm_timeout_seconds: float = 20.0
    llm_daily_token_budget: int = 200_000
    llm_max_output_tokens: int = 1500

    retention_days: int = 30
    auto_migrate: bool = False  # run migrations at startup (local only; Azure uses the migrate job)
    seed_demo: bool = False  # add the synthetic demo queue at startup if it is empty (local only)
    repo_url: str = ""
    rate_limit_per_minute: int = 20
    max_body_chars: int = 6000

    applicationinsights_connection_string: SecretStr | None = Field(
        default=None, validation_alias=AliasChoices("APPLICATIONINSIGHTS_CONNECTION_STRING")
    )

    @property
    def analyst_id_set(self) -> frozenset[str]:
        return frozenset(i.strip().lower() for i in self.analyst_ids.split(",") if i.strip())

    @property
    def is_azure_sql(self) -> bool:
        return self.database_url is None and self.sql_server is not None

    @model_validator(mode="after")
    def _check(self) -> Settings:
        if self.env == "prod" and self.database_url is None and self.sql_server is None:
            raise ValueError("prod needs TRIAGE_SQL_SERVER or TRIAGE_DATABASE_URL")
        if self.llm_provider == "azure_openai" and not (self.openai_endpoint and self.openai_deployment):
            raise ValueError("azure_openai needs TRIAGE_OPENAI_ENDPOINT and TRIAGE_OPENAI_DEPLOYMENT")
        if self.sql_server and not self.sql_database:
            raise ValueError("TRIAGE_SQL_SERVER needs TRIAGE_SQL_DATABASE")
        return self

    def check_web(self) -> None:
        """Sign-in checks for serving web requests. The maintenance jobs do not serve requests, so they
        do not need the analyst key or the Easy Auth settings."""
        if self.env != "prod":
            return
        if self.auth_mode == "none":
            raise ValueError("TRIAGE_AUTH_MODE=none is only allowed outside prod")
        if self.auth_mode == "easyauth" and not self.trust_easy_auth_headers:
            raise ValueError(
                "easyauth mode needs TRIAGE_TRUST_EASY_AUTH_HEADERS=true behind Container Apps auth"
            )
        if self.auth_mode == "apikey" and not self.analyst_api_key:
            raise ValueError("apikey mode needs TRIAGE_ANALYST_API_KEY")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
