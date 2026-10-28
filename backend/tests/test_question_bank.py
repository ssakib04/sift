from app.api.v1.question_bank import router
from app.services.question_bank import (
    parse_question_bank,
    prefer_bank_question,
    related_bank_questions,
    spoken_with_bank,
)

BANK = [
    "How do you design database indexes for Postgres?",
    "What is your approach to stakeholder management?",
]


def test_a_question_file_keeps_each_question() -> None:
    text = "1. How do you design database indexes? 2. Describe your Docker experience"
    assert parse_question_bank(text) == [
        "How do you design database indexes?",
        "Describe your Docker experience?",
    ]


def test_related_bank_questions_skip_an_unrelated_list() -> None:
    assert related_bank_questions("Tell me about your leadership style", BANK) == []
    assert related_bank_questions("How do you design database indexes?", BANK) == [
        "How do you design database indexes for Postgres?"
    ]


def test_a_related_bank_question_replaces_a_generated_one() -> None:
    chosen = prefer_bank_question(
        "How did you ship the API?",
        "Docker and database indexes",
        BANK,
        "recruiter: Hello",
    )
    assert chosen == "How do you design database indexes for Postgres?"


def test_a_bank_question_already_asked_is_not_repeated() -> None:
    spoken = "recruiter: How do you design database indexes for Postgres?"
    assert prefer_bank_question("How did you ship the API?", "database indexes", BANK, spoken) == "How did you ship the API?"


def test_the_interviewer_asks_a_related_bank_question_as_written() -> None:
    spoken = spoken_with_bank(
        "Thanks. How do you design database indexes?",
        "database indexes",
        BANK,
        "candidate: I build APIs.",
    )
    assert spoken == "Thanks. How do you design database indexes for Postgres?"


def test_question_bank_routes_are_registered() -> None:
    paths = {getattr(route, "path", "") for route in router.routes}
    assert "/question-bank" in paths
