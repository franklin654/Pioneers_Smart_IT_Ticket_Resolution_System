"""Typed, env-driven application settings.

Zero configuration in code (CLAUDE.md backend §13). Every environment-specific
value comes from an environment variable, documented with a sample in
`.env.example`. The process refuses to start if a required secret is missing
or still set to the old placeholder — audit fix H2 (`docs/03_BACKEND_DESIGN.md`).
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_REJECTED_ADMIN_PASSWORDS = {"changeme123", "password", "admin"}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        # Docker-only vars (POSTGRES_DB, GRAFANA_PASSWORD, ...) may share this .env
        # file without tripping validation on unrelated keys.
        extra="ignore",
    )

    # --- App ---
    app_name: str = "TicketIQ"
    app_version: str = "2.0.0"
    environment: Literal["development", "staging", "production"] = "development"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"

    # --- Database ---
    database_url: str
    db_pool_size: int = 10
    db_max_overflow: int = 20
    db_pool_timeout: int = 30
    db_echo: bool = False

    # --- Auth ---
    admin_username: str = "admin"
    admin_password: str
    jwt_secret_key: str
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 15
    refresh_token_expire_days: int = 7

    # --- LLM ---
    llm_provider: Literal["ollama", "claude"] = "ollama"
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "mistral:7b-instruct"
    ollama_timeout_seconds: int = 60
    anthropic_api_key: str | None = None
    claude_model: str = "claude-haiku-4-5-20251001"
    llm_temperature: float = 0.1
    llm_max_tokens: int = 1024

    # --- Embedding ---
    embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"
    embedding_dim: int = 384
    embedding_batch_size: int = 32

    # --- Classification thresholds ---
    confidence_high_threshold: float = 0.85
    confidence_low_threshold: float = 0.60
    multi_domain_diff_threshold: float = 0.15
    classifier_min_samples: int = 100

    # --- Routing / quality gate ---
    llm_quality_threshold: float = 3.5

    # --- RAG ---
    rag_dense_weight: float = 0.40
    rag_bm25_weight: float = 0.60
    rag_top_k: int = 5
    rag_candidate_pool: int = 20
    mmr_lambda: float = 0.7

    # --- Ingestion ---
    dedup_similarity_threshold: float = 0.95
    dedup_window_days: int = 7

    # --- API ---
    rate_limit_per_minute: int = 100
    cors_allowed_origins: list[str] = ["http://localhost:5173"]

    # --- Paths ---
    model_dir: str = "data/models"

    # --- Monitoring ---
    prometheus_enabled: bool = True

    @field_validator("admin_password")
    @classmethod
    def _reject_default_admin_password(cls, value: str) -> str:
        if not value or not value.strip():
            raise ValueError(
                "ADMIN_PASSWORD must be set — refusing to start with no admin password."
            )
        if value.strip().lower() in _REJECTED_ADMIN_PASSWORDS:
            raise ValueError(
                "ADMIN_PASSWORD is set to a known placeholder value. Choose a real secret."
            )
        return value

    @field_validator("jwt_secret_key")
    @classmethod
    def _require_strong_jwt_secret(cls, value: str) -> str:
        if not value or len(value) < 32:
            raise ValueError("JWT_SECRET_KEY must be set and at least 32 characters long.")
        return value

    @model_validator(mode="after")
    def _require_anthropic_key_when_selected(self) -> Settings:
        if self.llm_provider == "claude" and not self.anthropic_api_key:
            raise ValueError("ANTHROPIC_API_KEY is required when LLM_PROVIDER=claude.")
        return self


@lru_cache
def get_settings() -> Settings:
    """Process-wide settings singleton. Raises at import/first-call time if
    required configuration is missing — failing closed, never falling back to
    an insecure default (audit fix H2)."""
    return Settings()  # type: ignore[call-arg]
