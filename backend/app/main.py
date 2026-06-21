import logging
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator

from fastapi import APIRouter, FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError
from starlette.exceptions import HTTPException as StarletteHTTPException

from .api import admin, auth, evidence, files, tasks
from .config import settings
from .database import SessionLocal, initialize_database
from .schemas import AppError, ErrorDetail, ErrorResponse
from .services.auth_service import seed_default_admin
from .skills.registry import sync_skill_configs

API_PREFIX = "/api/v1"
INTERNAL_ERROR_MESSAGE = "服务器内部错误，请稍后重试"
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    initialize_database()
    with SessionLocal() as db:
        seed_default_admin(db)
        sync_skill_configs(db)
    yield


def _error_response(code: str, message: str, http_status: int) -> JSONResponse:
    payload = ErrorResponse(detail=ErrorDetail(code=code, message=message))
    return JSONResponse(status_code=http_status, content=payload.model_dump())


def create_app() -> FastAPI:
    app = FastAPI(title=settings.app_name, lifespan=lifespan)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    api_router = APIRouter(prefix=API_PREFIX)

    @api_router.get("/health", status_code=status.HTTP_200_OK)
    async def health() -> dict[str, Any]:
        return {
            "data": {
                "status": "ok",
                "app": settings.app_name,
                "environment": settings.env,
            },
            "message": "ok",
        }

    api_router.include_router(auth.router)
    api_router.include_router(tasks.router)
    api_router.include_router(files.router)
    api_router.include_router(evidence.router)
    api_router.include_router(admin.router)

    app.include_router(api_router)

    @app.exception_handler(AppError)
    async def handle_app_error(_: Request, exc: AppError) -> JSONResponse:
        return _error_response(exc.code, exc.message, exc.http_status)

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(
        _: Request, exc: RequestValidationError
    ) -> JSONResponse:
        return _error_response(
            "VALIDATION_ERROR",
            str(exc),
            status.HTTP_422_UNPROCESSABLE_CONTENT,
        )

    @app.exception_handler(StarletteHTTPException)
    async def handle_http_error(
        _: Request, exc: StarletteHTTPException
    ) -> JSONResponse:
        message = exc.detail if isinstance(exc.detail, str) else "HTTP error"
        return _error_response("HTTP_ERROR", message, exc.status_code)

    @app.exception_handler(SQLAlchemyError)
    async def handle_database_error(_: Request, exc: SQLAlchemyError) -> JSONResponse:
        logger.error(
            "Database error: %s",
            type(exc).__name__,
            exc_info=(type(exc), exc, exc.__traceback__),
        )
        return _error_response(
            "DATABASE_ERROR",
            INTERNAL_ERROR_MESSAGE,
            status.HTTP_500_INTERNAL_SERVER_ERROR,
        )

    @app.exception_handler(Exception)
    async def handle_unexpected_error(_: Request, exc: Exception) -> JSONResponse:
        logger.error(
            "Unhandled error: %s",
            type(exc).__name__,
            exc_info=(type(exc), exc, exc.__traceback__),
        )
        return _error_response(
            "INTERNAL_SERVER_ERROR",
            INTERNAL_ERROR_MESSAGE,
            status.HTTP_500_INTERNAL_SERVER_ERROR,
        )

    return app


app = create_app()
