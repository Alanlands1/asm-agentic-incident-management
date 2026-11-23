"""Knowledge Builder services: save resolved cases, match them to articles, and report coverage.

Importing the package loads every module, so their admin-editable documents are registered.
"""

from app.services.knowledge import coverage, drafts, problems
from app.services.knowledge.run import AGENT, RunResult, match_case, run_knowledge

__all__ = ["AGENT", "RunResult", "coverage", "drafts", "match_case", "problems", "run_knowledge"]
