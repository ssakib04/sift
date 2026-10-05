"""Native text extraction for uploaded PDF and DOCX curricula vitae."""

import hashlib
import io
from pathlib import Path
from typing import Literal

import fitz
from docx import Document

_LOW_DENSITY_CHARACTER_THRESHOLD = 50
ExtractionStatus = Literal["completed", "low_density"]


def calculate_sha256(file_bytes: bytes) -> str:
    """Return the hexadecimal SHA-256 digest of the raw file bytes."""
    return hashlib.sha256(file_bytes).hexdigest()


def extract_text_from_pdf(file_bytes: bytes) -> str:
    """Extract plain text from a digital PDF."""
    if not file_bytes:
        raise ValueError("CV_PARSE_FAILED: PDF bytes are empty")

    try:
        document = fitz.open(stream=file_bytes, filetype="pdf")
    except Exception as exc:
        raise ValueError(f"CV_PARSE_FAILED: unable to open PDF ({exc})") from exc

    try:
        if document.needs_pass:
            raise ValueError("CV_PARSE_FAILED: PDF is encrypted")
        page_text = [page.get_text("text") for page in document]
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError(f"CV_PARSE_FAILED: unable to read PDF ({exc})") from exc
    finally:
        document.close()

    return _clean_text("\n".join(page_text))


def extract_text_from_docx(file_bytes: bytes) -> str:
    """Extract paragraph text from a DOCX document."""
    if not file_bytes:
        raise ValueError("CV_PARSE_FAILED: DOCX bytes are empty")

    try:
        document = Document(io.BytesIO(file_bytes))
        paragraphs = [paragraph.text for paragraph in document.paragraphs]
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError(f"CV_PARSE_FAILED: unable to read DOCX ({exc})") from exc

    return _clean_text("\n".join(paragraphs))


def parse_cv_bytes(file_bytes: bytes, filename: str) -> dict[str, str | int]:
    """Parse a CV by extension and report text density for later OCR routing."""
    extension = Path(filename).suffix.lower()
    if extension == ".pdf":
        raw_text = extract_text_from_pdf(file_bytes)
    elif extension == ".docx":
        raw_text = extract_text_from_docx(file_bytes)
    else:
        label = extension or filename or "unknown"
        raise ValueError(f"CV_PARSE_FAILED: unsupported file extension '{label}'")

    character_count = len(raw_text.strip())
    extraction_status: ExtractionStatus = (
        "low_density"
        if character_count < _LOW_DENSITY_CHARACTER_THRESHOLD
        else "completed"
    )
    return {
        "raw_text": raw_text,
        "character_count": character_count,
        "extraction_status": extraction_status,
    }


def _clean_text(text: str) -> str:
    """Normalize newlines and collapse repeated blank lines."""
    normalized = text.replace("\x00", "").replace("\r\n", "\n").replace("\r", "\n")
    lines = [line.strip() for line in normalized.split("\n")]
    collapsed: list[str] = []
    previous_blank = False
    for line in lines:
        if line == "":
            if not previous_blank:
                collapsed.append("")
            previous_blank = True
            continue
        collapsed.append(line)
        previous_blank = False
    return "\n".join(collapsed).strip()
