import logging
import re
from collections.abc import Awaitable, Callable

from langgraph.graph import END, START, StateGraph

from app.core.llm_fallback import FallbackLLMManager
from app.graphs.job_creation_graph import _save_graph_png, parse_json_object
from app.graphs.state import CVScreeningState
from app.services.cv_facts import (
    coerce_work_history,
    computed_experience_years,
    open_for_local_review,
    reconcile_evaluation,
    screening_facts,
    upgrade_open_evaluations,
)
from app.services.documents import chunk_text
from app.services.embeddings import Embedder
from app.services.ocr_service import EmptyCvError, InvalidCvError, parse_cv
from app.services.ranking import score_checklist

logger = logging.getLogger(__name__)

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
            "work_history, education, and experience_years. "
            "work_history must list every job as an object with title, company, start, end, and summary. "
            "Use YYYY-MM for start and end, and \"present\" when the job is current. "
            "Include a job even when the dates are approximate. "
            "skills must list tools and technologies as written on the CV. "
            "Use an empty string, empty list, or 0 when the CV does not say. "
            "Do not infer gender, age, religion, or ethnicity.\n"
            f"CV:\n{state.get('raw_text', '')[:12000]}"
        )
        response = await llm.complete(prompt, system="Return only a JSON object. Do not use markdown.")
        payload = parse_json_object(response.content)
        work_history = coerce_work_history(payload.get("work_history"))
        attributes = {
            "full_name": _text(payload.get("full_name")),
            "email": _text(payload.get("email")),
            "skills": _texts(payload.get("skills")),
            "work_history": work_history,
            "education": _texts(payload.get("education")),
            "experience_years": computed_experience_years(work_history, payload.get("experience_years")),
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
        attributes = dict(state.get("extracted_attributes") or {})
        facts = screening_facts(attributes)
        semantic = {
            str(item["query_id"]): float(item["score"]) for item in state.get("semantic_matches") or []
        }
        evaluations: list[dict[str, object]] = []
        fallback_used = bool(state.get("fallback_used"))
        last_tier = str(state.get("llm_tier") or "unknown")
        for query in checklist:
            query_id = str(query["query_id"])
            hints = query.get("evidence_hints") or []
            hint_values = [str(hint) for hint in hints] if isinstance(hints, list) else []
            hint_line = ""
            if hint_values:
                hint_line = "Evidence hints: " + "; ".join(hint_values) + "\n"
            question = str(query["question"])
            excerpts = _top_excerpts(embedder, raw_text, question)
            prompt = (
                "Evaluate the CV against this one query. Return JSON "
                f'{{"query_id": "{query_id}", "status": "met", "confidence": 0.8, "evidence": "quote"}} . '
                "status must be met, partially_met, unmet, or insufficient_evidence. "
                "evidence must be a short quote copied from the CV, or an empty string. "
                "Treat the verified facts as authoritative for total years of experience. "
                "If a listed skill appears in the CV, do not answer insufficient_evidence for that skill.\n"
                f"Verified facts:\n{facts}\n"
                f"Query: {query_id} ({query['requirement_type']}, {query['dimension']}): {question}\n"
                f"Rubric: {query['scoring_rubric']}\n"
                f"{hint_line}"
                f"Relevant excerpts:\n{excerpts[:4000]}\n"
                f"CV:\n{raw_text[:12000]}"
            )
            response = await llm.complete(prompt, system="Return only a JSON object. Do not use markdown.")
            last_tier = response.tier.value
            fallback_used = fallback_used or response.fallback_used
            payload = parse_json_object(response.content)
            item = payload
            if isinstance(payload.get("evaluations"), list) and payload["evaluations"]:
                first = payload["evaluations"][0]
                if isinstance(first, dict):
                    item = first
            proposed = str(item.get("status") or "insufficient_evidence")
            status, evidence = reconcile_evaluation(
                question=question,
                dimension=str(query["dimension"]),
                status=proposed,
                evidence=str(item.get("evidence") or ""),
                hints=hint_values,
                attributes=attributes,
                raw_text=raw_text,
            )
            confidence = item.get("confidence")
            confidence_value = float(confidence) if isinstance(confidence, int | float) else 0.0
            if status != proposed:
                confidence_value = max(confidence_value, 0.75)
            evaluations.append(
                {
                    "query_id": query_id,
                    "status": status,
                    "confidence": confidence_value,
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
            "llm_tier": last_tier,
            "fallback_used": fallback_used,
        }

    async def local_skill_recheck(state: CVScreeningState) -> dict[str, object]:
        if state.get("errors"):
            return {}
        evaluations = [dict(item) for item in state.get("query_evaluations") or []]
        checklist = list(state.get("locked_checklist") or [])
        open_items = open_for_local_review(evaluations, checklist)
        if not open_items:
            return {}
        raw_text = state.get("raw_text") or ""
        by_id = {str(query["query_id"]): query for query in checklist}
        lines: list[str] = []
        for item in open_items:
            query = by_id[str(item["query_id"])]
            evidence = str(item.get("evidence") or "") or "none"
            lines.append(
                f"{item['query_id']} ({query['dimension']}, current {item['status']}, "
                f"similarity {float(item.get('semantic_score') or 0):.2f}): {query['question']}\n"
                f"Current evidence: {evidence}"
            )
        prompt = (
            "Recheck checklist items that are not met. A framework or library can imply its language "
            "or platform. Example: expertise in FastAPI implies Python experience. "
            'Return JSON {"reviews": [{"query_id": "Q1", "status": "partially_met", "evidence": "quote"}]} . '
            "status may only be met or partially_met. "
            "Use partially_met when the CV shows a related tool rather than the requirement itself. "
            "Use met when the CV states the requirement. "
            "evidence must be a short quote copied from the CV. "
            "Omit an item you would not raise. Do not lower any item. "
            "Do not judge years of experience.\n"
            f"Verified facts:\n{screening_facts(dict(state.get('extracted_attributes') or {}))}\n"
            "Open items:\n"
            + "\n".join(lines)
            + f"\nCV:\n{raw_text[:12000]}"
        )
        try:
            response = await llm.complete_local(prompt, system="Return only a JSON object. Do not use markdown.")
            payload = parse_json_object(response.content)
        except Exception as exc:
            logger.warning("local_skill_recheck_skipped error_type=%s", type(exc).__name__)
            return {}
        reviews = payload.get("reviews")
        if not isinstance(reviews, list):
            reviews = payload.get("evaluations") if isinstance(payload.get("evaluations"), list) else []
        upgraded = upgrade_open_evaluations(evaluations, reviews, checklist, raw_text)
        statuses = {str(item["query_id"]): str(item["status"]) for item in upgraded}
        totals = score_checklist(checklist, statuses)
        return {
            "query_evaluations": upgraded,
            "aggregate_score": totals.aggregate_score,
            "must_have_ratio": totals.must_have_ratio,
            "technical_score": totals.technical_score,
            "experience_score": totals.experience_score,
            "qualification_score": totals.qualification_score,
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
        years = (state.get("extracted_attributes") or {}).get("experience_years")
        if isinstance(years, int | float) and not isinstance(years, bool) and years > 0:
            lines.append(f"Computed professional experience is {years} years after merging overlapping jobs.")
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
    graph.add_node("local_skill_recheck", local_skill_recheck)
    graph.add_node("fairness_guard", fairness_guard)
    graph.add_node("generate_justifications", generate_justifications)
    graph.add_edge(START, "parse_and_normalize")
    graph.add_edge("parse_and_normalize", "extract_cv_attributes")
    graph.add_edge("extract_cv_attributes", "load_locked_checklist")
    graph.add_edge("load_locked_checklist", "semantic_match")
    graph.add_edge("semantic_match", "checklist_evaluator")
    graph.add_edge("checklist_evaluator", "local_skill_recheck")
    graph.add_edge("local_skill_recheck", "fairness_guard")
    graph.add_edge("fairness_guard", "generate_justifications")
    graph.add_edge("generate_justifications", END)
    compiled = graph.compile()
    _save_graph_png(compiled, "cv-screening-graph.png")

    async def run(state: CVScreeningState) -> CVScreeningState:
        return await compiled.ainvoke(state)

    return run


def _text(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""


def _texts(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item.strip() for item in value if isinstance(item, str) and item.strip()]


def _dot(left: list[float], right: list[float]) -> float:
    return float(sum(a * b for a, b in zip(left, right, strict=True)))


def _redact(value: object) -> object:
    if isinstance(value, str):
        return _redact_text(value)
    if isinstance(value, list):
        return [_redact(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _redact(item) for key, item in value.items()}
    return value


def _top_excerpts(embedder: Embedder, raw_text: str, question: str, limit: int = 3) -> str:
    chunks = [chunk for chunk in chunk_text(raw_text, size=600, overlap=80) if chunk.strip()]
    if len(chunks) <= limit:
        return "\n---\n".join(chunks)
    vectors = embedder.embed([question, *chunks])
    ranked = sorted(
        zip(chunks, vectors[1:], strict=True),
        key=lambda item: _dot(vectors[0], item[1]),
        reverse=True,
    )
    return "\n---\n".join(chunk for chunk, _ in ranked[:limit])


def _redact_text(value: str) -> str:
    return _PROTECTED.sub("[redacted]", value)
