"""Agent settings: LLM + LangFuse + host tenant identity. Depends only on types."""

import logging
from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings

logger = logging.getLogger(__name__)


class AgentSettings(BaseSettings):
    openai_api_key: str = ""
    openai_base_url: str = ""
    # Legacy chat-model configuration. Preserved during migration so existing
    # OPENAI_CHAT_MODEL deployments keep working. Preferred interface is now
    # AGENTIC_ASSISTANT_FAST_MODEL / AGENTIC_ASSISTANT_REASONING_MODEL below.
    # When a new route variable is unset, the legacy value is used as fallback.
    openai_chat_model: str = "gpt-4o-mini"
    openai_fast_model: str = Field(
        default="gpt-4o-mini", validation_alias="AGENTIC_ASSISTANT_FAST_MODEL"
    )
    openai_reasoning_model: str = Field(
        default="gpt-5-nano", validation_alias="AGENTIC_ASSISTANT_REASONING_MODEL"
    )
    openai_retry_attempts: int = 3
    openai_retry_min_wait: float = 1.0
    openai_retry_max_wait: float = 10.0
    # Per-request timeout: an unbounded LLM call hangs its WebSocket task
    # forever (one stalled provider response wedged a live follow-up).
    openai_request_timeout_seconds: float = Field(
        default=120.0, gt=0, validation_alias="AGENTIC_ASSISTANT_LLM_TIMEOUT_SECONDS"
    )
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
    max_history_turns: int = Field(
        default=6, gt=0, validation_alias="AGENTIC_ASSISTANT_MAX_HISTORY_TURNS"
    )
    memory_max_tokens: int = Field(
        default=2048, gt=0, validation_alias="AGENTIC_ASSISTANT_MEMORY_MAX_TOKENS"
    )
    memory_summary_max_tokens: int = Field(
        default=768, gt=0, validation_alias="AGENTIC_ASSISTANT_MEMORY_SUMMARY_MAX_TOKENS"
    )
    ws_ticket_ttl_seconds: int = Field(
        default=60, gt=0, validation_alias="AGENTIC_ASSISTANT_WS_TICKET_TTL_SECONDS"
    )
    cors_allowed_origins: list[str] = Field(
        default=["http://localhost:3000", "http://localhost:3001"],
        validation_alias="AGENTIC_ASSISTANT_CORS_ORIGINS",
    )

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "extra": "ignore",
    }

    def resolve_fast_model(self) -> str:
        """Fast route model: new var wins, legacy chat model is the fallback."""
        if "openai_fast_model" not in self.model_fields_set and (
            "openai_chat_model" in self.model_fields_set
        ):
            return self.openai_chat_model
        return self.openai_fast_model

    def resolve_reasoning_model(self) -> str:
        """Reasoning route model: new var wins, legacy chat model is fallback."""
        if "openai_reasoning_model" not in self.model_fields_set and (
            "openai_chat_model" in self.model_fields_set
        ):
            return self.openai_chat_model
        return self.openai_reasoning_model

    def model_for_route(self, route: str) -> str:
        if route == "fast":
            return self.resolve_fast_model()
        if route == "reasoning":
            return self.resolve_reasoning_model()
        raise ValueError(f"unknown model route: {route!r}")


@lru_cache
def get_agent_settings() -> AgentSettings:
    settings = AgentSettings()
    logger.info(
        "agent settings loaded: fast_model=%s reasoning_model=%s "
        "legacy_chat_model=%s tenant=%s openai_configured=%s "
        "langfuse_configured=%s service_token_configured=%s jwt_configured=%s db_configured=%s",
        settings.resolve_fast_model(),
        settings.resolve_reasoning_model(),
        settings.openai_chat_model,
        settings.default_tenant,
        bool(settings.openai_api_key),
        bool(settings.langfuse_public_key and settings.langfuse_secret_key),
        bool(settings.agent_service_token),
        bool(settings.assistant_jwt_secret),
        bool(settings.agentic_assistant_database_url),
    )
    return settings
