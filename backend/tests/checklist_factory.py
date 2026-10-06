def sample_queries() -> list[dict[str, object]]:
    dimensions = ["technical"] * 6 + ["experience", "experience", "qualification", "qualification"]
    requirement_types = ["must_have", "preferred"] * 5
    return [
        {
            "query_id": f"Q{index}",
            "question": f"Does the candidate satisfy production criterion {index}?",
            "dimension": dimensions[index - 1],
            "requirement_type": requirement_types[index - 1],
            "weight": 0.1,
            "evidence_hints": ["project"],
            "scoring_rubric": "Met when the CV shows the skill in production work.",
        }
        for index in range(1, 11)
    ]
