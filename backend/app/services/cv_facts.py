import re
from datetime import date, timedelta

_MONTHS = {
    "jan": 1,
    "january": 1,
    "feb": 2,
    "february": 2,
    "mar": 3,
    "march": 3,
    "apr": 4,
    "april": 4,
    "may": 5,
    "jun": 6,
    "june": 6,
    "jul": 7,
    "july": 7,
    "aug": 8,
    "august": 8,
    "sep": 9,
    "sept": 9,
    "september": 9,
    "oct": 10,
    "october": 10,
    "nov": 11,
    "november": 11,
    "dec": 12,
    "december": 12,
}
_OPEN = {"present", "current", "now", "ongoing", "today"}
_GENERIC = {
    "experience",
    "experiences",
    "professional",
    "professional experience",
    "work",
    "work experience",
    "industry",
    "industry experience",
    "relevant",
    "relevant experience",
    "total",
    "total experience",
    "overall",
    "overall experience",
    "employment",
    "project",
    "projects",
    "skill",
    "skills",
    "year",
    "years",
    "production",
    "role",
    "job",
    "software",
    "engineering",
    "development",
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
    "years",
    "year",
    "experience",
    "experienced",
    "professional",
    "work",
    "working",
    "using",
    "used",
    "has",
    "have",
    "candidate",
    "does",
    "not",
}
_TOKEN = re.compile(r"[A-Za-z0-9+#]+(?:[./-][A-Za-z0-9+#]+)*")
_REQUIRED_YEARS = re.compile(r"\b(\d{1,2})\s*\+?\s*years?\b", re.IGNORECASE)
_SKILL_YEARS = re.compile(
    r"\byears?\b(?:\s+of)?(?:\s+experience)?\s+(?:with|in|using)\s+([A-Za-z0-9][A-Za-z0-9+#./-]{1,40})",
    re.IGNORECASE,
)
_LOOSE_RANGE = re.compile(
    r"(?P<start>[A-Za-z]{3,9}\s+\d{4}|\d{4}[-/.]\d{1,2}|\d{1,2}[-/.]\d{4}|\d{4})"
    r"\s*(?:-|–|—|to)\s*"
    r"(?P<end>present|current|now|ongoing|[A-Za-z]{3,9}\s+\d{4}|\d{4}[-/.]\d{1,2}|\d{1,2}[-/.]\d{4}|\d{4})",
    re.IGNORECASE,
)
_YEAR_SNIPPET = re.compile(r"\S(?:.{0,90}\b(?:19|20)\d{2}\b.{0,90})")
_ALLOWED = {"met", "partially_met", "unmet", "insufficient_evidence"}
_STATUS_RANK = {"insufficient_evidence": 0, "unmet": 0, "partially_met": 1, "met": 2}


def coerce_work_history(value: object) -> list[dict[str, str]]:
    """Normalize model output into role records with optional dates."""
    if not isinstance(value, list):
        return []
    roles: list[dict[str, str]] = []
    for item in value:
        if isinstance(item, str) and item.strip():
            start, end = _range_in_text(item)
            roles.append({"title": "", "company": "", "start": start, "end": end, "summary": item.strip()})
        elif isinstance(item, dict):
            roles.append(_role_from_mapping(item))
    return [role for role in roles if any(role.values())]


def computed_experience_years(
    work_history: list[dict[str, str]],
    stated_years: object,
    *,
    today: date | None = None,
) -> float:
    """Sum dated roles in Python. Overlaps count once. Undated history uses the model's number."""
    clock = today or date.today()
    spans = _spans(work_history, clock)
    if spans:
        return _merged_years(spans)
    return _stated_years(stated_years)


def screening_facts(attributes: dict[str, object]) -> str:
    """Facts the checklist evaluator must treat as already calculated."""
    years = attributes.get("experience_years")
    shown = years if isinstance(years, int | float) and not isinstance(years, bool) else 0
    lines = [
        f"Total professional experience, after merging overlapping jobs: {shown} years.",
        "Use that total for questions about overall years of experience. Do not add the dates again.",
    ]
    history = attributes.get("work_history")
    if isinstance(history, list):
        for role in history:
            if not isinstance(role, dict):
                continue
            title = str(role.get("title") or "Role")
            company = str(role.get("company") or "unknown employer")
            start = str(role.get("start") or "unknown start")
            end = str(role.get("end") or "unknown end")
            summary = str(role.get("summary") or "").strip()
            detail = f"- {title} at {company}, {start} to {end}."
            if summary:
                detail = f"{detail} {summary}"
            lines.append(detail)
    skills = attributes.get("skills")
    if isinstance(skills, list):
        named = [skill.strip() for skill in skills if isinstance(skill, str) and skill.strip()]
        if named:
            lines.append("Skills written on the CV: " + ", ".join(named) + ".")
            lines.append("If one of these skills appears in the CV, it is evidenced.")
    return "\n".join(lines)


def reconcile_evaluation(
    *,
    question: str,
    dimension: str,
    status: str,
    evidence: str,
    hints: list[str],
    attributes: dict[str, object],
    raw_text: str,
    today: date | None = None,
) -> tuple[str, str]:
    """Keep a judgment only when the CV supports it, and apply computed tenure."""
    resolved = status if status in _ALLOWED else "insufficient_evidence"
    supported, faithful = resolve_evidence(evidence, raw_text)
    if evidence.strip() and not supported:
        resolved = "insufficient_evidence"
        faithful = ""
    required = _required_years(question)
    if dimension == "experience" and required is not None:
        available = _available_years(question, attributes, today=today)
        if available is not None and available + 1e-9 >= required and resolved != "met":
            resolved = "met"
            if not faithful:
                faithful = tenure_quote(raw_text)
        return resolved, faithful
    if resolved == "insufficient_evidence":
        span = supporting_skill_span(question, hints, attributes, raw_text)
        if span:
            return "met", span
    return resolved, faithful


def open_for_local_review(
    evaluations: list[dict[str, object]],
    checklist: list[dict[str, object]],
) -> list[dict[str, object]]:
    """Items the local model may try to raise. Met items and computed year checks stay put."""
    by_id = {str(query["query_id"]): query for query in checklist}
    open_items: list[dict[str, object]] = []
    for item in evaluations:
        if str(item.get("status") or "") == "met":
            continue
        query = by_id.get(str(item.get("query_id") or ""))
        if query is not None and _skip_local_review(query):
            continue
        open_items.append(item)
    return open_items


def upgrade_open_evaluations(
    evaluations: list[dict[str, object]],
    reviews: list[object],
    checklist: list[dict[str, object]],
    raw_text: str,
) -> list[dict[str, object]]:
    """Apply a local review only when it raises a non-met item and quotes the CV."""
    by_id = {str(query["query_id"]): query for query in checklist}
    review_by_id: dict[str, dict[str, object]] = {}
    for review in reviews:
        if isinstance(review, dict) and review.get("query_id"):
            review_by_id[str(review["query_id"])] = review
    updated: list[dict[str, object]] = []
    for item in evaluations:
        query_id = str(item.get("query_id") or "")
        current = str(item.get("status") or "insufficient_evidence")
        query = by_id.get(query_id)
        review = review_by_id.get(query_id)
        if current == "met" or query is None or review is None or _skip_local_review(query):
            updated.append(item)
            continue
        proposed = str(review.get("status") or "")
        if _STATUS_RANK.get(proposed, -1) <= _STATUS_RANK.get(current, 0):
            updated.append(item)
            continue
        supported, faithful = resolve_evidence(str(review.get("evidence") or ""), raw_text)
        if not supported or not faithful:
            updated.append(item)
            continue
        updated.append({**item, "status": proposed, "evidence": faithful, "confidence": _raised_confidence(item, review)})
    return updated


def _skip_local_review(query: dict[str, object]) -> bool:
    return str(query.get("dimension") or "") == "experience" and _required_years(str(query.get("question") or "")) is not None


def _raised_confidence(item: dict[str, object], review: dict[str, object]) -> float:
    current = item.get("confidence")
    proposed = review.get("confidence")
    current_value = float(current) if isinstance(current, int | float) and not isinstance(current, bool) else 0.0
    proposed_value = float(proposed) if isinstance(proposed, int | float) and not isinstance(proposed, bool) else 0.7
    return max(current_value, proposed_value, 0.7)


def resolve_evidence(quote: str, raw_text: str) -> tuple[bool, str]:
    """Accept a quote when its words, or a distinctive phrase inside it, occur in the CV."""
    cleaned = " ".join(quote.split())
    if not cleaned:
        return True, ""
    quote_tokens = [match.group(0).casefold() for match in _TOKEN.finditer(cleaned)]
    cv_tokens = [(match.group(0), match.start(), match.end()) for match in _TOKEN.finditer(raw_text)]
    if not quote_tokens or not cv_tokens:
        return False, ""
    lowered = [token.casefold() for token, _, _ in cv_tokens]
    best_start = 0
    best_length = 0
    for quote_start in range(len(quote_tokens)):
        for cv_start in range(len(lowered)):
            length = 0
            while (
                quote_start + length < len(quote_tokens)
                and cv_start + length < len(lowered)
                and quote_tokens[quote_start + length] == lowered[cv_start + length]
            ):
                length += 1
            if length > best_length:
                best_start = cv_start
                best_length = length
    if best_length:
        coverage = best_length / len(quote_tokens)
        matched = lowered[best_start : best_start + best_length]
        distinctive = [token for token in matched if token not in _STOP and len(token) >= 4]
        if coverage >= 0.6 or best_length == len(quote_tokens) or distinctive:
            snippet = raw_text[cv_tokens[best_start][1] : cv_tokens[best_start + best_length - 1][2]]
            return True, snippet
    for width in range(min(3, len(quote_tokens)), 0, -1):
        for index in range(len(quote_tokens) - width + 1):
            piece = "".join(quote_tokens[index : index + width])
            if len(piece) < 5 or piece in _STOP:
                continue
            span = _find_compact(piece, cv_tokens, raw_text)
            if span:
                return True, span
    return False, ""


def supporting_skill_span(
    question: str,
    hints: list[str],
    attributes: dict[str, object],
    raw_text: str,
) -> str | None:
    """Return the CV wording of a named skill when the question is not a years threshold."""
    if _required_years(question) is not None:
        return None
    terms: list[str] = []
    skills = attributes.get("skills")
    if isinstance(skills, list):
        for skill in skills:
            if isinstance(skill, str) and find_skill_span(skill, question):
                terms.append(skill)
    for hint in hints:
        if hint.strip() and not _is_generic(hint) and find_skill_span(hint, question):
            terms.append(hint)
    for term in terms:
        span = find_skill_span(term, raw_text)
        if span:
            return span
    return None


def find_skill_span(skill: str, text: str) -> str | None:
    """Locate a skill even when the CV joins or splits the token, such as pgvector / PG Vector."""
    parts = [match.group(0).casefold() for match in _TOKEN.finditer(skill)]
    tokens = [(match.group(0), match.start(), match.end()) for match in _TOKEN.finditer(text)]
    if not parts or not tokens:
        return None
    lowered = [token.casefold() for token, _, _ in tokens]
    width = len(parts)
    for index in range(len(tokens) - width + 1):
        if lowered[index : index + width] == parts:
            return text[tokens[index][1] : tokens[index + width - 1][2]]
    compact = "".join(parts)
    if len(compact) < 4:
        return None
    return _find_compact(compact, tokens, text)


def tenure_quote(raw_text: str) -> str:
    match = _YEAR_SNIPPET.search(raw_text)
    if match is None:
        return ""
    return " ".join(match.group(0).split())[:240]


def _role_from_mapping(item: dict[str, object]) -> dict[str, str]:
    title = _field(item, "title")
    company = _field(item, "company") or _field(item, "employer")
    summary = _field(item, "summary") or _field(item, "description") or _field(item, "text")
    start = _field(item, "start") or _field(item, "start_date")
    end = _field(item, "end") or _field(item, "end_date")
    loose_start, loose_end = _range_in_text(" ".join(part for part in (title, company, summary) if part))
    return {
        "title": title,
        "company": company,
        "start": start or loose_start,
        "end": end or loose_end,
        "summary": summary,
    }


def _field(item: dict[str, object], key: str) -> str:
    value = item.get(key)
    return value.strip() if isinstance(value, str) else ""


def _range_in_text(text: str) -> tuple[str, str]:
    match = _LOOSE_RANGE.search(text)
    if match is None:
        return "", ""
    return match.group("start"), match.group("end")


def _spans(work_history: list[dict[str, str]], today: date) -> list[tuple[date, date]]:
    spans: list[tuple[date, date]] = []
    for role in work_history:
        start_text = role.get("start", "")
        end_text = role.get("end", "")
        if not start_text or not end_text:
            loose_start, loose_end = _range_in_text(_role_blob(role))
            start_text = start_text or loose_start
            end_text = end_text or loose_end
        start = _parse_boundary(start_text, is_end=False, today=today)
        end = _parse_boundary(end_text, is_end=True, today=today)
        if start is None or end is None or end < start:
            continue
        spans.append((start, end))
    return spans


def _parse_boundary(value: str, *, is_end: bool, today: date) -> date | None:
    text = re.sub(r"\s+", " ", value.strip().casefold().replace(",", " "))
    if not text:
        return None
    if text in _OPEN:
        return today
    parsed = _month_year(text, is_end=is_end)
    if parsed is None:
        year_only = re.fullmatch(r"(\d{4})", text)
        if year_only:
            year = int(year_only.group(1))
            parsed = date(year, 12, 31) if is_end else date(year, 1, 1)
        else:
            iso = re.fullmatch(r"(\d{4})[-/.](\d{1,2})(?:[-/.](\d{1,2}))?", text)
            month_first = re.fullmatch(r"(\d{1,2})[-/.](\d{4})", text)
            if iso:
                year = int(iso.group(1))
                month = int(iso.group(2))
                day = int(iso.group(3)) if iso.group(3) else None
                parsed = _safe_date(year, month, day, is_end=is_end)
            elif month_first:
                parsed = _safe_date(int(month_first.group(2)), int(month_first.group(1)), None, is_end=is_end)
    if parsed is None:
        return None
    return today if parsed > today else parsed


def _month_year(text: str, *, is_end: bool) -> date | None:
    match = re.fullmatch(r"([a-z]+)\s+(\d{4})", text)
    if match is None:
        return None
    month = _MONTHS.get(match.group(1))
    if month is None:
        return None
    return _safe_date(int(match.group(2)), month, None, is_end=is_end)


def _safe_date(year: int, month: int, day: int | None, *, is_end: bool) -> date | None:
    if month < 1 or month > 12 or year < 1970 or year > 2100:
        return None
    if day is None:
        day = _month_end(year, month) if is_end else 1
    try:
        return date(year, month, day)
    except ValueError:
        return None


def _month_end(year: int, month: int) -> int:
    if month == 12:
        return 31
    return (date(year, month + 1, 1) - timedelta(days=1)).day


def _merged_years(spans: list[tuple[date, date]]) -> float:
    ordered = sorted(spans)
    merged = [ordered[0]]
    for start, end in ordered[1:]:
        previous_start, previous_end = merged[-1]
        if start <= previous_end + timedelta(days=1):
            merged[-1] = (previous_start, max(previous_end, end))
        else:
            merged.append((start, end))
    days = sum((end - start).days for start, end in merged)
    return round(days / 365.25, 1)


def _stated_years(value: object) -> float:
    if isinstance(value, bool):
        return 0.0
    if isinstance(value, int | float):
        return round(max(float(value), 0.0), 1)
    if isinstance(value, str):
        match = re.search(r"\d+(?:\.\d+)?", value)
        if match:
            return round(float(match.group(0)), 1)
    return 0.0


def _required_years(question: str) -> int | None:
    match = _REQUIRED_YEARS.search(question)
    if match is None:
        return None
    return int(match.group(1))


def _available_years(question: str, attributes: dict[str, object], *, today: date | None) -> float | None:
    history = attributes.get("work_history")
    roles = [role for role in history if isinstance(role, dict)] if isinstance(history, list) else []
    skills = attributes.get("skills")
    named = [skill for skill in skills if isinstance(skill, str)] if isinstance(skills, list) else []
    target = _specific_skill(question, named)
    if target:
        matching = [role for role in roles if find_skill_span(target, _role_blob(role))]
        if not matching:
            return None
        return computed_experience_years([dict(role) for role in matching], 0, today=today)
    years = attributes.get("experience_years")
    if isinstance(years, int | float) and not isinstance(years, bool):
        return float(years)
    return None


def _specific_skill(question: str, skills: list[str]) -> str | None:
    if _required_years(question) is None:
        return None
    for skill in skills:
        if not _is_generic(skill) and find_skill_span(skill, question):
            return skill
    match = _SKILL_YEARS.search(question)
    if match is None:
        return None
    term = match.group(1).strip()
    if _is_generic(term):
        return None
    return term


def _role_blob(role: dict[str, object]) -> str:
    return " ".join(str(role.get(key) or "") for key in ("title", "company", "summary"))


def _is_generic(term: str) -> bool:
    return " ".join(term.casefold().split()) in _GENERIC


def _find_compact(compact: str, tokens: list[tuple[str, int, int]], raw_text: str) -> str | None:
    lowered = [re.sub(r"[^a-z0-9]", "", token.casefold()) for token, _, _ in tokens]
    for index, folded in enumerate(lowered):
        if folded == compact:
            return raw_text[tokens[index][1] : tokens[index][2]]
    for width in (2, 3):
        for index in range(len(lowered) - width + 1):
            if "".join(lowered[index : index + width]) == compact:
                return raw_text[tokens[index][1] : tokens[index + width - 1][2]]
    return None
