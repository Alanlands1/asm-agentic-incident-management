"""Jira connection, project picker and sync (read-only towards Jira)."""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.session import get_db
from app.models.jira import JiraProject, JiraSync
from app.services import jira

# shortcut: no auth, like the DQ endpoints; put behind sign-in once roles are real.
router = APIRouter(prefix="/jira", tags=["jira"])


class ConnectionOut(BaseModel):
    site: str
    email_set: bool
    token_set: bool
    connected: bool
    account_name: str | None = None
    error: str | None = None
    sync_minutes: int
    write_back: bool = False  # a person may post comments and reviewed priorities to Jira


class ProjectOut(BaseModel):
    key: str
    name: str
    selected: bool
    team: str | None = None


class ProjectIn(BaseModel):
    key: str = Field(min_length=1, max_length=32, pattern=r"^[A-Z][A-Z0-9_]*$")
    name: str = Field(min_length=1, max_length=128)
    team: str | None = Field(None, max_length=64)


class SyncOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    trigger: str
    projects: str
    started_at: datetime
    finished_at: datetime | None = None
    pulled: int
    created: int
    updated: int
    queued: int
    error: str | None = None


@router.get("/connection", response_model=ConnectionOut, summary="Test the Jira connection")
async def connection() -> ConnectionOut:
    out = ConnectionOut(
        site=settings.ATLASSIAN_BASE_URL,
        email_set=bool(settings.ATLASSIAN_EMAIL),
        token_set=bool(settings.ATLASSIAN_API_TOKEN.get_secret_value()),
        connected=False,
        sync_minutes=settings.JIRA_SYNC_MINUTES,
        write_back=settings.JIRA_WRITE_BACK,
    )
    try:
        out.account_name = await jira.whoami()
        out.connected = True
    except jira.JiraError as exc:
        out.error = str(exc)
    return out


@router.get("/projects", response_model=list[ProjectOut], summary="Jira projects, with the ones picked for sync")
async def projects(db: AsyncSession = Depends(get_db)) -> list[ProjectOut]:
    try:
        remote = await jira.list_projects()
    except jira.JiraError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    picked = {p.key: p for p in await db.scalars(select(JiraProject))}
    return [
        ProjectOut(**p, selected=p["key"] in picked, team=picked[p["key"]].team if p["key"] in picked else None)
        for p in remote
    ]


@router.put("/projects", response_model=list[ProjectIn], summary="Replace the projects to sync")
async def save_projects(payload: list[ProjectIn], db: AsyncSession = Depends(get_db)) -> list[ProjectIn]:
    await db.execute(delete(JiraProject))
    for p in payload:
        db.add(JiraProject(key=p.key, name=p.name, team=(p.team or "").strip() or None))
    await db.commit()
    return payload


@router.post("/sync", response_model=SyncOut, summary="Pull the selected projects now")
async def sync_now(db: AsyncSession = Depends(get_db)) -> SyncOut:
    """Pull now; new open tickets then go through Data Quality and Triage in the background."""
    if jira.sync_lock.locked():
        raise HTTPException(status_code=409, detail="A sync is already running")
    run = await jira.run_sync(db, "manual")
    if run.queued:
        jira.start_agents()
    return SyncOut.model_validate(run)


@router.get("/syncs", response_model=list[SyncOut], summary="Sync history, newest first")
async def syncs(limit: int = Query(20, ge=1, le=200), db: AsyncSession = Depends(get_db)) -> list[SyncOut]:
    rows = await db.scalars(select(JiraSync).order_by(JiraSync.started_at.desc(), JiraSync.id.desc()).limit(limit))
    return [SyncOut.model_validate(r) for r in rows]
