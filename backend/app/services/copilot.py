from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.llm_fallback import FallbackLLMManager
from app.graphs.job_creation_graph import JobGraphError, PolicyRetriever, parse_json_object
from app.schemas.copilot import CopilotMessage, CopilotPlan, CopilotTurnResponse
from app.schemas.job import JOB_CATEGORIES, JobCreateRequest, JobRead
from app.services.job_service import create_job, list_jobs
from app.services.policy_ingest import list_policies

PLANNER_SYSTEM = (
    "You are the Sift recruiter copilot. You draft jobs through the policy workflow and "
    "answer questions about jobs and uploaded policies that are already stored. "
    "Return only a JSON object with keys action, message, and job. "
    "action is one of reply, create_job, list_jobs, list_policies. "
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
    "Do not approve, lock, or post a job. Do not invent stored records."
)

_SENIORITY: frozenset[str] = frozenset({"Junior", "Mid-Level", "Senior", "Not specified"})
_CONTRACTS: frozenset[str] = frozenset({"Full Time", "Part Time", "Freelance", "Internship"})


def conversation_transcript(messages: list[CopilotMessage]) -> str:
    lines = [f"{message.role}: {message.content.strip()}" for message in messages[-12:]]
    return "\n".join(lines)


def plan_from_model_text(text: str) -> CopilotPlan:
    payload = parse_json_object(text)
    action = payload.get("action")
    if action not in {"reply", "create_job", "list_jobs", "list_policies"}:
        return CopilotPlan(action="reply", message="Tell me the role title and the required skills.")
    message = payload.get("message")
    job = payload.get("job")
    return CopilotPlan(
        action=action,
        message=message.strip() if isinstance(message, str) else "",
        job=job if isinstance(job, dict) else None,
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


async def run_copilot_turn(
    session: AsyncSession | None,
    messages: list[CopilotMessage],
    *,
    llm: FallbackLLMManager,
    retriever: PolicyRetriever,
    settings: Settings,
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
