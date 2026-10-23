from pathlib import Path

from app.services.screening import invite_block_reason


def test_invitation_route_is_registered() -> None:
    source = Path(__file__).resolve().parents[1].joinpath("app/api/v1/jobs.py").read_text(encoding="utf-8")
    assert '@router.post("/{job_id}/invitations"' in source


def test_an_applicant_is_invited_only_when_scored_and_reachable() -> None:
    assert invite_block_reason(email="ada@example.com", already_invited=False, scored=True) is None
    assert invite_block_reason(email="ada@example.com", already_invited=True, scored=True) == "already_invited"
    assert invite_block_reason(email="ada@example.com", already_invited=False, scored=False) == "not_scored"
    assert invite_block_reason(email="", already_invited=False, scored=True) == "no_email"
