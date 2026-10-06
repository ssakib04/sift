from io import BytesIO

import pytest
from docx import Document

from app.services.ocr_service import EmptyCvError, InvalidCvError, parse_cv, validate_cv


def _docx(text: str) -> bytes:
    buffer = BytesIO()
    document = Document()
    document.add_paragraph(text)
    document.save(buffer)
    return buffer.getvalue()


def test_docx_uses_native_extraction() -> None:
    text = "Ada Lovelace built production FastAPI services and shipped a policy-compliant hiring platform."
    parsed = parse_cv("ada.docx", _docx(text))
    assert parsed.parse_method == "native"
    assert "FastAPI" in parsed.text
    assert parsed.parse_confidence > 0.9


def test_invalid_extension_is_rejected() -> None:
    with pytest.raises(InvalidCvError):
        validate_cv("notes.txt", b"hello")


def test_low_density_pdf_uses_ocr(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.services.ocr_service._tier1", lambda suffix, data: "short")
    monkeypatch.setattr("app.services.ocr_service._tier2", lambda data: "still short")
    monkeypatch.setattr(
        "app.services.ocr_service._tier3",
        lambda data: "Scanned CV for a production engineer with FastAPI and Docker experience across several teams.",
    )
    parsed = parse_cv("scan.pdf", b"%PDF-1.4\n" + b"0" * 32)
    assert parsed.parse_method == "ocr_fallback"
    assert "Fallback OCR executed" in parsed.warnings


def test_empty_pdf_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.services.ocr_service._tier1", lambda suffix, data: "")
    monkeypatch.setattr("app.services.ocr_service._tier2", lambda data: "")
    monkeypatch.setattr("app.services.ocr_service._tier3", lambda data: "")
    with pytest.raises(EmptyCvError):
        parse_cv("blank.pdf", b"%PDF-1.4\n" + b"0" * 32)
