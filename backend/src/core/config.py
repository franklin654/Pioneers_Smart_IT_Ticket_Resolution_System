"""Application configuration loaded from environment variables.

All settings are sourced from a .env file or the process environment.
Use ``get_settings()`` to obtain the singleton instance.
"""

from functools import lru_cache
from typing import Literal

from pydantic import PostgresDsn, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Central configuration object for the ticket routing application.

    All fields map 1-to-1 with environment variables (case-insensitive).
    Required fields without defaults will raise ``ValidationError`` at
    startup if the environment variable is missing.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── App ────────────────────────────────────────────────────────────────
    app_name: str = "IT Ticket Routing Agent"
    app_version: str = "0.1.0"
    app_env: Literal["development", "staging", "production"] = "development"
    debug: bool = False

    # ── Database ───────────────────────────────────────────────────────────
    database_url: PostgresDsn  # required
    db_pool_size: int = 10
    db_max_overflow: int = 20
    db_pool_timeout: int = 30
    db_echo: bool = False  # set True to log all SQL (noisy in production)

    # ── JWT / Auth ─────────────────────────────────────────────────────────
    secret_key: str  # required; minimum 32 characters enforced below
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 60
    refresh_token_expire_days: int = 7

    # ── Embedding ──────────────────────────────────────────────────────────
    embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"
    embedding_dim: int = 384
    embedding_batch_size: int = 32

    # ── Classification thresholds ──────────────────────────────────────────
    confidence_high_threshold: float = 0.85
    confidence_low_threshold: float = 0.60
    # Gap between top-2 probabilities below which a ticket is multi-domain
    multi_domain_diff_threshold: float = 0.15

    # ── LLM backend ────────────────────────────────────────────────────────
    llm_backend: Literal["ollama", "claude"] = "ollama"
    ollama_base_url: str = "http://ollama:11434"
    ollama_model: str = "mistral:7b-instruct"
    ollama_timeout: int = 60
    anthropic_api_key: str = ""
    claude_model: str = "claude-haiku-4-5-20251001"
    llm_temperature: float = 0.1
    llm_max_tokens: int = 1024

    # ── RAG ────────────────────────────────────────────────────────────────
    rag_dense_weight: float = 0.70
    rag_bm25_weight: float = 0.30
    rag_top_k: int = 5
    rag_candidate_pool: int = 20  # fetch this many before MMR reranking
    mmr_lambda: float = 0.7  # relevance vs diversity trade-off (higher = more relevant)

    # ── Ingestion / deduplication ──────────────────────────────────────────
    dedup_similarity_threshold: float = 0.95
    dedup_window_days: int = 7

    # ── Rate limiting ──────────────────────────────────────────────────────
    rate_limit_per_minute: int = 100

    # ── CORS ───────────────────────────────────────────────────────────────
    cors_origins: list[str] = ["http://localhost:4200", "http://localhost:3000"]

    # ── Classification ─────────────────────────────────────────────────────
    model_dir: str = "data/models"          # directory for saved classifier artifacts
    classifier_min_samples: int = 100       # minimum labeled tickets required to train

    # ── Admin credentials (hackathon demo auth) ────────────────────────────
    admin_username: str = "admin"
    admin_password: str  # required; must be set in .env — no insecure default

    # ── Monitoring ─────────────────────────────────────────────────────────
    prometheus_enabled: bool = True

    # ── Validators ─────────────────────────────────────────────────────────

    @field_validator("secret_key")
    @classmethod
    def secret_key_min_length(cls, v: str) -> str:
        if len(v) < 32:
            raise ValueError("secret_key must be at least 32 characters")
        return v

    @field_validator("admin_password")
    @classmethod
    def admin_password_not_placeholder(cls, v: str) -> str:
        if not v or v == "changeme123":
            raise ValueError(
                "ADMIN_PASSWORD must be set to a non-default value in .env"
            )
        return v

    @model_validator(mode="after")
    def claude_api_key_required_when_claude_backend(self) -> "Settings":
        if self.llm_backend == "claude" and not self.anthropic_api_key:
            raise ValueError(
                "anthropic_api_key is required when llm_backend='claude'. "
                "Set ANTHROPIC_API_KEY in your .env file."
            )
        return self

    # ── Computed properties ────────────────────────────────────────────────

    @property
    def is_production(self) -> bool:
        """Return True when running in production environment."""
        return self.app_env == "production"

    @property
    def is_development(self) -> bool:
        """Return True when running in development environment."""
        return self.app_env == "development"


@lru_cache
def get_settings() -> Settings:
    """Return the application settings singleton.

    Uses ``functools.lru_cache`` so the Settings object (and any
    file/env reads) are performed only once per process.
    """
    return Settings()
