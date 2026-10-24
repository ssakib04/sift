import json

import pytest

from app.core.llm_fallback import FallbackLLMManager
from app.graphs.qa_analysis_graph import (
    _justification,
    apply_dimension_scores,
    find_discrepancies,
    mean_dimension,
    segment_turns,
    uncovered_gaps,
)
from app.services.interview_analysis import draft_for_empty_transcript, draft_for_transcript


class BoomProvider:
    async def complete(self, prompt: str, *, system: str | None = None) -> str:
        del prompt, system
        raise AssertionError("empty transcript must not call the model")


class ScriptedProvider:
    def __init__(self, *, justification: dict[str, object] | None = None, relevance: dict[str, object] | None = None) -> None:
        self.calls = 0
        self.justification = justification or {
            "summary": "The candidate described a FastAPI service.",
            "claims": [
                {
                    "claim": "The candidate shipped a FastAPI service.",
                    "citation": "Transcript turn 2.5-4.0",
                }
            ],
        }
        self.relevance = relevance or {"scores": [{"pair_id": "QA_01", "score": 9, "note": "on topic"}]}

    async def complete(self, prompt: str, *, system: str | None = None) -> str:
        del system
        self.calls += 1
        if prompt.startswith("Label the intent"):
            return json.dumps({"pairs": [{"pair_id": "QA_01", "intent": "technical"}]})
        if prompt.startswith("Score relevance"):
            return json.dumps(self.relevance)
        if prompt.startswith("Score technical accuracy"):
            return json.dumps({"scores": [{"pair_id": "QA_01", "score": 3, "note": "thin"}]})
        if prompt.startswith("Score completeness"):
            return json.dumps({"scores": [{"pair_id": "QA_01", "score": 8, "note": "mostly"}]})
        if prompt.startswith("Score articulation"):
            return json.dumps({"scores": [{"pair_id": "QA_01", "score": 8, "note": "clear"}]})
        if prompt.startswith("Map each candidate answer"):
            return json.dumps({"pairs": [{"pair_id": "QA_01", "query_ids": ["Q1", "Q9"]}]})
        if prompt.startswith("Write justifications"):
            return json.dumps(self.justification)
        raise AssertionError(prompt[:80])


def _checklist() -> list[dict[str, str]]:
    return [
        {"query_id": "Q1", "question": "FastAPI experience"},
        {"query_id": "Q2", "question": "Docker experience"},
    ]


def _turns() -> list[dict[str, object]]:
    return [
        {"speaker": "recruiter", "start": 1.0, "end": 2.0, "text": "How have you used FastAPI?"},
        {"speaker": "candidate", "start": 2.5, "end": 4.0, "text": "I shipped a FastAPI service."},
    ]


def test_segment_pairs_a_question_with_the_following_answer() -> None:
    pairs = segment_turns(
        [
            {"speaker": "candidate", "start": 0.0, "end": 1.0, "text": "Hello."},
            {"speaker": "recruiter", "start": 1.0, "end": 2.0, "text": "How have you used FastAPI?"},
            {"speaker": "candidate", "start": 2.5, "end": 3.0, "text": "I shipped a service."},
            {"speaker": "candidate", "start": 3.0, "end": 4.0, "text": "It used FastAPI."},
            {"speaker": "recruiter", "start": 5.0, "end": 6.0, "text": "And Docker?"},
        ]
    )
    assert [pair["pair_id"] for pair in pairs] == ["QA_01", "QA_02", "QA_03"]
    assert pairs[0]["question"] == "The candidate spoke before a question was asked."
    assert pairs[1]["answer"] == "I shipped a service. It used FastAPI."
    assert pairs[1]["citation"] == "Transcript turn 2.5-4.0"
    assert pairs[2]["answer"] == ""
    assert pairs[2]["citation"] == "Transcript turn 5.0-6.0"


def test_a_follow_up_before_the_answer_stays_one_question() -> None:
    pairs = segment_turns(
        [
            {"speaker": "recruiter", "start": 1.0, "end": 2.0, "text": "How have you used FastAPI?"},
            {"speaker": "recruiter", "start": 2.0, "end": 3.0, "text": "What do you use to build those services?"},
            {"speaker": "candidate", "start": 3.5, "end": 5.0, "text": "I build the backend in Python."},
        ]
    )
    assert len(pairs) == 1
    assert pairs[0]["question"] == "How have you used FastAPI? What do you use to build those services?"
    assert pairs[0]["answer"] == "I build the backend in Python."


def test_headline_scores_ignore_blank_answers() -> None:
    pairs = [
        {"answer": "I shipped a FastAPI service.", "relevance": 10},
        {"answer": "   ", "relevance": 0},
    ]
    assert mean_dimension(pairs, "relevance") == 10.0
    assert mean_dimension([{"answer": "", "relevance": 0}], "relevance") == 0.0


def test_discrepancies_and_gaps_use_the_pair_scores() -> None:
    close = {"pair_id": "QA_01", "citation": "Transcript turn 0.0-1.0", "relevance": 8, "technical_accuracy": 6, "completeness": 7, "articulation": 7, "query_ids": ["Q1"]}
    wide = {"pair_id": "QA_02", "citation": "Transcript turn 1.0-2.0", "relevance": 9, "technical_accuracy": 3, "completeness": 8, "articulation": 8, "query_ids": []}
    assert find_discrepancies([close]) == []
    assert "technical accuracy 3.0" in find_discrepancies([wide])[0]
    assert uncovered_gaps(_checklist(), [close]) == ["Docker experience"]
    scored = apply_dimension_scores(
        [{"pair_id": "QA_01"}],
        {"relevance_by_pair": {}},
    )
    assert scored[0]["relevance"] == 0.0
    assert scored[0]["notes"]["relevance"] == "The model did not score this answer."


def test_invented_citations_are_dropped() -> None:
    pairs = [{"pair_id": "QA_01", "answer": "I shipped a FastAPI service.", "citation": "Transcript turn 2.5-4.0"}]
    summary, claims = _justification(
        {"summary": "Noted.", "claims": [{"claim": "Invented.", "citation": "Transcript turn 9.0-9.5"}]},
        pairs,
    )
    assert summary == "Noted."
    assert claims == [{"claim": "QA_01: I shipped a FastAPI service.", "citation": "Transcript turn 2.5-4.0"}]


@pytest.mark.asyncio
async def test_empty_transcript_is_scored_without_a_model() -> None:
    draft = await draft_for_transcript(
        FallbackLLMManager(BoomProvider(), BoomProvider(), BoomProvider()),
        _checklist(),
        [{"speaker": "candidate", "start": 0, "end": 1, "text": "   "}],
    )
    assert draft == draft_for_empty_transcript()
    assert draft.pairs == []


@pytest.mark.asyncio
async def test_workflow_scores_each_answer_and_records_gaps() -> None:
    provider = ScriptedProvider()
    draft = await draft_for_transcript(
        FallbackLLMManager(provider, provider, provider),
        _checklist(),
        _turns(),
    )
    assert provider.calls == 7
    assert draft.relevance == 9.0
    assert draft.technical_accuracy == 3.0
    assert draft.completeness == 8.0
    assert draft.articulation == 8.0
    assert draft.gaps == ["Docker experience"]
    assert len(draft.discrepancies) == 1
    assert "Transcript turn 2.5-4.0" in draft.discrepancies[0]
    assert draft.summary == "The candidate described a FastAPI service."
    assert draft.justifications[0].citation == "Transcript turn 2.5-4.0"
    assert draft.pairs[0].intent == "technical"
    assert draft.pairs[0].query_ids == ["Q1"]
    assert draft.pairs[0].pair_id == "QA_01"
    assert draft.fallback_used is False


class RelevanceOutage:
    async def complete(self, prompt: str, *, system: str | None = None) -> str:
        if prompt.startswith("Score relevance"):
            raise RuntimeError("model down")
        return await ScriptedProvider().complete(prompt, system=system)


@pytest.mark.asyncio
async def test_a_failed_model_call_still_saves_a_draft() -> None:
    draft = await draft_for_transcript(
        FallbackLLMManager(RelevanceOutage(), RelevanceOutage(), RelevanceOutage()),
        _checklist(),
        _turns(),
    )
    assert draft.pairs[0].relevance == 0.0
    assert draft.technical_accuracy == 3.0
    assert draft.fallback_used is True
    assert draft.summary == "The candidate described a FastAPI service."


@pytest.mark.asyncio
async def test_a_missing_dimension_score_counts_as_zero() -> None:
    provider = ScriptedProvider(relevance={"scores": []})
    draft = await draft_for_transcript(
        FallbackLLMManager(provider, provider, provider),
        _checklist(),
        _turns(),
    )
    assert draft.pairs[0].relevance == 0.0
    assert draft.relevance == 0.0
    assert draft.pairs[0].notes["relevance"] == "The model did not score this answer."
