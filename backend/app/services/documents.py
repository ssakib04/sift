import re
from io import BytesIO
from pathlib import Path

_CHUNK_SIZE = 800
_CHUNK_OVERLAP = 100


class UnsupportedDocumentError(ValueError):
    """The upload is not a PDF or DOCX file."""


class EmptyDocumentError(ValueError):
    """The file did not contain extractable text."""


def extract_text(filename: str, data: bytes) -> str:
    suffix = Path(filename).suffix.lower()
    if suffix == ".pdf":
        text = _extract_pdf(data)
    elif suffix == ".docx":
        text = _extract_docx(data)
    else:
        raise UnsupportedDocumentError("Upload a PDF or DOCX policy document.")
    collapsed = re.sub(r"\s+", " ", text).strip()
    if not collapsed:
        raise EmptyDocumentError("The policy document did not contain extractable text.")
    return collapsed


def chunk_text(text: str, size: int = _CHUNK_SIZE, overlap: int = _CHUNK_OVERLAP) -> list[str]:
    if size <= overlap:
        raise ValueError("chunk size must be larger than overlap")
    if len(text) <= size:
        return [text]
    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = min(start + size, len(text))
        chunks.append(text[start:end].strip())
        if end == len(text):
            break
        start = end - overlap
    return [chunk for chunk in chunks if chunk]


def _extract_pdf(data: bytes) -> str:
    from pypdf import PdfReader

    reader = PdfReader(BytesIO(data))
    return "\n".join(page.extract_text() or "" for page in reader.pages)


def _extract_docx(data: bytes) -> str:
    from docx import Document

    document = Document(BytesIO(data))
    return "\n".join(paragraph.text for paragraph in document.paragraphs)
