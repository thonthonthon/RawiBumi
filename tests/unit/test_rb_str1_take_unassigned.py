"""RB-STR1: reclaim only unassigned modules, atomically and through the API."""
import json

import pytest

from apps.api.history import ELECTRICAL_ENVELOPE
from electrical.topology.editor import ElectricalTopologyEditorSession
from tests.unit.test_rb_fix_s2_honest_preflight import Project


def command(modules, **parameters):
    return {"schema_name": "ElectricalTopologyCommand", "schema_version": "0.1",
            "command_id": "str1", "command_type": "create_string",
            "parameters": {"string_id": "manual", "module_instance_ids": modules, **parameters}}


@pytest.fixture
def project(tmp_path):
    return Project(tmp_path, 12, weather=False, string_length=4)


def remove(project):
    inv = project.bundle()["electrical_design"]["inverter_instances"][0]["inverter_instance_id"]
    response = project.client.delete(project.url + "/inverters/" + inv)
    assert response.status_code == 200, response.text
    return project.bundle()["electrical_design"]


def test_reclaim_api_dry_run_and_one_undo(project):
    before = remove(project)
    original_bytes = json.dumps(before, sort_keys=True)
    first, second = before["strings"][:2]
    modules = first["module_instance_ids"] + second["module_instance_ids"][1:3]
    request = {"commands": [command(modules)]}
    response = project.client.post(project.url + "/electrical/commands", json=request)
    assert response.status_code == 422 and "modules already belong to strings" in response.text
    request["commands"][0]["parameters"]["take_from_unassigned"] = True
    preview = project.client.post(project.url + "/electrical/commands", json={**request, "dry_run": True})
    assert preview.status_code == 200, preview.text
    expected = {first["string_id"]: first["module_instance_ids"], second["string_id"]: second["module_instance_ids"][1:3]}
    assert preview.json()["command_results"][0]["result"]["taken_from"] == expected
    assert json.dumps(project.bundle()["electrical_design"], sort_keys=True) == original_bytes
    response = project.client.post(project.url + "/electrical/commands", json=request)
    assert response.status_code == 200, response.text
    view = response.json()
    result = view["command_results"][0]["result"]
    assert result["taken_from"] == expected
    assert result["deleted_string_ids"] == [first["string_id"]]
    after = {s["string_id"]: s for s in view["bundle"]["electrical_design"]["strings"]}
    assert first["string_id"] not in after
    assert after[second["string_id"]]["module_instance_ids"] == second["module_instance_ids"][::3]
    assert after["manual"]["module_instance_ids"] == modules
    fence = {"expected_project_revision_id": view["bundle"]["workspace_state"]["active_project_revision_id"],
             "expected_entry_id": view["history"]["past"][-1]["entry_id"]}
    assert project.client.post(project.url + "/undo", json=fence).status_code == 200
    # Browser undo issues a new revision envelope; the complete topology is restored byte-for-byte.
    topology_bytes = lambda design: json.dumps({k: v for k, v in design.items() if k not in ELECTRICAL_ENVELOPE}, sort_keys=True)
    assert topology_bytes(project.bundle()["electrical_design"]) == topology_bytes(before)


def test_engine_undo_restores_exact_design(project):
    before = remove(project)
    session = ElectricalTopologyEditorSession(project.bundle()["scene"], before)
    original = session.canonical_json()
    session.create_string(string_id="manual", module_instance_ids=before["strings"][0]["module_instance_ids"], take_from_unassigned=True)
    assert session.undo_depth == 1 and session.undo()
    assert session.canonical_json() == original
    assert json.dumps(session.electrical_design) == json.dumps(before)


@pytest.mark.parametrize("flag", [False, True])
def test_assigned_modules_refused_in_plain_words(project, flag):
    before = project.bundle()["electrical_design"]
    string = before["strings"][0]
    response = project.client.post(project.url + "/electrical/commands", json={"commands": [command(string["module_instance_ids"], take_from_unassigned=flag)]})
    assert response.status_code == 422
    assert f"These modules are already in {string['string_id']} on MPPT" in response.json()["detail"]
    assert f"Remove them from {string['string_id']} first, or use Move module." in response.json()["detail"]
    assert not any(mid in response.text for mid in string["module_instance_ids"])
    assert project.bundle()["electrical_design"] == before


@pytest.mark.parametrize("flag", [1, "true", None])
def test_flag_is_strict_bool(project, flag):
    modules = project.bundle()["electrical_design"]["strings"][0]["module_instance_ids"]
    response = project.client.post(project.url + "/electrical/commands", json={"commands": [command(modules, take_from_unassigned=flag)]})
    assert response.status_code == 422


def test_mixed_assigned_and_unassigned_selection_is_atomic(project):
    bundle = project.bundle()
    session = ElectricalTopologyEditorSession(bundle["scene"], bundle["electrical_design"])
    first, second = session.electrical_design["strings"][:2]
    session.unassign_strings([first["string_id"]])
    before, depth = session.canonical_json(), session.undo_depth
    with pytest.raises(ValueError, match="These modules are already in"):
        session.create_string(string_id="manual", module_instance_ids=first["module_instance_ids"] + second["module_instance_ids"], take_from_unassigned=True)
    assert session.canonical_json() == before and session.undo_depth == depth
