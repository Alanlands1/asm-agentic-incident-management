"""Feedback from use: what people already do on a ticket counts as a rating of the agent's result, so most results are
rated without anyone being asked. Agreeing with Triage's priority, saying a fix worked, accepting Closure Quality's
draft, a reporter supplying what Data Quality asked for: each is stored as a rating marked "From use", next to the
thumbs people give by hand. A person's latest rating of a result counts, so a thumb given later overrides it.
"""

from sqlalchemy.orm import Session

from app.models.ticket import AgentRun, Feedback

FROM_USE = "From use: "  # how a rating from use starts; one given by hand never does
UP, PARTLY, DOWN = 5, 3, 1  # thumbs up, in between, thumbs down on the 1-5 scale the ratings use
AUTO = "AMS agents (auto)"  # services/triage/run.AUTO_REVIEWER: the agents approving their own result is no feedback


def from_use(db: Session, run: AgentRun | None, stars: int, reviewer: str, what: str) -> None:
    """Record what a person did as a rating of the agent's result. Not committed."""
    if run is None or reviewer == AUTO:
        return
    db.add(Feedback(ticket_id=run.ticket_id, agent_run_id=run.id, agent=run.agent, stars=stars,
                    reason=f"{FROM_USE}{what}", reviewer=reviewer.strip()))
