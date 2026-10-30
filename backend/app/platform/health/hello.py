"""Hello greeting endpoints."""

from fastapi import APIRouter

from app.platform.health.schemas import MessageResponse

router = APIRouter(tags=["greeting"])


@router.get("/hello", response_model=MessageResponse, summary="Hello World / Greeting")
async def say_hello() -> MessageResponse:
    """Returns a greeting message."""
    return MessageResponse(message="hello there")
