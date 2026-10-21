from app.api.v1.notices import router
from app.services.notices import notice_message, ordinal


def test_position_uses_an_ordinal_and_names_the_role() -> None:
    assert ordinal(1) == "1st"
    assert ordinal(2) == "2nd"
    assert ordinal(3) == "3rd"
    assert ordinal(11) == "11th"
    assert ordinal(12) == "12th"
    assert ordinal(13) == "13th"
    assert ordinal(21) == "21st"
    message = notice_message(
        full_name="Ada Lovelace",
        email="ada@example.com",
        job_title="Backend Engineer",
        rank=2,
    )
    assert message == "Ada Lovelace has applied for Backend Engineer and is sitting in 2nd position."


def test_an_unplaced_applicant_is_still_announced() -> None:
    message = notice_message(full_name="", email="ada@example.com", job_title="Backend Engineer", rank=None)
    assert message == "ada@example.com has applied for Backend Engineer and is waiting to be placed."
    assert "score" not in message.casefold()
    assert "rank" not in message.casefold()


def test_notification_routes_are_registered() -> None:
    paths = {getattr(route, "path", "") for route in router.routes}
    assert "/notifications" in paths
    assert "/notifications/{notice_id}/read" in paths
