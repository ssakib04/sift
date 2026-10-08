from datetime import date

from app.services.cv_facts import (
    computed_experience_years,
    reconcile_evaluation,
    resolve_evidence,
    upgrade_open_evaluations,
)

TODAY = date(2026, 10, 8)


def test_sequential_jobs_add_past_eleven_years() -> None:
    history = [
        {"title": "Engineer", "company": "Northwind", "start": "2013-01", "end": "2016-01", "summary": "APIs"},
        {"title": "Engineer", "company": "Contoso", "start": "2016-01", "end": "2019-06", "summary": "Search"},
        {"title": "Engineer", "company": "Fabrikam", "start": "2019-06", "end": "2023-01", "summary": "pgvector"},
        {"title": "Engineer", "company": "Litware", "start": "2023-01", "end": "2026-01", "summary": "FastAPI"},
    ]
    years = computed_experience_years(history, 3, today=TODAY)
    assert years >= 11


def test_overlapping_jobs_are_not_double_counted() -> None:
    history = [
        {"title": "Engineer", "company": "A", "start": "2018-01-01", "end": "2020-01-01", "summary": ""},
        {"title": "Consultant", "company": "B", "start": "2019-01-01", "end": "2021-01-01", "summary": ""},
    ]
    years = computed_experience_years(history, 0, today=TODAY)
    assert years == 3.0


def test_undated_history_keeps_the_stated_years() -> None:
    history = [{"title": "", "company": "", "start": "", "end": "", "summary": "Sift"}]
    assert computed_experience_years(history, 4, today=TODAY) == 4.0


def test_prose_role_dates_are_parsed() -> None:
    history = [
        {
            "title": "",
            "company": "",
            "start": "",
            "end": "",
            "summary": "Engineer at Northwind, January 2014 - January 2018",
        }
    ]
    years = computed_experience_years(history, 0, today=TODAY)
    assert years >= 4


def test_paraphrased_pgvector_quote_stays_supported() -> None:
    cv = "Built retrieval pipelines with pgvector and FastAPI."
    supported, evidence = resolve_evidence("deep experience with PG Vector", cv)
    assert supported is True
    assert "pgvector" in evidence.casefold()


def test_hallucinated_quote_is_rejected() -> None:
    supported, evidence = resolve_evidence("led robotics at NASA", "Built retrieval pipelines with pgvector.")
    assert supported is False
    assert evidence == ""


def test_years_threshold_uses_the_computed_total() -> None:
    attributes = {
        "experience_years": 11.4,
        "skills": ["pgvector", "FastAPI"],
        "work_history": [
            {"title": "Engineer", "company": "Northwind", "start": "2015-01", "end": "2026-01", "summary": "APIs"},
        ],
    }
    cv = "Engineer at Northwind from 2015 to 2026. Skills include pgvector."
    status, evidence = reconcile_evaluation(
        question="Does the candidate have at least 8 years of professional experience?",
        dimension="experience",
        status="unmet",
        evidence="",
        hints=["experience"],
        attributes=attributes,
        raw_text=cv,
        today=TODAY,
    )
    assert status == "met"
    assert "2015" in evidence


def test_skill_years_ignore_unrelated_jobs() -> None:
    attributes = {
        "experience_years": 11.0,
        "skills": ["pgvector", "Java"],
        "work_history": [
            {"title": "Engineer", "company": "A", "start": "2014-01", "end": "2024-01", "summary": "Java services"},
            {"title": "Engineer", "company": "B", "start": "2024-01", "end": "2025-01", "summary": "pgvector search"},
        ],
    }
    status, _evidence = reconcile_evaluation(
        question="Does the candidate have at least 5 years of experience with pgvector?",
        dimension="experience",
        status="insufficient_evidence",
        evidence="",
        hints=["pgvector"],
        attributes=attributes,
        raw_text="Java services from 2014 and pgvector search in 2024.",
        today=TODAY,
    )
    assert status == "insufficient_evidence"


def test_named_skill_is_met_when_the_cv_contains_it() -> None:
    attributes = {"experience_years": 11.0, "skills": ["pgvector"], "work_history": []}
    status, evidence = reconcile_evaluation(
        question="Does the candidate have experience with pgvector?",
        dimension="technical",
        status="insufficient_evidence",
        evidence="extensive PG Vector production work",
        hints=["pgvector"],
        attributes=attributes,
        raw_text="Highlights include production pgvector retrieval.",
        today=TODAY,
    )
    assert status == "met"
    assert evidence.casefold() == "pgvector"


def test_local_review_raises_fastapi_to_partial_python() -> None:
    checklist = [
        {
            "query_id": "Q1",
            "question": "Does the candidate have Python experience?",
            "dimension": "technical",
        }
    ]
    evaluations = [
        {"query_id": "Q1", "status": "insufficient_evidence", "evidence": "", "confidence": 0.2, "semantic_score": 0.4}
    ]
    upgraded = upgrade_open_evaluations(
        evaluations,
        [{"query_id": "Q1", "status": "partially_met", "evidence": "expertise in FastAPI"}],
        checklist,
        "The candidate has expertise in FastAPI.",
    )
    assert upgraded[0]["status"] == "partially_met"
    assert "FastAPI" in str(upgraded[0]["evidence"])


def test_local_review_cannot_lower_or_accept_a_missing_quote() -> None:
    checklist = [
        {"query_id": "Q1", "question": "Does the candidate have Python experience?", "dimension": "technical"},
        {"query_id": "Q2", "question": "Does the candidate have at least 8 years of professional experience?", "dimension": "experience"},
        {"query_id": "Q3", "question": "Does the candidate have Java experience?", "dimension": "technical"},
    ]
    evaluations = [
        {"query_id": "Q1", "status": "partially_met", "evidence": "FastAPI", "confidence": 0.6, "semantic_score": 0.4},
        {"query_id": "Q2", "status": "insufficient_evidence", "evidence": "", "confidence": 0.2, "semantic_score": 0.2},
        {"query_id": "Q3", "status": "insufficient_evidence", "evidence": "", "confidence": 0.2, "semantic_score": 0.1},
    ]
    upgraded = upgrade_open_evaluations(
        evaluations,
        [
            {"query_id": "Q1", "status": "unmet", "evidence": "expertise in FastAPI"},
            {"query_id": "Q2", "status": "met", "evidence": "expertise in FastAPI"},
            {"query_id": "Q3", "status": "met", "evidence": "led robotics at NASA"},
        ],
        checklist,
        "The candidate has expertise in FastAPI.",
    )
    by_id = {item["query_id"]: item for item in upgraded}
    assert by_id["Q1"]["status"] == "partially_met"
    assert by_id["Q2"]["status"] == "insufficient_evidence"
    assert by_id["Q3"]["status"] == "insufficient_evidence"
