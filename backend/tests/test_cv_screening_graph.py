import json
from io import BytesIO

import pytest
from docx import Document

from app.core.llm_fallback import FallbackLLMManager
from app.graphs.cv_screening_graph import build_cv_screening_graph
from app.services.embeddings import HashingEmbedder
from tests.checklist_factory import sample_queries

CV_TEXT = (
    "Ada Lovelace built production FastAPI services and shipped a policy-compliant hiring platform "
    "with Docker. She is a female engineer."
)


class ScriptedProvider:
    async def complete(self, prompt: str, *, system: str | None = None) -> str:
        del system
        if "Extract candidate attributes" in prompt:
            return json.dumps(
                {
                    "full_name": "Ada Lovelace",
                    "email": "ada@example.com",
                    "skills": ["FastAPI"],
                    "work_history": ["Sift"],
                    "education": ["Mathematics"],
                    "experience_years": 4,
                }
            )
        evidence = "shipped a policy-compliant hiring platform"
        return json.dumps(
            {
                "evaluations": [
                    {"query_id": f"Q{index}", "status": "met", "confidence": 0.9, "evidence": evidence}
                    for index in range(1, 11)
                ]
            }
        )


def _docx() -> bytes:
    buffer = BytesIO()
    document = Document()
    document.add_paragraph(CV_TEXT)
    document.save(buffer)
    return buffer.getvalue()


@pytest.mark.asyncio
async def test_workflow_scores_a_cv_against_the_locked_checklist() -> None:
    provider = ScriptedProvider()
    run = build_cv_screening_graph(FallbackLLMManager(provider, provider, provider), HashingEmbedder())
    result = await run(
        {
            "filename": "ada.docx",
            "file_bytes": _docx(),
            "job_description": "A" * 120,
            "locked_checklist": sample_queries(),
        }
    )
    assert result["parse_method"] == "native"
    assert result["aggregate_score"] == 1
    assert result["extracted_attributes"]["full_name"] == "Ada Lovelace"
    assert "female" in result["fairness_flags"]
    assert len(result["query_evaluations"]) == 10
    assert result["justifications"]
