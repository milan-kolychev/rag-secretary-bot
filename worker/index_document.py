"""Manual indexing of REAL documents into Qdrant for the existing RAG /ask.

Usage: uv run python -m worker.index_document --file "documents/rules.pdf"

This is a CLI ingestion path, not yet the future POST /documents + PostgreSQL job queue.
"""
from __future__ import annotations

import argparse
import hashlib
import uuid
from pathlib import Path

from qdrant_client import QdrantClient, models

from worker.chunking import chunk_document
from worker.config import WorkerConfig
from worker.document_loader import read_document
from worker.embedder import BgeM3Embedder

VECTOR_DIMENSION = 1024


def index_file(path: Path, replace: bool = False) -> None:
    cfg = WorkerConfig()
    path = path.expanduser().resolve()
    source = str(path)
    print(f"Reading: {path.name}", flush=True)
    parts = read_document(path)
    if not any(part.text.strip() for part in parts):
        raise ValueError("Document has no extractable text. Scanned PDFs require OCR.")

    # Read-only Qdrant operations happen before heavy model startup.
    client = QdrantClient(url=cfg.qdrant_url, timeout=30)
    exists = client.collection_exists(cfg.qdrant_collection)
    if exists:
        info = client.get_collection(cfg.qdrant_collection)
        vectors = info.config.params.vectors
        if not isinstance(vectors, dict) or "dense" not in vectors:
            raise ValueError("Qdrant collection must have a named vector 'dense'.")
        if vectors["dense"].size != VECTOR_DIMENSION:
            raise ValueError("Qdrant collection 'dense' must have dimension 1024.")

    try:
        stable_name = str(path.relative_to(Path.cwd().resolve())).replace("\\", "/")
    except ValueError:
        stable_name = source
    doc_id = uuid.uuid5(uuid.NAMESPACE_URL, f"fpi-rag-real-document/{stable_name}")
    filter_doc = models.Filter(
        must=[models.FieldCondition(key="doc_id", match=models.MatchValue(value=str(doc_id)))]
    )
    if exists:
        existing, _ = client.scroll(
            collection_name=cfg.qdrant_collection,
            scroll_filter=filter_doc,
            limit=1,
            with_payload=False,
            with_vectors=False,
        )
        if existing and not replace:
            raise ValueError("This document is already indexed. Pass --replace to reindex it.")

    print("Loading BGE-M3 tokenizer...", flush=True)
    from transformers import AutoTokenizer

    tokenizer = AutoTokenizer.from_pretrained("BAAI/bge-m3")
    chunks = chunk_document(parts, tokenizer, size=500, overlap=60)
    if not chunks:
        raise ValueError("No nonempty chunks produced")
    print(f"Chunks: {len(chunks)}; preparing embeddings on {cfg.embed_device}...", flush=True)

    embedder = BgeM3Embedder(cfg.embed_device)
    points = []
    checksum = hashlib.sha256(path.read_bytes()).hexdigest()
    version = int(checksum[:12], 16)
    for first in range(0, len(chunks), 4):
        batch = chunks[first : first + 4]
        vectors = embedder.encode([item.text for item in batch])
        for offset, (chunk, vector) in enumerate(zip(batch, vectors, strict=True)):
            idx = first + offset
            point_id = uuid.uuid5(doc_id, f"{version}:{idx}")
            points.append(
                models.PointStruct(
                    id=str(point_id),
                    vector={"dense": vector},
                    payload={
                        "doc_id": str(doc_id),
                        "title": path.stem,
                        "version": version,
                        "section": chunk.section,
                        "page": chunk.page,
                        "chunk_index": idx,
                        "text": chunk.text,
                        "source": stable_name,
                        "is_active": True,
                    },
                )
            )
        print(f"Embedded {min(first + 4, len(chunks))}/{len(chunks)}", flush=True)

    if not exists:
        client.create_collection(
            collection_name=cfg.qdrant_collection,
            vectors_config={
                "dense": models.VectorParams(
                    size=VECTOR_DIMENSION, distance=models.Distance.COSINE
                )
            },
        )
    if replace:
        # Simple manual replacement. Not atomic across Qdrant and PostgreSQL.
        client.delete(
            collection_name=cfg.qdrant_collection,
            points_selector=models.FilterSelector(filter=filter_doc),
            wait=True,
        )
    for first in range(0, len(points), 32):
        client.upsert(
            collection_name=cfg.qdrant_collection,
            points=points[first : first + 32],
            wait=True,
        )
    print(
        f"Indexed {len(points)} chunks into {cfg.qdrant_collection} | "
        f"doc_id={doc_id}",
        flush=True,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Index real faculty documents in Qdrant")
    parser.add_argument("--file", type=Path, required=True, help="Path to .pdf/.docx/.txt")
    parser.add_argument("--replace", action="store_true", help="Reindex an existing file")
    args = parser.parse_args()
    index_file(args.file, replace=args.replace)


if __name__ == "__main__":
    main()
