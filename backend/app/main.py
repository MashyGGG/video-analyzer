import logging
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.health import check_dependencies


class Readiness(BaseModel):
    status: str
    code: str
    dependencies: dict[str, bool]
    models: str = "not_configured"


def create_app(checker: Callable[[], dict[str, bool]] = check_dependencies) -> FastAPI:
    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        logging.getLogger(__name__).info('{"event":"api_started","version":"0.1.0"}')
        yield

    application = FastAPI(title="Video-analyzer", version="0.1.0", lifespan=lifespan)

    @application.get("/api/v1/health/live")
    def live() -> dict[str, str]:
        return {"status": "alive", "version": "0.1.0"}

    @application.get("/api/v1/health/ready", response_model=Readiness, responses={503: {"model": Readiness}})
    def ready() -> JSONResponse:
        try:
            dependencies = checker()
            available = dependencies.get("database", False) and dependencies.get("redis", False)
        except Exception:
            dependencies, available = {"database": False, "redis": False}, False
        payload = Readiness(
            status="ready" if available else "unavailable",
            code="OK" if available else "DEPENDENCY_UNAVAILABLE",
            dependencies=dependencies,
        )
        return JSONResponse(payload.model_dump(), status_code=200 if available else 503)

    return application


app = create_app()
