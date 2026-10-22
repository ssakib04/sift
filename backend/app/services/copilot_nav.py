import uuid

STATIC_PLACES: dict[str, tuple[str, str]] = {
    "home": ("/#home", "Home"),
    "policies": ("/docs#policies", "Policies"),
    "jobs": ("/jobs#roles", "Existing roles"),
    "create": ("/jobs?view=create#create", "Create a role"),
    "candidates": ("/candidates#candidates", "Candidates"),
    "progress": ("/progress#progress", "Progress"),
    "practice": ("/practice#practice", "Practice"),
}

JOB_PLACES: frozenset[str] = frozenset({"job_brief", "job_people", "portraits", "standing"})
PLACES: frozenset[str] = frozenset(STATIC_PLACES) | JOB_PLACES | frozenset({"policy", "person"})

_ALIASES = {
    "job": "jobs",
    "roles": "jobs",
    "existing_roles": "jobs",
    "create_role": "create",
    "create_a_role": "create",
    "brief": "job_brief",
    "applicants": "job_people",
    "portraits": "portraits",
    "docs": "policies",
    "policy_index": "policies",
    "candidate": "person",
}


def normalize_place(value: str) -> str:
    text = "_".join(value.strip().lower().replace("-", " ").split())
    text = _ALIASES.get(text, text)
    return text if text in PLACES else ""


def static_target(place: str) -> tuple[str, str] | None:
    return STATIC_PLACES.get(place)


def job_target(place: str, job_id: uuid.UUID) -> tuple[str, str] | None:
    if place == "job_brief":
        return f"/jobs?job={job_id}&tab=brief#brief", "Brief"
    if place == "job_people":
        return f"/jobs?job={job_id}&tab=people#people", "Applicants"
    if place == "portraits":
        return f"/candidates?job={job_id}&view=people#people", "Portraits"
    if place == "standing":
        return f"/candidates?job={job_id}&view=standing#standing", "Standing"
    return None


def person_target(candidate_id: uuid.UUID) -> tuple[str, str]:
    return f"/candidates/{candidate_id}#person", "Open candidate"


def policy_target(document_id: uuid.UUID) -> tuple[str, str]:
    return f"/docs?doc={document_id}#policy", "Policy"


def ranking_target(job_id: uuid.UUID) -> str:
    return f"/candidates?job={job_id}&view=people#people"


def progress_target() -> str:
    return "/progress#progress"
