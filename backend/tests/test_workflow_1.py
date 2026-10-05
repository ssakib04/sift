"""Verification for LangGraph Workflow 1 job creation."""

import pytest

from app.graphs.workflow_1_job_creation import workflow_1_graph


@pytest.fixture
def anyio_backend() -> str:
    """Run the workflow on asyncio."""
    return "asyncio"


@pytest.mark.anyio
async def test_workflow_1_senior_ai_systems_engineer() -> None:
    """Invoke Workflow 1 for a senior AI systems role and print the frozen result."""
    result = await workflow_1_graph.ainvoke(
        {
            "role_title": "Senior AI Systems Engineer",
            "raw_prompt": "Senior AI Systems Engineer",
        }
    )
    schema_valid = bool(result["schema_valid"])
    locked_count = len(result["locked_checklist"])
    job_version_id = str(result.get("job_version_id", ""))
    print(f"schema_valid={schema_valid}")
    print(f"locked_queries={locked_count}")
    print(f"job_version_id={job_version_id}")
    assert schema_valid is True
    assert locked_count == 10
    assert job_version_id
