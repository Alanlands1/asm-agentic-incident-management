"""Run the Triage agent over tickets that passed Data Quality and record each recommended priority."""

import logging
from collections import Counter
from dataclasses import asdict, dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.agents.triage.config import get_config
from app.agents.triage.model_check import TriageAssessment, assess_priority, impact, triage_priority_spec, verified
from app.agents.triage.rules import Decision, Facts, RuleResult, decide, evaluate, find_rule, without_rulebook
from app.agents.triage.signals import clean_text
from app.agents.triage.verdict import Verdict
from app.core.config import settings
from app.llm import CallAudit, ModelError
from app.llm.client import effort, model_id
from app.models.ticket import AgentRun, PipelineStatus, Storm, Ticket
from app.services.data_quality import OutageBreaker, fingerprint, last_run, reporter_text
from app.services.triage.storms import detect_storms

logger = logging.getLogger("app.triage")

AGENT = "triage"


@dataclass
class RunResult:
    evaluated: int = 0
    skipped: int = 0
    model_errors: int = 0
    needs_review: int = 0
    by_verdict: Counter = field(default_factory=Counter)


def _input_hash(ticket: Ticket, body: str) -> str:
    """What the triage saw: a change to the ticket, the rulebook, or the model and its prompt re-triages it."""
    model = f"{model_id('triage')}|{effort('triage')}|{triage_priority_spec().prompt_version}"
    stages = model if settings.LLM_ENABLED else "rules"
    return fingerprint(ticket.summary, body, ticket.application, str(ticket.opened_at), str(ticket.storm_id),
                       get_config().version, stages)


def _recommendation(ticket: Ticket, decision: Decision | None, reason: str, ai: str) -> dict:
    """The reporter's priority is never changed. Large shifts, lowered P1/P2s and guesses are flagged for review."""
    priority, reported = (decision.priority if decision else None), ticket.reported_priority
    shift = priority - reported if priority and reported else None
    downgrade = shift is not None and reported <= 2 and shift > 0
    leaned = bool(decision and decision.leaned_high)
    kept = bool(decision and decision.kept_reported)
    return {
        "priority": priority,
        "reported_priority": reported,
        "shift": shift,
        "downgrade": downgrade,
        "leaned_high": leaned,
        "kept_reported": kept,
        "needs_review": downgrade or leaned or kept or (shift is not None and abs(shift) > get_config().review_shift),
        "rule": decision.rule if decision else None,
        "must_follow": decision.must_follow if decision else None,
        "reason": reason,
        "ai": ai,  # not_needed (follows a storm) | used | off | failed
    }


def model_decision(ticket: Ticket, body: str, outcome: RuleResult) -> tuple[Decision, TriageAssessment, list[str], CallAudit]:
    """Ask the model for the missing facts, drop any it cannot quote, and calculate the priority from the rulebook.
    Raises app.llm.ModelError when there is no usable answer."""
    config = get_config()
    answer, audit = assess_priority(ticket, body, outcome)
    answer, dropped = verified(answer, f"{ticket.summary}\n{body}")
    s = outcome.signals
    facts = Facts(answer.application, answer.scope, s.windows, s.failed_jobs, lambda _: answer.context_applies)
    rule = find_rule(config, answer.application, answer.rule)  # checked by TriageAssessment
    decision = decide(rule, facts, clean_text(ticket.summary, body, config), config)
    if answer.application is None:
        decision = without_rulebook(decision, ticket.reported_priority)
    return decision, answer, dropped, audit


def triage_ticket(db: Session, ticket: Ticket, use_model: bool = True) -> tuple[AgentRun, ModelError | None]:
    """Rules first, then the model once on every ticket: it reports the impact, and the facts the rules could not find.
    A priority the rules settled stands. Without a usable model answer the rules' own answer (leaning high) is used.
    Returns the final run and the model error, if there was one."""
    config = get_config()
    body = reporter_text(ticket)
    outcome = evaluate(ticket.summary, body, ticket.application, ticket.opened_at, in_storm=ticket.storm_id is not None)
    rules_output = {"stage": "rules", "rules_version": config.version, "missing": list(outcome.missing),
                    "application": outcome.signals.application, "storm_id": ticket.storm_id, "signals": asdict(outcome.signals)}
    final = AgentRun(ticket_id=ticket.id, agent=AGENT, verdict=outcome.verdict, input_hash=_input_hash(ticket, body),
                     output={**rules_output, **_recommendation(ticket, outcome.decision, outcome.reason, "off")})
    db.add(final)

    error, ai = None, "off"
    if settings.LLM_ENABLED and use_model:
        try:
            decision, answer, dropped, audit = model_decision(ticket, body, outcome)
        except ModelError as exc:
            error, ai = exc, "failed"
            final.output = {**final.output, "ai": ai}  # counted on the dashboard
        else:
            found = {"impact": impact(answer), "answer": answer.model_dump(), "dropped_facts": dropped, "audit": asdict(audit)}
            if outcome.verdict != Verdict.UNCERTAIN:  # the rules had every fact: their priority stands
                final.output = {**final.output, "ai": "used", **found}
            else:
                final = AgentRun(
                    ticket_id=ticket.id, agent=AGENT, verdict=Verdict.of(decision.priority), input_hash=final.input_hash,
                    output={"stage": "model", "rules_version": config.version, "storm_id": ticket.storm_id,
                            "application": answer.application or outcome.signals.application,
                            **_recommendation(ticket, decision, decision.reason, "used"), **found},
                )
                db.add(final)

    if final.verdict == Verdict.UNCERTAIN:
        if outcome.fallback:
            final.verdict = Verdict.of(outcome.fallback.priority)
            final.output = {**rules_output, **_recommendation(ticket, outcome.fallback, outcome.fallback.reason, ai)}
        elif error:
            final.input_hash = None  # nothing to fall back on: try again on the next run
    if final.verdict != Verdict.UNCERTAIN:
        ticket.pipeline_status = PipelineStatus.TRIAGED
    return final, error


def _follow_main(db: Session, ticket: Ticket, storm: Storm, main_run: AgentRun) -> AgentRun:
    """A ticket in a storm follows its main ticket: the same priority, with no model call and no message of its own."""
    old = main_run.output
    reason = f"Same issue as {storm.main_ticket_id} (storm {storm.id}); the priority follows the main ticket"
    decision = Decision(old["priority"], old["rule"] or "storm", reason, old["must_follow"])
    run = AgentRun(
        ticket_id=ticket.id, agent=AGENT, verdict=main_run.verdict, input_hash=_input_hash(ticket, reporter_text(ticket)),
        output={"stage": "storm", "rules_version": get_config().version, "application": old["application"],
                "storm_id": storm.id, "linked_to": storm.main_ticket_id, "impact": old.get("impact"),
                **_recommendation(ticket, decision, reason, "not_needed")},
    )
    db.add(run)
    ticket.pipeline_status = PipelineStatus.TRIAGED
    return run


def run_triage(db: Session) -> RunResult:
    """Triage every ticket that passed Data Quality. Tickets whose input has not changed since their last triage are skipped.
    Storms are found first: the main ticket of each is triaged first and the others in it follow its priority."""
    detect_storms(db)
    tickets = db.scalars(
        select(Ticket)
        .where(Ticket.pipeline_status == PipelineStatus.DQ_PASSED, Ticket.closed_at.is_(None))  # closed in the source: left alone
        .options(selectinload(Ticket.agent_runs), selectinload(Ticket.comments))
    ).all()
    storms = {s.id: s for s in db.scalars(select(Storm).where(Storm.id.in_({t.storm_id for t in tickets if t.storm_id})))}
    tickets.sort(key=lambda t: not (t.storm_id and storms[t.storm_id].main_ticket_id == t.id))  # main tickets first
    triaged: dict[str, AgentRun] = {}  # this run's results, by ticket id

    result = RunResult()
    breaker = OutageBreaker(settings.TRIAGE_OUTAGE_BREAKER)
    use_model = True
    for ticket in tickets:
        last = last_run(ticket, AGENT)
        if last is not None and last.input_hash == _input_hash(ticket, reporter_text(ticket)):
            result.skipped += 1
            continue

        storm = storms.get(ticket.storm_id)
        main_run = triaged.get(storm.main_ticket_id) if storm and storm.main_ticket_id != ticket.id else None
        if main_run is not None and main_run.verdict != Verdict.UNCERTAIN:
            agent_run, error = _follow_main(db, ticket, storm, main_run), None
        else:
            agent_run, error = triage_ticket(db, ticket, use_model)
        triaged[ticket.id] = agent_run
        if error:
            result.model_errors += 1
            logger.warning(f"Triage: model stage failed for {ticket.id}: {error!r}")
        if use_model and agent_run.output["ai"] in ("used", "failed") and breaker.record(error):
            logger.error(f"Triage: model unavailable {breaker.in_a_row} times in a row; rules only for the rest of this run")
            use_model = False
        result.evaluated += 1
        result.needs_review += agent_run.output["needs_review"]
        result.by_verdict[agent_run.verdict] += 1
    db.commit()

    logger.info(
        f"Triage: evaluated={result.evaluated} skipped={result.skipped} model_errors={result.model_errors} "
        f"needs_review={result.needs_review} by_verdict={dict(result.by_verdict)}"
    )
    return result
