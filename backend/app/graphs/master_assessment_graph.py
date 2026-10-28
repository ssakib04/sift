from collections.abc import Awaitable, Callable
from decimal import Decimal, ROUND_HALF_UP

from langgraph.graph import END, START, StateGraph

from app.core.llm_fallback import FallbackLLMManager
from app.graphs.job_creation_graph import JobGraphError, parse_json_object
from app.graphs.state import MasterAssessmentState

CV_WEIGHT = Decimal("0.375")
MCQ_WEIGHT = Decimal("0")
INTERVIEW_WEIGHT = Decimal("0.625")
STRONG_FIT_MIN = Decimal("75.0")
MODERATE_FIT_MIN = Decimal("50.0")
INTERVIEW_DIMENSIONS = ("relevance", "technical_accuracy", "completeness", "articulation")
_CITED_SOURCES = {"cv", "transcript"}
_POSITIVE_CV = {"met", "partially_met"}
_GAP_CV = {"unmet", "insufficient_evidence"}
_CLAIM_LIMIT = 400
_NARRATIVE_LIMIT = 4000

SUITABILITY_LABELS = {
    "strong_fit": "Strong Fit",
    "moderate_fit": "Moderate Fit",
    "unsuited": "Unsuited",
    "insufficient_evidence": "Insufficient evidence",
}


class AssessmentGraphError(RuntimeError):
    """Workflow 4 could not read the candidate id it was given."""


def build_master_assessment_graph(
    llm: FallbackLLMManager,
) -> Callable[[MasterAssessmentState], Awaitable[MasterAssessmentState]]:
    """Workflow 4: load the CV and the interview Q&A, then write one cited assessment."""

    async def load_candidate_data(state: MasterAssessmentState) -> dict[str, object]:
        candidate_id = str(state.get("candidate_id") or "").strip()
        if not candidate_id:
            raise AssessmentGraphError("A candidate id is required.")
        return {"candidate_id": candidate_id}

    async def load_cv_screening_snapshot(state: MasterAssessmentState) -> dict[str, object]:
        return {"cv_screening": normalize_cv(state.get("cv_screening"))}

    async def load_qa_analysis(state: MasterAssessmentState) -> dict[str, object]:
        return {"qa_analysis": normalize_qa(state.get("qa_analysis"))}

    async def synthesize_strengths_and_weaknesses(state: MasterAssessmentState) -> dict[str, object]:
        cv = state.get("cv_screening")
        qa = state.get("qa_analysis")
        catalog = evidence_catalog(cv if isinstance(cv, dict) else None, qa if isinstance(qa, dict) else None)
        if not catalog:
            strengths, weaknesses = fallback_citations(cv if isinstance(cv, dict) else None, qa if isinstance(qa, dict) else None)
            return {"strengths": [item["claim"] for item in strengths], "weaknesses": [item["claim"] for item in weaknesses], "traceability": strengths + weaknesses}
        prompt = (
            "Name strengths and weaknesses using only the evidence catalog. "
            'Return JSON {"strengths":[{"claim":"...","source_type":"cv","source_reference":"Q1"}],'
            '"weaknesses":[{"claim":"...","source_type":"transcript","source_reference":"Transcript turn 0.0-1.0"}]} . '
            "Copy source_type and source_reference from the catalog. Do not invent excerpts or timestamps.\n"
            f"{_catalog_block(catalog)}"
        )
        response = await llm.complete(
            prompt,
            system="You cite CV excerpts and transcript turns. Return only a JSON object.",
        )
        payload = _payload(response.content)
        strengths = accept_citations(payload.get("strengths"), catalog)
        weaknesses = accept_citations(payload.get("weaknesses"), catalog)
        if not strengths and not weaknesses:
            strengths, weaknesses = fallback_citations(cv if isinstance(cv, dict) else None, qa if isinstance(qa, dict) else None)
        return {
            "strengths": [item["claim"] for item in strengths],
            "weaknesses": [item["claim"] for item in weaknesses],
            "traceability": strengths + weaknesses,
            "tier_notes": [response.tier.value],
            "fallback_flags": [response.fallback_used],
        }

    async def identify_evidence_gaps(state: MasterAssessmentState) -> dict[str, object]:
        cv = state.get("cv_screening")
        qa = state.get("qa_analysis")
        return {
            "evidence_gaps": evidence_gaps_for(
                cv if isinstance(cv, dict) else None,
                qa if isinstance(qa, dict) else None,
            )
        }

    async def calculate_overall_suitability(state: MasterAssessmentState) -> dict[str, object]:
        cv = state.get("cv_screening")
        qa = state.get("qa_analysis")
        scores, overall, suitability = score_components(
            cv if isinstance(cv, dict) else None,
            qa if isinstance(qa, dict) else None,
        )
        return {"component_scores": scores, "overall_score": overall, "overall_suitability": suitability}

    async def generate_traceable_assessment_narrative(state: MasterAssessmentState) -> dict[str, object]:
        cv = state.get("cv_screening")
        qa = state.get("qa_analysis")
        catalog = evidence_catalog(cv if isinstance(cv, dict) else None, qa if isinstance(qa, dict) else None)
        fallback = fallback_narrative(
            state.get("component_scores") or {},
            state.get("overall_score"),
            str(state.get("overall_suitability") or "insufficient_evidence"),
            catalog,
        )
        if not catalog:
            return {"narrative": fallback}
        references = [reference for _source_type, reference in catalog]
        prompt = (
            "Write the assessment narrative for this candidate. "
            'Return JSON {"narrative":"..."} . '
            "Every claim about the candidate must include a source_reference copied from the catalog.\n"
            f"Suitability: {state.get('overall_suitability')}\n"
            "The quiz is a separate score. Do not mention it.\n"
            f"Scores: {state.get('component_scores')}\n"
            f"{_catalog_block(catalog)}"
        )
        response = await llm.complete(
            prompt,
            system="You write a short assessment and cite the catalog. Return only a JSON object.",
        )
        narrative = str(_payload(response.content).get("narrative") or "").strip()
        if not narrative_cites(narrative, references):
            narrative = fallback
        narrative = _state_contradictions(narrative, _contradiction_notes(qa.get("contradictions") if isinstance(qa, dict) else None))
        return {
            "narrative": _clip(narrative, _NARRATIVE_LIMIT),
            "tier_notes": [response.tier.value],
            "fallback_flags": [response.fallback_used],
        }

    async def persist_consolidated_assessment(state: MasterAssessmentState) -> dict[str, object]:
        notes = list(state.get("tier_notes") or [])
        flags = list(state.get("fallback_flags") or [])
        return {
            "llm_tier": notes[-1] if notes else "none",
            "fallback_used": any(flags),
        }

    graph: StateGraph = StateGraph(MasterAssessmentState)
    graph.add_node("load_candidate_data", load_candidate_data)
    graph.add_node("load_cv_screening_snapshot", load_cv_screening_snapshot)
    graph.add_node("load_qa_analysis", load_qa_analysis)
    graph.add_node("synthesize_strengths_and_weaknesses", synthesize_strengths_and_weaknesses)
    graph.add_node("identify_evidence_gaps", identify_evidence_gaps)
    graph.add_node("calculate_overall_suitability", calculate_overall_suitability)
    graph.add_node("generate_traceable_assessment_narrative", generate_traceable_assessment_narrative)
    graph.add_node("persist_consolidated_assessment", persist_consolidated_assessment)
    graph.add_edge(START, "load_candidate_data")
    graph.add_edge("load_candidate_data", "load_cv_screening_snapshot")
    graph.add_edge("load_cv_screening_snapshot", "load_qa_analysis")
    graph.add_edge("load_qa_analysis", "synthesize_strengths_and_weaknesses")
    graph.add_edge("synthesize_strengths_and_weaknesses", "identify_evidence_gaps")
    graph.add_edge("identify_evidence_gaps", "calculate_overall_suitability")
    graph.add_edge("calculate_overall_suitability", "generate_traceable_assessment_narrative")
    graph.add_edge("generate_traceable_assessment_narrative", "persist_consolidated_assessment")
    graph.add_edge("persist_consolidated_assessment", END)
    compiled = graph.compile()

    async def run(state: MasterAssessmentState) -> MasterAssessmentState:
        return await compiled.ainvoke(state)

    return run


def normalize_cv(raw: object) -> dict[str, object] | None:
    if not isinstance(raw, dict) or "aggregate_score" not in raw:
        return None
    try:
        aggregate = float(raw["aggregate_score"])
    except (TypeError, ValueError):
        return None
    evaluations: list[dict[str, str]] = []
    raw_evaluations = raw.get("evaluations") or []
    if isinstance(raw_evaluations, list):
        for item in raw_evaluations:
            if not isinstance(item, dict):
                continue
            query_id = str(item.get("query_id") or "").strip()
            if not query_id:
                continue
            evaluations.append(
                {
                    "query_id": query_id,
                    "question": str(item.get("question") or "").strip(),
                    "status": str(item.get("status") or "").strip(),
                    "evidence": " ".join(str(item.get("evidence") or "").split()),
                }
            )
    return {
        "aggregate_score": aggregate,
        "technical_score": _float(raw.get("technical_score")),
        "experience_score": _float(raw.get("experience_score")),
        "qualification_score": _float(raw.get("qualification_score")),
        "evaluations": evaluations,
    }


def normalize_mcq(raw: object) -> int | None:
    if isinstance(raw, dict):
        raw = raw.get("score")
    if raw is None or isinstance(raw, bool):
        return None
    try:
        score = int(raw)
    except (TypeError, ValueError):
        return None
    if score < 0 or score > 100:
        return None
    return score


def normalize_qa(raw: object) -> dict[str, object] | None:
    if not isinstance(raw, dict):
        return None
    if any(name not in raw for name in INTERVIEW_DIMENSIONS):
        return None
    pairs: list[dict[str, object]] = []
    raw_pairs = raw.get("pairs") or []
    if isinstance(raw_pairs, list):
        for item in raw_pairs:
            if not isinstance(item, dict):
                continue
            pair_id = str(item.get("pair_id") or "").strip()
            citation = str(item.get("citation") or "").strip()
            if not pair_id and not citation:
                continue
            pairs.append(
                {
                    "pair_id": pair_id,
                    "citation": citation,
                    "answer": " ".join(str(item.get("answer") or "").split()),
                    "relevance": _float(item.get("relevance")),
                    "technical_accuracy": _float(item.get("technical_accuracy")),
                    "completeness": _float(item.get("completeness")),
                    "articulation": _float(item.get("articulation")),
                }
            )
    gaps = raw.get("gaps") or []
    return {
        "relevance": _float(raw.get("relevance")),
        "technical_accuracy": _float(raw.get("technical_accuracy")),
        "completeness": _float(raw.get("completeness")),
        "articulation": _float(raw.get("articulation")),
        "gaps": [str(item).strip() for item in gaps if str(item).strip()] if isinstance(gaps, list) else [],
        "pairs": pairs,
        "contradictions": _contradiction_notes(raw.get("contradictions")),
    }


def checklist_points(value: float) -> float:
    """Turn a 0–1 checklist ratio into points on a 0–100 scale."""
    number = Decimal(str(round(float(value), 6)))
    if number <= 1:
        number *= 100
    if number < 0:
        number = Decimal(0)
    if number > 100:
        number = Decimal(100)
    return float(number.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))


def interview_points(relevance: float, technical_accuracy: float, completeness: float, articulation: float) -> float:
    """Turn four 0–10 interview dimensions into one 0–100 score."""
    parts = [_clamp_ten(item) for item in (relevance, technical_accuracy, completeness, articulation)]
    mean = sum(parts, Decimal(0)) / Decimal(4)
    return float((mean * 10).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))


def weighted_overall(cv: float, interview: float) -> float:
    """CV 37.5% and interview Q&A 62.5%. The quiz is not part of this score."""
    total = Decimal(str(cv)) * CV_WEIGHT + Decimal(str(interview)) * INTERVIEW_WEIGHT
    return float(total.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))


def overall_from_parts(cv: float | None, interview: float | None) -> tuple[float | None, str]:
    """The published master score. A missing CV or interview leaves it unset."""
    if cv is None or interview is None:
        return None, "insufficient_evidence"
    overall = weighted_overall(cv, interview)
    return overall, classify_suitability(overall)


def classify_suitability(overall: float | None) -> str:
    if overall is None:
        return "insufficient_evidence"
    score = Decimal(str(overall))
    if score >= STRONG_FIT_MIN:
        return "strong_fit"
    if score >= MODERATE_FIT_MIN:
        return "moderate_fit"
    return "unsuited"


def suitability_label(key: str) -> str:
    return SUITABILITY_LABELS.get(key, key)


def score_components(
    cv: dict[str, object] | None,
    qa: dict[str, object] | None,
) -> tuple[dict[str, float | None], float | None, str]:
    cv_score = checklist_points(float(cv["aggregate_score"])) if cv is not None else None
    technical = checklist_points(float(cv["technical_score"])) if cv is not None else None
    experience = checklist_points(float(cv["experience_score"])) if cv is not None else None
    qualification = checklist_points(float(cv["qualification_score"])) if cv is not None else None
    interview = (
        interview_points(
            float(qa["relevance"]),
            float(qa["technical_accuracy"]),
            float(qa["completeness"]),
            float(qa["articulation"]),
        )
        if qa is not None
        else None
    )
    overall, suitability = overall_from_parts(cv_score, interview)
    scores = {
        "cv_screening": cv_score,
        "interview_qa": interview,
        "technical_dimension": technical,
        "experience_dimension": experience,
        "qualification_dimension": qualification,
    }
    return scores, overall, suitability


def evidence_catalog(cv: dict[str, object] | None, qa: dict[str, object] | None) -> dict[tuple[str, str], str]:
    catalog: dict[tuple[str, str], str] = {}
    if cv is not None:
        evaluations = cv.get("evaluations") or []
        if isinstance(evaluations, list):
            for item in evaluations:
                if not isinstance(item, dict):
                    continue
                evidence = str(item.get("evidence") or "").strip()
                query_id = str(item.get("query_id") or "").strip()
                if query_id and evidence:
                    catalog.setdefault(("cv", query_id), evidence)
    if qa is not None:
        pairs = qa.get("pairs") or []
        if isinstance(pairs, list):
            for item in pairs:
                if not isinstance(item, dict):
                    continue
                citation = str(item.get("citation") or "").strip()
                answer = str(item.get("answer") or "").strip()
                if citation and answer:
                    catalog.setdefault(("transcript", citation), answer)
        for index, note in enumerate(_contradiction_notes(qa.get("contradictions")), start=1):
            catalog[("interview", f"CV contradiction {index}")] = note
    return catalog


def evidence_gaps_for(cv: dict[str, object] | None, qa: dict[str, object] | None) -> list[str]:
    gaps: list[str] = []
    if cv is None:
        gaps.append("CV screening snapshot is not available.")
    else:
        evaluations = cv.get("evaluations") or []
        if isinstance(evaluations, list):
            for item in evaluations:
                if not isinstance(item, dict) or item.get("status") not in _GAP_CV:
                    continue
                query_id = str(item.get("query_id") or "")
                label = str(item.get("question") or "").strip() or query_id
                gaps.append(f"CV evidence gap for {query_id}: {label}.")
    if qa is None:
        gaps.append("Interview Q&A analysis is not available.")
        return gaps
    raw_gaps = qa.get("gaps") or []
    if isinstance(raw_gaps, list):
        for item in raw_gaps:
            text = str(item).strip()
            if text and text not in gaps:
                gaps.append(text)
    pairs = qa.get("pairs") or []
    if isinstance(pairs, list):
        for item in pairs:
            if not isinstance(item, dict) or str(item.get("answer") or "").strip():
                continue
            citation = str(item.get("citation") or "").strip()
            pair_id = str(item.get("pair_id") or "answer")
            gaps.append(f"No answer recorded at {citation}." if citation else f"No answer recorded for {pair_id}.")
    for note in _contradiction_notes(qa.get("contradictions")):
        if note not in gaps:
            gaps.append(note)
    return gaps


def _contradiction_notes(raw: object) -> list[str]:
    if not isinstance(raw, list):
        return []
    notes: list[str] = []
    for item in raw:
        text = " ".join(str(item).split())
        if text and text not in notes:
            notes.append(text)
    return notes


def _state_contradictions(narrative: str, notes: list[str]) -> str:
    missing = [note for note in notes if note not in narrative]
    if not missing:
        return narrative
    return f"{narrative.rstrip()} {' '.join(missing)}".strip()


def accept_citations(raw: object, catalog: dict[tuple[str, str], str]) -> list[dict[str, str]]:
    if not isinstance(raw, list):
        return []
    accepted: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for item in raw:
        if not isinstance(item, dict):
            continue
        source_type = str(item.get("source_type") or "").strip()
        reference = str(item.get("source_reference") or "").strip()
        claim = " ".join(str(item.get("claim") or "").split())
        key = (source_type, reference)
        if source_type not in _CITED_SOURCES or key not in catalog or not claim or key in seen:
            continue
        seen.add(key)
        accepted.append(
            {
                "claim": _clip(claim, _CLAIM_LIMIT),
                "source_type": source_type,
                "source_reference": reference,
                "evidence": catalog[key],
            }
        )
    return accepted


def fallback_citations(
    cv: dict[str, object] | None,
    qa: dict[str, object] | None,
) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    strengths: list[dict[str, str]] = []
    weaknesses: list[dict[str, str]] = []
    if cv is not None:
        evaluations = cv.get("evaluations") or []
        if isinstance(evaluations, list):
            for item in evaluations:
                if not isinstance(item, dict):
                    continue
                evidence = str(item.get("evidence") or "").strip()
                query_id = str(item.get("query_id") or "").strip()
                status = str(item.get("status") or "")
                if not evidence or not query_id:
                    continue
                label = str(item.get("question") or "").strip() or query_id
                record = {
                    "claim": f"{label} is {status.replace('_', ' ')}.",
                    "source_type": "cv",
                    "source_reference": query_id,
                    "evidence": evidence,
                }
                if status in _POSITIVE_CV:
                    strengths.append(record)
                elif status in _GAP_CV:
                    weaknesses.append(record)
    if qa is not None:
        pairs = qa.get("pairs") or []
        if isinstance(pairs, list):
            for item in pairs:
                if not isinstance(item, dict):
                    continue
                citation = str(item.get("citation") or "").strip()
                answer = str(item.get("answer") or "").strip()
                if not citation or not answer:
                    continue
                mean = sum(_float(item.get(name)) for name in INTERVIEW_DIMENSIONS) / 4
                record = {
                    "claim": _clip(answer, 180),
                    "source_type": "transcript",
                    "source_reference": citation,
                    "evidence": answer,
                }
                if mean >= 7:
                    strengths.append(record)
                elif mean < 5:
                    weaknesses.append(record)
    return strengths[:6], weaknesses[:6]


def narrative_cites(narrative: str, references: list[str]) -> bool:
    for reference in sorted((item for item in references if item), key=len, reverse=True):
        if _contains_reference(narrative, reference):
            return True
    return False


def fallback_narrative(
    scores: dict[str, float | None],
    overall: float | None,
    suitability: str,
    catalog: dict[tuple[str, str], str],
) -> str:
    cv_text = _points(scores.get("cv_screening"))
    qa_text = _points(scores.get("interview_qa"))
    overall_text = f"{overall:.1f}" if overall is not None else "not calculated"
    sentences = [
        (
            "The master score weights CV screening at 37.5 percent "
            f"({cv_text}) and interview Q&A at 62.5 percent ({qa_text})."
        ),
        f"The overall score is {overall_text}. Overall suitability is {suitability_label(suitability)}.",
    ]
    if catalog:
        (_source_type, reference), evidence = next(iter(catalog.items()))
        sentences.append(f"Cited source {reference}: {evidence}")
    else:
        sentences.append("No CV excerpt or interview transcript turn was available to cite.")
    return " ".join(sentences)


def _contains_reference(narrative: str, reference: str) -> bool:
    start = 0
    while True:
        index = narrative.find(reference, start)
        if index < 0:
            return False
        after = index + len(reference)
        before_ok = index == 0 or not narrative[index - 1].isalnum()
        after_ok = after >= len(narrative) or not narrative[after].isalnum()
        if before_ok and after_ok:
            return True
        start = index + 1


def _catalog_block(catalog: dict[tuple[str, str], str]) -> str:
    lines = [f"- {source_type} {reference}: {evidence}" for (source_type, reference), evidence in catalog.items()]
    return "Catalog:\n" + "\n".join(lines)


def _payload(text: str) -> dict[str, object]:
    try:
        return parse_json_object(text)
    except JobGraphError:
        return {}


def _float(value: object) -> float:
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0.0


def _clamp_ten(value: float) -> Decimal:
    number = Decimal(str(round(float(value), 4)))
    if number < 0:
        return Decimal(0)
    if number > 10:
        return Decimal(10)
    return number


def _points(value: float | None) -> str:
    if value is None:
        return "unavailable"
    return f"{value:.1f}"


def _clip(text: str, limit: int) -> str:
    cleaned = " ".join(text.split())
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: limit - 1].rstrip() + "…"
