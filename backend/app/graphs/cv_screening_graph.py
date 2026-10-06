import re
from collections.abc import Awaitable, Callable

from langgraph.graph import END, START, StateGraph

from app.core.llm_fallback import FallbackLLMManager
from app.graphs.job_creation_graph import parse_json_object
from app.graphs.state import CVScreeningState
from app.services.embeddings import Embedder
from app.services.ocr_service import EmptyCvError, InvalidCvError, parse_cv
from app.services.ranking import score_checklist

_ALLOWED_STATUS = {"met", "partially_met", "unmet", "insufficient_evidence"}
_PROTECTED = re.compile(
    r"\b(male|female|non-binary|gender|christian|muslim|hindu|jewish|buddhist|"
    r"religion|caucasian|african|asian|hispanic|ethnicity|disabled|disability|"
    r"\d{1,2}\s*years old)\b",
    re.IGNORECASE,
)


class CVGraphError(ValueError):
    """Workflow 2 could not score the CV against the locked checklist."""


def build_cv_screening_graph(
    llm: FallbackLLMManager,
    embedder: Embedder,
) -> Callable[[CVScreeningState], Awaitable[CVScreeningState]]:
    async def parse_and_normalize(state: CVScreeningState) -> dict[str, object]:
        filename = state.get("filename") or "cv.pdf"
        data = state.get("file_bytes") or b""
        try:
            parsed = parse_cv(filename, data)
        except (InvalidCvError, EmptyCvError) as exc:
            return {"errors": [str(exc)], "raw_text": "", "warnings": [str(exc)], "parse_method": "failed"}
        return {
            "raw_text": parsed.text,
            "parse_method": parsed.parse_method,
            "parse_confidence": parsed.parse_confidence,
            "warnings": parsed.warnings,
            "errors": [],
        }

    async def extract_cv_attributes(state: CVScreeningState) -> dict[str, object]:
        if state.get("errors"):
            return {}
        prompt = (
            "Extract candidate attributes as JSON with keys full_name, email, skills, "
            "work_history, education, and experience_years. Use an empty string, empty list, "
            "or 0 when the CV does not say. Do not infer gender, age, religion, or ethnicity.\n"
            f"CV:\n{state.get('raw_text', '')[:12000]}"
        )
        response = await llm.complete(prompt, system="Return only a JSON object. Do not use markdown.")
        payload = parse_json_object(response.content)
        attributes = {
            "full_name": _text(payload.get("full_name")),
            "email": _text(payload.get("email")),
            "skills": _texts(payload.get("skills")),
            "work_history": _texts(payload.get("work_history")),
            "education": _texts(payload.get("education")),
            "experience_years": _years(payload.get("experience_years")),
        }
        return {
            "extracted_attributes": attributes,
            "llm_tier": response.tier.value,
            "fallback_used": response.fallback_used,
        }

    async def load_locked_checklist(state: CVScreeningState) -> dict[str, object]:
        if state.get("errors"):
            return {}
        checklist = state.get("locked_checklist") or []
        if len(checklist) != 10:
            return {"errors": ["The locked checklist must contain 10 queries."]}
        return {"locked_checklist": checklist}

    async def semantic_match(state: CVScreeningState) -> dict[str, object]:
        if state.get("errors"):
            return {}
        checklist = state.get("locked_checklist") or []
        raw_text = state.get("raw_text") or ""
        questions = [str(query["question"]) for query in checklist]
        vectors = embedder.embed([raw_text, *questions])
        cv_vector = vectors[0]
        matches: list[dict[str, float | str]] = []
        for query, vector in zip(checklist, vectors[1:], strict=True):
            matches.append(
                {
                    "query_id": str(query["query_id"]),
                    "score": _dot(cv_vector, vector),
                }
            )
        return {"semantic_matches": matches}

    async def checklist_evaluator(state: CVScreeningState) -> dict[str, object]:
        if state.get("errors"):
            return {}
        checklist = state.get("locked_checklist") or []
        raw_text = state.get("raw_text") or ""
        lines = []
        for query in checklist:
            lines.append(
                f"{query['query_id']} ({query['requirement_type']}, {query['dimension']}): {query['question']} "
                f"Rubric: {query['scoring_rubric']}"
            )
        prompt = (
            "Evaluate the CV against every query. Return JSON "
            '{"evaluations": [{"query_id": "Q1", "status": "met", "confidence": 0.8, "evidence": "quote"}]} . '
            "status must be met, partially_met, unmet, or insufficient_evidence. "
            "evidence must be an exact contiguous quote from the CV, or an empty string.\n"
            f"Queries:\n" + "\n".join(lines) + f"\nCV:\n{raw_text[:12000]}"
        )
        response = await llm.complete(prompt, system="Return only a JSON object. Do not use markdown.")
        payload = parse_json_object(response.content)
        raw_items = payload.get("evaluations")
        if not isinstance(raw_items, list):
            raise CVGraphError("The model did not return evaluations.")
        by_id = {str(item.get("query_id")): item for item in raw_items if isinstance(item, dict)}
        semantic = {str(item["query_id"]): float(item["score"]) for item in state.get("semantic_matches") or []}
        evaluations: list[dict[str, object]] = []
        for query in checklist:
            query_id = str(query["query_id"])
            item = by_id.get(query_id, {})
            status = str(item.get("status") or "insufficient_evidence")
            if status not in _ALLOWED_STATUS:
                status = "insufficient_evidence"
            evidence = str(item.get("evidence") or "").strip()
            if evidence and evidence.casefold() not in raw_text.casefold():
                status = "insufficient_evidence"
                evidence = ""
            confidence = item.get("confidence")
            evaluations.append(
                {
                    "query_id": query_id,
                    "status": status,
                    "confidence": float(confidence) if isinstance(confidence, int | float) else 0.0,
                    "evidence": evidence,
                    "semantic_score": semantic.get(query_id, 0.0),
                }
            )
        statuses = {str(item["query_id"]): str(item["status"]) for item in evaluations}
        totals = score_checklist(checklist, statuses)
        return {
            "query_evaluations": evaluations,
            "aggregate_score": totals.aggregate_score,
            "must_have_ratio": totals.must_have_ratio,
            "technical_score": totals.technical_score,
            "experience_score": totals.experience_score,
            "qualification_score": totals.qualification_score,
            "llm_tier": response.tier.value,
            "fallback_used": bool(state.get("fallback_used")) or response.fallback_used,
        }

    async def fairness_guard(state: CVScreeningState) -> dict[str, object]:
        if state.get("errors"):
            return {}
        raw_text = state.get("raw_text") or ""
        flags = sorted({match.group(0).casefold() for match in _PROTECTED.finditer(raw_text)})
        attributes = dict(state.get("extracted_attributes") or {})
        redacted_attributes = {key: _redact(value) for key, value in attributes.items()}
        return {"fairness_flags": flags, "extracted_attributes": redacted_attributes}

    async def generate_justifications(state: CVScreeningState) -> dict[str, object]:
        if state.get("errors"):
            return {}
        lines: list[str] = []
        for item in state.get("query_evaluations") or []:
            evidence = str(item.get("evidence") or "")
            quote = f' Evidence: "{evidence}"' if evidence else " No direct CV quote was available."
            lines.append(f"{item['query_id']} is {item['status']}.{quote}")
        redacted = [_redact_text(line) for line in lines]
        return {"justifications": redacted}

    graph = StateGraph(CVScreeningState)
    graph.add_node("parse_and_normalize", parse_and_normalize)
    graph.add_node("extract_cv_attributes", extract_cv_attributes)
    graph.add_node("load_locked_checklist", load_locked_checklist)
    graph.add_node("semantic_match", semantic_match)
    graph.add_node("checklist_evaluator", checklist_evaluator)
    graph.add_node("fairness_guard", fairness_guard)
    graph.add_node("generate_justifications", generate_justifications)
    graph.add_edge(START, "parse_and_normalize")
    graph.add_edge("parse_and_normalize", "extract_cv_attributes")
    graph.add_edge("extract_cv_attributes", "load_locked_checklist")
    graph.add_edge("load_locked_checklist", "semantic_match")
    graph.add_edge("semantic_match", "checklist_evaluator")
    graph.add_edge("checklist_evaluator", "fairness_guard")
    graph.add_edge("fairness_guard", "generate_justifications")
    graph.add_edge("generate_justifications", END)
    compiled = graph.compile()

    async def run(state: CVScreeningState) -> CVScreeningState:
        return await compiled.ainvoke(state)

    return run


def _text(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""


def _texts(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item.strip() for item in value if isinstance(item, str) and item.strip()]


def _years(value: object) -> int:
    if isinstance(value, bool):
        return 0
    if isinstance(value, int):
        return max(value, 0)
    if isinstance(value, float):
        return max(int(value), 0)
    return 0


def _dot(left: list[float], right: list[float]) -> float:
    return float(sum(a * b for a, b in zip(left, right, strict=True)))


def _redact(value: object) -> object:
    if isinstance(value, str):
        return _redact_text(value)
    if isinstance(value, list):
        return [_redact(item) for item in value]
    return value


def _redact_text(value: str) -> str:
    return _PROTECTED.sub("[redacted]", value)
