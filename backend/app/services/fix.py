"""The engineer's answer to a suggested fix (worked, partly, wrong) and the closure note that follows it.

Answers are stored as reviews of the Resolution run (agent "resolution"); the latest answer on a run counts. "worked"
or "partly" confirms the fix and opens the closure note, drafted from the fix; "wrong" asks Resolution for another fix,
until three fixes did not work and the ticket waits for the lead (design D7).
"""

import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.ticket import AgentRun, PipelineStatus, Review, Ticket
from app.services import feedback
from app.services.data_quality import last_run

AGENT = "resolution"
MAX_WRONG = 3  # fixes that did not work before the lead looks
OPEN = (PipelineStatus.REVIEWED, PipelineStatus.FIX_CONFIRMED, PipelineStatus.NEEDS_LEAD)
GAP = "[engineer to add: {}]"  # the marks Closure Quality's drafts use for a missing part
NUMBERED = re.compile(r"^\d+[.)]\s*")


class OutcomeError(ValueError):
    """The answer does not fit, e.g. "wrong" without saying what happened."""


class NotOpen(OutcomeError):
    """The ticket has no fix to answer now: closed, not at that stage, or a newer fix came."""


def answers(db: Session, ticket_id: str) -> dict[int, Review]:
    """The latest answer on each Resolution run of the ticket, by run id."""
    rows = db.scalars(select(Review).where(Review.ticket_id == ticket_id, Review.agent == AGENT).order_by(Review.id))
    return {r.agent_run_id: r for r in rows}


def tried(runs: list[AgentRun], latest: dict[int, Review]) -> str:
    """The fixes the engineer said did not work, and what happened, for Resolution to read before it looks again."""
    lines = []
    for n, run in enumerate(runs, 1):
        answer = latest.get(run.id)
        if answer is None or answer.action != "wrong":
            continue
        o = run.output
        lines += [f"Fix v{n} did not work.",
                  *([f"Cause it named: {o['root_cause']}"] if o.get("root_cause") else []),
                  *(f"Step {i}: {NUMBERED.sub('', s)}" for i, s in enumerate(o.get("steps") or [], 1)),
                  f"What happened, from the engineer: {answer.note}"]
    return "Fixes already tried:\n" + "\n".join(lines) if lines else ""


def draft(run: AgentRun, changed: str | None) -> str:
    """The closure note to start from: the fix's cause and steps, what the engineer changed, and a mark where only they
    can say how they checked it."""
    o = run.output
    steps = [NUMBERED.sub("", s) for s in o.get("steps") or []]
    lines = [f"Cause: {o.get('root_cause') or GAP.format('cause')}"]
    if steps:
        refs = f" ({', '.join(o['references'])})" if o.get("references") else ""
        lines += [f"Fix: followed the suggested fix{refs}:", *(f"{i}. {s}" for i, s in enumerate(steps, 1))]
        if changed:
            lines.append(f"Changed from the suggested fix: {changed}")
    else:
        lines.append(f"Fix: {changed or GAP.format('action')}")
    lines.append(f"Checked: {GAP.format('check')}")
    return "\n".join(lines)


def record(db: Session, ticket: Ticket, run_id: int, outcome: str, reviewer: str, note: str | None = None) -> Review:
    """Record the engineer's answer on the latest suggested fix and move the ticket on. Not committed.

    worked  the fix worked as suggested
    partly  it worked with changes (note: what changed); with no fix suggested, what the engineer did instead
    wrong   it did not work (note: what happened); Resolution looks again, or the lead after three
    """
    run = last_run(ticket, AGENT)
    if ticket.closed_at is not None or ticket.pipeline_status not in OPEN or run is None:
        raise NotOpen(f"Ticket {ticket.id} has no suggested fix to answer")
    if run.id != run_id:
        raise NotOpen("A newer fix was suggested: answer that one")
    note = (note or "").strip() or None
    if run.verdict != "resolved" and outcome != "partly":
        raise OutcomeError("No fix was suggested: say what you did instead")
    if outcome != "worked" and note is None:
        raise OutcomeError("Say what you changed" if outcome == "partly" else "Say what happened when you tried it")
    if outcome == "wrong" and ticket.pipeline_status == PipelineStatus.NEEDS_LEAD:
        raise NotOpen(f"{MAX_WRONG} fixes did not work: the lead looks at this ticket")

    answer = Review(ticket_id=ticket.id, agent_run_id=run.id, agent=AGENT, action=outcome, note=note,
                    reviewer=reviewer.strip())
    db.add(answer)
    feedback.from_use(db, run, {"worked": feedback.UP, "partly": feedback.PARTLY}.get(outcome, feedback.DOWN), reviewer,
                      {"worked": "the fix worked", "partly": "the fix worked with changes"}.get(outcome, "the fix didn't work"))
    db.flush()
    if outcome == "wrong":
        wrong = sum(a.action == "wrong" for a in answers(db, ticket.id).values())
        ticket.pipeline_status = PipelineStatus.NEEDS_LEAD if wrong >= MAX_WRONG else PipelineStatus.REVIEWED
    else:
        ticket.pipeline_status = PipelineStatus.FIX_CONFIRMED
        if not (ticket.resolution_notes or "").strip():
            ticket.resolution_notes = draft(run, note if outcome == "partly" else None)
    return answer
