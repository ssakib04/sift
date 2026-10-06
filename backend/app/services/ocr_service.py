import re
from io import BytesIO
from pathlib import Path

from pydantic import BaseModel, Field

_MIN_TEXT = 80
_MAX_BYTES = 8 * 1024 * 1024


class InvalidCvError(ValueError):
    """The attachment is not a PDF or DOCX CV within the size limit."""


class EmptyCvError(ValueError):
    """Native, layout, and OCR extraction all returned too little text."""


class CvParseResult(BaseModel):
    parse_method: str
    parse_confidence: float = Field(ge=0, le=1)
    warnings: list[str]
    text: str


def validate_cv(filename: str, data: bytes) -> str:
    if len(data) > _MAX_BYTES:
        raise InvalidCvError("CV exceeds 8 MB.")
    suffix = Path(filename).suffix.lower()
    if suffix == ".pdf" and data.startswith(b"%PDF"):
        return "application/pdf"
    if suffix == ".docx" and data.startswith(b"PK"):
        return "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    raise InvalidCvError("A CV must be a PDF or DOCX file.")


def parse_cv(filename: str, data: bytes) -> CvParseResult:
    """Extract CV text with native reading, then spatial order, then OCR."""
    validate_cv(filename, data)
    suffix = Path(filename).suffix.lower()
    warnings: list[str] = []
    native = _normalize(_tier1(suffix, data))
    if _dense(native):
        return CvParseResult(parse_method="native", parse_confidence=0.92, warnings=warnings, text=native)
    warnings.append("Low text density after native extraction")
    if suffix == ".pdf":
        layout = _normalize(_tier2(data))
        if _dense(layout):
            warnings.append("Spatial block ordering used")
            return CvParseResult(parse_method="layout", parse_confidence=0.78, warnings=warnings, text=layout)
        warnings.append("Low text density after spatial extraction")
        ocr_text = _normalize(_tier3(data))
        if _dense(ocr_text):
            warnings.extend(["Possible scanned document", "Fallback OCR executed"])
            return CvParseResult(
                parse_method="ocr_fallback",
                parse_confidence=0.6,
                warnings=warnings,
                text=ocr_text,
            )
    raise EmptyCvError("The CV did not contain extractable text.")


def _dense(text: str) -> bool:
    return len(text) >= _MIN_TEXT


def _normalize(text: str) -> str:
    return re.sub(r"[ \t]+", " ", re.sub(r"\n{3,}", "\n\n", text)).strip()


def _tier1(suffix: str, data: bytes) -> str:
    if suffix == ".pdf":
        import pdfplumber

        with pdfplumber.open(BytesIO(data)) as document:
            return "\n".join(page.extract_text() or "" for page in document.pages)
    from docx import Document

    document = Document(BytesIO(data))
    return "\n".join(paragraph.text for paragraph in document.paragraphs)


def _tier2(data: bytes) -> str:
    import fitz

    document = fitz.open(stream=data, filetype="pdf")
    blocks: list[tuple[int, float, float, str]] = []
    for page in document:
        for block in page.get_text("blocks"):
            if len(block) < 5:
                continue
            x0, y0, _x1, _y1, text = block[:5]
            if isinstance(text, str) and text.strip():
                blocks.append((page.number, float(y0), float(x0), text))
    blocks.sort()
    return "\n".join(text for _page, _y, _x, text in blocks)


def _tier3(data: bytes) -> str:
    import fitz
    from PIL import Image

    try:
        import pytesseract
    except ImportError:
        return ""
    document = fitz.open(stream=data, filetype="pdf")
    pages: list[str] = []
    for page in document:
        pixmap = page.get_pixmap(dpi=200)
        image = Image.open(BytesIO(pixmap.tobytes("png")))
        try:
            pages.append(pytesseract.image_to_string(image))
        except pytesseract.TesseractNotFoundError:
            return ""
    return "\n".join(pages)
