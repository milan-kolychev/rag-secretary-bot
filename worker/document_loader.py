"""Extract text from real TXT, DOCX and text-based PDF files for indexing."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

MAX_DOCUMENT_BYTES = 20 * 1024 * 1024


@dataclass(frozen=True)
class DocumentPart:
    text: str
    section: str | None = None
    page: int | None = None


def read_document(path: Path) -> list[DocumentPart]:
    if not path.is_file():
        raise FileNotFoundError(f"Document not found: {path}")
    if path.stat().st_size > MAX_DOCUMENT_BYTES:
        raise ValueError("Document is larger than the 20 MB limit")

    suffix = path.suffix.lower()
    if suffix == ".txt":
        # Support UTF-8 TXT files, including those saved with a BOM.
        return [DocumentPart(text=path.read_text(encoding="utf-8-sig"))]
    if suffix == ".docx":
        from zipfile import ZipFile

        with ZipFile(path) as archive:
            members = archive.infolist()
            if len(members) > 2000 or sum(item.file_size for item in members) > 100 * 1024 * 1024:
                raise ValueError("DOCX expanded archive exceeds safe processing limits")
        from docx import Document

        doc = Document(path)
        parts: list[DocumentPart] = []
        section: str | None = None
        buffer: list[str] = []
        for paragraph in doc.paragraphs:
            text = paragraph.text.strip()
            if not text:
                continue
            if paragraph.style is not None and paragraph.style.name.startswith("Heading"):
                if buffer:
                    parts.append(DocumentPart("\n".join(buffer), section))
                    buffer = []
                section = text
            else:
                buffer.append(text)
        if buffer:
            parts.append(DocumentPart("\n".join(buffer), section))
        return parts
    if suffix == ".pdf":
        import fitz  # provided by PyMuPDF

        parts = []
        with fitz.open(path) as document:
            for page_number, page in enumerate(document, start=1):
                text = page.get_text("text").strip()
                if text:
                    parts.append(DocumentPart(text=text, page=page_number))
        return parts
    raise ValueError("Only .txt, .docx and .pdf are supported")
