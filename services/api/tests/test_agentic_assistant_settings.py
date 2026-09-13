"""The API's agentic-assistant integration uses the shared namespace."""

from app.config.settings import Settings


def test_agentic_assistant_service_settings_use_prefixed_env(monkeypatch):
    monkeypatch.setenv("AGENTIC_ASSISTANT_SERVICE_URL", "http://agent:8001")
    monkeypatch.setenv("AGENTIC_ASSISTANT_SERVICE_TOKEN", "service-token")
    monkeypatch.setenv("AGENT_SERVICE_URL", "http://legacy-agent:8001")
    monkeypatch.setenv("AGENT_SERVICE_TOKEN", "legacy-token")

    settings = Settings(_env_file=None)

    assert settings.agent_service_url == "http://agent:8001"
    assert settings.agent_service_token == "service-token"
