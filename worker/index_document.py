"""Versioned CLI ingestion; --doc-id explicitly identifies updates."""

import argparse
import uuid
from pathlib import Path

from core.db import Database
from worker.config import WorkerConfig
from worker.documents import DocumentService
from worker.embedder import BgeM3Embedder
from worker.store import DenseStore


def index_file(path: Path, doc_id=None, replace=False):
    if replace:
        raise ValueError("--replace is unsafe and removed; use --doc-id to create a new version")
    cfg = WorkerConfig()
    if not cfg.database_url:
        raise ValueError("DATABASE_URL is required; run alembic upgrade head first")
    from transformers import AutoTokenizer

    db = Database(cfg.database_url)
    service = DocumentService(
        db,
        DenseStore(cfg.qdrant_url, cfg.qdrant_collection, db),
        BgeM3Embedder(cfg.embed_device),
        AutoTokenizer.from_pretrained("BAAI/bge-m3"),
    )
    if path.stat().st_size > 20 * 1024 * 1024:
        raise ValueError("Document exceeds 20 MB")
    result = service.upload(path.read_bytes(), path.name, path.stem, doc_id)
    print(f"doc_id={result['document_id']} version={result['version']} status={result['status']}")
    if result["status"] != "indexed":
        raise RuntimeError("Indexing failed; previous version remains active")


def main():
    parser = argparse.ArgumentParser(description="Versioned faculty document ingestion")
    parser.add_argument("--file", type=Path, required=True)
    parser.add_argument("--doc-id", type=uuid.UUID)
    parser.add_argument("--replace", action="store_true", help="Removed; use --doc-id")
    args = parser.parse_args()
    index_file(args.file, args.doc_id, args.replace)


if __name__ == "__main__":
    main()
