"""Durable document versions. PostgreSQL pointer is the visibility boundary."""

import hashlib
import logging
import tempfile
import uuid
from pathlib import Path

from qdrant_client import models
from sqlalchemy import func, select

from core.db import Document, DocumentVersion, now
from worker.chunking import chunk_document
from worker.document_loader import read_document

logger = logging.getLogger(__name__)


def version_filter(doc_id, version=None):
    conditions = [models.FieldCondition(key="doc_id", match=models.MatchValue(value=doc_id))]
    if version is not None:
        conditions.append(
            models.FieldCondition(key="version", match=models.MatchValue(value=version))
        )
    return models.Filter(must=conditions)


def version_body(row, active):
    return {
        "document_id": row.doc_id,
        "title": row.title,
        "filename": row.filename,
        "version": row.version,
        "status": row.status,
        "chunks": row.chunks,
        "uploaded_at": row.uploaded_at,
        "indexed_at": row.indexed_at,
        "error": row.error,
        "is_active": active == row.version,
    }


class DocumentService:
    def __init__(self, db, store, embedder, tokenizer):
        self.db, self.store, self.embedder, self.tokenizer = db, store, embedder, tokenizer

    def upload(self, content, filename, title, doc_id=None):
        doc_id = str(doc_id or uuid.uuid4())
        checksum = hashlib.sha256(content).hexdigest()
        # Same lock order as inference: execution, then metadata visibility.
        with self.db.lock(71002), self.db.lock(71003):
            with self.db.sessions.begin() as session:
                doc = session.get(Document, doc_id)
                if doc is None:
                    if doc_id and session.scalar(
                        select(DocumentVersion).where(DocumentVersion.doc_id == doc_id)
                    ):
                        raise ValueError("Invalid document metadata")
                    doc = Document(id=doc_id)
                    session.add(doc)
                    session.flush()
                row = session.scalar(
                    select(DocumentVersion).where(
                        DocumentVersion.doc_id == doc_id, DocumentVersion.checksum == checksum
                    )
                )
                if row and row.status == "indexed":
                    return version_body(row, doc.active_version)
                if row is None:
                    latest = (
                        session.scalar(
                            select(func.max(DocumentVersion.version)).where(
                                DocumentVersion.doc_id == doc_id
                            )
                        )
                        or 0
                    )
                    row = DocumentVersion(
                        doc_id=doc_id,
                        version=latest + 1,
                        checksum=checksum,
                        content=content,
                        filename=filename,
                        title=title,
                    )
                    session.add(row)
                row.status, row.error = "indexing", None
                session.flush()
                row_id, version = row.id, row.version
            try:
                chunks = self._index(doc_id, version, content, filename, title)
                # All acknowledged chunks are verified before changing the SQL pointer.
                with self.db.sessions.begin() as session:
                    row = session.get(DocumentVersion, row_id)
                    row.status, row.chunks, row.indexed_at = "indexed", chunks, now()
                    session.get(Document, doc_id).active_version = version
                self._reconcile(doc_id, version)
            except Exception as exc:
                logger.warning(
                    "index_failed doc_id=%s version=%d error=%s",
                    doc_id,
                    version,
                    type(exc).__name__,
                )
                with self.db.sessions.begin() as session:
                    row = session.get(DocumentVersion, row_id)
                    # A cleanup failure after activation is not an indexing failure.
                    if session.get(Document, doc_id).active_version != version:
                        row.status, row.error = "failed", type(exc).__name__
            with self.db.sessions() as session:
                return version_body(
                    session.get(DocumentVersion, row_id),
                    session.get(Document, doc_id).active_version,
                )

    def _index(self, doc_id, version, content, filename, title):
        with tempfile.TemporaryDirectory(prefix="rag-document-") as directory:
            path = Path(directory) / ("source" + Path(filename).suffix.lower())
            path.write_bytes(content)
            chunks = chunk_document(read_document(path), self.tokenizer, size=500, overlap=60)
        if not chunks:
            raise ValueError("No extractable document text")
        client, collection = self.store.client, self.store.collection
        if not client.collection_exists(collection):
            client.create_collection(
                collection,
                vectors_config={
                    "dense": models.VectorParams(size=1024, distance=models.Distance.COSINE)
                },
            )
        for start in range(0, len(chunks), 4):
            batch = chunks[start : start + 4]
            vectors = self.embedder.encode([chunk.text for chunk in batch])
            points = [
                models.PointStruct(
                    id=str(uuid.uuid5(uuid.UUID(doc_id), f"{version}:{start + offset}")),
                    vector={"dense": vector},
                    payload={
                        "doc_id": doc_id,
                        "version": version,
                        "title": title,
                        "section": chunk.section,
                        "page": chunk.page,
                        "text": chunk.text,
                        "source": filename,
                        "chunk_index": start + offset,
                        "is_active": True,
                    },
                )
                for offset, (chunk, vector) in enumerate(zip(batch, vectors, strict=True))
            ]
            client.upsert(collection, points, wait=True)
        count = client.count(collection, count_filter=version_filter(doc_id, version), exact=True)
        if count.count != len(chunks):
            raise RuntimeError("Indexed chunk count mismatch")
        return len(chunks)

    def _reconcile(self, doc_id, version):
        # SQL filtering remains authoritative even if a process dies between these writes.
        client, collection = self.store.client, self.store.collection
        old = version_filter(doc_id)
        old.must_not = [
            models.FieldCondition(key="version", match=models.MatchValue(value=version))
        ]
        client.set_payload(collection, {"is_active": False}, points=old, wait=True)
        client.set_payload(
            collection, {"is_active": True}, points=version_filter(doc_id, version), wait=True
        )

    def versions(self, doc_id):
        with self.db.sessions() as session:
            doc = session.get(Document, str(doc_id))
            if not doc:
                return None
            rows = session.scalars(
                select(DocumentVersion)
                .where(DocumentVersion.doc_id == str(doc_id))
                .order_by(DocumentVersion.version)
            )
            return {
                "document_id": doc.id,
                "active_version": doc.active_version,
                "items": [version_body(row, doc.active_version) for row in rows],
            }

    def retry(self, doc_id, version):
        with self.db.sessions() as session:
            row = session.scalar(
                select(DocumentVersion).where(
                    DocumentVersion.doc_id == str(doc_id), DocumentVersion.version == version
                )
            )
            if row is None:
                raise ValueError("Document version not found")
            content, filename, title = row.content, row.filename, row.title
        return self.upload(content, filename, title, doc_id)

    def restore(self, doc_id, version):
        doc_id = str(doc_id)
        with self.db.lock(71002), self.db.lock(71003):
            with self.db.sessions() as session:
                doc = session.get(Document, doc_id)
                if doc and doc.active_version == version:
                    return self.versions(doc_id)
                row = session.scalar(
                    select(DocumentVersion).where(
                        DocumentVersion.doc_id == doc_id,
                        DocumentVersion.version == version,
                        DocumentVersion.status == "indexed",
                    )
                )
                if not row:
                    raise ValueError("Indexed version not found")
                # Rebuild from durable original; repair partially lost Qdrant records too.
                self._index(doc_id, version, row.content, row.filename, row.title)
            with self.db.sessions.begin() as session:
                session.get(Document, doc_id).active_version = version
            try:
                self._reconcile(doc_id, version)
            except Exception as exc:
                logger.warning("payload_reconcile_failed error=%s", type(exc).__name__)
            return self.versions(doc_id)
