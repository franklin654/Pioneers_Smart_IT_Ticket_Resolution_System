"""Unit tests for application configuration (src/core/config.py).

All tests instantiate Settings directly with keyword arguments so they
are independent of any .env file on disk.
"""

import pytest
from pydantic import ValidationError

from src.core.config import Settings, get_settings

# Minimum valid kwargs — every test starts from here and overrides as needed
_VALID_BASE = {
    "database_url": "postgresql+asyncpg://user:pass@localhost:5432/db",
    "secret_key": "a" * 32,
}


class TestSettingsDefaults:
    def test_app_env_defaults_to_development(self):
        s = Settings(**_VALID_BASE)
        assert s.app_env == "development"

    def test_llm_backend_defaults_to_ollama(self):
        s = Settings(**_VALID_BASE)
        assert s.llm_backend == "ollama"

    def test_confidence_thresholds_defaults(self):
        s = Settings(**_VALID_BASE)
        assert s.confidence_high_threshold == 0.85
        assert s.confidence_low_threshold == 0.60
        assert s.multi_domain_diff_threshold == 0.15

    def test_rag_weights_sum_to_one(self):
        s = Settings(**_VALID_BASE)
        assert abs(s.rag_dense_weight + s.rag_bm25_weight - 1.0) < 1e-9

    def test_is_production_false_by_default(self):
        s = Settings(**_VALID_BASE)
        assert s.is_production is False

    def test_is_development_true_by_default(self):
        s = Settings(**_VALID_BASE)
        assert s.is_development is True


class TestSettingsValidation:
    def test_secret_key_too_short_raises(self):
        with pytest.raises(ValidationError, match="at least 32 characters"):
            Settings(
                database_url="postgresql+asyncpg://user:pass@localhost/db",
                secret_key="tooshort",
            )

    def test_secret_key_exactly_32_chars_accepted(self):
        s = Settings(**{**_VALID_BASE, "secret_key": "x" * 32})
        assert len(s.secret_key) == 32

    def test_claude_backend_without_api_key_raises(self):
        with pytest.raises(ValidationError, match="anthropic_api_key is required"):
            Settings(**_VALID_BASE, llm_backend="claude", anthropic_api_key="")

    def test_claude_backend_with_api_key_succeeds(self):
        s = Settings(**_VALID_BASE, llm_backend="claude", anthropic_api_key="sk-valid")
        assert s.llm_backend == "claude"

    def test_invalid_app_env_raises(self):
        with pytest.raises(ValidationError):
            Settings(**_VALID_BASE, app_env="unknown")


class TestSettingsProperties:
    def test_is_production_true_in_production(self):
        s = Settings(**_VALID_BASE, app_env="production")
        assert s.is_production is True
        assert s.is_development is False

    def test_is_development_true_in_development(self):
        s = Settings(**_VALID_BASE, app_env="development")
        assert s.is_development is True
        assert s.is_production is False


class TestGetSettings:
    def test_get_settings_returns_same_instance(self, monkeypatch):
        """get_settings must be cached — same object on repeated calls."""
        monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://u:p@localhost/db")
        monkeypatch.setenv("SECRET_KEY", "a" * 32)
        get_settings.cache_clear()

        s1 = get_settings()
        s2 = get_settings()
        assert s1 is s2

        get_settings.cache_clear()  # restore clean state for other tests

    def test_get_settings_is_settings_instance(self, monkeypatch):
        monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://u:p@localhost/db")
        monkeypatch.setenv("SECRET_KEY", "a" * 32)
        get_settings.cache_clear()

        assert isinstance(get_settings(), Settings)

        get_settings.cache_clear()
