import json
from collections.abc import Awaitable, Callable
from typing import Protocol

from langgraph.graph import END, START, StateGraph

from app.core.llm_fallback import FallbackLLMManager
from app.graphs.state import JobCreationState
from app.schemas.job import ChecklistQuerySet, JobCreateRequest


class JobGraphError(ValueError):
    """Workflow 1 produced a description or checklist that failed validation."""


class PolicyRetriever(Protocol):
    async def search(self, query: str, limit: int = 5) -> list[str]:
        """Return policy excerpts most similar to the query."""


def parse_json_object(text: str) -> dict[str, object]:
    stripped = text.strip()
    if stripped.startswith("```"):
        lines = stripped.split("\n")
        stripped = "\n".join(lines[1:])
        fence = stripped.rfind("```")
        if fence >= 0:
            stripped = stripped[:fence]
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start < 0 or end < start:
        raise JobGraphError("The model response did not contain a JSON object.")
    try:
        value = json.loads(stripped[start : end + 1])
    except json.JSONDecodeError as exc:
        raise JobGraphError("The model response was not valid JSON.") from exc
    if not isinstance(value, dict):
        raise JobGraphError("The model response JSON must be an object.")
    return value


def build_job_creation_graph(
    llm: FallbackLLMManager,
    retriever: PolicyRetriever,
) -> Callable[[JobCreationState], Awaitable[JobCreationState]]:
    async def retrieve_policy_rules(state: JobCreationState) -> dict[str, object]:
        skills = ", ".join(state["required_skills"] + state["preferred_skills"])
        query = f"{state['title']} {state['seniority']} {skills} {state['qualifications']}"
        excerpts = await retriever.search(query)
        return {"policy_excerpts": excerpts}

    async def synthesize_jd(state: JobCreationState) -> dict[str, object]:
        excerpts = state.get("policy_excerpts") or []
        policy_block = "\n".join(f"- {excerpt}" for excerpt in excerpts) or "No policy excerpts were retrieved."
        prompt = (
            "Write a policy-compliant job description as JSON with a single key, description. "
            "The description must be at least 120 characters and must reflect the policy excerpts "
            "when they constrain salary, location, or hiring rules.\n"
            f"Title: {state['title']}\n"
            f"Seniority: {state['seniority']}\n"
            f"Required skills: {', '.join(state['required_skills'])}\n"
            f"Preferred skills: {', '.join(state['preferred_skills'])}\n"
            f"Qualifications: {state['qualifications']}\n"
            f"Minimum years: {state['minimum_years']}\n"
            f"Policy excerpts:\n{policy_block}"
        )
        response = await llm.complete(prompt, system="Return only a JSON object. Do not use markdown.")
        payload = parse_json_object(response.content)
        description = payload.get("description")
        if not isinstance(description, str) or len(description.strip()) < 100:
            raise JobGraphError("The generated job description must be at least 100 characters.")
        return {
            "description": description.strip(),
            "llm_tier": response.tier.value,
            "fallback_used": response.fallback_used,
        }

    async def generate_scoring_weights(state: JobCreationState) -> dict[str, object]:
        prompt = (
            "Create exactly 10 evaluation queries as JSON: {\"queries\": [...]} . "
            "Use query_id values Q1 through Q10 once each. "
            "Each item needs question, dimension (technical, experience, or qualification), "
            "requirement_type (must_have or preferred), weight, evidence_hints, and scoring_rubric. "
            "scoring_rubric must be one string, not an object or score map. "
            "Weights must be positive and should sum to 1. "
            "Cover the required skills, minimum years, and qualifications.\n"
            f"Dimension weights: technical {state['technical_weight']}, "
            f"experience {state['experience_weight']}, qualification {state['qualification_weight']}.\n"
            f"Job description:\n{state['description']}"
        )
        response = await llm.complete(prompt, system="Return only a JSON object. Do not use markdown.")
        payload = parse_json_object(response.content)
        queries = payload.get("queries")
        if not isinstance(queries, list):
            raise JobGraphError("The model did not return a queries array.")
        return {
            "queries": queries,
            "llm_tier": response.tier.value,
            "fallback_used": bool(state.get("fallback_used")) or response.fallback_used,
        }

    async def validate_schema(state: JobCreationState) -> dict[str, object]:
        raw_queries = state.get("queries")
        if not isinstance(raw_queries, list):
            raise JobGraphError("Checklist queries were missing before validation.")
        try:
            validated = ChecklistQuerySet.model_validate({"queries": raw_queries})
        except ValueError as exc:
            raise JobGraphError(str(exc)) from exc
        description = state.get("description", "")
        if len(description) < 100:
            raise JobGraphError("The job description must be at least 100 characters.")
        return {"queries": validated.queries, "description": description}

    graph = StateGraph(JobCreationState)
    graph.add_node("retrieve_policy_rules", retrieve_policy_rules)
    graph.add_node("synthesize_jd", synthesize_jd)
    graph.add_node("generate_scoring_weights", generate_scoring_weights)
    graph.add_node("validate_schema", validate_schema)
    graph.add_edge(START, "retrieve_policy_rules")
    graph.add_edge("retrieve_policy_rules", "synthesize_jd")
    graph.add_edge("synthesize_jd", "generate_scoring_weights")
    graph.add_edge("generate_scoring_weights", "validate_schema")
    graph.add_edge("validate_schema", END)
    compiled = graph.compile()

    async def run(state: JobCreationState) -> JobCreationState:
        result = await compiled.ainvoke(state)
        return result

    return run


def state_from_request(request: JobCreateRequest) -> JobCreationState:
    return {
        "title": request.title,
        "seniority": request.seniority,
        "required_skills": request.required_skills,
        "preferred_skills": request.preferred_skills,
        "qualifications": request.qualifications,
        "minimum_years": request.minimum_years,
        "technical_weight": request.technical_weight,
        "experience_weight": request.experience_weight,
        "qualification_weight": request.qualification_weight,
    }
