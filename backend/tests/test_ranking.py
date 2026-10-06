import uuid
from datetime import UTC, datetime, timedelta

from app.services.ranking import RankInput, invite_ids, rank_candidates, score_checklist
from tests.checklist_factory import sample_queries


def test_met_queries_score_higher_than_unmet() -> None:
    queries = sample_queries()
    met = {query["query_id"]: "met" for query in queries}
    unmet = {query["query_id"]: "unmet" for query in queries}
    assert score_checklist(queries, met).aggregate_score == 1
    assert score_checklist(queries, unmet).aggregate_score == 0


def test_tie_break_prefers_earlier_candidate_when_scores_match() -> None:
    earlier = uuid.UUID("00000000-0000-0000-0000-000000000010")
    later = uuid.UUID("00000000-0000-0000-0000-000000000001")
    now = datetime.now(UTC)
    ranks = rank_candidates(
        [
            RankInput(later, 0.8, 0.5, 0.5, 0.5, 0.5, now),
            RankInput(earlier, 0.8, 0.5, 0.5, 0.5, 0.5, now - timedelta(minutes=5)),
        ]
    )
    assert ranks[earlier] == 1
    assert ranks[later] == 2


def test_higher_aggregate_outranks_an_earlier_application() -> None:
    weak = uuid.uuid4()
    strong = uuid.uuid4()
    now = datetime.now(UTC)
    ranks = rank_candidates(
        [
            RankInput(weak, 0.4, 1, 1, 1, 1, now - timedelta(days=1)),
            RankInput(strong, 0.9, 0.2, 0.2, 0.2, 0.2, now),
        ]
    )
    assert ranks[strong] == 1


def test_invites_go_to_the_top_three_once() -> None:
    ids = [uuid.uuid4() for _ in range(4)]
    ranks = {candidate_id: index for index, candidate_id in enumerate(ids, start=1)}
    assert invite_ids(ranks, set()) == ids[:3]
    assert invite_ids(ranks, {ids[0]}) == ids[1:3]
