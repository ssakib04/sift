"""LangGraph Workflow 1: job description synthesis and locked checklist."""

import math
import re
from typing import Any, Literal, TypeVar, cast

from langchain_core.runnables import Runnable
from langgraph.graph import END, StateGraph
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.core.llm import get_llm_client
from app.models.job import Job, JobChecklistQuery, JobVersion
from app.schemas.job_creation import (
    DimensionalWeights,
    GeneratedJobDescription,
    JobCreationState,
    LockedChecklistQuery,
    QueryId,
)

ModelT = TypeVar("ModelT", bound=BaseModel)

_SENIORITY_YEARS: dict[str, int] = {
    "intern": 0,
    "junior": 1,
    "mid": 3,
    "senior": 5,
    "lead": 7,
    "staff": 8,
    "principal": 10,
}
_SENIORITY_LABELS: dict[str, str] = {
    "intern": "Intern",
    "junior": "Junior",
    "mid": "Mid",
    "senior": "Senior",
    "lead": "Lead",
    "staff": "Staff",
    "principal": "Principal",
}
_POLICY_INDEX: tuple[tuple[str, str], ...] = (
    (
        "salary",
        "Salary bands are tied to seniority and reviewed annually. Junior roles range from "
        "60000 to 85000 USD. Mid-level roles range from 90000 to 120000 USD. Senior roles "
        "range from 130000 to 170000 USD. Lead and principal roles range from 175000 to "
        "220000 USD. Offers above the published band require director approval.",
    ),
    (
        "remote",
        "Remote work policy: individual contributor roles may be fully remote inside the "
        "hiring country. Hybrid roles within 50 miles of an office require two on-site days "
        "each week. International remote arrangements need legal approval. A secure network "
        "and company equipment are required.",
    ),
    (
        "diversity",
        "Diversity guidelines: job descriptions use inclusive language and list only "
        "job-related requirements. Do not use proxies for age, gender, ethnicity, religion, "
        "or disability. Preferred skills must stay preferred. Evaluate applicants on skills "
        "and experience.",
    ),
)
_WEIGHT_TOLERANCE = 0.02
_MAX_SCHEMA_RETRIES = 2
_QUERY_IDS = tuple(f"Q{index}" for index in range(1, 11))


class _ChecklistQueryDraft(BaseModel):
    """LLM payload for one checklist query before ids and weights are frozen."""

    model_config = ConfigDict(extra="ignore")

    query_id: str = ""
    question: str = Field(min_length=1)
    dimension: Literal["technical", "experience", "qualification"]
    requirement_type: Literal["must_have", "preferred"]
    weight: float = Field(ge=0)
    evidence_hints: list[str] = Field(default_factory=list)
    scoring_rubric: str = Field(min_length=1)


class _ScoringPlan(BaseModel):
    """Structured scoring weights and the ten locked queries."""

    model_config = ConfigDict(extra="ignore")

    technical: float = 0.50
    experience: float = 0.30
    qualification: float = 0.20
    queries: list[_ChecklistQueryDraft] = Field(min_length=10, max_length=10)


def collect_role_inputs_node(state: JobCreationState) -> dict[str, Any]:
    """Normalize the recruiter prompt into role title, seniority, skills, and experience."""
    raw_prompt = (state.get("raw_prompt") or state.get("role_title") or "").strip()
    role_title = (state.get("role_title") or raw_prompt).strip()
    seniority_level = (state.get("seniority_level") or _infer_seniority(role_title)).strip()
    core_skills = [skill.strip() for skill in state.get("core_skills") or [] if skill.strip()]
    if not core_skills:
        core_skills = _infer_skills(role_title, seniority_level)
    if "min_years_exp" in state:
        min_years_exp = int(state["min_years_exp"])
    else:
        min_years_exp = _SENIORITY_YEARS.get(seniority_level.lower(), 0)
    return {
        "role_title": role_title,
        "seniority_level": seniority_level,
        "core_skills": core_skills,
        "min_years_exp": min_years_exp,
        "raw_prompt": raw_prompt or role_title,
        "clarifying_questions": list(state.get("clarifying_questions") or []),
        "recruiter_answers": list(state.get("recruiter_answers") or []),
        "validation_errors": list(state.get("validation_errors") or []),
        "schema_valid": False,
    }


def retrieve_policy_rules_node(state: JobCreationState) -> dict[str, list[str]]:
    """Rank company policy chunks against the role with term-vector cosine similarity."""
    query = " ".join(
        [
            state.get("role_title") or "",
            state.get("seniority_level") or "",
            " ".join(state.get("core_skills") or []),
            state.get("raw_prompt") or "",
        ]
    )
    return {"retrieved_policy_chunks": _retrieve_policy_chunks(query)}


def check_role_clarity_node(state: JobCreationState) -> dict[str, Any]:
    """Decide whether the role inputs are complete enough to synthesize a job description."""
    missing = _missing_role_fields(state)
    return {
        "is_clear": not missing,
        "clarifying_questions": [] if not missing else [_question_for(field) for field in missing],
    }


def ask_clarifying_questions_node(state: JobCreationState) -> dict[str, Any]:
    """Merge recruiter answers into the role context for the next clarity check."""
    answers = [answer.strip() for answer in state.get("recruiter_answers") or [] if answer.strip()]
    skills = [skill.strip() for skill in state.get("core_skills") or [] if skill.strip()]
    title = (state.get("role_title") or "").strip()
    seniority = (state.get("seniority_level") or _infer_seniority(title)).strip()
    years = state.get("min_years_exp")
    if not isinstance(years, int):
        years = _SENIORITY_YEARS.get(seniority.lower(), 0)
    if answers:
        skills.extend(answers)
    elif not skills and title:
        skills = _infer_skills(title, seniority)
    prompt = state.get("raw_prompt") or title
    if answers:
        prompt = f"{prompt}\nRecruiter clarifications:\n" + "\n".join(answers)
    return {
        "role_title": title,
        "seniority_level": seniority,
        "core_skills": skills,
        "min_years_exp": years,
        "raw_prompt": prompt,
        "recruiter_answers": answers,
    }


async def synthesize_jd_node(state: JobCreationState) -> dict[str, Any]:
    """Generate a policy-aware job description with structured LLM output."""
    structured: Runnable[Any, Any] = get_llm_client(temperature=0.2).with_structured_output(
        GeneratedJobDescription
    )
    try:
        payload = await structured.ainvoke(_job_description_prompt(state))
        job_description = _coerce_model(payload, GeneratedJobDescription)
    except Exception:
        job_description = _job_description_from_inputs(state)
    return {"synthesized_jd": job_description.model_dump()}


async def generate_scoring_weights_node(state: JobCreationState) -> dict[str, Any]:
    """Generate exactly ten locked checklist queries whose weights sum to 1."""
    structured: Runnable[Any, Any] = get_llm_client(temperature=0.0).with_structured_output(
        _ScoringPlan
    )
    try:
        payload = await structured.ainvoke(_scoring_prompt(state))
        plan = _coerce_model(payload, _ScoringPlan)
        weights = _normalize_dimensional_weights(plan.technical, plan.experience, plan.qualification)
        checklist = _freeze_queries(plan.queries)
    except Exception:
        weights = DimensionalWeights()
        checklist = _checklist_from_inputs(state)
    return {
        "dimensional_weights": weights.model_dump(),
        "locked_checklist": [query.model_dump() for query in checklist],
    }


def validate_schema_node(state: JobCreationState) -> dict[str, Any]:
    """Require a job description, ten queries, and checklist weights near 1.0."""
    errors: list[str] = []
    synthesized = state.get("synthesized_jd")
    if not synthesized:
        errors.append("synthesized_jd is missing")
    else:
        try:
            GeneratedJobDescription.model_validate(synthesized)
        except ValidationError as exc:
            errors.append(f"synthesized_jd is invalid: {exc.errors()[0]['msg']}")

    checklist = state.get("locked_checklist") or []
    if len(checklist) != 10:
        errors.append(f"locked_checklist must contain exactly 10 queries, found {len(checklist)}")
    else:
        try:
            queries = [LockedChecklistQuery.model_validate(item) for item in checklist]
        except ValidationError as exc:
            errors.append(f"locked_checklist is invalid: {exc.errors()[0]['msg']}")
        else:
            total_weight = sum(query.weight for query in queries)
            if abs(total_weight - 1.0) > _WEIGHT_TOLERANCE:
                errors.append(f"checklist weights sum to {total_weight:.4f}, expected 1.0")

    prior_attempts = _validation_attempts(state.get("validation_errors") or [])
    if errors:
        errors.append(f"validation attempt {prior_attempts + 1}")
    return {"schema_valid": not errors, "validation_errors": errors}


def post_job_to_linkedin_node(state: JobCreationState) -> dict[str, str]:
    """Freeze the checklist on a job version and return its id."""
    synthesized = state.get("synthesized_jd") or {}
    title = str(synthesized.get("title") or state.get("role_title") or "").strip()
    seniority = str(synthesized.get("seniority") or state.get("seniority_level") or "").strip()
    job = Job(title=title, seniority=seniority)
    version = JobVersion(
        job_id=job.id,
        version_number=1,
        synthesized_jd=dict(synthesized),
        dimensional_weights=dict(state.get("dimensional_weights") or DimensionalWeights().model_dump()),
        is_frozen=True,
        schema_valid=True,
    )
    frozen_queries = [
        JobChecklistQuery(
            job_version_id=version.id,
            query_id=str(item["query_id"]),
            question=str(item["question"]),
            dimension=str(item["dimension"]),
            requirement_type=str(item["requirement_type"]),
            weight=float(item["weight"]),
            evidence_hints=[str(hint) for hint in item.get("evidence_hints") or []],
            scoring_rubric=str(item["scoring_rubric"]),
        )
        for item in state.get("locked_checklist") or []
    ]
    if len(frozen_queries) != 10:
        raise ValueError("locked checklist must contain 10 queries before it can be frozen")
    return {"job_version_id": str(version.id)}


def route_clarity(state: JobCreationState) -> Literal["synthesize_jd", "ask_clarifying_questions"]:
    """Send a clear role to synthesis and an incomplete role back for answers."""
    if state.get("is_clear"):
        return "synthesize_jd"
    return "ask_clarifying_questions"


def route_validation(state: JobCreationState) -> Literal["post_job_to_linkedin", "generate_scoring_weights", "end"]:
    """Publish a valid checklist, retry scoring twice, then stop."""
    if state.get("schema_valid"):
        return "post_job_to_linkedin"
    if _validation_attempts(state.get("validation_errors") or []) >= _MAX_SCHEMA_RETRIES:
        return "end"
    return "generate_scoring_weights"


def _infer_seniority(role_title: str) -> str:
    tokens = re.findall(r"[A-Za-z]+", role_title.lower())
    for token in tokens:
        label = _SENIORITY_LABELS.get(token)
        if label is not None:
            return label
    return ""


def _infer_skills(role_title: str, seniority_level: str) -> list[str]:
    skill = role_title
    if seniority_level:
        skill = re.sub(rf"^{re.escape(seniority_level)}\s+", "", role_title, flags=re.IGNORECASE).strip()
    if not skill:
        return []
    return [skill]


def _missing_role_fields(state: JobCreationState) -> list[str]:
    missing: list[str] = []
    if not (state.get("role_title") or "").strip():
        missing.append("role_title")
    if not (state.get("seniority_level") or "").strip():
        missing.append("seniority_level")
    if not state.get("core_skills"):
        missing.append("core_skills")
    if "min_years_exp" not in state:
        missing.append("min_years_exp")
    return missing


def _question_for(field_name: str) -> str:
    questions = {
        "role_title": "What is the role title?",
        "seniority_level": "What seniority level should this role use?",
        "core_skills": "Which core skills are required?",
        "min_years_exp": "What is the minimum years of experience?",
    }
    return questions[field_name]


def _retrieve_policy_chunks(query: str) -> list[str]:
    query_vector = _term_vector(query)
    ranked = sorted(
        (
            (
                _cosine(query_vector, _term_vector(text)),
                category,
                text,
            )
            for category, text in _POLICY_INDEX
        ),
        key=lambda item: item[0],
        reverse=True,
    )
    selected: list[str] = []
    seen: set[str] = set()
    for _score, category, text in ranked:
        if category in seen:
            continue
        selected.append(text)
        seen.add(category)
    return selected


def _term_vector(text: str) -> dict[str, float]:
    counts: dict[str, float] = {}
    for token in re.findall(r"[a-z0-9]+", text.lower()):
        counts[token] = counts.get(token, 0.0) + 1.0
    return counts


def _cosine(left: dict[str, float], right: dict[str, float]) -> float:
    if not left or not right:
        return 0.0
    dot = sum(weight * right[token] for token, weight in left.items() if token in right)
    left_norm = math.sqrt(sum(weight * weight for weight in left.values()))
    right_norm = math.sqrt(sum(weight * weight for weight in right.values()))
    if left_norm == 0.0 or right_norm == 0.0:
        return 0.0
    return dot / (left_norm * right_norm)


def _job_description_from_inputs(state: JobCreationState) -> GeneratedJobDescription:
    """Build a schema-valid job description from the role and retrieved policy text."""
    title = (state.get("role_title") or "Untitled role").strip()
    seniority = (state.get("seniority_level") or "Mid").strip()
    skills = [skill for skill in state.get("core_skills") or [] if skill.strip()]
    if not skills:
        skills = [title]
    years = int(state.get("min_years_exp") or 0)
    skill_list = ", ".join(skills)
    return GeneratedJobDescription(
        title=title,
        seniority=seniority,
        summary=(
            f"{title} is a {seniority} role focused on {skill_list}. "
            f"Candidates need at least {years} years of relevant experience."
        ),
        responsibilities=[
            f"Design and deliver {skill_list} solutions for production use.",
            "Document decisions and collaborate with recruiters and hiring managers.",
            "Measure quality and improve the systems owned by the role.",
        ],
        required_skills=skills,
        preferred_skills=[f"Production {skills[0]} delivery"],
        qualification_requirements=[
            f"Job-related experience or education that supports work as a {title}.",
        ],
        minimum_years_experience=years,
        salary_range_summary=_policy_sentence(state, "salary", seniority),
        remote_policy_summary=_policy_sentence(state, "remote", "remote"),
    )


def _checklist_from_inputs(state: JobCreationState) -> list[LockedChecklistQuery]:
    """Build ten role-specific checklist queries with weights that sum to 1."""
    title = (state.get("role_title") or "this role").strip()
    skill = (state.get("core_skills") or [title])[0]
    years = int(state.get("min_years_exp") or 0)
    weights = (0.12, 0.10, 0.10, 0.10, 0.10, 0.08, 0.12, 0.08, 0.10, 0.10)
    drafts = [
        ("technical", "must_have", f"Does the candidate have hands-on {skill} experience?", [skill]),
        ("technical", "must_have", f"Has the candidate designed systems relevant to a {title}?", [title, skill]),
        ("technical", "preferred", f"Has the candidate shipped {skill} work with other engineers?", [skill, "collaboration"]),
        ("technical", "must_have", f"Can the candidate explain production tradeoffs for {skill}?", [skill, "production"]),
        ("technical", "preferred", f"Has the candidate improved reliability or quality in {skill} systems?", [skill, "quality"]),
        ("technical", "preferred", f"Does the candidate show current tooling depth for {title} work?", [title]),
        ("experience", "must_have", f"Does the candidate have at least {years} years of relevant experience?", ["experience", str(years)]),
        ("experience", "preferred", "Is there evidence of production project delivery?", ["production", "delivery"]),
        ("qualification", "must_have", f"Does the candidate meet the job-related qualifications for {title}?", ["qualification", title]),
        ("qualification", "preferred", "Does the candidate show ongoing professional development in this field?", ["learning", skill]),
    ]
    rubric = "Met when the CV shows practical evidence. Partial when the evidence is only theoretical. Unmet when it is missing."
    return [
        LockedChecklistQuery(
            query_id=cast(QueryId, _QUERY_IDS[index]),
            question=question,
            dimension=dimension,  # type: ignore[arg-type]
            requirement_type=requirement_type,  # type: ignore[arg-type]
            weight=weight,
            evidence_hints=hints,
            scoring_rubric=rubric,
        )
        for index, ((dimension, requirement_type, question, hints), weight) in enumerate(zip(drafts, weights, strict=True))
    ]


def _policy_sentence(state: JobCreationState, category_token: str, focus: str) -> str:
    chunks = state.get("retrieved_policy_chunks") or []
    matched = [chunk for chunk in chunks if category_token in chunk.lower()]
    text = matched[0] if matched else (chunks[0] if chunks else "")
    focus_key = focus.lower()
    for sentence in text.split(". "):
        cleaned = sentence.strip().rstrip(".")
        if cleaned and focus_key in cleaned.lower():
            return f"{cleaned}."
    if text.strip():
        return text.strip()
    return f"Apply the company {category_token} policy for this role."


def _job_description_prompt(state: JobCreationState) -> str:
    policies = "\n".join(f"- {chunk}" for chunk in state.get("retrieved_policy_chunks") or [])
    skills = ", ".join(state.get("core_skills") or [])
    return (
        "You write inclusive job descriptions that obey the company policy constraints.\n"
        f"Role title: {state.get('role_title')}\n"
        f"Seniority: {state.get('seniority_level')}\n"
        f"Core skills: {skills}\n"
        f"Minimum years of experience: {state.get('min_years_exp')}\n"
        f"Recruiter prompt:\n{state.get('raw_prompt')}\n"
        f"Company policy constraints:\n{policies}\n"
        "Use the salary band that matches the seniority and restate the remote work policy. "
        "Keep every requirement job-related."
    )


def _scoring_prompt(state: JobCreationState) -> str:
    job_description = state.get("synthesized_jd") or {}
    return (
        "Create a locked evaluation checklist for this role.\n"
        f"Job description: {job_description}\n"
        "Return exactly 10 queries with ids Q1 through Q10. "
        "Cover technical, experience, and qualification. "
        "Use requirement_type must_have or preferred. "
        "Assign positive weights that sum to 1.0. "
        "Include evidence_hints and a scoring_rubric for every query. "
        "Also return dimensional weights for technical, experience, and qualification that sum to 1.0."
    )


def _coerce_model(payload: Any, schema: type[ModelT]) -> ModelT:
    if isinstance(payload, schema):
        return payload
    if isinstance(payload, BaseModel):
        return schema.model_validate(payload.model_dump())
    if isinstance(payload, dict):
        return schema.model_validate(payload)
    raise TypeError(f"structured output was {type(payload).__name__}, expected {schema.__name__}")


def _normalize_dimensional_weights(
    technical: float,
    experience: float,
    qualification: float,
) -> DimensionalWeights:
    raw = [max(technical, 0.0), max(experience, 0.0), max(qualification, 0.0)]
    total = sum(raw)
    if total <= 0:
        return DimensionalWeights()
    technical_weight = round(raw[0] / total, 4)
    experience_weight = round(raw[1] / total, 4)
    qualification_weight = round(1.0 - technical_weight - experience_weight, 4)
    return DimensionalWeights(
        technical=technical_weight,
        experience=experience_weight,
        qualification=qualification_weight,
    )


def _freeze_queries(drafts: list[_ChecklistQueryDraft]) -> list[LockedChecklistQuery]:
    if len(drafts) != 10:
        raise ValueError(f"expected 10 checklist queries, received {len(drafts)}")
    raw_weights = [max(draft.weight, 0.0) for draft in drafts]
    total = sum(raw_weights)
    if total <= 0:
        scaled = [1.0 / 10.0] * 10
    else:
        scaled = [weight / total for weight in raw_weights]
    rounded = [round(weight, 4) for weight in scaled[:-1]]
    rounded.append(round(1.0 - sum(rounded), 4))
    frozen: list[LockedChecklistQuery] = []
    for index, draft in enumerate(drafts):
        hints = [hint.strip() for hint in draft.evidence_hints if hint.strip()]
        frozen.append(
            LockedChecklistQuery(
                query_id=cast(QueryId, _QUERY_IDS[index]),
                question=draft.question.strip(),
                dimension=draft.dimension,
                requirement_type=draft.requirement_type,
                weight=rounded[index],
                evidence_hints=hints,
                scoring_rubric=draft.scoring_rubric.strip(),
            )
        )
    return frozen


def _validation_attempts(errors: list[str]) -> int:
    return sum(1 for error in errors if error.startswith("validation attempt "))


def _build_workflow() -> Any:
    builder = StateGraph(JobCreationState)
    builder.add_node("collect_role_inputs", collect_role_inputs_node)
    builder.add_node("retrieve_policy_rules", retrieve_policy_rules_node)
    builder.add_node("check_role_clarity", check_role_clarity_node)
    builder.add_node("ask_clarifying_questions", ask_clarifying_questions_node)
    builder.add_node("synthesize_jd", synthesize_jd_node)
    builder.add_node("generate_scoring_weights", generate_scoring_weights_node)
    builder.add_node("validate_schema", validate_schema_node)
    builder.add_node("post_job_to_linkedin", post_job_to_linkedin_node)
    builder.set_entry_point("collect_role_inputs")
    builder.add_edge("collect_role_inputs", "retrieve_policy_rules")
    builder.add_edge("retrieve_policy_rules", "check_role_clarity")
    builder.add_conditional_edges(
        "check_role_clarity",
        route_clarity,
        {
            "synthesize_jd": "synthesize_jd",
            "ask_clarifying_questions": "ask_clarifying_questions",
        },
    )
    builder.add_edge("ask_clarifying_questions", "check_role_clarity")
    builder.add_edge("synthesize_jd", "generate_scoring_weights")
    builder.add_edge("generate_scoring_weights", "validate_schema")
    builder.add_conditional_edges(
        "validate_schema",
        route_validation,
        {
            "post_job_to_linkedin": "post_job_to_linkedin",
            "generate_scoring_weights": "generate_scoring_weights",
            "end": END,
        },
    )
    builder.add_edge("post_job_to_linkedin", END)
    return builder.compile()


workflow_1_graph = _build_workflow()
