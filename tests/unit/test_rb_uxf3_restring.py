"""UXF3 (U2-25): re-stringing an inverter whose modules are all strung. Without `release_modules` a new length cannot
find modules (today's behaviour, kept); with it, the inverter's released strings give their modules back, matching
strings keep their IDs, and the result is one undo step."""
import pytest

from tests.unit.test_rb_fix_s2_honest_preflight import Project


def _apply(project, inverter, layout, **extra):
    command = {"schema_name": "ElectricalTopologyCommand", "schema_version": "0.1", "command_id": f"uxf3-{len(str(layout))}-{id(extra)}",
               "command_type": "apply_mppt_layout", "parameters": {"inverter_instance_id": inverter, "layout": layout, **extra}}
    return project.client.post(project.url + "/electrical/commands", json={"commands": [command]})


@pytest.fixture
def roof_d(tmp_path):
    """57 modules as 4 strings of 14 on two MPPTs, one module unstrung (the owner's roof D)."""
    project = Project(tmp_path, 57, weather=False, strings=False)
    inverter = project.bundle()["electrical_design"]["inverter_instances"][0]["inverter_instance_id"]
    response = _apply(project, inverter, [[14, 14], [14, 14]])
    assert response.status_code == 200, response.text
    return project, inverter


def _strings(project):
    design = project.bundle()["electrical_design"]
    return {s["string_id"]: (len(s["module_instance_ids"]), s.get("target_mppt_instance_id")) for s in design["strings"]}


def test_without_the_option_a_new_length_still_cannot_find_modules(roof_d):
    project, inverter = roof_d
    before = project.bundle()["electrical_design"]
    response = _apply(project, inverter, [[15, 14], [14, 14]])
    assert response.status_code == 422 and "not enough unstrung modules" in response.text
    assert project.bundle()["electrical_design"] == before


def test_release_modules_restrings_and_keeps_matching_strings(roof_d):
    project, inverter = roof_d
    before = _strings(project)
    kept_mppt2 = {sid for sid, (n, mppt) in before.items() if mppt and mppt.endswith("2")}
    response = _apply(project, inverter, [[15, 14], [14, 14]], release_modules=True)
    assert response.status_code == 200, response.text
    after = _strings(project)
    assert sorted(n for n, mppt in after.values() if mppt) == [14, 14, 14, 15]
    assert sum(n for n, _ in after.values()) == 57  # every module strung, none lost
    assert all(sid in after for sid in kept_mppt2)  # untouched MPPT 2 strings keep their IDs
    assert not [sid for sid, (_, mppt) in after.items() if mppt is None]  # no leftover unassigned strings
    # One undo step returns the previous layout exactly.
    view = project.client.get(project.url).json()
    undone = project.client.post(project.url + "/undo", json={
        "expected_project_revision_id": view["bundle"]["project"]["project_revision"]["project_revision_id"],
        "expected_entry_id": view["history"]["past"][-1]["entry_id"]})
    assert undone.status_code == 200, undone.text
    assert _strings(project) == before


def test_a_restring_that_needs_more_modules_than_exist_is_still_refused(roof_d):
    project, inverter = roof_d
    response = _apply(project, inverter, [[15, 15], [15, 15]], release_modules=True)
    assert response.status_code == 422 and "not enough unstrung modules" in response.text
