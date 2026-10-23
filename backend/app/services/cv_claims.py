"""Cross-check CV claims against the interview and phrase flags as follow-up questions."""

import re
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import desc, nulls_last, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.llm_fallback import FallbackLLMManager, LLMFallbackExhaustedError
from app.graphs.job_creation_graph import JobGraphError, parse_json_object
from app.models.candidate import (
    Candidate,
    CandidateParseResult,
    ClaimFlag,
    ClaimVerification,
    CvClaim,
    InterviewSession,
    TranscriptSegment,
)
from app.schemas.claims import ClaimFlagRead, ClaimVerificationRead
from app.services.cv_facts import (
    coerce_work_history,
    computed_experience_years,
    find_skill_span,
    resolve_evidence,
    tenure_quote,
)

_TOKEN = re.compile(r"[A-Za-z0-9+#]+(?:[./-][A-Za-z0-9+#]+)*")
_YEARS = re.compile(r"\b(\d{1,2}(?:\.\d+)?)\s*\+?\s*years?\b", re.IGNORECASE)
_YEAR = re.compile(r"\b(?:19|20)\d{2}\b")
_ACCUSATION = re.compile(r"\b(lie|lied|liar|lies|dishonest|fraud|reject|fabricat\w*)\b", re.IGNORECASE)
_DENIALS = {
    "never",
    "not",
    "no",
    "don't",
    "dont",
    "didn't",
    "didnt",
    "haven't",
    "havent",
    "hasn't",
    "hasnt",
    "wasn't",
    "wasnt",
    "weren't",
    "werent",
    "without",
    "none",
}
_VERBS = {
    "built",
    "shipped",
    "implemented",
    "designed",
    "led",
    "reduced",
    "deployed",
    "wrote",
    "maintained",
    "launched",
    "owned",
    "migrated",
    "scaled",
    "improved",
    "delivered",
    "created",
    "developed",
    "packaged",
    "operated",
    "supported",
}
_STOP = {
    "a",
    "an",
    "the",
    "of",
    "and",
    "or",
    "with",
    "in",
    "for",
    "to",
    "on",
    "at",
    "by",
    "from",
    "as",
    "is",
    "are",
    "was",
    "were",
    "be",
    "this",
    "that",
    "have",
    "has",
    "had",
    "know",
    "knew",
    "used",
    "using",
    "use",
    "some",
    "also",
    "just",
    "very",
    "really",
    "experience",
    "experienced",
    "professional",
    "work",
    "working",
    "years",
    "year",
}
_PREFIX = {"tenure": "T", "role": "R", "achievement": "A", "skill": "S", "education": "E"}
_LIMITS = {"role": 6, "achievement": 4, "skill": 8, "education": 3}
_COMPARE_SYSTEM = (
    "You compare CV claims with the candidate's own words. "
    "Return only a JSON object. Do not use markdown."
)
_EXTRACT_SYSTEM = "Return only a JSON object. Do not use markdown."


class ClaimError(Exception):
    def __init__(self, code: str, message: str, status_code: int) -> None:
        self.code = code
        self.message = message
        self.status_code = status_code
        super().__init__(message)


@dataclass(frozen=True)
class CvClaimDraft:
    claim_id: str
    kind: str
    statement: str
    subject: str
    cv_quote: str
    amount: float | None = None


@dataclass(frozen=True)
class ClaimFlagDraft:
    claim_id: str
    kind: str
    statement: str
    status: str
    cv_quote: str
    interview_quote: str
    follow_up: str


@dataclass(frozen=True)
class VerificationDraft:
    """Follow-up prompts only. Suitability scoring does not read this result."""

    flags: list[ClaimFlagDraft]
    llm_tier: str
    fallback_used: bool


def claims_from_attributes(attributes: dict[str, object], raw_text: str) -> list[CvClaimDraft]:
    """Claims whose wording can be found in the CV. An unquoted claim is dropped."""
    pending: list[tuple[str, str, str, str, float | None]] = []
    years = attributes.get("experience_years")
    if isinstance(years, int | float) and not isinstance(years, bool) and float(years) > 0:
        quote = tenure_quote(raw_text)
        if quote:
            shown = _shown_years(float(years))
            pending.append(
                (
                    "tenure",
                    f"The CV shows {shown} years of professional experience.",
                    f"{shown} years",
                    quote,
                    float(years),
                )
            )
    history = attributes.get("work_history")
    roles = [role for role in history if isinstance(role, dict)] if isinstance(history, list) else []
    role_count = 0
    achievement_count = 0
    for role in roles:
        if role_count >= _LIMITS["role"]:
            break
        title = _text(role.get("title"))
        company = _text(role.get("company"))
        summary = _text(role.get("summary"))
        start = _text(role.get("start"))
        end = _text(role.get("end"))
        quote = _grounded_quote(company or title, raw_text) or _grounded_quote(summary, raw_text)
        subject = company or title
        if quote and subject:
            pending.append(("role", _role_statement(title, company, start, end), subject, quote, None))
            role_count += 1
        if achievement_count >= _LIMITS["achievement"] or not summary or re.search(r"\d", summary) is None:
            continue
        achievement_quote = _grounded_quote(summary, raw_text)
        if achievement_quote:
            pending.append(("achievement", f"The CV says {summary}.", summary[:80], achievement_quote, None))
            achievement_count += 1
    skills = attributes.get("skills")
    skill_count = 0
    if isinstance(skills, list):
        for skill in skills:
            if skill_count >= _LIMITS["skill"] or not isinstance(skill, str) or not skill.strip():
                continue
            quote = find_skill_span(skill.strip(), raw_text)
            if not quote:
                continue
            pending.append(("skill", f"The CV lists {skill.strip()}.", skill.strip(), quote, None))
            skill_count += 1
    education = attributes.get("education")
    education_count = 0
    if isinstance(education, list):
        for item in education:
            if education_count >= _LIMITS["education"] or not isinstance(item, str) or not item.strip():
                continue
            quote = _grounded_quote(item.strip(), raw_text)
            if not quote:
                continue
            pending.append(("education", f"The CV lists {item.strip()}.", item.strip()[:80], quote, None))
            education_count += 1
    return _number(pending)


def reconcile_claim(claim: CvClaimDraft, interview_quote: str, follow_up: str, speech: str) -> ClaimFlagDraft:
    """Assign one status from the transcript. A quote that is not in the transcript cannot convict."""
    status, quote = _classify(claim, speech, interview_quote)
    return ClaimFlagDraft(
        claim_id=claim.claim_id,
        kind=claim.kind,
        statement=claim.statement,
        status=status,
        cv_quote=claim.cv_quote,
        interview_quote=quote,
        follow_up=_follow_up(claim, status, follow_up),
    )


def follow_up_flags(flags: list[ClaimFlagDraft]) -> list[ClaimFlagDraft]:
    """Supported claims stay on the record and off the recruiter prompt list."""
    return [flag for flag in flags if flag.status != "supported"]


async def verify_claims(
    llm: FallbackLLMManager,
    claims: list[CvClaimDraft],
    lines: list[tuple[float, float, str]],
) -> VerificationDraft:
    """One completion proposes quotes and questions. Python assigns the status."""
    speech = "\n".join(text.strip() for _start, _end, text in lines if text.strip())
    if not claims:
        return VerificationDraft(flags=[], llm_tier="none", fallback_used=False)
    if not speech.strip():
        flags = [reconcile_claim(claim, "", "", "") for claim in claims]
        return VerificationDraft(flags=flags, llm_tier="none", fallback_used=False)
    response = await llm.complete(_compare_prompt(claims, speech), system=_COMPARE_SYSTEM)
    proposed = _proposals(response.content)
    flags = [
        reconcile_claim(
            claim,
            proposed.get(claim.claim_id, {}).get("interview_quote", ""),
            proposed.get(claim.claim_id, {}).get("follow_up", ""),
            speech,
        )
        for claim in claims
    ]
    return VerificationDraft(flags=flags, llm_tier=response.tier.value, fallback_used=response.fallback_used)


def store_cv_claims(
    session: AsyncSession,
    candidate_id: uuid.UUID,
    attributes: dict[str, object],
    raw_text: str,
) -> None:
    """Save the ledger while the screening attributes are still in hand."""
    for claim in claims_from_attributes(attributes, raw_text):
        session.add(_claim_row(candidate_id, claim))


async def verify_stored_claims(
    db: AsyncSession,
    llm: FallbackLLMManager,
    interview: InterviewSession,
    segments: list[TranscriptSegment],
) -> None:
    """Check the stored ledger once the interview transcript is final."""
    existing = await db.scalar(select(ClaimVerification.id).where(ClaimVerification.session_id == interview.id))
    if existing is not None:
        return
    rows = await _claim_rows(db, interview.candidate_id)
    if not rows:
        rows = await _backfill_claims(db, llm, interview.candidate_id)
    claims = [_draft_from_row(row) for row in rows]
    lines = [
        (segment.start_time, segment.end_time, segment.text)
        for segment in segments
        if segment.speaker == "candidate" and segment.text.strip()
    ]
    draft = await verify_claims(llm, claims, lines)
    verification = ClaimVerification(
        id=uuid.uuid4(),
        session_id=interview.id,
        llm_tier=draft.llm_tier,
        fallback_used=draft.fallback_used,
        created_at=datetime.now(UTC),
    )
    db.add(verification)
    await db.flush()
    for sequence, flag in enumerate(draft.flags, start=1):
        db.add(
            ClaimFlag(
                id=uuid.uuid4(),
                verification_id=verification.id,
                sequence=sequence,
                claim_id=flag.claim_id,
                kind=flag.kind,
                statement=flag.statement,
                status=flag.status,
                cv_quote=flag.cv_quote,
                interview_quote=flag.interview_quote,
                follow_up=flag.follow_up,
            )
        )


async def read_claim_verification(db: AsyncSession, candidate_id: uuid.UUID) -> ClaimVerificationRead:
    if await db.get(Candidate, candidate_id) is None:
        raise ClaimError("CANDIDATE_NOT_FOUND", "Candidate not found.", 404)
    verification = await _verification(db, candidate_id)
    if verification is None:
        raise ClaimError("CLAIM_CHECK_NOT_FOUND", "CV claims have not been checked against an interview yet.", 404)
    return _to_read(candidate_id, verification)


async def build_claim_verification(
    db: AsyncSession,
    llm: FallbackLLMManager,
    candidate_id: uuid.UUID,
) -> ClaimVerificationRead:
    if await db.get(Candidate, candidate_id) is None:
        raise ClaimError("CANDIDATE_NOT_FOUND", "Candidate not found.", 404)
    interview = await db.scalar(_latest_interview(candidate_id))
    if interview is None or interview.status != "ended":
        raise ClaimError("INTERVIEW_NOT_ENDED", "CV claim checks run after the interview ends.", 409)
    existing = await _verification(db, candidate_id)
    if existing is not None:
        await db.delete(existing)
        await db.flush()
    result = await db.scalars(
        select(TranscriptSegment)
        .where(TranscriptSegment.session_id == interview.id)
        .order_by(TranscriptSegment.start_time, TranscriptSegment.created_at)
    )
    await verify_stored_claims(db, llm, interview, list(result.all()))
    await db.commit()
    stored = await _verification(db, candidate_id)
    if stored is None:
        raise ClaimError("CLAIM_CHECK_EMPTY", "No CV claims could be checked.", 409)
    return _to_read(candidate_id, stored)


def _to_read(candidate_id: uuid.UUID, verification: ClaimVerification) -> ClaimVerificationRead:
    ordered = sorted(verification.flags, key=lambda flag: flag.sequence)
    return ClaimVerificationRead(
        candidate_id=candidate_id,
        llm_tier=verification.llm_tier,
        fallback_used=verification.fallback_used,
        supported_count=sum(1 for flag in ordered if flag.status == "supported"),
        flags=[
            ClaimFlagRead(
                claim_id=flag.claim_id,
                kind=flag.kind,
                statement=flag.statement,
                status=flag.status,
                cv_quote=flag.cv_quote,
                interview_quote=flag.interview_quote,
                follow_up=flag.follow_up,
            )
            for flag in ordered
            if flag.status != "supported"
        ],
    )


def _classify(claim: CvClaimDraft, speech: str, proposed_quote: str) -> tuple[str, str]:
    if claim.kind == "tenure":
        conflict = _tenure_conflict(claim, speech)
        if conflict:
            return "contradiction", _chosen_quote(proposed_quote, speech, conflict)
        if _YEARS.search(speech) is None and re.search(r"\byears?\b", speech, re.IGNORECASE) is None:
            return "not_discussed", ""
        support = _tenure_support(claim, speech)
        if support:
            return "supported", _chosen_quote(proposed_quote, speech, support)
        return "unverified", _mention(claim, speech, proposed_quote)
    conflict = _subject_conflict(claim, speech)
    if conflict:
        return "contradiction", _chosen_quote(proposed_quote, speech, conflict)
    if not _subject_in(claim.subject, speech):
        return "not_discussed", ""
    support = _subject_support(claim, speech)
    if support:
        return "supported", _chosen_quote(proposed_quote, speech, support)
    return "unverified", _mention(claim, speech, proposed_quote)


def _tenure_conflict(claim: CvClaimDraft, speech: str) -> str:
    if claim.amount is None:
        return ""
    denial_on_number = ""
    mismatch = ""
    matched = False
    for snippet in _snippets(speech):
        spoken = _spoken_years(snippet)
        close = spoken is not None and abs(spoken - claim.amount) < 1
        if close and _denial_near("years", snippet):
            denial_on_number = snippet
        elif close:
            matched = True
        elif spoken is not None and not mismatch:
            mismatch = snippet
    if denial_on_number:
        return denial_on_number
    if matched:
        return ""
    return mismatch


def _tenure_support(claim: CvClaimDraft, speech: str) -> str:
    if claim.amount is None:
        return ""
    for snippet in _snippets(speech):
        spoken = _spoken_years(snippet)
        if spoken is None or abs(spoken - claim.amount) >= 1 or _denial_near("years", snippet):
            continue
        return snippet
    return ""


def _subject_conflict(claim: CvClaimDraft, speech: str) -> str:
    for snippet in _snippets(speech):
        if _subject_in(claim.subject, snippet) and _denial_near(claim.subject, snippet):
            return snippet
    return ""


def _subject_support(claim: CvClaimDraft, speech: str) -> str:
    for snippet in _snippets(speech):
        if _supports(claim, snippet):
            return snippet
    return ""


def _supports(claim: CvClaimDraft, snippet: str) -> bool:
    if not _subject_in(claim.subject, snippet) or _denial_near(claim.subject, snippet):
        return False
    words = [match.group(0).casefold() for match in _TOKEN.finditer(snippet)]
    subject_words = {match.group(0).casefold() for match in _TOKEN.finditer(claim.subject)}
    extras = [word for word in words if word not in subject_words and word not in _STOP and len(word) >= 4]
    verbs = [word for word in extras if word in _VERBS]
    details = [word for word in extras if word not in _VERBS]
    if verbs and details:
        return True
    if claim.kind in {"role", "education"} and _YEAR.search(snippet):
        return True
    return bool(claim.kind == "achievement" and re.search(r"\d", snippet))


def _mention(claim: CvClaimDraft, speech: str, proposed_quote: str) -> str:
    chosen = _chosen_quote(proposed_quote, speech, "")
    if chosen and _subject_in(claim.subject, chosen):
        return chosen
    for snippet in _snippets(speech):
        if _subject_in(claim.subject, snippet):
            return snippet
    return ""


def _chosen_quote(proposed: str, speech: str, fallback: str) -> str:
    ok, snippet = anchored_quote(proposed, speech)
    if ok:
        return snippet
    return " ".join(fallback.split())


def anchored_quote(quote: str, text: str) -> tuple[bool, str]:
    """Accept a quote only when most of its words appear in order in the transcript."""
    quote_tokens = [match.group(0).casefold() for match in _TOKEN.finditer(" ".join(quote.split()))]
    spans = [(match.group(0).casefold(), match.start(), match.end()) for match in _TOKEN.finditer(text)]
    if not quote_tokens or not spans:
        return False, ""
    lowered = [token for token, _start, _end in spans]
    best_start = 0
    best_length = 0
    for quote_start in range(len(quote_tokens)):
        for text_start in range(len(lowered)):
            length = 0
            while (
                quote_start + length < len(quote_tokens)
                and text_start + length < len(lowered)
                and quote_tokens[quote_start + length] == lowered[text_start + length]
            ):
                length += 1
            if length > best_length:
                best_start = text_start
                best_length = length
    need = len(quote_tokens) if len(quote_tokens) < 4 else max(4, (len(quote_tokens) * 3 + 3) // 4)
    if best_length < need:
        return False, ""
    snippet = text[spans[best_start][1] : spans[best_start + best_length - 1][2]]
    return True, " ".join(snippet.split())


def _follow_up(claim: CvClaimDraft, status: str, proposed: str) -> str:
    if status == "supported":
        return ""
    text = " ".join(proposed.split())
    if text.endswith("?") and 12 <= len(text) <= 240 and _ACCUSATION.search(text) is None:
        return text
    subject = claim.subject
    if status == "contradiction":
        return f"Ask how {subject} lines up with what is written on the CV?"
    if status == "unverified":
        return f"Ask for a specific example that shows {subject}?"
    return f"Ask whether {subject} was part of their recent work?"


def _compare_prompt(claims: list[CvClaimDraft], speech: str) -> str:
    lines = [f"{claim.claim_id} ({claim.kind}): {claim.statement} CV quote: {claim.cv_quote}" for claim in claims]
    return (
        "For each claim, copy a short interview_quote from the candidate speech when they spoke about it. "
        "Leave interview_quote empty when they did not. "
        "follow_up must be one question a recruiter could ask. "
        "Do not accuse the candidate, and do not recommend a rejection.\n"
        'Return JSON {"checks":[{"claim_id":"","interview_quote":"","follow_up":""}]}\n'
        "Claims:\n"
        + "\n".join(lines)
        + "\nCandidate speech:\n"
        + speech[:12000]
    )


def _proposals(content: str) -> dict[str, dict[str, str]]:
    try:
        payload = parse_json_object(content)
    except JobGraphError:
        return {}
    raw = payload.get("checks")
    found: dict[str, dict[str, str]] = {}
    if not isinstance(raw, list):
        return found
    for item in raw:
        if not isinstance(item, dict) or not item.get("claim_id"):
            continue
        found[str(item["claim_id"])] = {
            "interview_quote": str(item.get("interview_quote") or ""),
            "follow_up": str(item.get("follow_up") or ""),
        }
    return found


async def _backfill_claims(db: AsyncSession, llm: FallbackLLMManager, candidate_id: uuid.UUID) -> list[CvClaim]:
    parse = await db.scalar(select(CandidateParseResult).where(CandidateParseResult.candidate_id == candidate_id))
    raw_text = parse.raw_text if parse is not None and parse.status == "parsed" else ""
    if not raw_text.strip():
        return []
    try:
        claims = await _claims_from_cv_text(llm, raw_text)
    except (JobGraphError, LLMFallbackExhaustedError):
        return []
    rows = [_claim_row(candidate_id, claim) for claim in claims]
    for row in rows:
        db.add(row)
    await db.flush()
    return rows


async def _claims_from_cv_text(llm: FallbackLLMManager, raw_text: str) -> list[CvClaimDraft]:
    prompt = (
        "Extract candidate attributes as JSON with keys skills, work_history, education, and experience_years. "
        "work_history must list every job as an object with title, company, start, end, and summary. "
        "Use YYYY-MM for start and end, and \"present\" when the job is current. "
        "skills must list tools and technologies as written on the CV. "
        "Use an empty string, empty list, or 0 when the CV does not say.\n"
        f"CV:\n{raw_text[:12000]}"
    )
    response = await llm.complete(prompt, system=_EXTRACT_SYSTEM)
    payload = parse_json_object(response.content)
    work_history = coerce_work_history(payload.get("work_history"))
    skills = payload.get("skills")
    education = payload.get("education")
    attributes: dict[str, object] = {
        "skills": [item.strip() for item in skills if isinstance(item, str) and item.strip()] if isinstance(skills, list) else [],
        "work_history": work_history,
        "education": [item.strip() for item in education if isinstance(item, str) and item.strip()] if isinstance(education, list) else [],
        "experience_years": computed_experience_years(work_history, payload.get("experience_years")),
    }
    return claims_from_attributes(attributes, raw_text)


def _claim_row(candidate_id: uuid.UUID, claim: CvClaimDraft) -> CvClaim:
    return CvClaim(
        id=uuid.uuid4(),
        candidate_id=candidate_id,
        claim_id=claim.claim_id,
        kind=claim.kind,
        statement=claim.statement,
        subject=claim.subject,
        cv_quote=claim.cv_quote,
        amount=claim.amount,
    )


def _draft_from_row(row: CvClaim) -> CvClaimDraft:
    return CvClaimDraft(
        claim_id=row.claim_id,
        kind=row.kind,
        statement=row.statement,
        subject=row.subject,
        cv_quote=row.cv_quote,
        amount=row.amount,
    )


async def _claim_rows(db: AsyncSession, candidate_id: uuid.UUID) -> list[CvClaim]:
    result = await db.scalars(select(CvClaim).where(CvClaim.candidate_id == candidate_id).order_by(CvClaim.claim_id))
    return list(result.all())


def _latest_interview(candidate_id: uuid.UUID):
    return (
        select(InterviewSession)
        .where(InterviewSession.candidate_id == candidate_id)
        .order_by(nulls_last(desc(InterviewSession.ended_at)), desc(InterviewSession.created_at))
    )


async def _verification(db: AsyncSession, candidate_id: uuid.UUID) -> ClaimVerification | None:
    interview = await db.scalar(_latest_interview(candidate_id))
    if interview is None:
        return None
    return await db.scalar(
        select(ClaimVerification)
        .where(ClaimVerification.session_id == interview.id)
        .options(selectinload(ClaimVerification.flags))
    )


def _number(pending: list[tuple[str, str, str, str, float | None]]) -> list[CvClaimDraft]:
    counts: dict[str, int] = {}
    seen: set[tuple[str, str]] = set()
    drafts: list[CvClaimDraft] = []
    for kind, statement, subject, quote, amount in pending:
        key = (kind, " ".join(subject.casefold().split()))
        if key in seen:
            continue
        seen.add(key)
        counts[kind] = counts.get(kind, 0) + 1
        drafts.append(
            CvClaimDraft(
                claim_id=f"{_PREFIX[kind]}{counts[kind]:02d}",
                kind=kind,
                statement=statement,
                subject=subject,
                cv_quote=quote,
                amount=amount,
            )
        )
    return drafts


def _role_statement(title: str, company: str, start: str, end: str) -> str:
    who = " at ".join(part for part in (title, company) if part)
    if start or end:
        return f"The CV lists {who} from {start or 'an unknown start'} to {end or 'an unknown end'}."
    return f"The CV lists {who}."


def _grounded_quote(term: str, raw_text: str) -> str:
    cleaned = " ".join(term.split())
    if not cleaned:
        return ""
    span = find_skill_span(cleaned, raw_text)
    if span:
        return span
    supported, quote = resolve_evidence(cleaned, raw_text)
    if supported and quote:
        return quote
    return ""


def _subject_in(subject: str, text: str) -> bool:
    if find_skill_span(subject, text):
        return True
    parts = [match.group(0) for match in _TOKEN.finditer(subject) if len(match.group(0)) >= 4 and match.group(0).casefold() not in _STOP]
    if not parts:
        return False
    key = max(parts, key=len)
    return find_skill_span(key, text) is not None


def _denial_near(subject: str, text: str) -> bool:
    subject_parts = {match.group(0).casefold() for match in _TOKEN.finditer(subject) if len(match.group(0)) >= 3}
    if not subject_parts:
        return False
    words = [match.group(0).casefold() for match in _TOKEN.finditer(text)]
    for index, word in enumerate(words):
        if word not in subject_parts and not any(part in word or word in part for part in subject_parts if len(part) >= 4):
            continue
        window = words[max(0, index - 8) : index]
        if "not" in window and "only" in window:
            window = [item for item in window if item != "not"]
        if any(item in _DENIALS for item in window):
            return True
    return False


def _spoken_years(text: str) -> float | None:
    match = _YEARS.search(text)
    if match is None:
        return None
    return float(match.group(1))


def _snippets(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?])\s+|\n+", text)
    return [part.strip() for part in parts if part.strip()]


def _shown_years(years: float) -> str:
    if years.is_integer():
        return str(int(years))
    return f"{years:.1f}"


def _text(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""
