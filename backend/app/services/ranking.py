import uuid
from dataclasses import dataclass
from datetime import datetime

STATUS_SCORE = {
    "met": 1.0,
    "partially_met": 0.5,
    "unmet": 0.0,
    "insufficient_evidence": 0.0,
}


@dataclass(frozen=True)
class ScoreTotals:
    aggregate_score: float
    must_have_ratio: float
    technical_score: float
    experience_score: float
    qualification_score: float


@dataclass(frozen=True)
class RankInput:
    candidate_id: uuid.UUID
    aggregate_score: float
    must_have_ratio: float
    technical_score: float
    experience_score: float
    qualification_score: float
    created_at: datetime


def score_checklist(queries: list[dict[str, object]], evaluations: dict[str, str]) -> ScoreTotals:
    """Weight each locked query by its checklist status."""
    weighted = 0.0
    dimension_weight = {"technical": 0.0, "experience": 0.0, "qualification": 0.0}
    dimension_score = {"technical": 0.0, "experience": 0.0, "qualification": 0.0}
    must_weight = 0.0
    must_score = 0.0
    for query in queries:
        query_id = str(query["query_id"])
        weight = float(query["weight"])
        status = evaluations.get(query_id, "insufficient_evidence")
        points = STATUS_SCORE.get(status, 0.0) * weight
        weighted += points
        dimension = str(query["dimension"])
        if dimension in dimension_weight:
            dimension_weight[dimension] += weight
            dimension_score[dimension] += points
        if query["requirement_type"] == "must_have":
            must_weight += weight
            must_score += points
    return ScoreTotals(
        aggregate_score=round(weighted, 6),
        must_have_ratio=round((must_score / must_weight) if must_weight else 0.0, 6),
        technical_score=round(_ratio(dimension_score["technical"], dimension_weight["technical"]), 6),
        experience_score=round(_ratio(dimension_score["experience"], dimension_weight["experience"]), 6),
        qualification_score=round(_ratio(dimension_score["qualification"], dimension_weight["qualification"]), 6),
    )


def rank_candidates(rows: list[RankInput]) -> dict[uuid.UUID, int]:
    """Order candidates with the locked tie-break hierarchy. Rank 1 is the strongest."""
    ordered = sorted(
        rows,
        key=lambda row: (
            -row.aggregate_score,
            -row.must_have_ratio,
            -row.technical_score,
            -row.experience_score,
            -row.qualification_score,
            row.created_at,
            str(row.candidate_id),
        ),
    )
    return {row.candidate_id: index for index, row in enumerate(ordered, start=1)}


def invite_ids(ranks: dict[uuid.UUID, int], already_invited: set[uuid.UUID], limit: int = 3) -> list[uuid.UUID]:
    chosen = [candidate_id for candidate_id, rank in ranks.items() if rank <= limit and candidate_id not in already_invited]
    return sorted(chosen, key=lambda candidate_id: ranks[candidate_id])


def _ratio(score: float, weight: float) -> float:
    if weight <= 0:
        return 0.0
    return score / weight
