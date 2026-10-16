import json

import pytest

from app.core.llm_fallback import FallbackLLMManager
from app.graphs.master_assessment_graph import (
    CV_WEIGHT,
    INTERVIEW_WEIGHT,
    MCQ_WEIGHT,
    build_master_assessment_graph,
    checklist_points,
    classify_suitability,
    evidence_gaps_for,
    interview_points,
    narrative_cites,
    normalize_mcq,
    weighted_overall,
)


class BoomProvider:
    async def complete(self, prompt: str, *, system: str | None = None) -> str:
        del prompt, system
        raise AssertionError("an assessment with no citations must not call the model")


class ScriptedProvider:
    def __init__(self, *, narrative: dict[str, object] | None = None) -> None:
        self.calls = 0
        self.narrative = narrative or {"narrative": "FastAPI work is cited at Q1."}

    async def complete(self, prompt: str, *, system: str | None = None) -> str:
        del system
        self.calls += 1
        if prompt.startswith("Name strengths and weaknesses"):
            return json.dumps(
                {
                    "strengths": [
                        {
                            "claim": "Candidate has strong FastAPI experience.",
                            "source_type": "cv",
                            "source_reference": "Q1",
                            "evidence": "rewritten excerpt",
                        }
                    ],
                    "weaknesses": [
                        {
                            "claim": "The candidate never mentioned Docker.",
                            "source_type": "transcript",
                            "source_reference": "Transcript turn 9.0-9.5",
                        }
                    ],
                }
            )
        if prompt.startswith("Write the assessment narrative"):
            return json.dumps(self.narrative)
        raise AssertionError(prompt[:80])


def _loaded() -> dict[str, object]:
    return {
        "candidate_id": "cand-1",
        "cv_screening": {
            "aggregate_score": 0.85,
            "technical_score": 0.88,
            "experience_score": 0.8,
            "qualification_score": 0.78,
            "evaluations": [
                {
                    "query_id": "Q1",
                    "question": "FastAPI experience",
                    "status": "met",
                    "evidence": "Built REST APIs using FastAPI and PostgreSQL.",
                },
                {
                    "query_id": "Q2",
                    "question": "Docker deployments",
                    "status": "unmet",
                    "evidence": "The CV does not mention Docker.",
                },
            ],
        },
        "mcq_score": 80,
        "qa_analysis": {
            "relevance": 8.5,
            "technical_accuracy": 8.0,
            "completeness": 8.0,
            "articulation": 8.5,
            "gaps": ["Tool Calling (MCP)"],
            "pairs": [
                {
                    "pair_id": "QA_01",
                    "citation": "Transcript turn 18.0-19.0",
                    "answer": "We re-embed document updates asynchronously.",
                    "relevance": 8.5,
                    "technical_accuracy": 8.0,
                    "completeness": 8.0,
                    "articulation": 8.5,
                }
            ],
        },
        "tier_notes": [],
        "fallback_flags": [],
    }


def test_weights_are_thirty_twenty_and_fifty() -> None:
    assert CV_WEIGHT + MCQ_WEIGHT + INTERVIEW_WEIGHT == 1
    assert checklist_points(0.85) == 85.0
    assert checklist_points(1) == 100.0
    assert checklist_points(85) == 85.0
    assert interview_points(8.5, 8.0, 8.0, 8.5) == 82.5
    assert weighted_overall(85.0, 80.0, 82.5) == 82.8
    assert classify_suitability(75.0) == "strong_fit"
    assert classify_suitability(74.9) == "moderate_fit"
    assert classify_suitability(50.0) == "moderate_fit"
    assert classify_suitability(49.9) == "unsuited"
    assert classify_suitability(None) == "insufficient_evidence"
    assert normalize_mcq(150) is None
    assert normalize_mcq(0) == 0


def test_q1_is_not_treated_as_q10() -> None:
    assert narrative_cites("See Q10 for the note.", ["Q1"]) is False
    assert narrative_cites("See Q1 for the note.", ["Q1"]) is True


def test_missing_inputs_are_gaps_and_block_the_overall_score() -> None:
    gaps = evidence_gaps_for(None, None, None)
    assert gaps == [
        "CV screening snapshot is not available.",
        "Submitted MCQ score is not available.",
        "Interview Q&A analysis is not available.",
    ]


@pytest.mark.asyncio
async def test_missing_inputs_do_not_call_the_model() -> None:
    provider = BoomProvider()
    result = await build_master_assessment_graph(FallbackLLMManager(provider, provider, provider))(
        {"candidate_id": "cand-1", "cv_screening": None, "mcq_score": None, "qa_analysis": None, "tier_notes": [], "fallback_flags": []}
    )
    assert result["overall_score"] is None
    assert result["overall_suitability"] == "insufficient_evidence"
    assert result["llm_tier"] == "none"
    assert result["fallback_used"] is False
    assert "No CV excerpt or interview transcript turn was available to cite." in result["narrative"]
    assert "30 percent" in result["narrative"]


@pytest.mark.asyncio
async def test_workflow_weights_the_three_scores_and_drops_invented_citations() -> None:
    provider = ScriptedProvider()
    result = await build_master_assessment_graph(FallbackLLMManager(provider, provider, provider))(_loaded())
    assert provider.calls == 2
    assert result["component_scores"]["cv_screening"] == 85.0
    assert result["component_scores"]["mcq_quiz"] == 80.0
    assert result["component_scores"]["interview_qa"] == 82.5
    assert result["component_scores"]["technical_dimension"] == 88.0
    assert result["overall_score"] == 82.8
    assert result["overall_suitability"] == "strong_fit"
    assert result["strengths"] == ["Candidate has strong FastAPI experience."]
    assert result["weaknesses"] == []
    assert result["traceability"] == [
        {
            "claim": "Candidate has strong FastAPI experience.",
            "source_type": "cv",
            "source_reference": "Q1",
            "evidence": "Built REST APIs using FastAPI and PostgreSQL.",
        }
    ]
    assert "Transcript turn 9.0-9.5" not in json.dumps(result["traceability"])
    assert "CV evidence gap for Q2: Docker deployments." in result["evidence_gaps"]
    assert "Tool Calling (MCP)" in result["evidence_gaps"]
    assert "Q1" in result["narrative"]
    assert result["fallback_used"] is False


@pytest.mark.asyncio
async def test_a_narrative_without_a_catalog_citation_is_replaced() -> None:
    provider = ScriptedProvider(narrative={"narrative": "The candidate is excellent."})
    result = await build_master_assessment_graph(FallbackLLMManager(provider, provider, provider))(_loaded())
    assert "Cited source Q1:" in result["narrative"]
    assert "Built REST APIs using FastAPI and PostgreSQL." in result["narrative"]


@pytest.mark.asyncio
async def test_a_missing_quiz_prevents_a_suitability_label() -> None:
    provider = ScriptedProvider()
    state = _loaded()
    state["mcq_score"] = None
    result = await build_master_assessment_graph(FallbackLLMManager(provider, provider, provider))(state)
    assert result["overall_score"] is None
    assert result["overall_suitability"] == "insufficient_evidence"
    assert result["component_scores"]["cv_screening"] == 85.0
    assert result["component_scores"]["mcq_quiz"] is None
    assert "Submitted MCQ score is not available." in result["evidence_gaps"]
