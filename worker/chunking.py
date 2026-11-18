"""Tokenizer-aware page/section-preserving chunks for BGE-M3."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from worker.document_loader import DocumentPart


class Tokenizer(Protocol):
    def encode(self, text: str, add_special_tokens: bool = False) -> list[int]: ...

    def decode(self, ids: list[int], skip_special_tokens: bool = True) -> str: ...


@dataclass(frozen=True)
class TextChunk:
    text: str
    section: str | None
    page: int | None


def chunk_document(
    parts: list[DocumentPart],
    tokenizer: Tokenizer,
    size: int = 500,
    overlap: int = 60,
) -> list[TextChunk]:
    if size <= 0 or overlap < 0 or overlap >= size:
        raise ValueError("Expected size > overlap >= 0")

    result = []
    step = size - overlap
    for part in parts:
        token_ids = tokenizer.encode(part.text, add_special_tokens=False)
        for start in range(0, len(token_ids), step):
            piece = token_ids[start : start + size]
            text = tokenizer.decode(piece, skip_special_tokens=True).strip()
            if text:
                result.append(TextChunk(text, part.section, part.page))
            if start + size >= len(token_ids):
                break
    return result
