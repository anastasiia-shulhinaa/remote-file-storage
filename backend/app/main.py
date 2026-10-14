import logging
import mimetypes

from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app.api import auth, files, folders, preview, settings as settings_api, sync
from app.api.deps import get_schema_check
from app.core.config import settings
from app.core.errors import AppError

logger = logging.getLogger("minidrive")

app = FastAPI(
    title="MiniDrive API",
    version="1.2.0",
    description="Client-server file storage (a simplified Google Drive).",
)

if settings.cors_origin_list:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=False,  # Bearer tokens, no cookies
        allow_methods=["GET", "POST", "PATCH", "DELETE"],
        allow_headers=["Authorization", "Content-Type"],
        expose_headers=["Content-Disposition", "X-File-Modified-At"],
    )


@app.exception_handler(AppError)
async def app_error_handler(request: Request, exc: AppError):
    if exc.status_code >= 500:
        logger.error("%s %s failed: %s", request.method, request.url.path, exc.detail)
    return JSONResponse(
        status_code=exc.status_code,
        content={**exc.extra, "detail": exc.detail, "code": exc.code},
    )


@app.exception_handler(RequestValidationError)
async def request_validation_handler(request: Request, exc: RequestValidationError):
    """422 with a stable code; an AppError raised by a model validator keeps its own code."""
    for error in exc.errors():
        cause = (error.get("ctx") or {}).get("error")
        if isinstance(cause, AppError):
            return await app_error_handler(request, cause)
    return JSONResponse(status_code=422, content={"detail": "Invalid request", "code": "validation_error"})


@app.exception_handler(Exception)
async def unexpected_error_handler(request: Request, exc: Exception):
    """Unexpected failures (e.g. a database error): log the traceback, never send it to clients."""
    logger.exception("%s %s crashed", request.method, request.url.path)
    return JSONResponse(status_code=500, content={"detail": "Internal server error", "code": "internal_error"})


@app.get("/health", tags=["health"])
def health(schema_check=Depends(get_schema_check)):
    """Always 200 while the API runs; "database" tells whether a migration is missing."""
    missing = schema_check()
    return {
        "status": "ok",
        "database": "migration_required" if missing else "ok",
        "missing_migrations": missing,
    }


app.include_router(auth.router)
app.include_router(folders.router)
app.include_router(files.router)
app.include_router(preview.router)
app.include_router(sync.router)
app.include_router(settings_api.router)

# Web client: the React/Vite production build (web/dist) served as static files.
# It is only a client — it talks to the API above like the desktop does.
# Mounted last, so API routes always win. Absent in development (Vite serves it).
# ES modules (e.g. the pdf.js worker) must be served as JavaScript; some systems
# (Windows registry) map .mjs to text/plain, which browsers refuse to execute.
mimetypes.add_type("text/javascript", ".mjs")

if settings.web_dist_dir.is_dir():
    app.mount("/", StaticFiles(directory=settings.web_dist_dir, html=True), name="web")
