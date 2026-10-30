"""What every agent's pipeline needs, whatever the agent: the text a ticket holds, a fingerprint of what an agent
saw, the agent's last verdict, and when to stop a run because the model keeps failing."""

import hashlib

from app.common.llm import ModelError, ModelUnavailableError
from app.models.ticket import AgentRun, Ticket


def reporter_text(ticket: Ticket) -> str:
    """The original description followed by every reply from the reporter, so a re-check sees the full story."""
    return "\n\n".join([ticket.description, *(c.body for c in ticket.comments if c.from_reporter)])


def fingerprint(*parts: str | None) -> str:
    """Hash of what an agent saw. Equal fingerprints mean the agent would see the same thing again."""
    return hashlib.sha256("\x1f".join(p or "" for p in parts).encode()).hexdigest()


def last_run(ticket: Ticket, agent: str) -> AgentRun | None:
    return next((r for r in reversed(ticket.agent_runs) if r.agent == agent), None)


class OutageBreaker:
    """Counts model outages in a row. A run stops once `limit` is reached; any other result resets the count."""

    def __init__(self, limit: int):
        self.limit, self.in_a_row = limit, 0

    def record(self, error: ModelError | None) -> bool:
        """Record one ticket's outcome (None = no model error). True means: stop the run now."""
        self.in_a_row = self.in_a_row + 1 if isinstance(error, ModelUnavailableError) else 0
        return self.in_a_row >= self.limit
