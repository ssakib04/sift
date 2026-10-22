from uuid import uuid4

from app.services.copilot_nav import (
    job_target,
    normalize_place,
    person_target,
    policy_target,
    ranking_target,
    static_target,
)


def test_place_names_map_to_sections() -> None:
    assert normalize_place("Home") == "home"
    assert normalize_place("applicants") == "job_people"
    assert normalize_place("not-a-page") == ""
    assert static_target("practice") == ("/practice#practice", "Practice")
    assert static_target("create") == ("/jobs?view=create#create", "Create a role")


def test_role_and_person_targets_keep_their_section() -> None:
    job_id = uuid4()
    person_id = uuid4()
    policy_id = uuid4()
    assert job_target("job_brief", job_id) == (f"/jobs?job={job_id}&tab=brief#brief", "Brief")
    assert job_target("standing", job_id) == (
        f"/candidates?job={job_id}&view=standing#standing",
        "Standing",
    )
    assert ranking_target(job_id).endswith("#people")
    assert person_target(person_id)[0] == f"/candidates/{person_id}#person"
    assert policy_target(policy_id)[0] == f"/docs?doc={policy_id}#policy"
