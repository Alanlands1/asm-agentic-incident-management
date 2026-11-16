"""Knowledge Builder endpoints."""

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import PlainTextResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.knowledge import KBDraft, ProblemCandidate, ResolvedCase
from app.schemas.knowledge import (
    AppCoverageOut,
    KBDraftOut,
    KBDraftReview,
    KnowledgeRunResponse,
    ProblemCandidateOut,
    ProblemDecision,
    ResolvedCaseOut,
)
from app.services.knowledge import coverage, drafts, problems, run_knowledge
from app.services.knowledge.run import RunResult

router = APIRouter(prefix="/knowledge", tags=["knowledge builder"])


@router.post("/run", response_model=KnowledgeRunResponse, summary="Save and match resolved tickets")
async def run(db: AsyncSession = Depends(get_db)) -> KnowledgeRunResponse:
    """Save every resolved ticket whose close notes passed as a masked case, and match it to a knowledge-base article.
    Safe to re-run: unchanged cases are skipped."""
    return run_response(await db.run_sync(run_knowledge))


def run_response(result: RunResult) -> KnowledgeRunResponse:
    return KnowledgeRunResponse(
        evaluated=result.evaluated, skipped=result.skipped, model_errors=result.model_errors, by_status=dict(result.by_status),
        drafts=dict(result.drafts), open_problems=result.problems,
    )


@router.get("/cases", response_model=list[ResolvedCaseOut], summary="Saved cases")
async def list_cases(
    match_status: str | None = Query(None, pattern="^(matched|gap|uncertain)$"),
    application: str | None = None,
    limit: int = Query(100, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
):
    """Saved cases, newest first. Filter by `match_status` or `application`; `gap` shows where an article is missing."""
    return await db.run_sync(_cases, match_status, application, limit)


def _cases(db: Session, match_status: str | None, application: str | None, limit: int) -> list[ResolvedCase]:
    query = select(ResolvedCase).order_by(ResolvedCase.closed_at.desc().nulls_last(), ResolvedCase.ticket_id).limit(limit)
    if match_status:
        query = query.where(ResolvedCase.match_status == match_status)
    if application:
        query = query.where(ResolvedCase.application == application)
    return list(db.scalars(query))


@router.get("/coverage", response_model=list[AppCoverageOut], summary="Knowledge-base coverage per application")
async def get_coverage(db: AsyncSession = Depends(get_db)) -> list[AppCoverageOut]:
    """Per application: articles, saved cases, how many an article covers, the gaps, and the articles never used."""
    rows = await db.run_sync(coverage.coverage)
    return [
        AppCoverageOut(application=r.application, articles=r.articles, cases=r.cases, matched=r.matched, gap=r.gap,
                       uncertain=r.uncertain, outside_kb=r.outside_kb, drafts_waiting=r.drafts_waiting,
                       covered_share=r.covered_share, unused_articles=r.unused_articles)
        for r in rows
    ]


@router.get("/drafts", response_model=list[KBDraftOut], summary="Drafted articles")
async def list_drafts(
    status: str | None = Query("draft", pattern="^(draft|approved|rejected)$"), db: AsyncSession = Depends(get_db)
):
    """Drafted articles, newest first; by default the ones waiting for an expert."""
    return await db.run_sync(lambda s: list(s.scalars(
        select(KBDraft).where(KBDraft.status == status).order_by(KBDraft.created_at.desc(), KBDraft.id.desc())
    )))


@router.get("/drafts/{draft_id}", response_model=KBDraftOut, summary="One drafted article")
async def get_draft(draft_id: int, db: AsyncSession = Depends(get_db)) -> KBDraft:
    return await db.run_sync(_draft_or_404, draft_id)


def _draft_or_404(db: Session, draft_id: int) -> KBDraft:
    draft = db.get(KBDraft, draft_id)
    if draft is None:
        raise HTTPException(status_code=404, detail=f"Draft {draft_id} not found")
    return draft


@router.post("/drafts/{draft_id}/review", response_model=KBDraftOut, summary="An expert's decision on a draft")
async def review_draft(draft_id: int, payload: KBDraftReview, db: AsyncSession = Depends(get_db)) -> KBDraft:
    """Approve the draft as written, edit and approve it, or reject it. Approving gives the next article id."""
    return await db.run_sync(_review, draft_id, payload)


def _review(db: Session, draft_id: int, payload: KBDraftReview) -> KBDraft:
    draft = _draft_or_404(db, draft_id)
    fields = payload.model_dump(include={"title", "symptoms", "root_cause", "resolution_steps", "escalation"})
    try:
        return drafts.review_draft(db, draft, payload.action, payload.reviewer, fields, payload.reason_code, payload.note)
    except drafts.AlreadyDecided as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except drafts.DraftError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/drafts/{draft_id}/export", response_class=PlainTextResponse, summary="A draft as markdown")
async def export_draft(draft_id: int, db: AsyncSession = Depends(get_db)) -> PlainTextResponse:
    """The draft, or the approved article, in the knowledge base's own markdown format. Nothing is written anywhere."""
    text = await db.run_sync(lambda s: drafts.export(_draft_or_404(s, draft_id)))
    return PlainTextResponse(text, media_type="text/markdown")


@router.get("/problems", response_model=list[ProblemCandidateOut], summary="Repeat issues")
async def list_problems(status: str | None = Query("open", pattern="^(open|accepted|dismissed)$"),
                        db: AsyncSession = Depends(get_db)):
    """Issues closed again and again: suggestions to open a problem record. By default the open ones."""
    return await db.run_sync(lambda s: list(s.scalars(
        select(ProblemCandidate).where(ProblemCandidate.status == status).order_by(ProblemCandidate.cases.desc())
    )))


@router.post("/problems/{problem_id}/decision", response_model=ProblemCandidateOut, summary="Accept or dismiss a repeat issue")
async def decide_problem(problem_id: int, payload: ProblemDecision, db: AsyncSession = Depends(get_db)) -> ProblemCandidate:
    """Accept (open a problem record) or dismiss. Nothing is created in ServiceNow or JIRA."""
    return await db.run_sync(_decide, problem_id, payload)


def _decide(db: Session, problem_id: int, payload: ProblemDecision) -> ProblemCandidate:
    candidate = db.get(ProblemCandidate, problem_id)
    if candidate is None:
        raise HTTPException(status_code=404, detail=f"Suggestion {problem_id} not found")
    try:
        return problems.decide(db, candidate, payload.action, payload.decided_by, payload.note)
    except problems.ProblemError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
