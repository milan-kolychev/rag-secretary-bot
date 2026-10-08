"""Сборка приложения FastAPI."""

import asyncio
import logging
import secrets
import time
import traceback
import uuid
from collections.abc import Awaitable, Callable
from typing import Annotated

from fastapi import Depends, FastAPI, Request, Response
from fastapi.concurrency import run_in_threadpool
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from starlette.exceptions import HTTPException as StarletteHTTPException

from api.config import ApiSettings
from api.engine import RagAnswer, RagEngine, RagUnavailableError
from api.schemas import AskRequest, AskResponse, Error, ErrorCode, ErrorDetail, Health

logger = logging.getLogger(__name__)

_bearer = HTTPBearer(auto_error=False)


class ApiError(Exception):
    """Ошибка, которая возвращается клиенту в формате `Error`.

    Args:
        status_code: HTTP-код ответа.
        code: Код ошибки из контракта.
        message: Описание для логов; не должно содержать текст вопроса.
    """

    def __init__(self, status_code: int, code: ErrorCode, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code: ErrorCode = code
        self.message = message


def _log_unexpected(exc: BaseException, user_id: int) -> None:
    # format_tb() leaves out the exception message, which may contain the question text.
    logger.error(
        "RAG engine error: error=%s user_id=%s\n%s",
        type(exc).__name__,
        user_id,
        "".join(traceback.format_tb(exc.__traceback__)),
    )


def error_response(status_code: int, code: ErrorCode, message: str) -> JSONResponse:
    """Собирает ответ с ошибкой в формате контракта."""
    body = Error(error=ErrorDetail(code=code, message=message))
    return JSONResponse(status_code=status_code, content=body.model_dump())


def create_app(settings: ApiSettings, engine: RagEngine) -> FastAPI:
    """Создаёт приложение.

    Args:
        settings: Настройки API.
        engine: RAG-движок.

    Returns:
        Приложение FastAPI.
    """
    app = FastAPI(
        title="RAG-система для секретарей ФПИ",
        version="1.0.0",
        description="Контракт описан в api/openapi.yaml.",
    )
    expected_token = settings.api_token.get_secret_value()

    async def require_token(
        credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    ) -> None:
        if credentials is None or not secrets.compare_digest(
            credentials.credentials.encode(), expected_token.encode()
        ):
            raise ApiError(401, "unauthorized", "Invalid or missing API token")

    @app.exception_handler(ApiError)
    async def handle_api_error(request: Request, exc: ApiError) -> JSONResponse:
        headers = {"WWW-Authenticate": "Bearer"} if exc.status_code == 401 else None
        response = error_response(exc.status_code, exc.code, exc.message)
        if headers:
            response.headers.update(headers)
        return response

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        # Only location and message: pydantic errors also carry the input, i.e. the question.
        parts = []
        for error in exc.errors():
            loc = ".".join(str(item) for item in error.get("loc", ()) if item != "body")
            parts.append(f"{loc}: {error.get('msg', 'invalid value')}" if loc else error["msg"])
        return error_response(422, "validation_error", "; ".join(parts) or "invalid request")

    @app.exception_handler(StarletteHTTPException)
    async def handle_http_error(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        if exc.status_code == 404:
            return error_response(404, "not_found", "Not found")
        if exc.status_code == 405:
            return error_response(405, "method_not_allowed", "Method not allowed")
        return error_response(exc.status_code, "internal_error", str(exc.detail))

    @app.exception_handler(Exception)
    async def handle_unexpected(request: Request, exc: Exception) -> JSONResponse:
        # The exception message may carry the question text, so only the traceback is logged.
        logger.error(
            "unexpected error: error=%s path=%s\n%s",
            type(exc).__name__,
            request.url.path,
            "".join(traceback.format_tb(exc.__traceback__)),
        )
        return error_response(500, "internal_error", "Internal server error")

    @app.middleware("http")
    async def log_requests(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        started = time.perf_counter()
        response = await call_next(request)
        logger.info(
            "%s %s status=%s latency=%.0fms",
            request.method,
            request.url.path,
            response.status_code,
            (time.perf_counter() - started) * 1000,
        )
        return response

    @app.get("/health", tags=["service"])
    async def health() -> Health:
        """Проверка доступности API."""
        return Health()

    @app.post("/ask", tags=["ask"], dependencies=[Depends(require_token)])
    async def ask(request: AskRequest) -> AskResponse:
        """Ответ на вопрос студента по документам."""
        started = time.perf_counter()
        try:
            raw = await asyncio.wait_for(
                run_in_threadpool(engine.answer, request.question),
                timeout=settings.rag_timeout,
            )
            # The engine may return its own model with the same fields.
            result = RagAnswer.model_validate(raw, from_attributes=True)
        except TimeoutError:
            raise ApiError(
                503, "rag_timeout", f"RAG engine did not answer in {settings.rag_timeout:g} s"
            ) from None
        except RagUnavailableError as exc:
            logger.warning("RAG engine unavailable: %s", exc)
            raise ApiError(503, "rag_unavailable", "RAG engine is unavailable") from None
        except Exception as exc:
            # Handled here rather than by the app-level handler: Starlette re-raises
            # unhandled errors and uvicorn would log their message, which may hold the question.
            _log_unexpected(exc, request.user_id)
            raise ApiError(500, "internal_error", "RAG engine failed") from None

        answered = result.status == "answered"
        response = AskResponse(
            answer_id=uuid.uuid4(),
            status=result.status,
            text=result.text if answered else "",
            sources=result.sources if answered else [],
            ticket_id=None,
        )
        logger.info(
            "ask: user_id=%s status=%s sources=%d latency=%.0fms",
            request.user_id,
            response.status,
            len(response.sources),
            (time.perf_counter() - started) * 1000,
        )
        return response

    return app
