"""Admin API schemas."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class SettingOut(BaseModel):
    """One setting: what runs now, what .env says, and whether an admin changed it."""
    key: str = Field(..., examples=["LLM_MODEL"])
    value: Any = Field(..., examples=["claude-opus-5-5"])
    baseline: Any = Field(..., examples=["claude-opus-5-5"], description="Value from .env or the default")
    overridden: bool = Field(..., examples=[False])
    editable: bool = Field(..., examples=[True], description="False for paths, secrets and guardrail limits")


class SettingIn(BaseModel):
    value: Any = Field(..., examples=["claude-haiku-5-5"])


class DocumentOut(BaseModel):
    """A reference document: rules, PII terms, applications or prompts."""
    name: str = Field(..., examples=["prompts"])
    overridden: bool = Field(..., examples=[False], description="False = the file in data/registry is in use")
    document: Any


class DocumentIn(BaseModel):
    document: Any = Field(..., description="The whole document, same shape as the YAML file")


class ChangeOut(BaseModel):
    """One admin change."""
    model_config = ConfigDict(from_attributes=True)

    id: int
    kind: str = Field(..., examples=["setting"])
    key: str = Field(..., examples=["LLM_MODEL"])
    old_value: Any
    new_value: Any = Field(..., description="null when the override was removed")
    claimed_by: str = Field(..., description="From X-Admin-User; not verified until real logins exist")
    changed_at: datetime
