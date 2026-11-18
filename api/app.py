"""Сборка приложения FastAPI."""

import asyncio
import logging
import secrets
import time
import traceback
import uuid
from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager
from threading import Lock
from typing import Annotated

from fastapi import Depends, FastAPI, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from starlette.exceptions import HTTPException as StarletteHTTPException

from api.config import ApiSettings
from api.engine import RagEngine
from api.schemas import AskRequest, AskResponse, Error, ErrorCode, ErrorDetail, Health
from core.db import Database
from core.queue import QueueRejected, RequestQueue

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


def create_app(
    settings: ApiSettings, engine: RagEngine, *, database=None, documents=None
) -> FastAPI:
    """Создаёт приложение.

    Args:
        settings: Настройки API.
        engine: RAG-движок.

    Returns:
        Приложение FastAPI.
    """
    db = database or Database(settings.database_url)
    queue = RequestQueue(db, settings, engine)
    runner = None
    stopping = False
    document_init = Lock()

    async def consume():
        while not stopping:
            try:
                processed = await asyncio.to_thread(queue.process_one)
            except Exception as exc:
                logger.error("queue_poll_failed error=%s", type(exc).__name__)
                processed = False
            await asyncio.sleep(0 if processed else settings.queue_poll_interval)

    def ensure_runner():
        nonlocal runner
        if runner is None or runner.done():
            runner = asyncio.create_task(consume())

    @asynccontextmanager
    async def lifespan(app):
        nonlocal stopping
        ensure_runner()
        try:
            yield
        finally:
            stopping = True
            if runner:
                await runner
            close = getattr(engine, "close", None)
            if close:
                await asyncio.to_thread(close)
            db.engine.dispose()

    app = FastAPI(
        lifespan=lifespan,
        title="RAG-система для секретарей ФПИ",
        version="1.0.0",
        description="Контракт описан в api/openapi.yaml.",
    )
    expected_token = settings.api_token.get_secret_value()
    app.state.queue = queue

    def document_service():
        nonlocal documents
        with document_init:
            return initialize_documents()

    def initialize_documents():
        nonlocal documents
        if documents is None:
            if not hasattr(engine, "embedder") or not hasattr(engine, "store"):
                raise ApiError(503, "rag_unavailable", "Document indexing requires the RAG engine")
            from transformers import AutoTokenizer

            from worker.documents import DocumentService

            documents = DocumentService(
                db, engine.store, engine.embedder, AutoTokenizer.from_pretrained("BAAI/bge-m3")
            )
        return documents

    async def queue_call(method, *args):
        try:
            return await asyncio.to_thread(method, *args)
        except QueueRejected:
            raise
        except Exception as exc:
            logger.warning("queue_storage_error error=%s", type(exc).__name__)
            raise ApiError(503, "rag_unavailable", "Request storage is unavailable") from None

    async def require_token(
        credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    ) -> None:
        if credentials is None or not secrets.compare_digest(
            credentials.credentials.encode(), expected_token.encode()
        ):
            raise ApiError(401, "unauthorized", "Invalid or missing API token")

    from api.documents import document_router

    app.include_router(
        document_router(document_service, ApiError), dependencies=[Depends(require_token)]
    )

    @app.post("/requests", status_code=202, dependencies=[Depends(require_token)])
    async def submit(request: AskRequest):
        try:
            request_id = await queue_call(queue.submit, request)
        except QueueRejected as exc:
            raise ApiError(
                409 if exc.code == "conflict" else 429,
                exc.code,
                "Previous request is busy"
                if exc.code == "conflict"
                else "Request queue is full; try again later",
            ) from None
        ensure_runner()
        return {"request_id": request_id, "state": "queued"}

    @app.get("/requests/{request_id}", dependencies=[Depends(require_token)])
    async def request_status(request_id: uuid.UUID):
        result = await queue_call(queue.get, request_id)
        if result is None:
            raise ApiError(404, "not_found", "Request not found")
        return result

    @app.delete("/requests/{request_id}", status_code=204, dependencies=[Depends(require_token)])
    async def acknowledge(request_id: uuid.UUID):
        await queue_call(queue.acknowledge, request_id)
        return Response(status_code=204)

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
        accepted = await submit(request)
        request_id = accepted["request_id"]
        try:
            while True:
                job = await queue_call(queue.get, request_id)
                if job["state"] == "done":
                    response = AskResponse.model_validate(job["result"])
                    logger.info(
                        "ask: user_id=%s status=%s sources=%d",
                        request.user_id,
                        response.status,
                        len(response.sources),
                    )
                    return response
                if job["state"] == "failed":
                    code = job["error"]
                    raise ApiError(
                        500 if code == "internal_error" else 503, code, "RAG engine failed"
                    )
                await asyncio.sleep(0.02)
        finally:
            await queue_call(queue.acknowledge, request_id)

    return app
