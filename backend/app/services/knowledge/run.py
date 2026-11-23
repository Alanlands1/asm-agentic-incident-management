"""Run the Knowledge Builder over resolved tickets whose close notes passed: save a masked case, match it to an article."""

import logging
from collections import Counter
from dataclasses import asdict, dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.agents.closure_quality.verdict import Verdict as ClosureVerdict
from app.agents.knowledge_builder.articles import articles, articles_version
from app.agents.knowledge_builder.config import get_config
from app.agents.knowledge_builder.matching import evaluate
from app.agents.knowledge_builder.model_check import assess_match, checked, kb_match_spec
from app.core.config import settings
from app.llm import ModelError
from app.models.knowledge import ProblemCandidate, ResolvedCase
from app.models.ticket import AgentRun, Review, Ticket
from app.privacy.masking import Masker
from app.services.closure.run import AGENT as CLOSURE_AGENT
from app.services.closure.run import RESOLVED
from app.services.data_quality import OutageBreaker, fingerprint, last_run
from app.services.knowledge.drafts import draft_for_gap
from app.services.knowledge.problems import detect_problems

logger = logging.getLogger("app.knowledge")

AGENT = "knowledge_builder"


@dataclass
class RunResult:
    evaluated: int = 0
    skipped: int = 0
    model_errors: int = 0
    by_status: Counter = field(default_factory=Counter)
    drafts: Counter = field(default_factory=Counter)  # what happened to each gap: created, joined, none, ...
    problems: int = 0  # open repeat-issue suggestions after this run


def _input_hash(ticket: Ticket, notes: str) -> str:
    """What the match saw: a change to the case, the settings, the articles, or the model and its prompt matches it again."""
    stages = f"{settings.LLM_MODEL}|{kb_match_spec().prompt_version}" if settings.LLM_ENABLED else "rules"
    return fingerprint(notes, ticket.summary, ticket.description, ticket.application,
                       get_config().version, articles_version(), stages)


def match_case(ticket: Ticket, notes: str, use_model: bool = True) -> tuple[str, str | None, str | None, dict, ModelError | None]:
    """Rules first; the model once for a case the rules are not sure of, and only when LLM_ENABLED.
    Returns status (matched, gap, uncertain), the article, how it was found, what to record, and any model error."""
    config = get_config()
    rules = evaluate(ticket.summary, ticket.description, notes, ticket.application)
    output = {"stage": "rules", "rules_version": config.version, "articles_version": articles_version(), "article": rules.article,
              "method": rules.method, "reason": rules.reason, "ranking": [list(r) for r in rules.ranking[:5]], "ai": "not_needed"}
    if rules.status == "matched":
        return "matched", rules.article, rules.method, output, None

    output["ai"] = "off"
    if not (settings.LLM_ENABLED and use_model):
        return "uncertain", None, None, output, None
    known = articles()
    shown = [known[kb] for kb, _ in rules.ranking[: config.candidates]]
    try:
        answer, audit = assess_match(ticket, notes, shown)
    except ModelError as exc:
        output["ai"] = "failed"
        return "uncertain", None, None, output, exc

    article, problem = checked(answer, [a.kb_id for a in shown], f"{ticket.summary}\n{ticket.description}\n{notes}")
    output.update(stage="model", ai="used", reason=answer.reason, answer=answer.model_dump(), problem=problem,
                  audit=asdict(audit))
    if article:
        output.update(article=article, method="model")
        return "matched", article, "model", output, None
    return ("uncertain" if problem else "gap"), None, None, output, None


def _passed(db: Session, tickets: list[Ticket]) -> dict[str, tuple[str, AgentRun]]:
    """Per resolved ticket whose close notes passed: the final notes (the engineer's edit if there was one), and the check."""
    decisions = {r.agent_run_id: r for r in db.scalars(
        select(Review).where(
            Review.agent == CLOSURE_AGENT, Review.action.in_(("accepted", "edited")), Review.final_text.is_not(None)
        )
    )}
    passed = {}
    for t in tickets:
        run = last_run(t, CLOSURE_AGENT)
        if run is None:
            continue
        if run.verdict == ClosureVerdict.GOOD:
            passed[t.id] = ((t.resolution_notes or "").strip(), run)
        elif run.id in decisions:
            passed[t.id] = (decisions[run.id].final_text.strip(), run)
    return passed


def _save(db: Session, ticket: Ticket, notes: str, check: AgentRun, status: str, article: str | None,
          method: str | None) -> ResolvedCase:
    """Store the case with names masked. The quotes are the engineer's own words, so they are kept only for unedited notes."""
    masker = Masker(known_names=[ticket.reporter_name, ticket.assignee], known_emails=[ticket.reporter_email])
    quotes = check.output.get("quotes") if notes == (ticket.resolution_notes or "").strip() else None
    case = db.get(ResolvedCase, ticket.id) or ResolvedCase(ticket_id=ticket.id)
    case.application, case.score, case.closed_at = ticket.application, check.output.get("score"), ticket.closed_at
    case.summary, case.description = str(masker.mask(ticket.summary)), str(masker.mask(ticket.description))
    case.notes = str(masker.mask(notes))
    case.cause, case.action, case.check = (
        (str(masker.mask(quotes[p])) if quotes and quotes.get(p) else None) for p in ("cause", "action", "check")
    )
    case.match_status, case.kb_article_id, case.match_method = status, article, method
    if status != "gap":
        case.gap_kind, case.draft_id = None, None
    db.add(case)
    return case


def run_knowledge(db: Session) -> RunResult:
    """Save and match every resolved ticket whose close notes passed. Safe to re-run: unchanged cases are skipped."""
    tickets = db.scalars(
        select(Ticket).where(Ticket.status.in_(RESOLVED)).options(selectinload(Ticket.agent_runs)).order_by(Ticket.id)
    ).all()
    result, breaker, use_model = RunResult(), OutageBreaker(settings.KNOWLEDGE_OUTAGE_BREAKER), True
    passed = _passed(db, tickets)
    for ticket in tickets:
        if ticket.id not in passed:
            continue
        notes, check = passed[ticket.id]
        last = last_run(ticket, AGENT)
        if last is not None and last.input_hash == _input_hash(ticket, notes):
            result.skipped += 1
            continue

        status, article, method, output, error = match_case(ticket, notes, use_model)
        case = _save(db, ticket, notes, check, status, article, method)
        if status == "gap":
            output["draft"], error = draft_for_gap(db, ticket, case, notes, use_model)
            result.drafts[output["draft"]["draft"]] += 1
        # the model should have judged the case, or written the draft: try again next run
        retry = (status == "uncertain" and settings.LLM_ENABLED) or output.get("draft", {}).get("draft") == "failed"
        db.add(AgentRun(ticket_id=ticket.id, agent=AGENT, verdict=status, output=output,
                        input_hash=None if retry else _input_hash(ticket, notes)))
        if error:
            result.model_errors += 1
            logger.warning(f"Knowledge Builder: model stage failed for {ticket.id}: {error!r}")
        if use_model and (output["ai"] in ("used", "failed") or "audit" in output.get("draft", {})) and breaker.record(error):
            logger.error(f"Knowledge Builder: model unavailable {breaker.in_a_row} times in a row; rules only for this run")
            use_model = False
        result.evaluated += 1
        result.by_status[status] += 1
    detect_problems(db)
    db.commit()
    result.problems = len(db.scalars(select(ProblemCandidate.id).where(ProblemCandidate.status == "open")).all())

    logger.info(
        f"Knowledge Builder: evaluated={result.evaluated} skipped={result.skipped} model_errors={result.model_errors} "
        f"by_status={dict(result.by_status)} drafts={dict(result.drafts)} open_problems={result.problems}"
    )
    return result
