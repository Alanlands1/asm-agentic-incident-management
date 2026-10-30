"""Every router, mounted under /api/v1 by main.py: one per agent, then the platform's."""

from fastapi import APIRouter

from app.agents.data_quality import router as data_quality
from app.platform.admin import router as admin
from app.platform.health import hello
from app.platform.health import router as health
from app.platform.tickets import router as tickets

api_router = APIRouter()

# Platform
api_router.include_router(health.router)
api_router.include_router(hello.router)
api_router.include_router(tickets.router)
api_router.include_router(admin.router)

# Agents
api_router.include_router(data_quality.router)
