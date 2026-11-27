"""Demo reset: start the open tickets again from scratch, in Jira and here, with fresh SLA clocks."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.endpoints.auth import require_role
from app.db.session import get_db
from app.services.atlassian import AtlassianError
from app.services.reset import reset_demo

router = APIRouter(prefix="/demo", tags=["demo"])


class ResetOut(BaseModel):
    tickets: int
    jira_issues: int
    jira_comments_deleted: int
    jira_moved_back: int
    jira_priorities_restored: int
    jira_closed: int = 0  # issues created after the baseline, closed because Jira cannot delete them
    jira_errors: list[str]
    restored_from: str | None = None  # when the restored baseline was taken; None = no baseline was used


@router.post("/reset", response_model=ResetOut, summary="Reset every open ticket and restart the SLA clocks",
             dependencies=[Depends(require_role("admin"))])
async def reset(rerun: bool = True, dry_run: bool = False, db: AsyncSession = Depends(get_db)) -> ResetOut:
    """Deletes the agents' comments and labels on the open Jira issues and moves them back to the status they were
    created in; clears the agents' results, reviews and ratings on every open ticket; restarts every SLA clock from now.
    Closed tickets and people's own comments are kept. With rerun (default) the agents then start again. Admins only.

    With a saved baseline (DEMO_BASELINE_DIR) it instead puts Jira and the console back as they were when the baseline
    was taken, clocks included, and does not start the agents. dry_run (baseline only) returns what that would do and
    changes nothing.
    """
    try:
        r = await reset_demo(db, rerun=rerun, dry_run=dry_run)
    except AtlassianError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return ResetOut(**r.__dict__)
