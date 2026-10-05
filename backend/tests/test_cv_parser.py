"""Unit tests for native PDF and DOCX CV parsing."""

import hashlib
import io

import fitz
import pytest
from docx import Document

from app.services.cv_parser import (
    calculate_sha256,
    extract_text_from_docx,
    extract_text_from_pdf,
    parse_cv_bytes,
)

_LONG_TEXT = (
    "Experienced Python engineer who built FastAPI services and production RAG pipelines."
)


def _pdf_bytes(text: str, *, password: str | None = None) -> bytes:
    document = fitz.open()
    page = document.new_page()
    page.insert_textbox(fitz.Rect(72, 72, 540, 720), text, fontsize=11)
    buffer = io.BytesIO()
    if password is None:
        document.save(buffer)
    else:
        document.save(
            buffer,
            encryption=fitz.PDF_ENCRYPT_AES_256,
            user_pw=password,
            owner_pw=password,
        )
    document.close()
    return buffer.getvalue()


def _docx_bytes(paragraphs: list[str]) -> bytes:
    document = Document()
    for paragraph in paragraphs:
        document.add_paragraph(paragraph)
    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()


def test_calculate_sha256_returns_hex_digest() -> None:
    """SHA-256 is computed from the raw bytes."""
    payload = b"candidate-cv"
    assert calculate_sha256(payload) == hashlib.sha256(payload).hexdigest()


def test_extract_text_from_pdf_returns_page_text() -> None:
    """PyMuPDF extraction returns the text written into the PDF."""
    extracted = extract_text_from_pdf(_pdf_bytes(_LONG_TEXT))
    assert _LONG_TEXT in extracted


def test_extract_text_from_docx_returns_paragraphs() -> None:
    """python-docx extraction returns each paragraph."""
    extracted = extract_text_from_docx(_docx_bytes(["Alpha role", "Beta role"]))
    assert "Alpha role" in extracted
    assert "Beta role" in extracted


def test_parse_pdf_marks_sufficient_text_completed() -> None:
    """A PDF with at least 50 characters is marked completed."""
    parsed = parse_cv_bytes(_pdf_bytes(_LONG_TEXT), "candidate.PDF")
    assert parsed["extraction_status"] == "completed"
    assert parsed["character_count"] == len(str(parsed["raw_text"]).strip())
    assert int(parsed["character_count"]) >= 50
    assert _LONG_TEXT in str(parsed["raw_text"])


def test_parse_pdf_marks_short_text_low_density() -> None:
    """Fewer than 50 characters flags the CV for later OCR."""
    short_text = "a" * 49
    parsed = parse_cv_bytes(_pdf_bytes(short_text), "scan.pdf")
    assert parsed["extraction_status"] == "low_density"
    assert parsed["character_count"] == 49


def test_parse_docx_marks_sufficient_text_completed() -> None:
    """A DOCX with at least 50 characters is marked completed."""
    parsed = parse_cv_bytes(_docx_bytes([_LONG_TEXT]), "candidate.docx")
    assert parsed["extraction_status"] == "completed"
    assert _LONG_TEXT in str(parsed["raw_text"])
    assert parsed["character_count"] == len(str(parsed["raw_text"]).strip())


def test_parse_cv_bytes_rejects_corrupt_pdf() -> None:
    """Corrupt PDF bytes raise a CV_PARSE_FAILED error."""
    with pytest.raises(ValueError, match=r"^CV_PARSE_FAILED:"):
        parse_cv_bytes(b"not-a-pdf", "cv.pdf")


def test_parse_cv_bytes_rejects_corrupt_docx() -> None:
    """Corrupt DOCX bytes raise a CV_PARSE_FAILED error."""
    with pytest.raises(ValueError, match=r"^CV_PARSE_FAILED:"):
        parse_cv_bytes(b"not-a-docx", "cv.docx")


def test_parse_cv_bytes_rejects_encrypted_pdf() -> None:
    """Password-protected PDFs raise a CV_PARSE_FAILED error."""
    encrypted = _pdf_bytes(_LONG_TEXT, password="secret")
    with pytest.raises(ValueError, match=r"^CV_PARSE_FAILED: PDF is encrypted"):
        parse_cv_bytes(encrypted, "locked.pdf")


def test_parse_cv_bytes_rejects_unsupported_extension() -> None:
    """Extensions other than .pdf and .docx are rejected."""
    with pytest.raises(ValueError, match=r"^CV_PARSE_FAILED: unsupported file extension"):
        parse_cv_bytes(b"plain text", "notes.txt")
