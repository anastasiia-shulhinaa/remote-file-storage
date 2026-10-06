"""FastAPI application entry point.

Run from the ``backend/`` directory:

    uvicorn app.main:app --reload
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from app import __version__
from app.config import Settings, get_settings


class HealthResponse(BaseModel):
    status: str
    service: str
    version: str
    environment: str


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()

    app = FastAPI(title="MiniDrive API", version=__version__)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/health", response_model=HealthResponse, tags=["health"])
    async def health() -> HealthResponse:
        return HealthResponse(
            status="ok",
            service="minidrive-backend",
            version=__version__,
            environment=settings.app_env,
        )

    return app


app = create_app()
