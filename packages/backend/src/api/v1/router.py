"""API v1 router aggregation."""

from fastapi import APIRouter

from src.api.v1.schemas import AboutResponse
from src.version import get_version_info
from src.api.v1.workflows import router as workflows_router
from src.api.v1.execution import router as execution_router
from src.api.v1.tools import router as tools_router
from src.api.v1.auth import router as auth_router
from src.api.v1.llm_providers import (
    router as llm_providers_router,
    workflows_router as llm_workflows_router,
)
from src.api.v1.stt_providers import (
    router as stt_providers_router,
    workflows_router as stt_workflows_router,
)
from src.api.v1.transcribe import router as transcribe_router

api_router = APIRouter()

api_router.include_router(auth_router)
api_router.include_router(workflows_router)
api_router.include_router(execution_router)
api_router.include_router(tools_router)
api_router.include_router(llm_providers_router)
api_router.include_router(llm_workflows_router)
api_router.include_router(stt_providers_router)
api_router.include_router(stt_workflows_router)
api_router.include_router(transcribe_router)


@api_router.get("/about", response_model=AboutResponse, tags=["system"])
async def about():
    """Return application version and metadata."""
    return get_version_info()
