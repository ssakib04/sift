import json

import pytest

from app.core.llm_fallback import FallbackLLMManager
from app.services.cv_claims import (
    CvClaimDraft,
    VerificationDraft,
    claims_from_attributes,
    follow_up_flags,
    reconcile_claim,
    verify_claims,
)

CV = "Engineer at Northwind from 2015 to 2026. Skills include FastAPI. Reduced latency 40%."


def _skill() -> CvClaimDraft:
    return CvClaimDraft(
        claim_id="S01",
        kind="skill",
        statement="The CV lists FastAPI.",
        subject="FastAPI",
        cv_quote="FastAPI",
    )


def _tenure() -> CvClaimDraft:
    return CvClaimDraft(
        claim_id="T01",
        kind="tenure",
        statement="The CV shows 11 years of professional experience.",
        subject="11 years",
        cv_quote="2015 to 2026",
        amount=11.0,
    )


class BoomProvider:
    async def complete(self, prompt: str, *, system: str | None = None) -> str:
        del prompt, system
        raise AssertionError("a silent interview must not call the model")


class ScriptedProvider:
    def __init__(self, payload: dict[str, object]) -> None:
        self.payload = payload
        self.calls = 0

    async def complete(self, prompt: str, *, system: str | None = None) -> str:
        del prompt, system
        self.calls += 1
        return json.dumps(self.payload)


def test_unquoted_skill_is_dropped() -> None:
    claims = claims_from_attributes(
        {
            "experience_years": 11,
            "skills": ["FastAPI", "Kubernetes"],
            "education": ["BSc Computer Science"],
            "work_history": [
                {
                    "title": "Engineer",
                    "company": "Northwind",
                    "start": "2015-01",
                    "end": "2026-01",
                    "summary": "Reduced latency 40%",
                }
            ],
        },
        CV,
    )
    subjects = [claim.subject for claim in claims]
    assert "FastAPI" in subjects
    assert "Northwind" in subjects
    assert "Kubernetes" not in subjects
    assert "BSc Computer Science" not in subjects
    assert all(claim.cv_quote in CV for claim in claims)


def test_denied_skill_stays_a_contradiction() -> None:
    flag = reconcile_claim(_skill(), "", "", "I have never used FastAPI.")
    assert flag.status == "contradiction"
    assert "FastAPI" in flag.interview_quote
    assert flag.follow_up.endswith("?")
    assert "reject" not in flag.follow_up.casefold()


def test_bare_assertion_is_unverified() -> None:
    flag = reconcile_claim(
        _skill(),
        "",
        "Can you show a FastAPI service you shipped?",
        "I know FastAPI.",
    )
    assert flag.status == "unverified"
    assert flag.follow_up == "Can you show a FastAPI service you shipped?"


def test_skill_missing_from_the_interview_was_not_discussed() -> None:
    flag = reconcile_claim(_skill(), "I have never used FastAPI", "Ask about FastAPI?", "I shipped billing services.")
    assert flag.status == "not_discussed"
    assert flag.interview_quote == ""
    assert flag.follow_up.endswith("?")


def test_invented_denial_is_downgraded_when_the_skill_was_mentioned() -> None:
    flag = reconcile_claim(_skill(), "I have never used FastAPI", "They lied about FastAPI?", "I know FastAPI.")
    assert flag.status == "unverified"
    assert "lied" not in flag.follow_up.casefold()
    assert flag.follow_up.endswith("?")


def test_concrete_example_is_supported_and_not_a_prompt() -> None:
    flag = reconcile_claim(
        _skill(),
        "",
        "",
        "I built a FastAPI service for payments in production.",
    )
    assert flag.status == "supported"
    assert flag.follow_up == ""
    assert follow_up_flags([flag]) == []


def test_year_count_that_disagrees_is_a_contradiction() -> None:
    flag = reconcile_claim(_tenure(), "", "", "I have 3 years of experience.")
    assert flag.status == "contradiction"
    assert flag.follow_up.startswith("Ask how")


def test_matching_year_count_is_supported() -> None:
    flag = reconcile_claim(_tenure(), "", "", "I have 11 years of experience building APIs.")
    assert flag.status == "supported"


def test_denied_year_count_is_a_contradiction() -> None:
    flag = reconcile_claim(_tenure(), "", "", "I do not have 11 years of experience.")
    assert flag.status == "contradiction"


def test_verification_carries_no_suitability_score() -> None:
    assert "overall_score" not in VerificationDraft.__dataclass_fields__
    assert "overall_suitability" not in VerificationDraft.__dataclass_fields__


@pytest.mark.asyncio
async def test_silent_interview_does_not_call_the_model() -> None:
    draft = await verify_claims(FallbackLLMManager(BoomProvider(), BoomProvider(), BoomProvider()), [_skill()], [])
    assert draft.llm_tier == "none"
    assert draft.fallback_used is False
    assert draft.flags[0].status == "not_discussed"


@pytest.mark.asyncio
async def test_model_question_is_kept_when_the_transcript_disagrees_with_its_quote() -> None:
    provider = ScriptedProvider(
        {
            "checks": [
                {
                    "claim_id": "S01",
                    "interview_quote": "I have never used FastAPI",
                    "follow_up": "Could you walk through the FastAPI work on your CV?",
                }
            ]
        }
    )
    draft = await verify_claims(
        FallbackLLMManager(provider, provider, provider),
        [_skill()],
        [(1.0, 2.0, "I know FastAPI.")],
    )
    assert provider.calls == 1
    assert draft.llm_tier == "claude"
    assert draft.flags[0].status == "unverified"
    assert draft.flags[0].follow_up == "Could you walk through the FastAPI work on your CV?"
    assert follow_up_flags(draft.flags) == draft.flags
