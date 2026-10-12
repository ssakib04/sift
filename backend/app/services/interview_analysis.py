from dataclasses import dataclass

from app.core.llm_fallback import FallbackLLMManager
from app.graphs.qa_analysis_graph import build_qa_analysis_graph


@dataclass(frozen=True)
class AnalysisDraft:
    relevance: float
    technical_accuracy: float
    completeness: float
    articulation: float
    gaps: list[str]
    summary: str
    llm_tier: str
    fallback_used: bool


def draft_for_empty_transcript() -> AnalysisDraft:
    return AnalysisDraft(
        relevance=0.0,
        technical_accuracy=0.0,
        completeness=0.0,
        articulation=0.0,
        gaps=["No interview transcript was captured."],
        summary="No speech was captured for this interview.",
        llm_tier="none",
        fallback_used=False,
    )


async def draft_for_transcript(
    llm: FallbackLLMManager,
    checklist: list[str],
    transcript: str,
) -> AnalysisDraft:
    if not transcript.strip():
        return draft_for_empty_transcript()
    result = await build_qa_analysis_graph(llm)(
        {
            "transcript": transcript,
            "checklist": checklist,
            "tier_notes": [],
            "fallback_flags": [],
        }
    )
    return AnalysisDraft(
        relevance=float(result.get("relevance") or 0.0),
        technical_accuracy=float(result.get("technical_accuracy") or 0.0),
        completeness=float(result.get("completeness") or 0.0),
        articulation=float(result.get("articulation") or 0.0),
        gaps=list(result.get("gaps") or []),
        summary=str(result.get("summary") or ""),
        llm_tier=str(result.get("llm_tier") or "unknown"),
        fallback_used=bool(result.get("fallback_used")),
    )
