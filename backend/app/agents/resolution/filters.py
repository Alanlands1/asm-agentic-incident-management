"""Resolution agent: the metadata pre-filter for a ticket (Phase 3 of the architecture)."""

from app.agents.resolution.retrieval import Filters
from app.core.registry import load_registry


def filters_for(application: str | None) -> Filters:
    """Filter the knowledge base to the ticket's application. Names match data/registry/apps.yaml, ignoring case.
    A missing or unknown application means no filter: the search covers every runbook."""
    if not application or not application.strip():
        return Filters()
    wanted = application.strip().casefold()
    for name in load_registry("apps.yaml"):
        if name.casefold() == wanted:
            return Filters(app=name)
    return Filters()
