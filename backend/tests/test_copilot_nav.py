from uuid import uuid4

from app.services.copilot_nav import (
    compare_target,
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
    assert static_target("interviews") == ("/interviews#interviews", "Interviews")
    assert normalize_place("progress") == "interviews"
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
    assert job_target("compare", job_id) == (
        f"/candidates?job={job_id}&view=compare#compare",
        "Compare",
    )
    assert normalize_place("comparison") == "compare"
    left_id = uuid4()
    right_id = uuid4()
    assert compare_target(job_id, left_id, right_id) == (
        f"/candidates?job={job_id}&view=compare&left={left_id}&right={right_id}#compare"
    )
    assert ranking_target(job_id).endswith("#people")
    assert person_target(person_id)[0] == f"/candidates/{person_id}#person"
    assert policy_target(policy_id)[0] == f"/docs?doc={policy_id}#policy"
