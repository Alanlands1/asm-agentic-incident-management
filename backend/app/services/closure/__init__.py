"""Closure Quality services: check the close notes of resolved tickets, and engineer review of the result.

Importing the package loads every module, so their admin-editable documents are registered.
"""

from app.services.closure import review
from app.services.closure.run import AGENT, RunResult, check_ticket, judge, run_closure

__all__ = ["AGENT", "RunResult", "check_ticket", "judge", "review", "run_closure"]
