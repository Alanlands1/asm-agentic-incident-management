"""Run the Resolution agent over tickets that are ready for it (REVIEWED) and record each answer as an agent_runs row."""

import logging
from collections import Counter
from dataclasses import asdict, dataclass, field

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.agents.resolution.case import CaseInput
from app.agents.resolution.embedding import Embedder
from app.agents.resolution.react import Resolution, prompt_versions, resolve
from app.core.config import settings
from app.db.session import AsyncSessionLocal
from app.llm import ModelError
from app.models.ticket import AgentRun, Feedback, PipelineStatus, Ticket
from app.services.data_quality import fingerprint, last_run, reporter_text

logger = logging.getLogger("app.resolution")

AGENT = "resolution"
STAR_WEIGHT = 0.1  # per star away from three: a one-star runbook ranks at 0.8 of its score, a five-star one at 1.2


@dataclass
class RunResult:
    evaluated: int = 0
    skipped: int = 0
    model_errors: int = 0
    by_verdict: Counter = field(default_factory=Counter)


def _input_hash(case: CaseInput, embedder: Embedder | None) -> str:
    """What the agent saw: a change to the ticket, the prompts, the model or the query embedder runs it again."""
    return fingerprint(case.summary, case.body, case.application, prompt_versions(), settings.LLM_MODEL,
                       embedder.model_name if embedder else "full-text",
                       *([repr(sorted(case.kb_weights.items()))] if case.kb_weights else []))  # unrated tickets keep their hash


def _rule(output: dict | None) -> str | None:
    return (output or {}).get("rule")


async def _kb_weights(db: AsyncSession, ticket: Ticket) -> dict[str, float]:
    """How engineers' star ratings re-rank the runbooks for this ticket: the average rating of each article that a rated
    Resolution answer cited, on tickets with the same kind of problem (this ticket included). Unrated articles are absent.
    shortcut: the same kind is the same application and triage rule, upgrade to ticket similarity once ratings are many."""
    rated = (
        await db.execute(
            select(Feedback.ticket_id, Feedback.stars, AgentRun.output, Feedback.agent_run_id, Feedback.reviewer)
            .join(AgentRun, AgentRun.id == Feedback.agent_run_id)
            .join(Ticket, Ticket.id == Feedback.ticket_id)
            .where(Feedback.agent == AGENT, Ticket.application == ticket.application)
            .order_by(Feedback.id)
        )
    ).all()
    rated = list({(r.agent_run_id, r.reviewer): r for r in rated}.values())  # a person's latest rating of a result
    if not rated:
        return {}
    triaged = await db.execute(
        select(AgentRun.ticket_id, AgentRun.output)
        .where(AgentRun.agent == "triage", AgentRun.ticket_id.in_({r.ticket_id for r in rated}))
        .order_by(AgentRun.id)
    )
    rules = {ticket_id: _rule(output) for ticket_id, output in triaged}  # the last triage of each rated ticket
    mine = _rule(getattr(last_run(ticket, "triage"), "output", None))
    stars: dict[str, list[int]] = {}
    for ticket_id, given, output, *_ in rated:
        if rules.get(ticket_id) == mine:
            for kb_id in (output or {}).get("references", []):
                stars.setdefault(kb_id, []).append(given)
    weights = {kb_id: round(1 + STAR_WEIGHT * (sum(s) / len(s) - 3), 3) for kb_id, s in stars.items()}
    return {kb_id: w for kb_id, w in weights.items() if w != 1}


def _output(res: Resolution, embedder: Embedder | None) -> dict:
    return {
        **res.answer.model_dump(),
        "filters": asdict(res.filters),
        "queries": res.queries,
        "hypothetical": res.hypothetical,
        "trace": res.trace,
        "audit": [asdict(a) for a in res.audits],
        "embedder": embedder.model_name if embedder else None,
    }


async def run_resolution(embedder: Embedder | None = None, ticket_id: str | None = None) -> RunResult:
    """Resolve every REVIEWED ticket. Tickets whose input has not changed since their last run are skipped.
    No database session is open while the model works. A ticket whose model call fails is left for the next run.
    With ticket_id only that ticket is resolved, and again even if nothing changed: a person asked."""
    result = RunResult()
    todo: list[tuple[CaseInput, str]] = []
    async with AsyncSessionLocal() as db:
        tickets = (
            await db.scalars(
                select(Ticket)
                .where(Ticket.pipeline_status == PipelineStatus.REVIEWED, *([Ticket.id == ticket_id] if ticket_id else []))
                .options(selectinload(Ticket.agent_runs), selectinload(Ticket.comments))
            )
        ).all()
        for t in tickets:
            case = CaseInput(
                id=t.id, summary=t.summary, application=t.application, body=reporter_text(t),
                reporter_name=t.reporter_name, reporter_email=t.reporter_email, assignee=t.assignee,
                kb_weights=await _kb_weights(db, t),
            )
            digest = _input_hash(case, embedder)
            last = last_run(t, AGENT)
            if ticket_id is None and last is not None and last.input_hash == digest:
                result.skipped += 1
            else:
                todo.append((case, digest))

    for case, digest in todo:
        try:
            res = await resolve(case, embedder)
        except ModelError as exc:
            result.model_errors += 1
            logger.warning(f"Resolution: model failed for {case.id}: {exc!r}")
            continue
        async with AsyncSessionLocal() as db:
            db.add(AgentRun(ticket_id=case.id, agent=AGENT, verdict=res.answer.verdict, input_hash=digest,
                            output={**_output(res, embedder), "kb_weights": case.kb_weights}))
            await db.commit()
        result.evaluated += 1
        result.by_verdict[res.answer.verdict] += 1

    logger.info(
        f"Resolution: evaluated={result.evaluated} skipped={result.skipped} model_errors={result.model_errors} "
        f"by_verdict={dict(result.by_verdict)}"
    )
    return result
