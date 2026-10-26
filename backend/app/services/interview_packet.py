import uuid
from dataclasses import dataclass

import pymupdf
from jinja2 import Environment, select_autoescape
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.session_tokens import SessionClaims
from app.models.candidate import Candidate, CandidateParseResult, InterviewSession, TranscriptSegment
from app.models.job import JobChecklistQuery, JobVersion
from app.services.interview_rules import InterviewError, assert_recruiter

_FONT = "times-roman"
_BOLD = "times-bold"
_BODY = 11
_HEADING = 14
_TITLE = 18
_LEADING = 15
_MARGIN = 54

_REPORT = Environment(autoescape=select_autoescape(["html"]), trim_blocks=True, lstrip_blocks=True).from_string(
    """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>{{ packet.full_name }} interview packet</title>
  <style>
    body { font-family: Georgia, serif; color: #1c1412; max-width: 800px; margin: 2rem auto; line-height: 1.5; }
    h1, h2 { font-weight: 600; }
    .muted { color: #5c534e; }
    pre { white-space: pre-wrap; font-family: Georgia, serif; }
    li { margin: 0.35rem 0; }
  </style>
</head>
<body>
  <p class="muted">Sift interview packet</p>
  <h1>{{ packet.full_name or "Unnamed" }}</h1>
  <p>{{ packet.job_title or "Role" }}</p>
  <h2>CV</h2>
  {% if packet.cv_text %}
  <pre>{{ packet.cv_text }}</pre>
  {% else %}
  <p class="muted">This CV has no parsed text yet.</p>
  {% endif %}
  <h2>Checklist questions</h2>
  {% if packet.questions %}
  <ol>
    {% for question in packet.questions %}<li>{{ question }}</li>{% endfor %}
  </ol>
  {% else %}
  <p class="muted">No checklist questions are stored for this role.</p>
  {% endif %}
  <h2>Transcript</h2>
  {% if packet.lines %}
  {% for line in packet.lines %}
  <p><strong>{{ speaker_label(line.speaker) }}.</strong> {{ line.text }}</p>
  {% endfor %}
  {% else %}
  <p class="muted">No transcript lines yet.</p>
  {% endif %}
</body>
</html>
"""
)


@dataclass(frozen=True)
class PacketLine:
    speaker: str
    text: str


@dataclass(frozen=True)
class InterviewPacket:
    full_name: str
    job_title: str
    cv_text: str
    questions: list[str]
    lines: list[PacketLine]


def speaker_label(speaker: str) -> str:
    if speaker == "candidate":
        return "Candidate"
    if speaker == "recruiter":
        return "Recruiter"
    cleaned = " ".join(speaker.split())
    return cleaned or "Speaker"


def render_packet_html(packet: InterviewPacket) -> str:
    return _REPORT.render(packet=packet, speaker_label=speaker_label)


def packet_filename(packet: InterviewPacket, suffix: str) -> str:
    stem = "".join(char if char.isalnum() else "-" for char in packet.full_name.lower())
    stem = "-".join(part for part in stem.split("-") if part) or "interview"
    return f"{stem}-interview.{suffix}"


def render_packet_pdf(packet: InterviewPacket) -> bytes:
    document = pymupdf.open()
    width, height = pymupdf.paper_size("a4")
    measure = width - (_MARGIN * 2)
    cursor: dict[str, object] = {"page": None, "y": _MARGIN}

    def blank() -> pymupdf.Page:
        page = document.new_page(width=width, height=height)
        cursor["page"] = page
        cursor["y"] = float(_MARGIN)
        return page

    def room(lines: int) -> pymupdf.Page:
        page = cursor["page"]
        y = float(cursor["y"])
        if not isinstance(page, pymupdf.Page) or y + (lines * _LEADING) > height - _MARGIN:
            return blank()
        return page

    def write(text: str, *, size: float = _BODY, font: str = _FONT, gap: float = 8) -> None:
        for line in _wrap(text, font, size, measure):
            page = room(1)
            y = float(cursor["y"])
            page.insert_text((_MARGIN, y + size), line, fontname=font, fontsize=size, color=(0.11, 0.08, 0.07))
            cursor["y"] = y + _LEADING
        cursor["y"] = float(cursor["y"]) + gap

    blank()
    write("Sift interview packet", gap=4)
    write(packet.full_name.strip() or "Unnamed", size=_TITLE, font=_BOLD, gap=2)
    write(packet.job_title.strip() or "Role", gap=14)
    write("CV", size=_HEADING, font=_BOLD, gap=6)
    write(packet.cv_text.strip() or "This CV has no parsed text yet.", gap=14)
    write("Checklist questions", size=_HEADING, font=_BOLD, gap=6)
    if packet.questions:
        for index, question in enumerate(packet.questions, start=1):
            write(f"{index}. {question}", gap=4)
    else:
        write("No checklist questions are stored for this role.")
    cursor["y"] = float(cursor["y"]) + 8
    write("Transcript", size=_HEADING, font=_BOLD, gap=6)
    if packet.lines:
        for line in packet.lines:
            write(f"{speaker_label(line.speaker)}. {line.text}", gap=6)
    else:
        write("No transcript lines yet.", gap=0)
    payload = document.tobytes()
    document.close()
    return payload


async def load_interview_packet(db: AsyncSession, claims: SessionClaims) -> InterviewPacket:
    assert_recruiter(claims.role)
    row = await db.scalar(
        select(InterviewSession)
        .where(InterviewSession.id == claims.session_id)
        .options(
            selectinload(InterviewSession.candidate).selectinload(Candidate.parse_result),
            selectinload(InterviewSession.candidate).selectinload(Candidate.version).selectinload(JobVersion.job),
            selectinload(InterviewSession.transcript_segments),
        )
    )
    if row is None or row.candidate is None or row.candidate.version is None or row.candidate.version.job is None:
        raise InterviewError("SESSION_NOT_FOUND", "This interview session is not available.", 404)
    candidate = row.candidate
    job = candidate.version.job
    if row.id != claims.session_id or candidate.id != claims.candidate_id or job.id != claims.job_id:
        raise InterviewError("INTERVIEW_FORBIDDEN", "This link does not match the interview.", 403)
    questions = await _questions(db, candidate.version.id)
    return InterviewPacket(
        full_name=candidate.full_name.strip(),
        job_title=job.title.strip(),
        cv_text=_cv_text(candidate.parse_result),
        questions=questions,
        lines=_lines(row.transcript_segments),
    )


def _cv_text(parse: CandidateParseResult | None) -> str:
    if parse is None or parse.status != "parsed":
        return ""
    return parse.raw_text.strip()


def _lines(segments: list[TranscriptSegment]) -> list[PacketLine]:
    ordered = sorted(segments, key=lambda segment: (segment.start_time, segment.created_at))
    return [PacketLine(speaker=segment.speaker, text=segment.text.strip()) for segment in ordered if segment.text.strip()]


async def _questions(db: AsyncSession, version_id: uuid.UUID) -> list[str]:
    result = await db.scalars(select(JobChecklistQuery).where(JobChecklistQuery.version_id == version_id))
    rows = list(result.all())
    rows.sort(key=lambda query: int(query.query_id[1:]) if query.query_id[1:].isdigit() else 0)
    return [query.question.strip() for query in rows if query.question.strip()]


def _wrap(text: str, font: str, size: float, width: float) -> list[str]:
    lines: list[str] = []
    for paragraph in text.replace("\r\n", "\n").split("\n"):
        words = paragraph.split()
        if not words:
            lines.append("")
            continue
        current = ""
        for word in words:
            for piece in _pieces(word, font, size, width):
                trial = piece if not current else f"{current} {piece}"
                if pymupdf.get_text_length(trial, fontname=font, fontsize=size) <= width:
                    current = trial
                    continue
                if current:
                    lines.append(current)
                current = piece
        if current:
            lines.append(current)
    return lines or [""]


def _pieces(word: str, font: str, size: float, width: float) -> list[str]:
    if pymupdf.get_text_length(word, fontname=font, fontsize=size) <= width:
        return [word]
    pieces: list[str] = []
    chunk = ""
    for char in word:
        trial = f"{chunk}{char}"
        if chunk and pymupdf.get_text_length(trial, fontname=font, fontsize=size) > width:
            pieces.append(chunk)
            chunk = char
        else:
            chunk = trial
    if chunk:
        pieces.append(chunk)
    return pieces or [word]
