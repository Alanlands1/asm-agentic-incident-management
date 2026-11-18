"""ServiceNow tickets API endpoints."""

import logging
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.models.servicenow import ServiceNowTicket
from app.schemas.servicenow import (
    ServiceNowIngestResponse,
    ServiceNowTicketDetail,
    ServiceNowTicketList,
)
from app.services.ingestion import ingest_servicenow_file

logger = logging.getLogger("app.api.servicenow")

router = APIRouter(prefix="/servicenow", tags=["servicenow"])

MAX_UPLOAD_SIZE = 10 * 1024 * 1024  # 10 MB


@router.post(
    "/ingest",
    response_model=ServiceNowIngestResponse,
    summary="Ingest ServiceNow tickets from Excel",
)
async def ingest_servicenow(
    file: Annotated[
        UploadFile,
        File(description="ServiceNow tickets Excel workbook (.xlsx)"),
    ],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ServiceNowIngestResponse:
    """Upload and ingest ServiceNow tickets from an Excel workbook (.xlsx)."""
    if not file.filename or not file.filename.lower().endswith(".xlsx"):
        raise HTTPException(
            status_code=400,
            detail="Invalid file format. Please upload an Excel file (.xlsx).",
        )

    content = await file.read(MAX_UPLOAD_SIZE + 1)
    if len(content) > MAX_UPLOAD_SIZE:
        raise HTTPException(
            status_code=413,
            detail="File size exceeds maximum limit of 10MB.",
        )

    try:
        result = await ingest_servicenow_file(
            db=db, file_bytes=content, filename=file.filename
        )
        return ServiceNowIngestResponse(
            message=(
                f"Successfully ingested {result.total_processed} ServiceNow tickets "
                f"({result.created} created, {result.updated} updated, {result.skipped} skipped)."
            ),
            total_processed=result.total_processed,
            created=result.created,
            updated=result.updated,
            skipped=result.skipped,
            filename=result.filename,
        )
    except ValueError as exc:
        await db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        await db.rollback()
        logger.exception("Failed to ingest ServiceNow Excel file")
        raise HTTPException(
            status_code=500,
            detail="Failed to ingest file due to an internal server error.",
        ) from exc


@router.get("/tickets", response_model=ServiceNowTicketList, summary="List ServiceNow tickets")
async def list_servicenow_tickets(
    dq_flag: Optional[bool] = Query(None, description="Filter by DQ flag"),
    dq_reason: Optional[str] = Query(None, description="Filter by DQ reason"),
    service: Optional[str] = Query(None, description="Filter by service"),
    priority: Optional[str] = Query(None, description="Filter by priority"),
    caller: Optional[str] = Query(None, description="Filter by caller"),
    is_unresolved: Optional[bool] = Query(None, description="Filter only unresolved tickets (closed_at is null)"),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
) -> ServiceNowTicketList:
    """ServiceNow tickets, filterable by DQ status and metadata."""
    query = select(ServiceNowTicket)

    if dq_flag is not None:
        query = query.where(ServiceNowTicket.dq_flag == dq_flag)
    if dq_reason is not None:
        query = query.where(ServiceNowTicket.dq_reason.ilike(f"%{dq_reason}%"))
    if service is not None:
        query = query.where(ServiceNowTicket.service == service)
    if priority is not None:
        query = query.where(ServiceNowTicket.priority == priority)
    if caller is not None:
        query = query.where(ServiceNowTicket.caller.ilike(f"%{caller}%"))
    if is_unresolved is True:
        query = query.where(ServiceNowTicket.closed_at.is_(None))
    elif is_unresolved is False:
        query = query.where(ServiceNowTicket.closed_at.is_not(None))

    total = await db.scalar(select(func.count()).select_from(query.subquery()))
    items = await db.scalars(
        query.order_by(ServiceNowTicket.opened_at.desc().nulls_last())
        .limit(limit)
        .offset(offset)
    )
    return ServiceNowTicketList(total=total or 0, items=list(items.all()))


@router.get("/tickets/{ticket_id}", response_model=ServiceNowTicketDetail, summary="Get one ServiceNow ticket")
async def get_servicenow_ticket(
    ticket_id: str,
    db: AsyncSession = Depends(get_db),
) -> ServiceNowTicket:
    """Get single ServiceNow ticket detail by ID."""
    ticket = await db.get(ServiceNowTicket, ticket_id)
    if ticket is None:
        raise HTTPException(status_code=404, detail=f"ServiceNow ticket {ticket_id} not found")
    return ticket
