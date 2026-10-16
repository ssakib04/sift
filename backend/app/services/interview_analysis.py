from dataclasses import dataclass

from app.core.llm_fallback import FallbackLLMManager
from app.graphs.qa_analysis_graph import build_qa_analysis_graph


@dataclass(frozen=True)
class QAPairDraft:
    pair_id: str
    sequence: int
    question: str
    answer: str
    intent: str
    start_time: float
    end_time: float
    citation: str
    query_ids: list[str]
    relevance: float
    technical_accuracy: float
    completeness: float
    articulation: float
    notes: dict[str, str]


@dataclass(frozen=True)
class JustificationDraft:
    claim: str
    citation: str


@dataclass(frozen=True)
class AnalysisDraft:
    relevance: float
    technical_accuracy: float
    completeness: float
    articulation: float
    gaps: list[str]
    discrepancies: list[str]
    summary: str
    justifications: list[JustificationDraft]
    pairs: list[QAPairDraft]
    llm_tier: str
    fallback_used: bool


def draft_for_empty_transcript() -> AnalysisDraft:
    return AnalysisDraft(
        relevance=0.0,
        technical_accuracy=0.0,
        completeness=0.0,
        articulation=0.0,
        gaps=["No interview transcript was captured."],
        discrepancies=[],
        summary="No speech was captured for this interview.",
        justifications=[],
        pairs=[],
        llm_tier="none",
        fallback_used=False,
    )


async def draft_for_transcript(
    llm: FallbackLLMManager,
    checklist: list[dict[str, str]],
    turns: list[dict[str, object]],
) -> AnalysisDraft:
    """Run LangGraph Workflow 3 for one finished interview."""
    if not any(str(turn.get("text") or "").strip() for turn in turns):
        return draft_for_empty_transcript()
    result = await build_qa_analysis_graph(llm)(
        {
            "turns": turns,
            "checklist": checklist,
            "tier_notes": [],
            "fallback_flags": [],
        }
    )
    return _draft(result)


def _draft(result: dict[str, object]) -> AnalysisDraft:
    pairs: list[QAPairDraft] = []
    raw_pairs = result.get("pairs") or []
    if isinstance(raw_pairs, list):
        for index, item in enumerate(raw_pairs, start=1):
            if isinstance(item, dict):
                pairs.append(_pair(item, index))
    justifications: list[JustificationDraft] = []
    raw_claims = result.get("justifications") or []
    if isinstance(raw_claims, list):
        for item in raw_claims:
            if not isinstance(item, dict):
                continue
            claim = str(item.get("claim") or "").strip()
            citation = str(item.get("citation") or "").strip()
            if claim and citation:
                justifications.append(JustificationDraft(claim=claim, citation=citation))
    gaps = [str(item) for item in result.get("gaps") or [] if str(item).strip()]
    discrepancies = [str(item) for item in result.get("discrepancies") or [] if str(item).strip()]
    return AnalysisDraft(
        relevance=float(result.get("relevance") or 0.0),
        technical_accuracy=float(result.get("technical_accuracy") or 0.0),
        completeness=float(result.get("completeness") or 0.0),
        articulation=float(result.get("articulation") or 0.0),
        gaps=gaps,
        discrepancies=discrepancies,
        summary=str(result.get("summary") or ""),
        justifications=justifications,
        pairs=pairs,
        llm_tier=str(result.get("llm_tier") or "unknown"),
        fallback_used=bool(result.get("fallback_used")),
    )


def _pair(item: dict[str, object], sequence: int) -> QAPairDraft:
    notes = item.get("notes") if isinstance(item.get("notes"), dict) else {}
    query_ids = item.get("query_ids") if isinstance(item.get("query_ids"), list) else []
    return QAPairDraft(
        pair_id=str(item.get("pair_id") or f"QA_{sequence:02d}"),
        sequence=sequence,
        question=str(item.get("question") or ""),
        answer=str(item.get("answer") or ""),
        intent=str(item.get("intent") or "unclassified"),
        start_time=float(item.get("start") or 0.0),
        end_time=float(item.get("end") or 0.0),
        citation=str(item.get("citation") or ""),
        query_ids=[str(query_id) for query_id in query_ids],
        relevance=float(item.get("relevance") or 0.0),
        technical_accuracy=float(item.get("technical_accuracy") or 0.0),
        completeness=float(item.get("completeness") or 0.0),
        articulation=float(item.get("articulation") or 0.0),
        notes={str(key): str(value) for key, value in notes.items()},
    )
