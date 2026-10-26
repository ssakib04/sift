import asyncio
from collections.abc import Awaitable, Callable

from langgraph.graph import END, START, StateGraph

from app.core.llm_fallback import FallbackLLMManager
from app.graphs.job_creation_graph import JobGraphError, parse_json_object
from app.graphs.state import QAAnalysisState
from app.services.transcript_cleanup import pair_speech

DIMENSIONS = ("relevance", "technical_accuracy", "completeness", "articulation")
INTENTS = {"technical", "experience", "qualification", "clarification", "other"}
DISCREPANCY_SPREAD = 3.0
_TEXT_LIMIT = 1200
_MODEL_WAIT_SECONDS = 45.0


def build_qa_analysis_graph(
    llm: FallbackLLMManager,
) -> Callable[[QAAnalysisState], Awaitable[QAAnalysisState]]:
    """Workflow 3: segment the transcript, score each answer, then record gaps."""

    async def load_transcript(state: QAAnalysisState) -> dict[str, object]:
        return {"turns": normalize_turns(state.get("turns") or []), "checklist": normalize_checklist(state.get("checklist") or [])}

    async def segment_transcript_into_qa(state: QAAnalysisState) -> dict[str, object]:
        return {"pairs": segment_turns(list(state.get("turns") or []))}

    async def classify_question_intent(state: QAAnalysisState) -> dict[str, object]:
        pairs = [dict(pair) for pair in state.get("pairs") or []]
        if not pairs:
            return {"pairs": []}
        prompt = (
            "Label the intent of each interview question. "
            'Return JSON {"pairs":[{"pair_id":"QA_01","intent":"technical"}]} . '
            f"intent must be one of: {', '.join(sorted(INTENTS))}.\n"
            f"{_pair_block(pairs)}"
        )
        payload, response, failed = await _model_json(
            llm,
            prompt,
            "You label interview questions. Return only a JSON object.",
        )
        intents = _intent_map(payload)
        for pair in pairs:
            pair["intent"] = intents.get(str(pair["pair_id"]), "unclassified")
        return {
            "pairs": pairs,
            "tier_notes": [response.tier.value if response is not None else "unavailable"],
            "fallback_flags": [failed or (response.fallback_used if response is not None else True)],
        }

    async def score_dimension(state: QAAnalysisState, dimension: str) -> dict[str, object]:
        pairs = list(state.get("pairs") or [])
        label = dimension.replace("_", " ")
        prompt = (
            f"Score {label} of each candidate answer from 0 to 10. "
            'Return JSON {"scores":[{"pair_id":"QA_01","score":8,"note":"why"}]} . '
            "Use only the answer and the checklist.\n"
            f"Checklist:\n{_checklist_block(state.get('checklist') or [])}\n\n"
            f"{_pair_block(pairs)}"
        )
        payload, response, failed = await _model_json(
            llm,
            prompt,
            "You score one interview dimension for each answer. Return only a JSON object.",
        )
        return {
            f"{dimension}_by_pair": scores_for(pairs, payload),
            "tier_notes": [response.tier.value if response is not None else "unavailable"],
            "fallback_flags": [failed or (response.fallback_used if response is not None else True)],
        }

    async def evaluate_relevance(state: QAAnalysisState) -> dict[str, object]:
        return await score_dimension(state, "relevance")

    async def evaluate_technical_accuracy(state: QAAnalysisState) -> dict[str, object]:
        return await score_dimension(state, "technical_accuracy")

    async def evaluate_completeness(state: QAAnalysisState) -> dict[str, object]:
        return await score_dimension(state, "completeness")

    async def evaluate_articulation(state: QAAnalysisState) -> dict[str, object]:
        return await score_dimension(state, "articulation")

    async def map_qa_to_checklist(state: QAAnalysisState) -> dict[str, object]:
        pairs = apply_dimension_scores(list(state.get("pairs") or []), state)
        if not pairs:
            return {"pairs": []}
        allowed = [item["query_id"] for item in state.get("checklist") or []]
        prompt = (
            "Map each candidate answer to checklist query ids. "
            'Return JSON {"pairs":[{"pair_id":"QA_01","query_ids":["Q1"]}]} . '
            "Use an empty list when the answer does not cover a query. "
            f"Allowed ids: {', '.join(allowed) or 'none'}.\n"
            f"Checklist:\n{_checklist_block(state.get('checklist') or [])}\n\n"
            f"{_pair_block(pairs)}"
        )
        payload, response, failed = await _model_json(
            llm,
            prompt,
            "You map answers to checklist ids. Return only a JSON object.",
        )
        mapped = _query_map(payload, set(allowed))
        for pair in pairs:
            pair["query_ids"] = mapped.get(str(pair["pair_id"]), [])
        return {
            "pairs": pairs,
            "tier_notes": [response.tier.value if response is not None else "unavailable"],
            "fallback_flags": [failed or (response.fallback_used if response is not None else True)],
        }

    async def identify_coverage_gaps(state: QAAnalysisState) -> dict[str, object]:
        pairs = list(state.get("pairs") or [])
        checklist = list(state.get("checklist") or [])
        return {"gaps": uncovered_gaps(checklist, pairs), "discrepancies": find_discrepancies(pairs)}

    async def generate_qa_justifications(state: QAAnalysisState) -> dict[str, object]:
        pairs = list(state.get("pairs") or [])
        citations = [str(pair["citation"]) for pair in pairs]
        prompt = (
            "Write justifications for this interview. "
            'Return JSON {"summary":"...","claims":[{"claim":"...","citation":"Transcript turn 0.0-1.0"}]} . '
            "Every citation must be copied from the citations list. Do not invent timestamps.\n"
            f"Citations:\n" + "\n".join(f"- {citation}" for citation in citations) + "\n"
            f"Gaps:\n" + "\n".join(f"- {gap}" for gap in state.get("gaps") or []) + "\n"
            f"Discrepancies:\n" + "\n".join(f"- {item}" for item in state.get("discrepancies") or []) + "\n"
            f"{_scored_block(pairs)}"
        )
        payload, response, failed = await _model_json(
            llm,
            prompt,
            "You justify interview scores with transcript citations. Return only a JSON object.",
        )
        summary, claims = _justification(payload, pairs)
        return {
            "summary": summary,
            "justifications": claims,
            "tier_notes": [response.tier.value if response is not None else "unavailable"],
            "fallback_flags": [failed or (response.fallback_used if response is not None else True)],
        }

    async def persist_qa_analysis(state: QAAnalysisState) -> dict[str, object]:
        pairs = list(state.get("pairs") or [])
        notes = list(state.get("tier_notes") or [])
        flags = list(state.get("fallback_flags") or [])
        summary = str(state.get("summary") or "").strip() or _fallback_summary(pairs)
        return {
            "relevance": mean_dimension(pairs, "relevance"),
            "technical_accuracy": mean_dimension(pairs, "technical_accuracy"),
            "completeness": mean_dimension(pairs, "completeness"),
            "articulation": mean_dimension(pairs, "articulation"),
            "summary": summary,
            "justifications": list(state.get("justifications") or []) or fallback_claims(pairs),
            "llm_tier": notes[-1] if notes else "unknown",
            "fallback_used": any(flags),
        }

    graph: StateGraph = StateGraph(QAAnalysisState)
    graph.add_node("load_transcript", load_transcript)
    graph.add_node("segment_transcript_into_qa", segment_transcript_into_qa)
    graph.add_node("classify_question_intent", classify_question_intent)
    graph.add_node("evaluate_relevance", evaluate_relevance)
    graph.add_node("evaluate_technical_accuracy", evaluate_technical_accuracy)
    graph.add_node("evaluate_completeness", evaluate_completeness)
    graph.add_node("evaluate_articulation", evaluate_articulation)
    graph.add_node("map_qa_to_checklist", map_qa_to_checklist)
    graph.add_node("identify_coverage_gaps", identify_coverage_gaps)
    graph.add_node("generate_qa_justifications", generate_qa_justifications)
    graph.add_node("persist_qa_analysis", persist_qa_analysis)
    graph.add_edge(START, "load_transcript")
    graph.add_edge("load_transcript", "segment_transcript_into_qa")
    graph.add_edge("segment_transcript_into_qa", "classify_question_intent")
    for name in (
        "evaluate_relevance",
        "evaluate_technical_accuracy",
        "evaluate_completeness",
        "evaluate_articulation",
    ):
        graph.add_edge("classify_question_intent", name)
        graph.add_edge(name, "map_qa_to_checklist")
    graph.add_edge("map_qa_to_checklist", "identify_coverage_gaps")
    graph.add_edge("identify_coverage_gaps", "generate_qa_justifications")
    graph.add_edge("generate_qa_justifications", "persist_qa_analysis")
    graph.add_edge("persist_qa_analysis", END)
    compiled = graph.compile()

    async def run(state: QAAnalysisState) -> QAAnalysisState:
        return await compiled.ainvoke(state)

    return run


def normalize_turns(raw: list[object]) -> list[dict[str, object]]:
    turns: list[dict[str, object]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        speaker = str(item.get("speaker") or "")
        text = str(item.get("text") or "").strip()
        if speaker not in {"recruiter", "candidate"} or not text:
            continue
        turns.append({"speaker": speaker, "start": _time(item.get("start")), "end": _time(item.get("end")), "text": text})
    return turns


def normalize_checklist(raw: list[object]) -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    for index, item in enumerate(raw, start=1):
        if isinstance(item, str) and item.strip():
            items.append({"query_id": f"Q{index}", "question": item.strip()})
            continue
        if not isinstance(item, dict):
            continue
        query_id = str(item.get("query_id") or "").strip()
        question = str(item.get("question") or "").strip()
        if query_id and question:
            items.append({"query_id": query_id, "question": question})
    return items


def segment_turns(turns: list[dict[str, object]]) -> list[dict[str, object]]:
    """Pair each recruiter question with the candidate answer that follows it."""
    sequenced = [
        (str(turn["speaker"]), str(turn["text"]), float(turn["start"]), float(turn["end"]))
        for turn in turns
    ]
    paired = pair_speech(sequenced, unasked="The candidate spoke before a question was asked.")
    pairs: list[dict[str, object]] = []
    for index, item in enumerate(paired, start=1):
        pair = _blank_pair(item.question, item.answer, item.start, item.end)
        pair["pair_id"] = f"QA_{index:02d}"
        pairs.append(pair)
    return pairs


def apply_dimension_scores(pairs: list[dict[str, object]], state: QAAnalysisState) -> list[dict[str, object]]:
    merged: list[dict[str, object]] = []
    for pair in pairs:
        updated = dict(pair)
        notes: dict[str, str] = {}
        pair_id = str(pair.get("pair_id") or "")
        for dimension in DIMENSIONS:
            bucket = state.get(f"{dimension}_by_pair") or {}
            item = bucket.get(pair_id) if isinstance(bucket, dict) else None
            score = _clamp(item.get("score")) if isinstance(item, dict) else 0.0
            note = str(item.get("note") or "").strip() if isinstance(item, dict) else ""
            if not note:
                note = "The model did not score this answer."
            updated[dimension] = score
            notes[dimension] = note
        updated["notes"] = notes
        merged.append(updated)
    return merged


def scores_for(pairs: list[dict[str, object]], payload: dict[str, object]) -> dict[str, dict[str, object]]:
    found: dict[str, dict[str, object]] = {}
    raw_scores = payload.get("scores")
    if isinstance(raw_scores, list):
        for item in raw_scores:
            if not isinstance(item, dict):
                continue
            pair_id = str(item.get("pair_id") or "")
            if not pair_id:
                continue
            note = str(item.get("note") or "").strip()
            found[pair_id] = {"score": _clamp(item.get("score")), "note": note}
    for pair in pairs:
        found.setdefault(str(pair["pair_id"]), {"score": 0.0, "note": "The model did not score this answer."})
    return found


def find_discrepancies(pairs: list[dict[str, object]]) -> list[str]:
    found: list[str] = []
    for pair in pairs:
        scores = {name: float(pair.get(name) or 0.0) for name in DIMENSIONS}
        high = max(scores, key=lambda name: scores[name])
        low = min(scores, key=lambda name: scores[name])
        if scores[high] - scores[low] < DISCREPANCY_SPREAD:
            continue
        found.append(
            f"{pair['pair_id']}: {high.replace('_', ' ')} {scores[high]:.1f} and "
            f"{low.replace('_', ' ')} {scores[low]:.1f} disagree. {pair['citation']}"
        )
    return found


def uncovered_gaps(checklist: list[dict[str, str]], pairs: list[dict[str, object]]) -> list[str]:
    covered: set[str] = set()
    for pair in pairs:
        raw_ids = pair.get("query_ids") or []
        if isinstance(raw_ids, list):
            covered.update(str(query_id) for query_id in raw_ids)
    return [item["question"] for item in checklist if item["query_id"] not in covered]


def mean_dimension(pairs: list[dict[str, object]], dimension: str) -> float:
    answered = [pair for pair in pairs if str(pair.get("answer") or "").strip()]
    if not answered:
        return 0.0
    total = sum(float(pair.get(dimension) or 0.0) for pair in answered)
    return round(total / len(answered), 1)


def fallback_claims(pairs: list[dict[str, object]]) -> list[dict[str, str]]:
    claims: list[dict[str, str]] = []
    for pair in pairs:
        answer = str(pair.get("answer") or "").strip()
        citation = str(pair.get("citation") or "")
        if not citation:
            continue
        excerpt = answer[:180] if answer else "The candidate did not answer."
        claims.append({"claim": f"{pair['pair_id']}: {excerpt}", "citation": citation})
    return claims


def _blank_pair(question: str, answer: str, start: float, end: float) -> dict[str, object]:
    return {
        "pair_id": "",
        "question": question,
        "answer": answer,
        "intent": "unclassified",
        "start": start,
        "end": end,
        "citation": f"Transcript turn {start:.1f}-{end:.1f}",
        "query_ids": [],
        "relevance": 0.0,
        "technical_accuracy": 0.0,
        "completeness": 0.0,
        "articulation": 0.0,
        "notes": {},
    }


def _pair_block(pairs: list[dict[str, object]]) -> str:
    lines: list[str] = []
    for pair in pairs:
        lines.append(
            f"{pair['pair_id']} {pair['citation']}\n"
            f"Question: {_clip(str(pair.get('question') or ''))}\n"
            f"Answer: {_clip(str(pair.get('answer') or ''))}"
        )
    return "\n\n".join(lines)


def _scored_block(pairs: list[dict[str, object]]) -> str:
    lines: list[str] = []
    for pair in pairs:
        scores = ", ".join(f"{name}={float(pair.get(name) or 0):.1f}" for name in DIMENSIONS)
        lines.append(f"{pair['pair_id']} {pair['citation']} {scores}\nAnswer: {_clip(str(pair.get('answer') or ''))}")
    return "\n\n".join(lines)


def _checklist_block(checklist: list[dict[str, str]]) -> str:
    if not checklist:
        return "No checklist was locked."
    return "\n".join(f"- {item['query_id']}: {item['question']}" for item in checklist)


def _intent_map(payload: dict[str, object]) -> dict[str, str]:
    found: dict[str, str] = {}
    raw_pairs = payload.get("pairs")
    if not isinstance(raw_pairs, list):
        return found
    for item in raw_pairs:
        if not isinstance(item, dict):
            continue
        pair_id = str(item.get("pair_id") or "")
        intent = str(item.get("intent") or "").strip().lower()
        if pair_id and intent in INTENTS:
            found[pair_id] = intent
    return found


def _query_map(payload: dict[str, object], allowed: set[str]) -> dict[str, list[str]]:
    found: dict[str, list[str]] = {}
    raw_pairs = payload.get("pairs")
    if not isinstance(raw_pairs, list):
        return found
    for item in raw_pairs:
        if not isinstance(item, dict):
            continue
        pair_id = str(item.get("pair_id") or "")
        raw_ids = item.get("query_ids")
        if not pair_id or not isinstance(raw_ids, list):
            continue
        ids = []
        for query_id in raw_ids:
            text = str(query_id).strip()
            if text in allowed and text not in ids:
                ids.append(text)
        found[pair_id] = ids
    return found


def _justification(payload: dict[str, object], pairs: list[dict[str, object]]) -> tuple[str, list[dict[str, str]]]:
    allowed = {str(pair.get("citation") or "") for pair in pairs}
    summary = str(payload.get("summary") or "").strip()
    claims: list[dict[str, str]] = []
    raw_claims = payload.get("claims")
    if isinstance(raw_claims, list):
        for item in raw_claims:
            if not isinstance(item, dict):
                continue
            claim = str(item.get("claim") or "").strip()
            citation = str(item.get("citation") or "").strip()
            if claim and citation in allowed:
                claims.append({"claim": claim, "citation": citation})
    if not summary:
        summary = _fallback_summary(pairs)
    if not claims:
        claims = fallback_claims(pairs)
    return summary, claims


def _fallback_summary(pairs: list[dict[str, object]]) -> str:
    if not pairs:
        return "No question and answer pairs were captured."
    return f"The interview produced {len(pairs)} question and answer pairs."


async def _model_json(llm: FallbackLLMManager, prompt: str, system: str) -> tuple[dict[str, object], object | None, bool]:
    """One model reply. A stall or a bad reply becomes an empty object so the report can still be saved."""
    try:
        response = await asyncio.wait_for(llm.complete(prompt, system=system), timeout=_MODEL_WAIT_SECONDS)
    except Exception:
        return {}, None, True
    return _payload(response.content), response, False


def _payload(text: str) -> dict[str, object]:
    try:
        return parse_json_object(text)
    except JobGraphError:
        return {}


def _clip(text: str) -> str:
    cleaned = " ".join(text.split())
    if len(cleaned) <= _TEXT_LIMIT:
        return cleaned
    return cleaned[:_TEXT_LIMIT]


def _time(value: object) -> float:
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0.0


def _clamp(value: object) -> float:
    try:
        score = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(10.0, score))
