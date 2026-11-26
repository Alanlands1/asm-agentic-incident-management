"""API v1 router registry."""

from fastapi import APIRouter, Depends

from app.admin import router as admin
from app.api.v1.endpoints import (
    auth,
    closure,
    confluence,
    dashboard,
    demo,
    data_quality,
    dq,
    health,
    hello,
    incidents,
    jira,
    knowledge,
    resolution,
    runbooks,
    servicenow,
    storms,
    tickets,
    triage,
)
from app.api.v1.endpoints.auth import current_user, require_role
from app.personas import router as personas

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(auth.router)

signed_in = APIRouter(dependencies=[Depends(current_user)])  # everything below needs a session
signed_in.include_router(hello.router)
signed_in.include_router(tickets.router)
signed_in.include_router(data_quality.router)
signed_in.include_router(triage.router)
signed_in.include_router(closure.router)
signed_in.include_router(knowledge.router)
signed_in.include_router(storms.router)
signed_in.include_router(admin.router, dependencies=[Depends(require_role("admin"))])  # and the X-Admin-Key
signed_in.include_router(servicenow.router)
signed_in.include_router(dq.router)
signed_in.include_router(jira.router)
signed_in.include_router(resolution.router)
signed_in.include_router(confluence.router)
signed_in.include_router(incidents.router)
signed_in.include_router(dashboard.router)
signed_in.include_router(personas.router)
signed_in.include_router(runbooks.router)
signed_in.include_router(demo.router)
api_router.include_router(signed_in)
