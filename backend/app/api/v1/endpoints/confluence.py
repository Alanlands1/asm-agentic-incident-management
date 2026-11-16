"""Confluence connection, space picker, sync and the copied pages (read-only towards Confluence)."""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.session import get_db
from app.models.confluence import ConfluencePage, ConfluenceSpace, ConfluenceSync
from app.services import atlassian, confluence
from app.services.atlassian import AtlassianError

# shortcut: no auth, like the DQ and Jira endpoints; put behind sign-in once roles are real.
router = APIRouter(prefix="/confluence", tags=["confluence"])


class ConnectionOut(BaseModel):
    site: str
    connected: bool
    account_name: str | None = None
    error: str | None = None
    sync_minutes: int


class SpaceOut(BaseModel):
    key: str
    id: str
    name: str
    selected: bool


class SpaceIn(BaseModel):
    key: str = Field(min_length=1, max_length=255)
    id: str = Field(min_length=1, max_length=32, pattern=r"^\d+$")
    name: str = Field(min_length=1, max_length=255)


class SyncOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    trigger: str
    spaces: str
    started_at: datetime
    finished_at: datetime | None = None
    pulled: int
    created: int
    updated: int
    removed: int
    error: str | None = None


class PageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    space_key: str
    title: str
    version: int
    url: str | None = None
    synced_at: datetime


class PageDetail(PageOut):
    body: str


@router.get("/connection", response_model=ConnectionOut, summary="Test the Confluence connection")
async def connection() -> ConnectionOut:
    out = ConnectionOut(site=settings.ATLASSIAN_BASE_URL, connected=False, sync_minutes=settings.CONFLUENCE_SYNC_MINUTES)
    try:
        await confluence.list_spaces()  # proves Confluence access, not only the account
        out.account_name = await atlassian.whoami()
        out.connected = True
    except AtlassianError as exc:
        out.error = str(exc)
    return out


@router.get("/spaces", response_model=list[SpaceOut], summary="Confluence spaces, with the ones picked for the copy")
async def spaces(db: AsyncSession = Depends(get_db)) -> list[SpaceOut]:
    try:
        remote = await confluence.list_spaces()
    except AtlassianError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    picked = set(await db.scalars(select(ConfluenceSpace.key)))
    return [SpaceOut(**s, selected=s["key"] in picked) for s in remote]


@router.put("/spaces", response_model=list[SpaceIn], summary="Replace the spaces to copy")
async def save_spaces(payload: list[SpaceIn], db: AsyncSession = Depends(get_db)) -> list[SpaceIn]:
    await db.execute(delete(ConfluenceSpace))
    for s in payload:
        db.add(ConfluenceSpace(key=s.key, space_id=s.id, name=s.name))
    await db.commit()
    return payload


@router.post("/sync", response_model=SyncOut, summary="Copy the selected spaces now")
async def sync_now(db: AsyncSession = Depends(get_db)) -> SyncOut:
    if confluence.sync_lock.locked():
        raise HTTPException(status_code=409, detail="A sync is already running")
    return SyncOut.model_validate(await confluence.run_sync(db, "manual"))


@router.get("/syncs", response_model=list[SyncOut], summary="Sync history, newest first")
async def syncs(limit: int = Query(20, ge=1, le=200), db: AsyncSession = Depends(get_db)) -> list[SyncOut]:
    newest = (ConfluenceSync.started_at.desc(), ConfluenceSync.id.desc())
    rows = await db.scalars(select(ConfluenceSync).order_by(*newest).limit(limit))
    return [SyncOut.model_validate(r) for r in rows]


@router.get("/pages", response_model=list[PageOut], summary="Copied pages")
async def pages(db: AsyncSession = Depends(get_db)) -> list[PageOut]:
    rows = await db.scalars(select(ConfluencePage).order_by(ConfluencePage.space_key, ConfluencePage.title))
    return [PageOut.model_validate(r) for r in rows]


@router.get("/pages/{page_id}", response_model=PageDetail, summary="One copied page with its text")
async def page(page_id: str, db: AsyncSession = Depends(get_db)) -> PageDetail:
    row = await db.get(ConfluencePage, page_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"Page {page_id} not copied")
    return PageDetail.model_validate(row)
