"""Resolution agent, Phase 2: query transformation. A ticket becomes several search queries (multi-query) and a
hypothetical runbook entry (HyDE). Without a working model the ticket summary is the only query."""

import asyncio
import logging
from dataclasses import dataclass, field

from pydantic import BaseModel, Field, field_validator

from app.agents.resolution.case import CaseInput, call_masked, case_text, masker_for, spec_for
from app.llm import CallAudit, ModelError

logger = logging.getLogger("app.resolution")


class QuerySet(BaseModel):
    queries: list[str] = Field(min_length=3, max_length=5, description="3 to 5 short keyword queries")

    @field_validator("queries")
    @classmethod
    def no_blank(cls, queries: list[str]) -> list[str]:
        if any(not q.strip() for q in queries):
            raise ValueError("a query is empty")
        return [q.strip() for q in queries]


class Hypothetical(BaseModel):
    note: str = Field(min_length=20, description="What the runbook entry for this problem would say")


@dataclass(frozen=True)
class Expansion:
    queries: list[str]  # the ticket summary first, then the model's variants; de-duplicated, never empty
    hypothetical: str | None
    audits: list[CallAudit] = field(default_factory=list)


async def _ask(name: str, output, case: CaseInput) -> tuple | None:
    try:
        return await asyncio.to_thread(call_masked, spec_for(name, output), masker_for(case), case_text(case))
    except ModelError as exc:
        logger.warning(f"Resolution: {name} failed for {case.id}, using the ticket summary only: {exc!r}")
        return None


async def expand(case: CaseInput) -> Expansion:
    multi, hyde = await asyncio.gather(_ask("resolution_multiquery", QuerySet, case), _ask("resolution_hyde", Hypothetical, case))
    queries = [case.summary, *(multi[0].queries if multi else [])]
    queries = list(dict.fromkeys(q.strip() for q in queries if q and q.strip()))
    audits = [result[1] for result in (multi, hyde) if result]
    return Expansion(queries=queries, hypothetical=hyde[0].note if hyde else None, audits=audits)
