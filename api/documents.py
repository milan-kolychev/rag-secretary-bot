"""Authenticated document management; extraction/indexing belongs to the worker."""

import logging
import uuid
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, File, Form, UploadFile
from fastapi.concurrency import run_in_threadpool

from worker.document_loader import MAX_DOCUMENT_BYTES


def document_router(service_factory, api_error):
    router = APIRouter(tags=["documents"])

    async def call_service(method, *args):
        def call():
            return getattr(service_factory(), method)(*args)

        try:
            return await run_in_threadpool(call)
        except (ValueError, api_error):
            raise
        except Exception as exc:
            logging.getLogger(__name__).warning(
                "document_operation_failed error=%s", type(exc).__name__
            )
            raise api_error(503, "rag_unavailable", "Document service is unavailable") from None

    @router.post("/documents", status_code=201)
    async def upload(
        file: Annotated[UploadFile, File()],
        title: Annotated[str, Form(min_length=1, max_length=300)],
        doc_id: Annotated[uuid.UUID | None, Form()] = None,
    ):
        filename = Path((file.filename or "").replace("\\", "/")).name
        if len(filename) > 300:
            raise api_error(422, "validation_error", "Filename exceeds 300 characters")
        if Path(filename).suffix.lower() not in {".txt", ".pdf", ".docx"}:
            raise api_error(422, "validation_error", "Only TXT, PDF and DOCX are supported")
        content = await file.read(MAX_DOCUMENT_BYTES + 1)
        await file.close()
        if len(content) > MAX_DOCUMENT_BYTES:
            raise api_error(413, "too_large", "Document exceeds 20 MB")
        if not content or not title.strip():
            raise api_error(422, "validation_error", "Empty document or title")
        return await call_service("upload", content, filename, title.strip(), doc_id)

    @router.get("/documents/{document_id}")
    async def document(document_id: uuid.UUID):
        result = await call_service("versions", document_id)
        if result is None:
            raise api_error(404, "not_found", "Document not found")
        return result

    @router.get("/documents/{document_id}/versions")
    async def versions(document_id: uuid.UUID):
        return await document(document_id)

    @router.post("/documents/{document_id}/versions/{version}/restore")
    async def restore(document_id: uuid.UUID, version: int):
        try:
            return await call_service("restore", document_id, version)
        except ValueError:
            raise api_error(404, "not_found", "Indexed version not found") from None

    @router.post("/documents/{document_id}/versions/{version}/retry")
    async def retry(document_id: uuid.UUID, version: int):
        try:
            return await call_service("retry", document_id, version)
        except ValueError:
            raise api_error(404, "not_found", "Document version not found") from None

    return router
