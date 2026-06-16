"""Settings must fail closed: missing/placeholder secrets raise at
construction time rather than silently falling back (audit fix H2)."""

import pytest
from pydantic import ValidationError

from src.core.config import Settings

_BASE_KWARGS = {
    "database_url": "postgresql+asyncpg://user:pass@localhost/test",
    "jwt_secret_key": "a" * 32,
    "admin_password": "a-real-production-secret",
}


def test_valid_settings_construct_successfully() -> None:
    settings = Settings(_env_file=None, **_BASE_KWARGS)
    assert settings.admin_password == "a-real-production-secret"
    assert settings.llm_provider == "ollama"


@pytest.mark.parametrize("bad_password", ["changeme123", "password", "admin", "", "   "])
def test_rejects_missing_or_placeholder_admin_passwords(bad_password: str) -> None:
    kwargs = {**_BASE_KWARGS, "admin_password": bad_password}
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **kwargs)


@pytest.mark.parametrize("bad_secret", ["short", "a" * 31])
def test_rejects_short_jwt_secret(bad_secret: str) -> None:
    kwargs = {**_BASE_KWARGS, "jwt_secret_key": bad_secret}
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **kwargs)


def test_requires_anthropic_key_when_claude_provider_selected() -> None:
    kwargs = {**_BASE_KWARGS, "llm_provider": "claude", "anthropic_api_key": None}
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **kwargs)


def test_claude_provider_is_fine_once_key_is_present() -> None:
    kwargs = {**_BASE_KWARGS, "llm_provider": "claude", "anthropic_api_key": "sk-ant-test"}
    settings = Settings(_env_file=None, **kwargs)
    assert settings.llm_provider == "claude"
