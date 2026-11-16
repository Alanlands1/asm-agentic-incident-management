"""Resolution agent, Phase 4: the ReAct loop. The model searches the runbooks and reads the excerpts, then finishes with an
answer (resolved, with steps and references) or no_match. Rules R1-R3 are in the prompt, resolution_react in prompts.yaml.

The transcript (case, excerpts, thoughts) is re-sent on every call. Searches use a short database session each; no
session is open during a model call.
"""

import asyncio
from dataclasses import dataclass, field

from app.agents.resolution.answer import ReActStep, ResolutionAnswer, unseen_references
from app.agents.resolution.case import CaseInput, call_masked, case_text, masker_for, spec_for
from app.agents.resolution.embedding import Embedder
from app.agents.resolution.filters import filters_for
from app.agents.resolution.queries import expand
from app.agents.resolution.retrieval import Filters, RetrievedChunk, search_all
from app.core.registry import load_registry
from app.db.session import AsyncSessionLocal
from app.llm import CallAudit

MAX_SEARCHES = 4  # searches after the first one
SHOWN = 5  # excerpts per search
MAX_CALLS = MAX_SEARCHES + 2  # every search, one finish and one spare for a rejected finish
PROMPTS = ("resolution_multiquery", "resolution_hyde", "resolution_react")


@dataclass(frozen=True)
class Resolution:
    answer: ResolutionAnswer
    filters: Filters
    queries: list[str]  # the first search's queries
    hypothetical: str | None
    trace: list[dict]
    audits: list[CallAudit] = field(default_factory=list)


def prompt_versions() -> str:
    """Changes when any resolution prompt changes; part of the input hash so tickets are resolved again."""
    prompts = load_registry("prompts.yaml")
    return "|".join(prompts[name]["version"] for name in PROMPTS)


async def _search(
    queries: list[str], embedder: Embedder | None, filters: Filters, weights: dict[str, float]
) -> list[RetrievedChunk]:
    vectors = [await asyncio.to_thread(embedder.embed_query, q) for q in queries] if embedder else [None] * len(queries)
    async with AsyncSessionLocal() as db:
        return await search_all(db, queries, vectors, filters, weights=weights)


def _render(chunks: list[RetrievedChunk]) -> str:
    if not chunks:
        return "No excerpts found."
    return "\n\n".join(f"[{c.kb_id or 'no KB id'}] {c.app} | {c.heading_path}\n{c.content}" for c in chunks)


async def _observe(
    queries: list[str], embedder: Embedder | None, filters: Filters, weights: dict[str, float], trace: list[dict], turn: int
) -> tuple[str, set[str]]:
    shown = (await _search(queries, embedder, filters, weights))[:SHOWN]
    kb_ids = [c.kb_id for c in shown if c.kb_id]
    trace.append({"turn": turn, "queries": queries, "kb_ids": kb_ids})
    return _render(shown), set(kb_ids)


async def resolve(case: CaseInput, embedder: Embedder | None = None) -> Resolution:
    """Find a runbook answer for one ticket. Raises app.llm.ModelError when the model cannot answer."""
    filters = filters_for(case.application)
    expansion = await expand(case)
    queries = expansion.queries + ([expansion.hypothetical] if expansion.hypothetical else [])
    trace: list[dict] = []
    audits = list(expansion.audits)

    observation, seen = await _observe(queries, embedder, filters, case.kb_weights, trace, turn=0)
    log = [f"Search: {queries}\nExcerpts:\n{observation}"]  # what the model reads after the ticket
    spec, masker = spec_for("resolution_react", ReActStep), masker_for(case)
    searches = 0

    for turn in range(1, MAX_CALLS + 1):
        step, audit = await asyncio.to_thread(call_masked, spec, masker, "\n\n".join([case_text(case), *log]))
        audits.append(audit)
        log.append(f"Thought: {step.thought}")

        if step.action == "finish":
            missing = unseen_references(step.answer, seen)
            if not missing:
                return Resolution(step.answer, filters, queries, expansion.hypothetical, trace, audits)
            trace.append({"turn": turn, "rejected_references": missing})
            log.append(
                f"Your answer cites {', '.join(missing)}, which no excerpt showed. "
                "Cite only KB ids shown above, or search again."
            )
            continue

        if searches >= MAX_SEARCHES:
            log.append("Search limit reached. Finish now with the excerpts you have.")
            continue
        searches += 1
        observation, ids = await _observe([step.query], embedder, filters, case.kb_weights, trace, turn=turn)
        seen |= ids
        log.append(f"Search: {step.query}\nExcerpts:\n{observation}")

    answer = ResolutionAnswer(
        verdict="no_match", confidence="low",
        notes="No answer within the search limit. Escalate to the support group for the application.",
    )
    return Resolution(answer, filters, queries, expansion.hypothetical, trace, audits)
