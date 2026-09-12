"""Agentic-assistant environment namespace contract."""

from agent.config import AgentSettings


def test_identity_settings_use_agentic_assistant_namespace(monkeypatch):
    monkeypatch.setenv("AGENTIC_ASSISTANT_DATABASE_URL", "postgresql://db")
    monkeypatch.setenv("AGENTIC_ASSISTANT_ADMIN_EMAIL", "root@example.com")
    monkeypatch.setenv("AGENTIC_ASSISTANT_ADMIN_PASSWORD", "password")
    monkeypatch.setenv("AGENTIC_ASSISTANT_JWT_SECRET", "jwt-secret")
    monkeypatch.setenv("AGENTIC_ASSISTANT_JWT_TTL_SECONDS", "900")
    monkeypatch.setenv("AGENTIC_ASSISTANT_SERVICE_TOKEN", "service-token")
    monkeypatch.setenv("AGENTIC_ASSISTANT_MAX_HISTORY_TURNS", "6")
    monkeypatch.setenv("AGENTIC_ASSISTANT_MEMORY_MAX_TOKENS", "2048")
    monkeypatch.setenv("AGENTIC_ASSISTANT_MEMORY_SUMMARY_MAX_TOKENS", "768")
    monkeypatch.setenv("AGENTIC_ASSISTANT_WS_TICKET_TTL_SECONDS", "60")
    monkeypatch.setenv("AGENTIC_ASSISTANT_TENANT", "assistant")
    monkeypatch.setenv("ASSISTANT_JWT_SECRET", "legacy-secret")
    monkeypatch.setenv("AGENT_SERVICE_TOKEN", "legacy-token")

    settings = AgentSettings(_env_file=None)

    assert settings.agentic_assistant_database_url == "postgresql://db"
    assert settings.agentic_assistant_admin_email == "root@example.com"
    assert settings.agentic_assistant_admin_password == "password"
    assert settings.assistant_jwt_secret == "jwt-secret"
    assert settings.agentic_assistant_jwt_ttl_seconds == 900
    assert settings.agent_service_token == "service-token"
    assert settings.default_tenant == "assistant"
    assert settings.max_history_turns == 6
    assert settings.memory_max_tokens == 2048
    assert settings.memory_summary_max_tokens == 768
    assert settings.ws_ticket_ttl_seconds == 60


def test_memory_settings_ignore_unscoped_environment_names(monkeypatch):
    for name in (
        "AGENTIC_ASSISTANT_MAX_HISTORY_TURNS",
        "AGENTIC_ASSISTANT_MEMORY_MAX_TOKENS",
        "AGENTIC_ASSISTANT_MEMORY_SUMMARY_MAX_TOKENS",
        "AGENTIC_ASSISTANT_WS_TICKET_TTL_SECONDS",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("MAX_HISTORY_TURNS", "99")
    monkeypatch.setenv("MEMORY_MAX_TOKENS", "99")
    monkeypatch.setenv("WS_TICKET_TTL_SECONDS", "99")

    settings = AgentSettings(_env_file=None)

    assert settings.max_history_turns == 6
    assert settings.memory_max_tokens == 2048
    assert settings.ws_ticket_ttl_seconds == 60
