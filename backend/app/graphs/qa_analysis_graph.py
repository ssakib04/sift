from collections.abc import Awaitable, Callable

from langgraph.graph import END, START, StateGraph

from app.core.llm_fallback import FallbackLLMManager
from app.graphs.job_creation_graph import JobGraphError, parse_json_object
from app.graphs.state import QAAnalysisState

_DIMENSIONS = ("relevance", "technical_accuracy", "completeness", "articulation")


def build_qa_analysis_graph(
    llm: FallbackLLMManager,
) -> Callable[[QAAnalysisState], Awaitable[QAAnalysisState]]:
    async def evaluate(state: QAAnalysisState, dimension: str) -> dict[str, object]:
        label = dimension.replace("_", " ")
        checklist = "\n".join(f"- {question}" for question in state.get("checklist") or [])
        prompt = (
            f"Score the candidate's interview answers for {label} on a scale from 0 to 10. "
            "Return JSON with keys score and note. Use only the transcript and the checklist.\n"
            f"Checklist:\n{checklist}\n\nTranscript:\n{state.get('transcript', '')}"
        )
        response = await llm.complete(
            prompt,
            system="You score one interview dimension. Return only a JSON object.",
        )
        score = 0.0
        try:
            payload = parse_json_object(response.content)
            score = _clamp(payload.get("score"))
        except JobGraphError:
            score = 0.0
        return {
            dimension: score,
            "tier_notes": [response.tier.value],
            "fallback_flags": [response.fallback_used],
        }

    async def relevance(state: QAAnalysisState) -> dict[str, object]:
        return await evaluate(state, "relevance")

    async def technical_accuracy(state: QAAnalysisState) -> dict[str, object]:
        return await evaluate(state, "technical_accuracy")

    async def completeness(state: QAAnalysisState) -> dict[str, object]:
        return await evaluate(state, "completeness")

    async def articulation(state: QAAnalysisState) -> dict[str, object]:
        return await evaluate(state, "articulation")

    async def synthesize(state: QAAnalysisState) -> dict[str, object]:
        checklist = "\n".join(f"- {question}" for question in state.get("checklist") or [])
        prompt = (
            "List requirement gaps that remain after the interview and write a short summary. "
            "Return JSON with keys gaps (list of strings) and summary (string).\n"
            f"relevance={state.get('relevance', 0)} "
            f"technical_accuracy={state.get('technical_accuracy', 0)} "
            f"completeness={state.get('completeness', 0)} "
            f"articulation={state.get('articulation', 0)}\n"
            f"Checklist:\n{checklist}\n\nTranscript:\n{state.get('transcript', '')}"
        )
        response = await llm.complete(
            prompt,
            system="You summarize an interview against a locked checklist. Return only a JSON object.",
        )
        gaps: list[str] = []
        summary = "The interview was scored."
        try:
            payload = parse_json_object(response.content)
            raw_gaps = payload.get("gaps")
            if isinstance(raw_gaps, list):
                gaps = [item.strip() for item in raw_gaps if isinstance(item, str) and item.strip()]
            raw_summary = payload.get("summary")
            if isinstance(raw_summary, str) and raw_summary.strip():
                summary = raw_summary.strip()
        except JobGraphError:
            gaps = []
        flags = list(state.get("fallback_flags") or [])
        flags.append(response.fallback_used)
        return {"gaps": gaps, "summary": summary, "llm_tier": response.tier.value, "fallback_used": any(flags)}

    graph: StateGraph = StateGraph(QAAnalysisState)
    graph.add_node("relevance", relevance)
    graph.add_node("technical_accuracy", technical_accuracy)
    graph.add_node("completeness", completeness)
    graph.add_node("articulation", articulation)
    graph.add_node("synthesize", synthesize)
    for name in _DIMENSIONS:
        graph.add_edge(START, name)
        graph.add_edge(name, "synthesize")
    graph.add_edge("synthesize", END)
    compiled = graph.compile()

    async def run(state: QAAnalysisState) -> QAAnalysisState:
        result = await compiled.ainvoke(state)
        return result

    return run


def _clamp(value: object) -> float:
    try:
        score = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(10.0, score))
