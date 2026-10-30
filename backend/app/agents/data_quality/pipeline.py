"""Run the Data Quality agent over pending tickets and record each verdict."""

import logging
from collections import Counter
from dataclasses import asdict, dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.agents.data_quality.model_check import check_completeness, dq_completeness_spec
from app.agents.data_quality.rules import evaluate
from app.agents.data_quality.verdict import Verdict
from app.common.agent_run import OutageBreaker, fingerprint, last_run, reporter_text
from app.common.config import settings
from app.common.llm import ModelError
from app.models.ticket import AgentRun, PipelineStatus, Ticket

logger = logging.getLogger("app.data_quality")

AGENT = "data_quality"
VERDICT_STATUS = {
    Verdict.NOT_AN_INCIDENT: PipelineStatus.REJECTED,
    Verdict.NEEDS_INFO: PipelineStatus.AWAITING_INFO,
    Verdict.PASSED: PipelineStatus.DQ_PASSED,
}  # uncertain keeps the ticket pending until the model step decides


@dataclass
class RunResult:
    evaluated: int = 0
    skipped: int = 0
    model_errors: int = 0
    by_verdict: Counter = field(default_factory=Counter)


def _input_hash(ticket: Ticket, body: str) -> str:
    """What the check saw, including which stages ran: switching the model on or changing its prompt re-checks."""
    stages = f"{settings.LLM_MODEL}|{dq_completeness_spec().prompt_version}" if settings.LLM_ENABLED else "rules"
    return fingerprint(ticket.summary, body, ticket.attachments, ticket.application, stages)


def check_ticket(db: Session, ticket: Ticket) -> AgentRun:
    """Rules first; the model only for tickets the rules cannot decide, and only when LLM_ENABLED.

    Raises app.common.llm.ModelError if the model gives no usable answer. The rules verdict is still recorded,
    without an input hash, so the next run tries again.
    """
    body = reporter_text(ticket)
    input_hash = _input_hash(ticket, body)
    outcome = evaluate(ticket.summary, body, ticket.attachments, ticket.application)
    final = AgentRun(
        ticket_id=ticket.id,
        agent=AGENT,
        verdict=outcome.verdict,
        input_hash=input_hash,
        output={"stage": "rules", "rule": outcome.rule, "reason": outcome.reason, "signals": asdict(outcome.signals)},
    )
    db.add(final)

    if outcome.verdict == Verdict.UNCERTAIN and settings.LLM_ENABLED:
        try:
            answer, audit = check_completeness(ticket, body)
        except ModelError:
            final.input_hash = None
            raise
        final = AgentRun(
            ticket_id=ticket.id,
            agent=AGENT,
            verdict=Verdict.PASSED if answer.complete else Verdict.NEEDS_INFO,
            input_hash=input_hash,
            output={"stage": "model", "answer": answer.model_dump(), "audit": asdict(audit)},
        )
        db.add(final)

    ticket.pipeline_status = VERDICT_STATUS.get(final.verdict, ticket.pipeline_status)
    return final


def run_data_quality(db: Session) -> RunResult:
    """Check every pending ticket. Tickets whose input has not changed since their last check are skipped."""
    tickets = db.scalars(
        select(Ticket)
        .where(Ticket.pipeline_status == PipelineStatus.PENDING)
        .options(selectinload(Ticket.agent_runs), selectinload(Ticket.comments))
    ).all()

    result = RunResult()
    breaker = OutageBreaker(settings.DQ_OUTAGE_BREAKER)
    for ticket in tickets:
        last = last_run(ticket, AGENT)
        if last is not None and last.input_hash == _input_hash(ticket, reporter_text(ticket)):
            result.skipped += 1
            continue

        try:
            agent_run = check_ticket(db, ticket)
        except ModelError as exc:
            result.model_errors += 1
            logger.warning(f"Data Quality: model stage failed for {ticket.id}: {exc!r}")
            if breaker.record(exc):
                logger.error(f"Data Quality: model unavailable {breaker.in_a_row} times in a row, stopping this run")
                break
            continue
        breaker.record(None)
        result.evaluated += 1
        result.by_verdict[agent_run.verdict] += 1
    db.commit()

    logger.info(
        f"Data Quality: evaluated={result.evaluated} skipped={result.skipped} "
        f"model_errors={result.model_errors} by_verdict={dict(result.by_verdict)}"
    )
    return result
