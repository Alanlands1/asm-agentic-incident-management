"""Pydantic response and request schemas."""

from pydantic import BaseModel, Field


class MessageResponse(BaseModel):
    """Standard greeting message response."""
    message: str = Field(..., examples=["hello there"])


class HealthResponse(BaseModel):
    """Health check status response."""
    status: str = Field(..., examples=["healthy"])
    environment: str = Field(..., examples=["production"])
