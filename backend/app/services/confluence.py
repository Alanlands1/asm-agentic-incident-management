"""Copy Confluence pages into confluence_pages as plain text: the knowledge base the agents read.

Read-only towards Confluence. Every sync copies every page of the selected spaces and drops pages deleted there.
"""

import asyncio
import logging
import re
import tempfile
from datetime import UTC, datetime
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.resolution.ingest import ingest_kb
from app.core.config import settings
from app.models.confluence import ConfluencePage, ConfluenceSpace, ConfluenceSync
from app.services import atlassian
from app.services.atlassian import AtlassianError

logger = logging.getLogger("app.confluence")

MAX_PAGES = 2000  # shortcut: one sync copies at most this many pages per space; page by date if a space grows past it
sync_lock = asyncio.Lock()


class _Text(HTMLParser):
    """Confluence storage format (XHTML with ac: macros) -> text with markdown-style headings, lists and tables."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.out: list[str] = []
        self.lists = 0
        self.skip = 0  # inside macro parameters

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag == "ac:parameter":
            self.skip += 1
        elif re.fullmatch(r"h[1-6]", tag):
            self.out.append("\n\n" + "#" * int(tag[1]) + " ")
        elif tag in ("ul", "ol"):
            self.lists += 1
        elif tag == "li":
            self.out.append("\n" + "  " * (self.lists - 1) + "- ")
        elif tag == "tr":
            self.out.append("\n|")
        elif tag in ("td", "th"):
            self.out.append(" ")
        elif tag == "br":
            self.out.append("\n")
        elif tag == "hr":
            self.out.append("\n\n---\n\n")
        elif tag == "code":
            self.out.append("`")
        elif tag == "strong":
            self.out.append("**")

    def handle_endtag(self, tag: str) -> None:
        if tag == "ac:parameter":
            self.skip -= 1
        elif re.fullmatch(r"h[1-6]", tag) or tag in ("p", "table", "ac:structured-macro"):
            self.out.append("\n\n")
        elif tag in ("ul", "ol"):
            self.lists -= 1
            if not self.lists:
                self.out.append("\n\n")
        elif tag in ("td", "th"):
            self.out.append(" |")
        elif tag == "code":
            self.out.append("`")
        elif tag == "strong":
            self.out.append("**")

    def handle_data(self, data: str) -> None:
        if not self.skip:
            self.out.append(data)

    def unknown_decl(self, data: str) -> None:
        if data.startswith("CDATA[") and not self.skip:  # code macro bodies
            self.out.append(data[6:])


def page_text(storage: str) -> str:
    parser = _Text()
    parser.feed(storage or "")
    parser.close()
    text = "".join(parser.out)
    text = re.sub(r"[ \t]+\n", "\n", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


async def list_spaces() -> list[dict[str, str]]:
    async with atlassian.client() as c:
        data = await atlassian.call(c, "GET", "/wiki/api/v2/spaces", params={"limit": 250, "sort": "name"})
    return [{"key": s["key"], "id": s["id"], "name": s["name"]} for s in data["results"] if s.get("type") != "personal"]


async def fetch_pages(space_id: str) -> list[dict[str, Any]]:
    pages: list[dict[str, Any]] = []
    url: str | None = f"/wiki/api/v2/spaces/{space_id}/pages?body-format=storage&limit=100&status=current"
    async with atlassian.client() as c:
        while url and len(pages) < MAX_PAGES:
            data = await atlassian.call(c, "GET", url if url.startswith("/wiki") else "/wiki" + url)
            base = data.get("_links", {}).get("base", "")
            for p in data["results"]:
                pages.append({
                    "id": p["id"],
                    "title": p["title"],
                    "version": p["version"]["number"],
                    "body": page_text(p.get("body", {}).get("storage", {}).get("value", "")),
                    "url": base + p["_links"]["webui"] if p.get("_links", {}).get("webui") else None,
                })
            url = data.get("_links", {}).get("next")
    return pages


async def run_sync(db: AsyncSession, trigger: str) -> ConfluenceSync:
    """Copy every page of the selected spaces; update changed versions, drop pages deleted in Confluence."""
    if sync_lock.locked():
        raise AtlassianError("A sync is already running")
    async with sync_lock:
        spaces = (await db.scalars(select(ConfluenceSpace).order_by(ConfluenceSpace.key))).all()
        run = ConfluenceSync(trigger=trigger, spaces=",".join(s.key for s in spaces))
        db.add(run)
        await db.commit()
        try:
            if not spaces:
                raise AtlassianError("No spaces selected: pick at least one space first")
            fetched = {s.key: await fetch_pages(s.space_id) for s in spaces}  # no transaction open while Confluence answers
            known = {p.id: p for p in await db.scalars(select(ConfluencePage).where(ConfluencePage.space_key.in_(fetched)))}
            now = datetime.now(UTC)
            for key, pages in fetched.items():
                for p in pages:
                    row = known.pop(p["id"], None)
                    if row is None:
                        db.add(ConfluencePage(space_key=key, synced_at=now, **p))
                        run.created += 1
                    elif row.version != p["version"] or row.title != p["title"] or row.space_key != key:
                        for k, v in p.items():
                            setattr(row, k, v)
                        row.space_key, row.synced_at = key, now
                        run.updated += 1
                run.pulled += len(pages)
            if known:  # left over: deleted or moved out of the selected spaces
                await db.execute(delete(ConfluencePage).where(ConfluencePage.id.in_(list(known))))
                run.removed = len(known)
            # pages of spaces no longer selected
            await db.execute(delete(ConfluencePage).where(ConfluencePage.space_key.not_in(list(fetched))))
        except Exception as exc:
            await db.rollback()  # nothing from this sync is kept
            await db.refresh(run)
            if isinstance(exc, AtlassianError):
                run.error = str(exc)
                logger.warning("Confluence sync %s: %s", run.id, exc)
            else:
                run.error = f"Sync failed: {exc.__class__.__name__}"
                logger.exception("Confluence sync %s failed", run.id)
        run.finished_at = datetime.now(UTC)
        db.add(run)
        await db.commit()
        logger.info(
            "Confluence sync %s: pulled=%s created=%s updated=%s removed=%s",
            run.id, run.pulled, run.created, run.updated, run.removed,
        )
        if run.error is None:
            await feed_resolution(db)
        return run


def runbook(page: ConfluencePage) -> str:
    """A copied page as a runbook file. The Resolution agent's chunker reads the application from the H1 title."""
    return f"# {page.title}\n\n{page.body}\n"


async def feed_resolution(db: AsyncSession) -> None:
    """The Resolution agent searches the copied pages in place of the runbook files; with nothing copied, the files.
    Its ingest skips text it already has, so an unchanged copy costs no model call."""
    pages = (await db.scalars(select(ConfluencePage))).all()
    await db.commit()  # no transaction open while the model describes the new chunks
    try:
        with tempfile.TemporaryDirectory() as folder:
            for page in pages:
                Path(folder, f"confluence-{page.id}.md").write_text(runbook(page), encoding="utf-8")
            stats = await ingest_kb(Path(folder) if pages else None)
        logger.info("Resolution knowledge base from %s copied pages: %s", len(pages), stats)
    except Exception:
        logger.exception("Resolution knowledge base was not updated")  # the copy itself is good


async def schedule_loop(session_factory) -> None:
    """Copy the selected spaces every CONFLUENCE_SYNC_MINUTES (0 = off) while the app runs."""
    waited = 0
    while True:
        await asyncio.sleep(60)
        waited += 1
        if not settings.CONFLUENCE_SYNC_MINUTES or waited < settings.CONFLUENCE_SYNC_MINUTES:
            continue
        waited = 0
        try:
            async with session_factory() as db:
                await run_sync(db, "schedule")
        except AtlassianError as exc:
            logger.info("Scheduled Confluence sync skipped: %s", exc)
        except Exception:
            logger.exception("Scheduled Confluence sync failed")  # keep the loop alive
