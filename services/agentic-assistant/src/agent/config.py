"""Agent settings: LLM + LangFuse + host tenant identity. Depends only on types."""

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings


class AgentSettings(BaseSettings):
    openai_api_key: str = ""
    openai_base_url: str = ""
    openai_chat_model: str = "gpt-4o-mini"
    openai_retry_attempts: int = 3
    openai_retry_min_wait: float = 1.0
    openai_retry_max_wait: float = 10.0
    langfuse_public_key: str = ""
    langfuse_secret_key: str = ""
    langfuse_base_url: str = ""
    # Corpus identity this host stamps when it builds filters for callers
    # that carry no tenant of their own. Distinct per independent project
    # sharing one RAG backend (mirrors services/api `rag_tenant = "api"`).
    default_tenant: str = Field(
        default="agentic-assistant", validation_alias="AGENTIC_ASSISTANT_TENANT"
    )
    # Machine-to-machine bearer for the ingest/purge routes below. The auth
    # session owns user identity; this token gates service callers only.
    # Shared secret, mirrored as `agent_service_token` in services/api.
    # Empty = ingest routes answer 503 (fail closed, never world-open).
    agent_service_token: str = Field(default="", validation_alias="AGENTIC_ASSISTANT_SERVICE_TOKEN")
    # User-identity secret for the same routes: assistant JWTs minted by the
    # login flow are verified with this (see agent.authz). Browser callers
    # present `Authorization: Bearer <admin JWT>` after frontend login.
    # Must match the minter's secret. Empty = JWT path absent; the service
    # token path alone decides (fail closed, never accept unsigned claims).
    assistant_jwt_secret: str = Field(default="", validation_alias="AGENTIC_ASSISTANT_JWT_SECRET")
    agentic_assistant_database_url: str = Field(
        default="", validation_alias="AGENTIC_ASSISTANT_DATABASE_URL"
    )
    agentic_assistant_admin_email: str = Field(
        default="", validation_alias="AGENTIC_ASSISTANT_ADMIN_EMAIL"
    )
    agentic_assistant_admin_password: str = Field(
        default="", validation_alias="AGENTIC_ASSISTANT_ADMIN_PASSWORD"
    )
    agentic_assistant_jwt_ttl_seconds: int = Field(
        default=12 * 3600,
        gt=0,
        validation_alias="AGENTIC_ASSISTANT_JWT_TTL_SECONDS",
    )

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


@lru_cache
def get_agent_settings() -> AgentSettings:
    return AgentSettings()
