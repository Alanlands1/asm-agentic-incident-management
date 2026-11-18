"""Application core configuration."""

from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

API_DIR = Path(__file__).resolve().parents[2]
REPO_DIR = API_DIR.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    PROJECT_NAME: str = "AMS Agentic Incident Management"
    ENVIRONMENT: str = "production"
    DEBUG: bool = False
    API_V1_STR: str = "/api/v1"

    # CORS
    CORS_ORIGINS: list[str] = ["*"]

    @field_validator("CORS_ORIGINS", mode="before")
    @classmethod
    def assemble_cors_origins(cls, v: str | list[str]) -> list[str]:
        if isinstance(v, str) and not v.startswith("["):
            return [i.strip() for i in v.split(",")]
        return v

    LOG_LEVEL: str = "INFO"

    # Storage / Database (PostgreSQL / Supabase default)
    DATABASE_URL: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/postgres"
    DB_POOL_SIZE: int = 5
    DB_MAX_OVERFLOW: int = 10
    DB_POOL_PRE_PING: bool = True
    DB_ECHO: bool = False

    TICKETS_FILE: Path = REPO_DIR / "data" / "tickets" / "ams_tickets.xlsx"
    REGISTRY_DIR: Path = REPO_DIR / "data" / "registry"  # editable rules and application terms
    KB_DIR: Path = REPO_DIR / "data" / "knowledge_base"  # Resolution agent runbooks (markdown)

    # Privacy / PII Masking
    PII_MASKING_ENABLED: bool = True

    # Model access (app/llm). Off by default: without it the pipeline runs rules only.
    LLM_ENABLED: bool = False
    LLM_PROVIDER: Literal["anthropic", "bedrock"] = "anthropic"
    LLM_MODEL: str = "claude-sonnet-5-5"  # same accuracy as Opus on the triage eval at half the cost
    LLM_EFFORT: Literal["low", "medium", "high", "xhigh", "max"] = "low"  # classification-sized tasks
    # Per agent; None = use LLM_MODEL / LLM_EFFORT above.
    DQ_LLM_MODEL: str | None = Field(None, min_length=1)
    DQ_LLM_EFFORT: Literal["low", "medium", "high", "xhigh", "max"] | None = None
    TRIAGE_LLM_MODEL: str | None = Field(None, min_length=1)
    TRIAGE_LLM_EFFORT: Literal["low", "medium", "high", "xhigh", "max"] | None = None
    LLM_REFUSAL_FALLBACK: bool = True  # Claude API only; not supported by every model
    LLM_TIMEOUT_S: float = Field(60.0, gt=0)
    LLM_TRANSPORT_RETRIES: int = Field(2, ge=0, le=10)  # network, timeout, 429 and 5xx retries inside the SDK
    LLM_VALIDATION_ATTEMPTS: int = Field(2, ge=1, le=5)  # 2 = one retry when an answer fails validation
    AWS_REGION: str = "ca-central-1"  # bedrock only; must be in ALLOWED_AWS_REGIONS
    ANTHROPIC_API_KEY: SecretStr = SecretStr("")  # empty = the SDK's own lookup (environment, `ant auth login`)

    # Monitoring: API request traces to Arize Phoenix (app/core/telemetry.py)
    PHOENIX_ENABLED: bool = False
    PHOENIX_COLLECTOR_ENDPOINT: str = "http://localhost:6006/v1/traces"
    PHOENIX_PROJECT_NAME: str = "ams-incident-management"

    # Resolution agent: knowledge base chunking and retrieval index (see backend/db/scripts/04_create_kb_chunks.sql)
    EMBEDDING_MODEL: str = "google/embeddinggemma-300m"  # embeddings are generated outside this app; recorded per row
    EMBEDDING_DIM: int = Field(256, ge=32, le=1024)  # Matryoshka truncation; must match kb_chunks.embedding
    KB_CONTEXT_MODEL: str = "claude-haiku-5-5"  # contextual retrieval: one short blurb per chunk, at ingest time
    KB_CHUNK_SIZE: int = Field(1200, gt=100)  # characters; larger issue blocks are split with overlap
    KB_CHUNK_OVERLAP: int = Field(150, ge=0)

    # Data Quality run
    DQ_OUTAGE_BREAKER: int = Field(5, ge=1)  # consecutive "model unavailable" failures that stop a run

    # Triage run
    TRIAGE_OUTAGE_BREAKER: int = Field(5, ge=1)  # same, for the Triage model stage

    # Jira Cloud (read-only pull into servicenow_tickets). Unset URL, email or token = Jira switched off.
    ATLASSIAN_BASE_URL: str = ""
    ATLASSIAN_EMAIL: str = ""
    ATLASSIAN_API_TOKEN: SecretStr = SecretStr("")
    JIRA_SYNC_MINUTES: int = Field(0, ge=0)  # 0 = no automatic sync, only "Sync now"
    SLA_AUTO_WARN: bool = False  # true = the system comments on a Jira issue at every 25% of its SLA target (if JIRA_WRITE_BACK)
    JIRA_WRITE_BACK: bool = False  # true = comments, reviewed priorities and the triaged status are written to the Jira issue
    CONFLUENCE_SYNC_MINUTES: int = Field(0, ge=0)  # knowledge base copy; 0 = only "Sync now"

    # Closure Quality run
    CLOSURE_OUTAGE_BREAKER: int = Field(5, ge=1)  # same, for the Closure Quality model stage

    # Admin API. Unset key = admin endpoints switched off. Set both in the environment only, never through the API.
    ADMIN_API_KEY: str = ""
    ALLOWED_AWS_REGIONS: list[str] = ["ca-central-1"]

    @model_validator(mode="after")
    def region_allowed(self) -> "Settings":
        if self.AWS_REGION not in self.ALLOWED_AWS_REGIONS:
            raise ValueError(f"AWS_REGION {self.AWS_REGION} is not in ALLOWED_AWS_REGIONS")
        return self


# What the admin API may change at runtime. Everything else (storage paths, secrets, the admin key, the region
# allow-list) is set in the environment only, so the API cannot loosen its own guardrails.
ADMIN_EDITABLE = frozenset({
    "LOG_LEVEL",
    "PII_MASKING_ENABLED",
    "LLM_ENABLED",
    "LLM_PROVIDER",
    "LLM_MODEL",
    "LLM_EFFORT",
    "DQ_LLM_MODEL",
    "DQ_LLM_EFFORT",
    "TRIAGE_LLM_MODEL",
    "TRIAGE_LLM_EFFORT",
    "LLM_REFUSAL_FALLBACK",
    "LLM_TIMEOUT_S",
    "LLM_TRANSPORT_RETRIES",
    "LLM_VALIDATION_ATTEMPTS",
    "AWS_REGION",
    "DQ_OUTAGE_BREAKER",
    "TRIAGE_OUTAGE_BREAKER",
    "CLOSURE_OUTAGE_BREAKER",
    "JIRA_SYNC_MINUTES",
    "CONFLUENCE_SYNC_MINUTES",
})

settings = Settings()

# Bumped on every admin change. Anything built from settings or reference documents caches per version, so a change
# reaches every cache without the code making the change having to know which caches exist.
_config_version = 0


def config_version() -> int:
    return _config_version


def bump_config_version() -> None:
    global _config_version
    _config_version += 1
