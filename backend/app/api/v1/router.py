"""API v1 router registry."""

from fastapi import APIRouter

from app.admin import router as admin
from app.api.v1.endpoints import (
    closure,
    confluence,
    dashboard,
    data_quality,
    dq,
    health,
    hello,
    incidents,
    jira,
    resolution,
    runbooks,
    servicenow,
    storms,
    tickets,
    triage,
)
from app.personas import router as personas

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(hello.router)
api_router.include_router(tickets.router)
api_router.include_router(data_quality.router)
api_router.include_router(triage.router)
api_router.include_router(closure.router)
api_router.include_router(storms.router)
api_router.include_router(admin.router)
api_router.include_router(servicenow.router)
api_router.include_router(dq.router)
api_router.include_router(jira.router)
api_router.include_router(resolution.router)
api_router.include_router(confluence.router)
api_router.include_router(incidents.router)
api_router.include_router(dashboard.router)
api_router.include_router(personas.router)
api_router.include_router(runbooks.router)

