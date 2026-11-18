"""Resolution agent API schemas."""

from typing import Any

from pydantic import BaseModel


class ResolutionRunResponse(BaseModel):
    evaluated: int
    skipped: int
    model_errors: int
    by_verdict: dict[str, int]


class ResolutionCheckResponse(BaseModel):
    """What the runbooks say about one ticket."""
    ticket_id: str
    verdict: str  # resolved | no_match
    stage: str
    output: dict[str, Any]
