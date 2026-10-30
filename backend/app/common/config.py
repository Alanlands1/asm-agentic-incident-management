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

    # Storage
    DATABASE_URL: str = f"sqlite:///{(API_DIR / 'ams.db').as_posix()}"
    TICKETS_FILE: Path = REPO_DIR / "data" / "tickets" / "ams_tickets.xlsx"
    REGISTRY_DIR: Path = REPO_DIR / "data" / "registry"  # editable rules and application terms

    # Model access (app/llm). Off by default: without it the pipeline runs rules only.
    LLM_ENABLED: bool = False
    LLM_PROVIDER: Literal["anthropic", "bedrock"] = "anthropic"
    LLM_MODEL: str = "claude-opus-5-5"
    LLM_EFFORT: Literal["low", "medium", "high", "xhigh", "max"] = "low"  # classification-sized tasks
    LLM_REFUSAL_FALLBACK: bool = True  # Claude API only; not supported by every model
    LLM_TIMEOUT_S: float = Field(60.0, gt=0)
    LLM_TRANSPORT_RETRIES: int = Field(2, ge=0, le=10)  # network, timeout, 429 and 5xx retries inside the SDK
    LLM_VALIDATION_ATTEMPTS: int = Field(2, ge=1, le=5)  # 2 = one retry when an answer fails validation
    AWS_REGION: str = "ca-central-1"  # bedrock only; must be in ALLOWED_AWS_REGIONS
    ANTHROPIC_API_KEY: SecretStr = SecretStr("")  # empty = the SDK's own lookup (environment, `ant auth login`)

    # Data Quality run
    DQ_OUTAGE_BREAKER: int = Field(5, ge=1)  # consecutive "model unavailable" failures that stop a run

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
    "LLM_ENABLED",
    "LLM_PROVIDER",
    "LLM_MODEL",
    "LLM_EFFORT",
    "LLM_REFUSAL_FALLBACK",
    "LLM_TIMEOUT_S",
    "LLM_TRANSPORT_RETRIES",
    "LLM_VALIDATION_ATTEMPTS",
    "AWS_REGION",
    "DQ_OUTAGE_BREAKER",
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
