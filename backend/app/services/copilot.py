import re
import uuid
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.llm_fallback import FallbackLLMManager
from app.graphs.job_creation_graph import JobGraphError, PolicyRetriever, parse_json_object
from app.schemas.copilot import (
    CopilotChip,
    CopilotFocus,
    CopilotMessage,
    CopilotNavigation,
    CopilotPlan,
    CopilotPractice,
    CopilotTurnResponse,
)
from app.services.copilot_nav import (
    JOB_PLACES,
    compare_target,
    job_target,
    normalize_place,
    person_target,
    policy_target,
    progress_target,
    ranking_target,
    static_target,
)
from app.schemas.job import JOB_CATEGORIES, JobCreateRequest, JobRead
from app.schemas.progress import ProgressBoardRead
from app.services.assessment import list_comparisons
from app.services.interview_practice import open_practice_session
from app.services.job_service import create_job, list_jobs
from app.services.policy_ingest import list_policies
from app.services.progress import list_progress
from app.services.screening import list_candidate_groups

PLANNER_SYSTEM = (
    "You are the Sift recruiter copilot. You draft jobs through the policy workflow and "
    "answer questions about jobs, applicants, assessments, and uploaded policies that are already stored. "
    "Return only a JSON object with keys action, message, job, job_query, candidate_name, other_name, focus, and place. "
    "action is one of reply, create_job, list_jobs, list_policies, rank_job, open_candidate, "
    "explain_rank, pipeline, open_job, open_report, navigate, start_practice, offer_approve, offer_inbox. "
    "Use create_job when the recruiter asks to create, draft, hire for, or open a role "
    "and the conversation names a title and at least one required skill. "
    "job uses title, seniority, required_skills, preferred_skills, qualifications, "
    "minimum_years, technical_weight, experience_weight, qualification_weight, contract, and category. "
    "seniority is Junior, Mid-Level, Senior, or Not specified. "
    "contract is Full Time, Part Time, Freelance, or Internship. "
    "category must be a supported job-board category. "
    "Dimension weights must sum to 1. Use 0.5, 0.3, and 0.2 when the recruiter does not set them. "
    "Use Mid-Level, Full Time, Information Technology, minimum_years 0, and "
    "qualifications 'Relevant professional experience' only when those details were not stated. "
    "If the title or required skills are missing, action must be reply and message must ask for them. "
    "Use list_jobs or list_policies when the recruiter asks what is already stored. "
    "Use rank_job to list or rank applicants for one role. job_query is a short title fragment. "
    "Use open_candidate when the recruiter names a person to open, show, find, or list. "
    "candidate_name is only the person's name. "
    "When they ask for everyone with that name, leave job_query empty. "
    "When they name one role, job_query is only that role. "
    "Use explain_rank when the recruiter asks to compare two people or why one person is ahead of another. "
    "candidate_name and other_name are those two names. This opens their comparison. "
    "Use pipeline for who is stuck or which roles have no applicants. "
    "focus is stuck, empty, or summary. "
    "Use open_job to open a stored job draft. Use open_report for the HTML assessment report. "
    "Use navigate to open a known place. place is one of home, policies, policy, jobs, create, "
    "job_brief, job_people, candidates, portraits, standing, compare, person, interviews, practice. "
    "job_query names the role or the policy file. candidate_name names the person. "
    "Use start_practice when the recruiter wants a practice call. "
    "Use offer_approve when the recruiter wants a draft approved and posted. "
    "Use offer_inbox when the recruiter wants the apply mailbox checked. "
    "Never approve, post, or check the inbox yourself. Do not invent stored records. Do not invent scores."
)

_ACTIONS = {
    "reply",
    "create_job",
    "list_jobs",
    "list_policies",
    "rank_job",
    "open_candidate",
    "explain_rank",
    "pipeline",
    "open_job",
    "open_report",
    "navigate",
    "start_practice",
    "offer_approve",
    "offer_inbox",
}
_SENIORITY: frozenset[str] = frozenset({"Junior", "Mid-Level", "Senior", "Not specified"})
_CONTRACTS: frozenset[str] = frozenset({"Full Time", "Part Time", "Freelance", "Internship"})
_FOCUSES: frozenset[str] = frozenset({"stuck", "empty", "summary"})


@dataclass(frozen=True)
class NamedJob:
    id: uuid.UUID
    title: str
    status: str
    version_number: int = 1


@dataclass(frozen=True)
class NamedPerson:
    id: uuid.UUID
    full_name: str
    job_id: uuid.UUID
    job_title: str
    rank: int | None
    aggregate_score: float | None
    overall_score: float | None
    suitability_label: str
    key_gap: str
    technical_dimension: float | None
    experience_dimension: float | None
    qualification_dimension: float | None
    mcq_score: float | None
    interview_qa: float | None
    assessed: bool


@dataclass(frozen=True)
class JobMatch:
    job: NamedJob | None
    matches: list[NamedJob]
    reason: str


def conversation_transcript(messages: list[CopilotMessage]) -> str:
    """Keep the latest command intact and shorten older turns so the planner stays inside context."""
    window = messages[-12:]
    lines: list[str] = []
    last = len(window) - 1
    for index, message in enumerate(window):
        text = message.content.strip()
        if index != last and len(text) > 600:
            text = text[:600].rstrip() + "…"
        lines.append(f"{message.role}: {text}")
    return "\n".join(lines)


def latest_user_text(messages: list[CopilotMessage]) -> str:
    for message in reversed(messages):
        if message.role == "user":
            return message.content.strip()
    return ""


_LEADING_COMMAND = re.compile(
    r"^(?:please\s+)?(?:open|show|list|find|get)\s+(?:me\s+)?(?:the\s+)?(?:profile\s+)?(?:for\s+)?",
    re.IGNORECASE,
)
_EVERY_MATCH = re.compile(r"\b(all|every|each|everyone)\b", re.IGNORECASE)
_PEOPLE_REQUEST = re.compile(
    r"\b(profile|profiles|candidate|candidates|applicant|applicants|person|people|who|list|everyone)\b",
    re.IGNORECASE,
)
_ON_ROLE = re.compile(r"^(?P<name>.+?)\s+on\s+(?P<role>.+)$", re.IGNORECASE)
_ALL_THE = re.compile(r"^(?:all|every|each)\s+(?:the\s+)?", re.IGNORECASE)


def wants_every_match(text: str) -> bool:
    return _EVERY_MATCH.search(text) is not None


def looks_like_people_request(text: str) -> bool:
    return _PEOPLE_REQUEST.search(text) is not None


def split_person_phrase(phrase: str) -> tuple[str, str]:
    """Separate a spoken name from a role, including 'Shafat on Dancer'."""
    text = " ".join(phrase.split())
    stripped = _LEADING_COMMAND.sub("", text).strip() or text
    stripped = _ALL_THE.sub("", stripped).strip() or stripped
    match = _ON_ROLE.match(stripped)
    if match is None:
        return stripped, ""
    name = match.group("name").strip()
    role = match.group("role").strip(" .")
    if len(name) < 2 or len(role) < 2:
        return stripped, ""
    return name, role


def resolve_person_query(name: str, job_query: str, utterance: str) -> tuple[str, str]:
    resolved_name, resolved_role = split_person_phrase(name) if name.strip() else ("", "")
    spoken_name, spoken_role = split_person_phrase(utterance)
    if len(resolved_name) < 2:
        resolved_name = spoken_name
    if not job_query.strip() and spoken_role:
        resolved_role = spoken_role
    return resolved_name, (job_query.strip() or resolved_role)


def known_person_name(text: str, people: list[NamedPerson]) -> str:
    folded = f" {text.casefold()} "
    names = sorted(
        {person.full_name.strip() for person in people if len(person.full_name.strip()) >= 3},
        key=len,
        reverse=True,
    )
    for name in names:
        if f" {name.casefold()} " in folded:
            return name
    return ""


def plan_from_model_text(text: str) -> CopilotPlan:
    payload = parse_json_object(text)
    action = payload.get("action")
    if action not in _ACTIONS:
        return CopilotPlan(action="reply", message="Tell me the role title and the required skills.")
    message = payload.get("message")
    job = payload.get("job")
    focus = payload.get("focus")
    return CopilotPlan(
        action=action,
        message=message.strip() if isinstance(message, str) else "",
        job=job if isinstance(job, dict) else None,
        job_query=_clean_text(payload.get("job_query")),
        candidate_name=_clean_text(payload.get("candidate_name")),
        other_name=_clean_text(payload.get("other_name")),
        focus=focus if isinstance(focus, str) and focus in _FOCUSES else "summary",  # type: ignore[arg-type]
        place=normalize_place(_clean_text(payload.get("place"))),
    )


def job_request_from_plan(plan: CopilotPlan) -> JobCreateRequest | str:
    if plan.action != "create_job":
        return plan.message or "What role should I draft?"
    raw = dict(plan.job or {})
    title = _clean_text(raw.get("title"))
    skills = _string_list(raw.get("required_skills"))
    if len(title) < 2 or not skills:
        return "I need a role title and at least one required skill before I draft the job."
    seniority = _choice(raw.get("seniority"), _SENIORITY, "Mid-Level")
    contract = _choice(raw.get("contract"), _CONTRACTS, "Full Time")
    category = _clean_text(raw.get("category")) or "Information Technology"
    if category not in JOB_CATEGORIES:
        category = "Information Technology"
    qualifications = _clean_text(raw.get("qualifications")) or "Relevant professional experience"
    technical, experience, qualification = _weights(raw)
    try:
        years = int(raw.get("minimum_years", 0))
    except (TypeError, ValueError):
        years = 0
    years = min(max(years, 0), 50)
    return JobCreateRequest(
        title=title,
        seniority=seniority,  # type: ignore[arg-type]
        required_skills=skills,
        preferred_skills=_string_list(raw.get("preferred_skills")),
        qualifications=qualifications,
        minimum_years=years,
        technical_weight=technical,
        experience_weight=experience,
        qualification_weight=qualification,
        contract=contract,  # type: ignore[arg-type]
        category=category,
    )


def summarize_jobs(jobs: list[JobRead]) -> str:
    if not jobs:
        return "There are no jobs stored yet."
    lines = ["Stored jobs:"]
    for job in jobs:
        latest = job.versions[-1] if job.versions else None
        if latest is None:
            lines.append(f"- {job.title}")
            continue
        lines.append(f"- {job.title}, version {latest.version_number}, {latest.status}")
    return "\n".join(lines)


def job_query_text(plan: CopilotPlan) -> str:
    if plan.job_query.strip():
        return plan.job_query.strip()
    if isinstance(plan.job, dict):
        return _clean_text(plan.job.get("title"))
    return ""


def select_jobs(jobs: list[NamedJob], query: str) -> JobMatch:
    needle = " ".join(query.casefold().split())
    if len(needle) < 2:
        return JobMatch(None, [], "missing")
    exact = [job for job in jobs if job.title.casefold() == needle]
    matches = exact or [
        job for job in jobs if needle in job.title.casefold() or job.title.casefold() in needle
    ]
    if not matches:
        return JobMatch(None, [], "unknown")
    if len(matches) > 1:
        return JobMatch(None, matches, "ambiguous")
    return JobMatch(matches[0], matches, "ok")


def select_people(people: list[NamedPerson], name: str, *, job_id: uuid.UUID | None = None) -> list[NamedPerson]:
    pool = [person for person in people if job_id is None or person.job_id == job_id]
    needle = " ".join(name.casefold().split())
    if len(needle) < 2:
        return []
    exact = [person for person in pool if person.full_name.casefold() == needle]
    if exact:
        return exact
    return [person for person in pool if needle in person.full_name.casefold()]


def order_people(people: list[NamedPerson]) -> list[NamedPerson]:
    return sorted(
        people,
        key=lambda person: (
            person.overall_score is None,
            -(person.overall_score or 0),
            person.rank is None,
            person.rank or 10_000,
            person.full_name.casefold(),
        ),
    )


def ranking_message(job_title: str, people: list[NamedPerson]) -> str:
    if not people:
        return f"{job_title} has no applicants yet."
    lines = [f"{job_title} ranking:"]
    for index, person in enumerate(order_people(people), start=1):
        lines.append(f"{index}. {_person_line(person)}")
    return "\n".join(lines)


def explain_pair(left: NamedPerson, right: NamedPerson) -> str:
    if left.job_id != right.job_id:
        return (
            f"{left.full_name} is on {left.job_title} and {right.full_name} is on {right.job_title}. "
            "Ranks are compared within one role."
        )
    if left.id == right.id:
        return "Name two different people on the same role."
    gaps = (
        "Key gap — "
        f"{left.full_name}: {_gap_text(left)}. "
        f"{right.full_name}: {_gap_text(right)}."
    )
    if _level(left, right):
        note = _dimension_note(left, right)
        subject = "overall score" if left.overall_score is not None else "the stored CV rank"
        lines = [f"{left.full_name} and {right.full_name} are level on {subject} for {left.job_title}."]
        if note:
            lines.append(note)
        lines.extend([_score_sentence(left), _score_sentence(right), gaps])
        return "\n".join(lines)
    ahead, behind = _ahead_pair(left, right)
    return "\n".join(
        [
            f"{ahead.full_name} is ahead of {behind.full_name} on {ahead.job_title}.",
            _score_sentence(ahead),
            _score_sentence(behind),
            gaps,
        ]
    )


def pipeline_message(boards: list[ProgressBoardRead], focus: CopilotFocus) -> str:
    sections: list[str] = []
    if focus in {"stuck", "summary"}:
        sections.append(_stuck_section(boards))
    if focus in {"empty", "summary"}:
        sections.append(_empty_section(boards))
    return "\n\n".join(sections)


def rank_from_records(jobs: list[NamedJob], people: list[NamedPerson], query: str) -> CopilotTurnResponse:
    match = select_jobs(jobs, query)
    missed = _job_choice("rank_job", query, match)
    if missed is not None:
        return missed
    assert match.job is not None
    chosen = [person for person in people if person.job_id == match.job.id]
    if not chosen:
        return CopilotTurnResponse(
            message=f"{match.job.title} has no applicants yet.",
            navigation=CopilotNavigation(href=progress_target(), label="Open interviews"),
            chips=[_navigate("Open interviews", progress_target())],
        )
    ordered = order_people(chosen)
    top = ordered[0]
    chips = [
        _navigate("Show ranking", ranking_target(match.job.id)),
        _navigate(f"Open {top.full_name}", person_target(top.id)[0]),
    ]
    if top.assessed:
        chips.append(CopilotChip(label="Open report", kind="report", candidate_id=top.id))
    href = ranking_target(match.job.id)
    return CopilotTurnResponse(
        message=ranking_message(match.job.title, chosen),
        navigation=CopilotNavigation(href=href, label="Show ranking"),
        chips=chips,
    )


def open_candidate_from_records(
    jobs: list[NamedJob],
    people: list[NamedPerson],
    *,
    name: str,
    job_query: str,
    utterance: str = "",
) -> CopilotTurnResponse:
    resolved_name, resolved_role = resolve_person_query(name, job_query, utterance)
    if wants_every_match(utterance):
        resolved_role = ""
    job_id, job_title, missed = _scoped_job(jobs, resolved_role, "open_candidate")
    if missed is not None:
        return missed
    return _open_person(
        people,
        resolved_name,
        job_id=job_id,
        job_title=job_title,
        report=False,
        utterance=utterance,
    )


def explain_from_records(
    jobs: list[NamedJob],
    people: list[NamedPerson],
    *,
    left_name: str,
    right_name: str,
    job_query: str,
) -> CopilotTurnResponse:
    if len(left_name.strip()) < 2 or len(right_name.strip()) < 2:
        return CopilotTurnResponse(message="Which two people should I compare?")
    job_id, job_title, missed = _scoped_job(jobs, job_query, "explain_rank")
    if missed is not None:
        return missed
    left = select_people(people, left_name, job_id=job_id)
    right = select_people(people, right_name, job_id=job_id)
    if len(left) != 1 or len(right) != 1:
        return _people_choice(left_name if len(left) != 1 else right_name, left if len(left) != 1 else right, job_title)
    if left[0].id == right[0].id:
        return CopilotTurnResponse(message="Name two different people on the same role.")
    if left[0].job_id != right[0].job_id:
        return CopilotTurnResponse(message=explain_pair(left[0], right[0]))
    href = compare_target(left[0].job_id, left[0].id, right[0].id)
    return CopilotTurnResponse(
        message=f"Opening the comparison of {left[0].full_name} and {right[0].full_name}.",
        navigation=CopilotNavigation(href=href, label="Open comparison"),
        chips=[_navigate("Open comparison", href)],
    )


def open_job_from_records(jobs: list[NamedJob], query: str) -> CopilotTurnResponse:
    match = select_jobs(jobs, query)
    missed = _job_choice("open_job", query, match)
    if missed is not None:
        return missed
    assert match.job is not None
    href = job_target("job_brief", match.job.id)[0]
    status = f", {match.job.status}" if match.job.status else ""
    return CopilotTurnResponse(
        message=f"Opening {match.job.title}{status}.",
        navigation=CopilotNavigation(href=href, label="Review draft"),
        chips=[_navigate("Review draft", href)],
    )


def open_report_from_records(
    jobs: list[NamedJob],
    people: list[NamedPerson],
    *,
    name: str,
    job_query: str,
) -> CopilotTurnResponse:
    job_id, job_title, missed = _scoped_job(jobs, job_query, "open_report")
    if missed is not None:
        return missed
    return _open_person(people, name, job_id=job_id, job_title=job_title, report=True)


def pipeline_from_boards(boards: list[ProgressBoardRead], focus: CopilotFocus) -> CopilotTurnResponse:
    return CopilotTurnResponse(
        message=pipeline_message(boards, focus),
        navigation=CopilotNavigation(href=progress_target(), label="Open interviews"),
        chips=[_navigate("Open interviews", progress_target())],
    )


def navigate_from_records(
    jobs: list[NamedJob],
    people: list[NamedPerson],
    policies: list[tuple[uuid.UUID, str]],
    *,
    place: str,
    job_query: str,
    candidate_name: str,
) -> CopilotTurnResponse:
    if not place:
        return CopilotTurnResponse(message="Where should I take you? Home, policies, jobs, candidates, interviews, or practice.")
    static = static_target(place)
    if static is not None:
        href, label = static
        return _open_place(label, href)
    if place == "policy":
        return _open_policy(policies, job_query)
    if place in JOB_PLACES:
        match = select_jobs(jobs, job_query)
        missed = _job_choice(place, job_query, match)
        if missed is not None:
            return missed
        assert match.job is not None
        target = job_target(place, match.job.id)
        assert target is not None
        return _open_place(f"{target[1]} for {match.job.title}", target[0])
    if place == "person":
        return open_candidate_from_records(jobs, people, name=candidate_name, job_query=job_query)
    return CopilotTurnResponse(message="Where should I take you? Home, policies, jobs, candidates, interviews, or practice.")


def offer_approve_from_records(jobs: list[NamedJob], query: str) -> CopilotTurnResponse:
    match = select_jobs(jobs, query)
    missed = _job_choice("offer_approve", query, match)
    if missed is not None:
        return missed
    assert match.job is not None
    job = match.job
    brief = job_target("job_brief", job.id)
    assert brief is not None
    if job.status != "draft":
        state = job.status or "stored"
        return CopilotTurnResponse(
            message=f"{job.title} is already {state}. Open the brief if it needs a new version.",
            navigation=CopilotNavigation(href=brief[0], label="Open brief"),
            chips=[_navigate("Open brief", brief[0])],
        )
    return CopilotTurnResponse(
        message=f"Approve and post {job.title}? This locks version {job.version_number} and publishes it.",
        chips=[
            CopilotChip(
                label=f"Approve and post {job.title}",
                kind="confirm",
                confirm="approve",
                job_id=job.id,
                version_number=job.version_number,
            )
        ],
    )


def offer_inbox_turn() -> CopilotTurnResponse:
    return CopilotTurnResponse(
        message="Check the apply mailbox? Unread CVs are scored. You choose who to invite from the ranking.",
        chips=[CopilotChip(label="Check inbox", kind="confirm", confirm="inbox")],
    )


def practice_turn(session_id: uuid.UUID, token: str, role: str, guest_url: str) -> CopilotTurnResponse:
    return CopilotTurnResponse(
        message=(
            f"Practice room ready. Guest link: {guest_url}\n"
            "Paste that link on another device. You are entering the call as the interviewer."
        ),
        navigation=CopilotNavigation(href=f"/interview/{session_id}", label="Enter the call"),
        practice=CopilotPractice(session_id=session_id, token=token, role=role, guest_url=guest_url),
    )


def _open_place(label: str, href: str) -> CopilotTurnResponse:
    return CopilotTurnResponse(
        message=f"Opening {label}.",
        navigation=CopilotNavigation(href=href, label=label),
        chips=[_navigate(label, href)],
    )


def _open_policy(policies: list[tuple[uuid.UUID, str]], query: str) -> CopilotTurnResponse:
    needle = " ".join(query.casefold().split())
    if len(needle) < 2:
        return CopilotTurnResponse(message="Which policy should I open?")
    exact = [item for item in policies if item[1].casefold() == needle]
    matches = exact or [item for item in policies if needle in item[1].casefold() or item[1].casefold() in needle]
    if not matches:
        return CopilotTurnResponse(message=f'No stored policy matches "{query.strip()}".')
    if len(matches) > 1:
        lines = ["Which policy do you mean?"]
        chips: list[CopilotChip] = []
        for _document_id, filename in matches:
            lines.append(f"- {filename}")
            chips.append(CopilotChip(label=filename, kind="prompt", prompt=f"Open the policy {filename}"))
        return CopilotTurnResponse(message="\n".join(lines), chips=chips)
    href, label = policy_target(matches[0][0])
    return _open_place(f"{label} {matches[0][1]}", href)


async def _direct_people_turn(
    session: AsyncSession | None,
    settings: Settings,
    messages: list[CopilotMessage],
) -> CopilotTurnResponse | None:
    """Answer a clear people command from stored names when the planner only replies."""
    text = latest_user_text(messages)
    if session is None or not looks_like_people_request(text):
        return None
    jobs, people = await _records(session, settings)
    name = known_person_name(text, people)
    if not name:
        return None
    _, role = split_person_phrase(text)
    if wants_every_match(text):
        role = ""
    return open_candidate_from_records(jobs, people, name=name, job_query=role, utterance=text)


async def run_copilot_turn(
    session: AsyncSession | None,
    messages: list[CopilotMessage],
    *,
    llm: FallbackLLMManager,
    retriever: PolicyRetriever,
    settings: Settings,
    host: str = "",
) -> CopilotTurnResponse:
    if not isinstance(llm, FallbackLLMManager):
        raise TypeError("The copilot requires FallbackLLMManager.")
    response = await llm.complete(
        f"Conversation:\n{conversation_transcript(messages)}",
        system=PLANNER_SYSTEM,
    )
    try:
        plan = plan_from_model_text(response.content)
    except JobGraphError:
        return CopilotTurnResponse(message="I could not read a job request. Tell me the role title and required skills.")
    if plan.action == "list_jobs":
        stored = await list_jobs(_require_session(session), settings)
        return CopilotTurnResponse(message=summarize_jobs(stored))
    if plan.action == "list_policies":
        documents = await list_policies(_require_session(session))
        if not documents:
            return CopilotTurnResponse(message="No company policies are indexed yet.")
        lines = ["Indexed policies:"]
        lines.extend(f"- {document.filename}, {len(document.chunks)} chunks" for document in documents)
        return CopilotTurnResponse(message="\n".join(lines))
    if plan.action == "rank_job":
        jobs, people = await _records(session, settings)
        return rank_from_records(jobs, people, job_query_text(plan))
    if plan.action == "reply":
        direct = await _direct_people_turn(session, settings, messages)
        if direct is not None:
            return direct
    if plan.action == "open_candidate":
        jobs, people = await _records(session, settings)
        utterance = latest_user_text(messages)
        name, job_query = resolve_person_query(plan.candidate_name, job_query_text(plan), utterance)
        return open_candidate_from_records(
            jobs,
            people,
            name=name,
            job_query=job_query,
            utterance=utterance,
        )
    if plan.action == "explain_rank":
        jobs, people = await _records(session, settings)
        return explain_from_records(
            jobs,
            people,
            left_name=plan.candidate_name,
            right_name=plan.other_name,
            job_query=job_query_text(plan),
        )
    if plan.action == "pipeline":
        boards = await list_progress(_require_session(session))
        return pipeline_from_boards(boards, plan.focus)
    if plan.action == "open_job":
        jobs, _people = await _records(session, settings)
        return open_job_from_records(jobs, job_query_text(plan))
    if plan.action == "open_report":
        jobs, people = await _records(session, settings)
        utterance = latest_user_text(messages)
        name, job_query = resolve_person_query(plan.candidate_name, job_query_text(plan), utterance)
        return open_report_from_records(jobs, people, name=name, job_query=job_query)
    if plan.action == "navigate":
        jobs, people = await _records(session, settings)
        documents = await list_policies(_require_session(session))
        policies = [(document.id, document.filename) for document in documents]
        return navigate_from_records(
            jobs,
            people,
            policies,
            place=plan.place,
            job_query=job_query_text(plan),
            candidate_name=plan.candidate_name,
        )
    if plan.action == "offer_approve":
        jobs, _people = await _records(session, settings)
        return offer_approve_from_records(jobs, job_query_text(plan))
    if plan.action == "offer_inbox":
        return offer_inbox_turn()
    if plan.action == "start_practice":
        opened, guest_url = await open_practice_session(_require_session(session), settings, host or "localhost")
        return practice_turn(opened.session_id, opened.token, opened.role, guest_url)
    if plan.action != "create_job":
        return CopilotTurnResponse(message=plan.message or "Tell me the role you want to draft.")
    prepared = job_request_from_plan(plan)
    if isinstance(prepared, str):
        return CopilotTurnResponse(message=prepared)
    created = await create_job(
        _require_session(session),
        prepared,
        llm=llm,
        retriever=retriever,
        settings=settings,
    )
    return CopilotTurnResponse(
        message=(
            f"Draft ready for {created.title}, version 1. "
            "It has 10 checklist queries and stays unlocked until you approve it."
        ),
        job=created,
    )


def _require_session(session: AsyncSession | None) -> AsyncSession:
    if session is None:
        raise RuntimeError("This copilot action needs a database session.")
    return session


def _clean_text(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""


def _string_list(value: object) -> list[str]:
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    if isinstance(value, list):
        return [item.strip() for item in value if isinstance(item, str) and item.strip()]
    return []


def _choice(value: object, allowed: frozenset[str], default: str) -> str:
    text = _clean_text(value)
    return text if text in allowed else default


def _weights(raw: dict[str, object]) -> tuple[float, float, float]:
    technical = _unit_float(raw.get("technical_weight"), 0.5)
    experience = _unit_float(raw.get("experience_weight"), 0.3)
    qualification = _unit_float(raw.get("qualification_weight"), 0.2)
    total = technical + experience + qualification
    if abs(total - 1.0) > 0.001 or total <= 0:
        return 0.5, 0.3, 0.2
    return technical, experience, qualification


def _unit_float(value: object, default: float) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return default
    number = float(value)
    if number < 0 or number > 1:
        return default
    return number


def _navigate(label: str, href: str) -> CopilotChip:
    return CopilotChip(label=label, kind="navigate", href=href)


def _job_prompt(action: str, title: str) -> str:
    if action == "open_job" or action == "job_brief":
        return f"Open the brief for {title}"
    if action == "job_people":
        return f"Open the applicants tab for {title}"
    if action == "portraits":
        return f"Open the portraits for {title}"
    if action == "standing":
        return f"Open the standing for {title}"
    if action == "offer_approve":
        return f"Approve and post {title}"
    if action == "open_report":
        return f"Open the report for {title}"
    if action == "explain_rank":
        return f"Compare ranks on {title}"
    if action == "open_candidate":
        return f"Open candidates for {title}"
    return f"Rank candidates for {title}"


def _job_choice(action: str, query: str, match: JobMatch) -> CopilotTurnResponse | None:
    if match.reason == "ok":
        return None
    if match.reason == "missing":
        return CopilotTurnResponse(message="Which role do you mean?")
    if match.reason == "unknown":
        shown = query.strip() or "that title"
        return CopilotTurnResponse(message=f'No stored job matches "{shown}".')
    lines = ["Which role do you mean?"]
    chips: list[CopilotChip] = []
    for job in match.matches:
        lines.append(f"- {job.title}")
        chips.append(CopilotChip(label=job.title, kind="prompt", prompt=_job_prompt(action, job.title)))
    return CopilotTurnResponse(message="\n".join(lines), chips=chips)


def _scoped_job(
    jobs: list[NamedJob],
    job_query: str,
    action: str,
) -> tuple[uuid.UUID | None, str, CopilotTurnResponse | None]:
    if not job_query.strip():
        return None, "", None
    match = select_jobs(jobs, job_query)
    missed = _job_choice(action, job_query, match)
    if missed is not None:
        return None, "", missed
    assert match.job is not None
    return match.job.id, match.job.title, None


def _person_label(person: NamedPerson, peers: list[NamedPerson]) -> str:
    shared = sum(1 for other in peers if other.full_name.casefold() == person.full_name.casefold())
    if shared > 1 and person.job_title.strip():
        return f"{person.full_name} · {person.job_title}"
    return person.full_name


def _profile_chip(person: NamedPerson, peers: list[NamedPerson]) -> CopilotChip:
    return _navigate(_person_label(person, peers), person_target(person.id)[0])


def _people_roster(name: str, matches: list[NamedPerson]) -> CopilotTurnResponse:
    ordered = order_people(matches)
    title = name.strip() or "that name"
    lines = [f"{len(ordered)} stored people match {title}:"]
    for person in ordered:
        lines.append(f"- {_person_line(person)}")
    return CopilotTurnResponse(
        message="\n".join(lines),
        chips=[_profile_chip(person, ordered) for person in ordered],
    )


def _people_choice(
    name: str,
    matches: list[NamedPerson],
    job_title: str,
    *,
    utterance: str = "",
) -> CopilotTurnResponse:
    if not matches:
        where = f" on {job_title}" if job_title else ""
        label = name.strip() or "that name"
        return CopilotTurnResponse(message=f"No stored candidate matches {label}{where}.")
    if wants_every_match(utterance):
        return _people_roster(name, matches)
    shown = sorted(matches, key=lambda person: (person.job_title.casefold(), person.full_name.casefold()))
    lines = [f"Which person matches {name.strip()}?"]
    for person in shown:
        lines.append(f"- {person.full_name} on {person.job_title}")
    return CopilotTurnResponse(
        message="\n".join(lines),
        chips=[_profile_chip(person, shown) for person in shown],
    )


def _open_person(
    people: list[NamedPerson],
    name: str,
    *,
    job_id: uuid.UUID | None,
    job_title: str,
    report: bool,
    utterance: str = "",
) -> CopilotTurnResponse:
    matches = select_people(people, name, job_id=job_id)
    if len(matches) != 1:
        return _people_choice(name, matches, job_title, utterance=utterance)
    person = matches[0]
    href = person_target(person.id)[0]
    chips = [
        _navigate("Show ranking", ranking_target(person.job_id)),
        _navigate(f"Open {person.full_name}", href),
    ]
    report_id = person.id if report and person.assessed else None
    if person.assessed:
        chips.append(CopilotChip(label="Open report", kind="report", candidate_id=person.id))
    if report and person.assessed:
        message = f"The HTML report for {person.full_name} is ready.\n{_person_line(person)}"
    elif report:
        message = f"No master assessment report for {person.full_name} yet.\n{_person_line(person)}"
    else:
        message = _person_line(person)
    return CopilotTurnResponse(
        message=message,
        navigation=CopilotNavigation(href=href, label=person.full_name),
        chips=chips,
        report_candidate_id=report_id,
    )


def _person_line(person: NamedPerson) -> str:
    if person.assessed and person.overall_score is not None:
        label = person.suitability_label or "unlabeled"
        return (
            f"{person.full_name} on {person.job_title} — overall {person.overall_score:.1f}, {label}. "
            f"Key gap: {_gap_text(person)}."
        )
    if person.rank is not None and person.aggregate_score is not None:
        return (
            f"{person.full_name} on {person.job_title} — CV rank #{person.rank}, "
            f"score {person.aggregate_score:.2f}. No master assessment yet."
        )
    return f"{person.full_name} on {person.job_title} — CV not scored yet."


def _score_sentence(person: NamedPerson) -> str:
    parts = [_person_line(person)]
    if person.assessed:
        parts.append(
            "CV dimensions "
            f"technical {_points(person.technical_dimension)}, "
            f"experience {_points(person.experience_dimension)}, "
            f"qualification {_points(person.qualification_dimension)}. "
            f"Quiz {_points(person.mcq_score)}. Interview Q&A {_points(person.interview_qa)}."
        )
    return " ".join(parts)


def _level(left: NamedPerson, right: NamedPerson) -> bool:
    if left.overall_score is not None or right.overall_score is not None:
        return left.overall_score == right.overall_score
    return left.rank == right.rank


def _dimension_note(left: NamedPerson, right: NamedPerson) -> str:
    pairs = [
        ("technical", left.technical_dimension, right.technical_dimension),
        ("experience", left.experience_dimension, right.experience_dimension),
        ("qualification", left.qualification_dimension, right.qualification_dimension),
        ("quiz", left.mcq_score, right.mcq_score),
        ("interview Q&A", left.interview_qa, right.interview_qa),
    ]
    notes: list[str] = []
    for label, first, second in pairs:
        if first is None or second is None or first == second:
            continue
        leader = left if first > second else right
        high = first if first > second else second
        low = second if first > second else first
        notes.append(f"{leader.full_name} leads on {label} ({_points(high)} vs {_points(low)}).")
    return " ".join(notes)


def _ahead_pair(left: NamedPerson, right: NamedPerson) -> tuple[NamedPerson, NamedPerson]:
    ordered = order_people([left, right])
    if ordered[0].id == ordered[1].id:
        return left, right
    return ordered[0], ordered[1]


def _gap_text(person: NamedPerson) -> str:
    if not person.assessed:
        return "Not assessed"
    return person.key_gap or "None"


def _points(value: float | None) -> str:
    if value is None:
        return "—"
    return f"{value:.1f}"


def _stuck_section(boards: list[ProgressBoardRead]) -> str:
    invited = _cards(boards, "invited")
    ended = _cards(boards, "interview", status="ended")
    started = _cards(boards, "interview", status="started")
    quiz = _cards(boards, "quiz")
    return "\n".join(
        [
            "Invited, interview not started:",
            _bullet_or_none(invited),
            "Interview in progress:",
            _bullet_or_none(started),
            "Interview finished, quiz missing:",
            _bullet_or_none(ended),
            "Quiz done, master assessment missing:",
            _bullet_or_none(quiz),
        ]
    )


def _empty_section(boards: list[ProgressBoardRead]) -> str:
    titles = [board.job_title for board in boards if board.applicant_count == 0]
    if not titles:
        return "Roles with no applicants:\nNone. Every stored role has at least one applicant."
    lines = ["Roles with no applicants:"]
    lines.extend(f"- {title}" for title in titles)
    return "\n".join(lines)


def _cards(boards: list[ProgressBoardRead], stage: str, *, status: str = "") -> list[str]:
    lines: list[str] = []
    for board in boards:
        column = next((item for item in board.columns if item.stage == stage), None)
        if column is None:
            continue
        for card in column.cards:
            if status and card.interview_status != status:
                continue
            lines.append(f"{card.full_name} on {board.job_title}")
    lines.sort(key=str.casefold)
    return lines


def _bullet_or_none(lines: list[str]) -> str:
    if not lines:
        return "- None"
    return "\n".join(f"- {line}" for line in lines)


async def _records(session: AsyncSession | None, settings: Settings) -> tuple[list[NamedJob], list[NamedPerson]]:
    stored = await list_jobs(_require_session(session), settings)
    jobs = [
        NamedJob(
            id=job.id,
            title=job.title,
            status=job.versions[-1].status if job.versions else "",
            version_number=job.versions[-1].version_number if job.versions else 1,
        )
        for job in stored
    ]
    groups = await list_candidate_groups(_require_session(session))
    comparisons = {
        row.candidate_id: row
        for comparison in await list_comparisons(_require_session(session))
        for row in comparison.rows
    }
    people: list[NamedPerson] = []
    for group in groups:
        for candidate in group.candidates:
            row = comparisons.get(candidate.id)
            assessed = row is not None and row.overall_suitability is not None
            people.append(
                NamedPerson(
                    id=candidate.id,
                    full_name=candidate.full_name,
                    job_id=group.job_id,
                    job_title=group.job_title,
                    rank=candidate.rank,
                    aggregate_score=candidate.aggregate_score,
                    overall_score=row.overall_score if row is not None else None,
                    suitability_label=row.suitability_label if row is not None else "",
                    key_gap=row.key_gap if row is not None else "",
                    technical_dimension=row.technical_dimension if row is not None else None,
                    experience_dimension=row.experience_dimension if row is not None else None,
                    qualification_dimension=row.qualification_dimension if row is not None else None,
                    mcq_score=row.mcq_score if row is not None else None,
                    interview_qa=row.interview_qa if row is not None else None,
                    assessed=assessed,
                )
            )
    return jobs, people
