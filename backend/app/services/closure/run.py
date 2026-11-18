"""Run the Closure Quality agent over resolved tickets and record how good each set of close notes is."""

import logging
from collections import Counter
from dataclasses import asdict, dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.agents.closure_quality.config import PARTS, get_config
from app.agents.closure_quality.model_check import assess_notes, cited_articles, closure_spec, invented, score, verified
from app.agents.closure_quality.rules import evaluate
from app.agents.closure_quality.verdict import Verdict
from app.core.config import settings
from app.llm import ModelError
from app.models.ticket import AgentRun, PipelineStatus, Ticket
from app.services.data_quality import OutageBreaker, fingerprint, last_run

logger = logging.getLogger("app.closure")

AGENT = "closure_quality"
RESOLVED = ("resolved", "closed")


@dataclass
class RunResult:
    evaluated: int = 0
    skipped: int = 0
    model_errors: int = 0
    by_verdict: Counter = field(default_factory=Counter)


def replies_text(ticket: Ticket) -> str:
    return "\n\n".join(c.body for c in ticket.comments)


def _input_hash(ticket: Ticket) -> str:
    """What the check saw: a change to the notes, the rules, or the model and its prompt checks the ticket again."""
    stages = f"{settings.LLM_MODEL}|{closure_spec().prompt_version}" if settings.LLM_ENABLED else "rules"
    return fingerprint(ticket.resolution_notes, ticket.summary, ticket.description, replies_text(ticket),
                       get_config().version, stages)


def judge(ticket: Ticket, use_model: bool = True) -> tuple[Verdict, dict, ModelError | None]:
    """Rules first; the model only for notes the rules cannot stop, and only when LLM_ENABLED.
    Returns the verdict, what to record, and the model error if there was one. The ticket is not changed."""
    config, notes = get_config(), (ticket.resolution_notes or "").strip()
    outcome = evaluate(notes, ticket.summary, ticket.description)
    output = {"stage": "rules", "rules_version": config.version, "rule": outcome.rule, "reason": outcome.reason,
              "ai": "not_needed", "score": None, "levels": None, "quotes": None, "dropped_quotes": [], "kb_cited": [],
              "questions": [], "draft_notes": None, "draft_invented": []}
    if outcome.verdict == Verdict.NEEDS_WORK:  # the rules are sure: every part is missing
        output["questions"] = [config.questions[p] for p in PARTS]
    if outcome.verdict != Verdict.UNCERTAIN:
        return outcome.verdict, output, None

    output["ai"] = "off"
    if not (settings.LLM_ENABLED and use_model):
        return Verdict.UNCERTAIN, output, None
    try:
        facts, audit = assess_notes(ticket, replies_text(ticket), notes)
    except ModelError as exc:
        output["ai"] = "failed"
        return Verdict.UNCERTAIN, output, exc

    levels, quotes, dropped = verified(facts, notes)
    cited = cited_articles(notes) if config.kb_citation_is_cause else []
    if cited and levels["action"] == 2 and levels["cause"] < 2:  # the article documents the cause
        levels["cause"], quotes["cause"] = 2, cited[0]
    total, passed = score(levels, config)
    source = f"{ticket.summary}\n{ticket.description}\n{replies_text(ticket)}\n{notes}"
    draft = None if passed else facts.draft_notes
    made_up = invented(draft, source) if draft else []
    output.update(
        stage="model", ai="used", reason=facts.reason, score=total, levels=levels, quotes=quotes, dropped_quotes=dropped,
        kb_cited=cited,
        questions=[] if passed else [config.questions[p] for p in PARTS if levels[p] < 2],
        draft_notes=None if made_up else draft, draft_invented=made_up, audit=asdict(audit),
    )
    return (Verdict.GOOD if passed else Verdict.NEEDS_WORK), output, None


def check_ticket(db: Session, ticket: Ticket, use_model: bool = True) -> tuple[AgentRun, ModelError | None]:
    """Check one ticket's close notes and record the result. Advisory: the ticket and its notes are not changed."""
    verdict, output, error = judge(ticket, use_model)
    retry = verdict == Verdict.UNCERTAIN and settings.LLM_ENABLED  # the model should have judged it: try again next run
    run = AgentRun(ticket_id=ticket.id, agent=AGENT, verdict=verdict, output=output,
                   input_hash=None if retry else _input_hash(ticket))
    db.add(run)
    return run, error


def run_closure(db: Session, include_history: bool = False) -> RunResult:
    """Check every resolved or closed ticket whose notes have not been checked. Tickets that were already closed when
    they arrived are reference history and are left alone unless include_history is set."""
    query = (
        select(Ticket)
        .where(Ticket.status.in_(RESOLVED))
        .options(selectinload(Ticket.agent_runs), selectinload(Ticket.comments))
        .order_by(Ticket.id)
    )
    if not include_history:
        query = query.where(Ticket.pipeline_status != PipelineStatus.HISTORICAL)

    result, breaker, use_model = RunResult(), OutageBreaker(settings.CLOSURE_OUTAGE_BREAKER), True
    for ticket in db.scalars(query).all():
        last = last_run(ticket, AGENT)
        if last is not None and last.input_hash == _input_hash(ticket):
            result.skipped += 1
            continue

        run, error = check_ticket(db, ticket, use_model)
        if error:
            result.model_errors += 1
            logger.warning(f"Closure Quality: model stage failed for {ticket.id}: {error!r}")
        if use_model and run.output["ai"] in ("used", "failed") and breaker.record(error):
            logger.error(f"Closure Quality: model unavailable {breaker.in_a_row} times in a row; rules only for this run")
            use_model = False
        result.evaluated += 1
        result.by_verdict[run.verdict] += 1
    db.commit()

    logger.info(
        f"Closure Quality: evaluated={result.evaluated} skipped={result.skipped} "
        f"model_errors={result.model_errors} by_verdict={dict(result.by_verdict)}"
    )
    return result
