"""S5 acceptance: persisted HTTP batches over the canonical topology editor."""

from copy import deepcopy
import ast
import json

from fastapi.testclient import TestClient
import pytest

from apps.api.server import create_app
from electrical.topology import ElectricalTopologyEditorSession
from tests.unit.test_rb_fix_s2_honest_preflight import Project, MODULE


@pytest.fixture
def project(tmp_path):
    return Project(tmp_path, 20, weather=False, strings=False)


def _command(kind, parameters, command_id="s5-command"):
    return {
        "schema_name": "ElectricalTopologyCommand", "schema_version": "0.1",
        "command_id": command_id, "command_type": kind, "parameters": parameters,
    }


def _ids(project):
    return [m["module_instance_id"] for m in project.bundle()["scene"]["module_instances"]]


def _inverter(project):
    return project.bundle()["electrical_design"]["inverter_instances"][0]["inverter_instance_id"]


def _mppts(project):
    return [m["mppt_instance_id"] for m in sorted(
        project.bundle()["electrical_design"]["mppt_instances"], key=lambda m: m["index"])]


def _post(project, commands, **options):
    return project.client.post(project.url + "/electrical/commands", json={"commands": commands, **options})


def _ok(project, commands, **options):
    response = _post(project, commands, **options)
    assert response.status_code == 200, response.text
    return response.json()


def _reject(project, commands=None, *, body=None, raw=None, contains=(), structured=False, **options):
    before = project.path.read_bytes()
    revision = project.bundle()["project"]["project_revision"]
    if raw is not None:
        response = project.client.post(project.url + "/electrical/commands", content=raw,
                                       headers={"Content-Type": "application/json"})
    else:
        response = project.client.post(project.url + "/electrical/commands", json=body if body is not None
                                       else {"commands": commands, **options})
    assert response.status_code == 422, response.text
    assert isinstance(response.json()["detail"], dict if structured else str)
    for message in contains:
        assert message in (response.json()["detail"]["message"] if structured else response.json()["detail"]), response.text
    assert project.path.read_bytes() == before
    assert project.bundle()["project"]["project_revision"] == revision
    return response.json()["detail"]


def _create(project, *, length=5, ids=None):
    result = _ok(project, [_command("create_strings", {
        "module_instance_ids": ids or _ids(project), "string_length": length,
    })])
    return result["command_results"][0]["result"]


def _session(project):
    b = project.bundle()
    return ElectricalTopologyEditorSession(b["scene"], b["electrical_design"],
        project_revision_id=project.service._project_revision_id(b),
        module_definitions=project.service._component_definitions(b, "modules"),
        inverter_definitions=project.service._component_definitions(b, "inverters"))


def test_01_envelope_index_and_path_and_batch_bounds(project):
    valid = _command("create_string", {"module_instance_ids": _ids(project)[:1]}, "valid-first")
    base = _command("delete_string", {"string_id": "unused"}, "bad-second")
    cases = []
    for key in base:
        bad = deepcopy(base)
        del bad[key]
        cases.append((bad, key))
    for key, value in [("schema_name", "Wrong"), ("schema_version", "99"),
                       ("extra", 1), ("command_type", "not_an_enum"), ("parameters", [])]:
        cases.append(({**base, key: value}, key if key != "extra" else "command"))
    for bad, path in cases:
        _reject(project, [valid, bad], contains=("command 1 (", path,
                "bad-second" if "command_id" in bad else "<missing>"))
    for body in ({}, {"commands": []}, {"commands": [valid] * 201},
                 {"commands": [valid], "extra": 1}):
        _reject(project, body=body)
    # The upper bound is inclusive. Two hundred genuinely unchanged commands
    # return two hundred results without a commit.
    string_id = _create(project, length=20)[0]
    before = project.path.read_bytes()
    response = _ok(project, [_command("unassign_strings", {"string_ids": [string_id]}, str(i)) for i in range(200)])
    assert len(response["command_results"]) == 200
    assert project.path.read_bytes() == before


def test_02_refused_commands_and_read_only_mixing(project):
    for kind, message in [("add_inverter", "POST /api/projects/{id}/inverters"),
                          ("commit_revision", "commits exactly once, implicitly")]:
        _reject(project, [_command(kind, {}, kind)], contains=("command 0", kind, message))
    read = _command("inspect_inverter", {"inverter_instance_id": _inverter(project)}, "read")
    mutate = _command("create_string", {"module_instance_ids": _ids(project)[:1]}, "mutate")
    for commands in ([read, mutate], [mutate, read], [read, read]):
        _reject(project, commands, contains=("read-only command must be the only", "read"))


def test_03_parameter_models_strict_ids_ints_limits_and_nonfinite_json(project):
    mids = _ids(project)
    parameters = {
        "create_string": {"module_instance_ids": mids[:1]},
        "create_strings": {"module_instance_ids": mids[:6], "string_length": 6},
        "assign_strings_to_mppt": {"string_ids": ["S001"], "mppt_instance_id": _mppts(project)[0]},
        "unassign_strings": {"string_ids": ["S001"]}, "delete_string": {"string_id": "S001"},
        "assign_strings": {"string_ids": ["S001"], "inverter_instance_id": _inverter(project)},
        "balance_mppt": {"inverter_instance_id": _inverter(project)},
        "suggest_string_length": {"module_definition_revision_id": MODULE, "inverter_instance_id": _inverter(project)},
        "inspect_inverter": {"inverter_instance_id": _inverter(project)},
    }
    for kind, params in parameters.items():
        for bad in ({}, {**params, "extra": 1}):
            _reject(project, [_command(kind, bad, "bad-params")], contains=("command 0 (bad-params,",))
    for value in (6.0, "6", True, 0):
        _reject(project, [_command("create_strings", {**parameters["create_strings"], "string_length": value})])
    for value in ("!bad", "", "a" * 65, None):
        _reject(project, [_command("create_string", {"module_instance_ids": mids[:1], "string_id": value})])
    _reject(project, [_command("create_string", {"module_instance_ids": mids[:1], "polarity": "invalid"})],
            contains=("command 0", "invalid string polarity"))
    for kind, size in (("create_string", 2001), ("create_strings", 20001)):
        for ids in ([], [mids[0]] * size):
            _reject(project, [_command(kind, {**parameters[kind], "module_instance_ids": ids})])
    for key, value in (("mppt_index", 1.0), ("mppt_index", "1"), ("mppt_index", 0)):
        _reject(project, [_command("suggest_string_length", {**parameters["suggest_string_length"], key: value})])
    for value in ("", 12):
        _reject(project, [_command("inspect_inverter", {"inverter_instance_id": value})])
    for value in (float("nan"), float("inf"), float("-inf")):
        for body in (
            {"commands": [_command("create_strings", {**parameters["create_strings"], "string_length": value})]},
            {"commands": [_command("create_string", {"module_instance_ids": mids[:1], "notes": value})]},
            {"commands": [_command("inspect_inverter", parameters["inspect_inverter"])], "dry_run": value},
            {"commands": [value]},
            {"commands": [_command("inspect_inverter", parameters["inspect_inverter"])], "extra": value},
        ):
            _reject(project, raw=json.dumps(body, allow_nan=True))


def test_04_audit_seven_strings_become_six_assigned_in_one_commit_and_simulate(tmp_path, monkeypatch):
    project = Project(tmp_path, 140, weather=True, strings=False)
    ids = _create(project, length=20, ids=_ids(project)[:140])
    assert ids == [f"S{i:03d}" for i in range(1, 8)]
    before = project.path.read_bytes()
    legacy = project.client.post(project.url + "/assignments", json={
        "string_ids": ids, "inverter_instance_id": _inverter(project)})
    assert legacy.status_code == 422, legacy.text
    assert project.path.read_bytes() == before
    original = project.bundle()
    counts = {"commit": 0, "save": 0}
    commit, save = project.service._commit_electrical, project.service._save
    def counted_commit(*args, **kwargs):
        counts["commit"] += 1
        return commit(*args, **kwargs)
    def counted_save(*args, **kwargs):
        counts["save"] += 1
        return save(*args, **kwargs)
    monkeypatch.setattr(project.service, "_commit_electrical", counted_commit)
    monkeypatch.setattr(project.service, "_save", counted_save)
    response = _ok(project, [
        _command("assign_strings_to_mppt", {"string_ids": ids[:3], "mppt_instance_id": _mppts(project)[0]}, "mppt-1"),
        _command("assign_strings_to_mppt", {"string_ids": ids[3:6], "mppt_instance_id": _mppts(project)[1]}, "mppt-2"),
        _command("delete_string", {"string_id": ids[6]}, "delete-remainder"),
    ])
    final = response["bundle"]
    assert counts == {"commit": 1, "save": 1}
    assert final["electrical_design"]["revision_number"] == original["electrical_design"]["revision_number"] + 1
    assert final["project"]["project_revision"]["revision_number"] == original["project"]["project_revision"]["revision_number"] + 1
    assert final["scene"] == original["scene"]
    assert [m["connected_string_ids"] for m in sorted(final["electrical_design"]["mppt_instances"], key=lambda m: m["index"])] == [ids[:3], ids[3:6]]
    assert response["command_results"][-1]["result"] is None
    ready = project.readiness()
    assert not [f for f in ready["findings"] if f["severity"] == "blocking_error"], ready
    warning = next(f for f in ready["findings"] if f["rule_id"] == "MODULES_NOT_SIMULATED")
    assert warning["context"]["module_count"] == len(_ids(project)) - 120
    assert warning["context"]["by_reason"] == {"unstrung": 20}
    assert ready["ready"], ready
    simulation = project.client.post(project.url + "/simulate", json={})
    assert simulation.status_code == 200, simulation.text
    assert simulation.json()["status"] in {"completed", "completed_with_warnings"}, simulation.text
    assert simulation.json()["summary_result"] is not None


def test_05_capacity_and_first_failure_leave_entire_batch_unsaved(project):
    ids = _create(project)
    _reject(project, [_command("assign_strings_to_mppt", {"string_ids": ids,
        "mppt_instance_id": _mppts(project)[0]}, "too-many")], contains=("command 0 (too-many,", "verified DC inputs"))
    _reject(project, [
        _command("delete_string", {"string_id": ids[0]}, "first-valid"),
        _command("assign_strings_to_mppt", {"string_ids": ["missing"], "mppt_instance_id": _mppts(project)[0]}, "second-invalid"),
        _command("delete_string", {"string_id": ids[1]}, "third-valid"),
    ], contains=("command 1 (second-invalid, assign_strings_to_mppt)", "missing"))
    # Lazy parameter validation must preserve execution order too.
    _reject(project, [_command("delete_string", {"string_id": "missing"}, "engine-first"),
                      _command("delete_string", {"extra": 1}, "params-second")], contains=("command 0 (engine-first,",))
    _reject(project, [_command("delete_string", {"string_id": ids[0]}, "valid"),
                      _command("delete_string", {"extra": 1}, "bad-params")], contains=("command 1 (bad-params,",))


def test_06_unassign_clears_reciprocal_links_and_readiness_reason(project):
    ids = _create(project)
    _ok(project, [_command("assign_strings", {"string_ids": ids, "inverter_instance_id": _inverter(project)})])
    response = _ok(project, [_command("unassign_strings", {"string_ids": [ids[1], ids[0]]})])
    assert response["command_results"][0]["result"] == ids[:2]
    assert {s["string_id"] for s in response["topology_view"]["unassigned_strings"]} == set(ids[:2])
    assert all(s["enabled"] is False for s in response["topology_view"]["unassigned_strings"])
    assert all(not set(ids[:2]) & set(m["connected_string_ids"]) for m in response["bundle"]["electrical_design"]["mppt_instances"])
    warning = next(f for f in project.readiness()["findings"] if f["rule_id"] == "MODULES_NOT_SIMULATED")
    assert warning["context"]["by_reason"] == {"string_unassigned": 10}


def test_07_explicit_path_identity_and_engine_refusals(project):
    mids = _ids(project)
    path = [mids[4], mids[0], mids[3]]
    result = _ok(project, [
        _command("create_string", {"string_id": "my-path", "module_instance_ids": path,
            "name": "Path", "polarity": "reversed", "notes": "Wiring order"}, "path"),
        _command("assign_strings_to_mppt", {"string_ids": ["my-path"], "mppt_instance_id": _mppts(project)[0]}, "assign-path"),
    ])
    stored = result["bundle"]["electrical_design"]["strings"][0]
    assert stored["module_instance_ids"] == path and stored["string_id"] == "my-path"
    assert stored["name"] == "Path" and stored["polarity"] == "reversed" and stored["notes"] == "Wiring order"
    created = result["command_results"][0]["result"]
    assert created["target_mppt_instance_id"] is None and created["enabled"] is False
    assert stored["target_mppt_instance_id"] == _mppts(project)[0] and stored["enabled"] is True
    for parameters in (
        {"module_instance_ids": path[:1]}, {"module_instance_ids": ["unknown-module"]},
        {"string_id": "my-path", "module_instance_ids": [mids[1]]},
    ):
        _reject(project, [_command("create_string", parameters, "invalid-path")], contains=("command 0 (invalid-path,",))
    bundle = project.bundle()
    next(m for m in bundle["scene"]["module_instances"] if m["module_instance_id"] == mids[2])["enabled"] = False
    project.service.store.save(bundle)
    _reject(project, [_command("create_string", {"module_instance_ids": [mids[2]]})], contains=("module is disabled",))


def test_07b_generated_ids_skip_all_electrical_entities_and_earlier_batch_ids(project):
    bundle = project.bundle()
    design = bundle["electrical_design"]
    replacements = {_inverter(project): "S001", _mppts(project)[0]: "S002",
                    design["connections"][0]["connection_id"]: "S003"}
    def replace(value):
        if isinstance(value, dict):
            return {k: replace(v) for k, v in value.items()}
        if isinstance(value, list):
            return [replace(v) for v in value]
        return replacements.get(value, value) if isinstance(value, str) else value
    bundle["electrical_design"] = replace(design)
    project.service.store.save(bundle)
    response = _ok(project, [_command("create_string", {"module_instance_ids": [mid]}, f"create-{i}")
                             for i, mid in enumerate(_ids(project)[:2])])
    assert [r["result"]["string_id"] for r in response["command_results"]] == ["S004", "S005"]
    # Generation always starts with the lowest unused counter.
    _ok(project, [_command("delete_string", {"string_id": "S004"})])
    response = _ok(project, [_command("create_string", {"module_instance_ids": _ids(project)[2:3]})])
    assert response["command_results"][0]["result"]["string_id"] == "S004"


def _without_revision_metadata(design):
    return {k: v for k, v in design.items() if k not in {"created_at", "change_summary"}}


def test_08_automatic_ordering_matches_selection_and_legacy_route(project):
    original = project.bundle()
    mids = list(reversed(_ids(project)))
    _ok(project, [_command("create_strings", {"module_instance_ids": mids, "string_length": 5, "ordering": "selection"})])
    assert [s["module_instance_ids"] for s in project.bundle()["electrical_design"]["strings"]] == [mids[i:i+5] for i in range(0, 20, 5)]
    project.service.store.save(original)
    row = _ok(project, [_command("create_strings", {"module_instance_ids": mids, "string_length": 5})])["bundle"]["electrical_design"]
    project.service.store.save(original)
    legacy = project.client.post(project.url + "/strings", json={"string_length": 5})
    assert legacy.status_code == 200, legacy.text
    assert _without_revision_metadata(row) == _without_revision_metadata(legacy.json()["bundle"]["electrical_design"])
    project.service.store.save(original)
    _reject(project, [_command("create_strings", {"module_instance_ids": mids, "string_length": 5,
        "ordering": "spiral"})], contains=("ordering must be selection, row_major or serpentine",))


def test_09_balance_returns_normalized_engine_map(project):
    _reject(project, [_command("balance_mppt", {"inverter_instance_id": _inverter(project)})], contains=("no assigned strings",))
    ids = _create(project, length=5, ids=_ids(project)[:15])
    _ok(project, [_command("assign_strings_to_mppt", {"string_ids": ids, "mppt_instance_id": _mppts(project)[0]})])
    expected = _session(project).balance_mppt(_inverter(project))
    response = _ok(project, [_command("balance_mppt", {"inverter_instance_id": _inverter(project)})])
    assert response["command_results"][0]["result"] == [{"mppt_index": i, "string_ids": list(s)} for i, s in sorted(expected.items())]
    assert sorted(len(m["connected_string_ids"]) for m in response["bundle"]["electrical_design"]["mppt_instances"]) == [1, 2]


def test_10_assign_command_matches_legacy_assignments(project):
    ids = _create(project)
    original = project.bundle()
    response = _ok(project, [_command("assign_strings", {"string_ids": ids, "inverter_instance_id": _inverter(project)})])
    result = response["command_results"][0]["result"]
    assert [r["mppt_index"] for r in result] == [1, 2]
    assert all(isinstance(r["mppt_index"], int) and isinstance(r["string_ids"], list) for r in result)
    project.service.store.save(original)
    legacy = project.client.post(project.url + "/assignments", json={"string_ids": ids, "inverter_instance_id": _inverter(project)})
    assert legacy.status_code == 200, legacy.text
    assert _without_revision_metadata(response["bundle"]["electrical_design"]) == _without_revision_metadata(legacy.json()["bundle"]["electrical_design"])


def test_11_one_revision_persistence_summary_and_noop(project):
    before = project.bundle()
    cmd = _command("create_string", {"module_instance_ids": _ids(project)[:2]}, "persist-command")
    response = _ok(project, [cmd])
    after = response["bundle"]
    assert after["scene"] == before["scene"]
    assert after["project"]["project_revision"]["revision_number"] == before["project"]["project_revision"]["revision_number"] + 1
    assert after["electrical_design"]["revision_number"] == before["electrical_design"]["revision_number"] + 1
    assert after["electrical_design"]["change_summary"] == "Electrical commands: ['create_string'] (['persist-command'])."
    fresh = TestClient(create_app(store_root=project.service.store.root))
    assert fresh.get(project.url).json()["bundle"] == after
    file_bytes = project.path.read_bytes()
    _ok(project, [_command("unassign_strings", {"string_ids": [response["command_results"][0]["result"]["string_id"]]})])
    assert project.path.read_bytes() == file_bytes
    # Long command IDs remain in results, while revision prose stays bounded.
    response = _ok(project, [_command("create_string", {"module_instance_ids": _ids(project)[2:3]}, "x" * 600)])
    assert len(response["bundle"]["electrical_design"]["change_summary"]) == 500


def test_12_dry_run_reflects_full_draft_and_never_writes(project):
    before = project.path.read_bytes()
    commands = [_command("create_string", {"module_instance_ids": _ids(project)[:2], "string_id": "preview"}),
                _command("assign_strings_to_mppt", {"string_ids": ["preview"], "mppt_instance_id": _mppts(project)[0]})]
    response = _ok(project, commands, dry_run=True)
    assert response["dry_run"] is True and len(response["command_results"]) == 2
    assert response["topology_consistency"]["blocking_count"] == 0
    assert any(s["string_id"] == "preview" for inv in response["topology_view"]["inverters"] for m in inv["mppts"] for s in m["strings"])
    assert project.path.read_bytes() == before
    _reject(project, commands + [_command("delete_string", {"string_id": "missing"}, "failed-preview")],
            dry_run=True, contains=("command 2 (failed-preview,",))


def _broken_string(project):
    _ok(project, [_command("create_string", {"module_instance_ids": _ids(project)[:1], "string_id": "legacy"})])
    bundle = project.bundle()
    bundle["electrical_design"]["strings"][0]["module_instance_ids"] = ["missing-legacy-module"]
    project.service.store.save(bundle)
    return _command("create_string", {"module_instance_ids": _ids(project)[1:2], "string_id": "new-valid-string"})


@pytest.mark.parametrize("case", ["a", "b", "c", "d"])
def test_13_a1_old_errors_repair_preview_and_inspection(project, case):
    create = _broken_string(project)
    before = project.path.read_bytes()
    revision = project.bundle()["electrical_design"]["revision_number"]
    if case == "a":
        detail = _reject(project, [create], structured=True, contains=("Electrical design has structural consistency errors; repair them in this batch",))
        assert len(detail["findings"]) == 1
        finding = detail["findings"][0]
        assert (finding["code"], finding["entity_id"], finding["origin"]) == ("string_unknown_module", "legacy", "pre-existing")
        assert "missing-legacy-module" in finding["message"]
        # A no-op on an old-error bundle is also unaffected by the commit guard.
        _ok(project, [_command("unassign_strings", {"string_ids": ["legacy"]})])
        assert project.path.read_bytes() == before
    elif case == "b":
        result = _ok(project, [create, _command("delete_string", {"string_id": "legacy"})])
        assert result["topology_consistency"]["blocking_count"] == 0
        assert result["bundle"]["electrical_design"]["revision_number"] == revision + 1
        assert [s["string_id"] for s in result["bundle"]["electrical_design"]["strings"]] == ["new-valid-string"]
    elif case == "c":
        result = _ok(project, [create], dry_run=True)
        assert any(f["code"] == "string_unknown_module" and f["entity_id"] == "legacy" for f in result["topology_consistency"]["findings"])
        assert len(result["topology_view"]["unassigned_strings"]) == 2
        assert project.path.read_bytes() == before
    else:
        _ok(project, [_command("inspect_inverter", {"inverter_instance_id": _inverter(project)})])
        assert project.path.read_bytes() == before


def test_13e_a1_marks_introduced_and_preexisting_errors(project, monkeypatch):
    create = _broken_string(project)
    original = ElectricalTopologyEditorSession.create_string
    def corrupt(self, **kwargs):
        result = original(self, **kwargs)
        self._design["strings"][-1]["target_mppt_instance_id"] = "missing-mppt"
        return result
    monkeypatch.setattr(ElectricalTopologyEditorSession, "create_string", corrupt)
    detail = _reject(project, [create], structured=True)
    findings = detail["findings"]
    assert {(f["code"], f["entity_id"]): f["origin"] for f in findings} == {
        ("string_unknown_module", "legacy"): "pre-existing",
        ("string_unknown_mppt", "new-valid-string"): "introduced",
    }


def test_14_read_only_matches_engine_and_never_writes(project):
    before = project.path.read_bytes()
    session = _session(project)
    before_hash = session.canonical_hash()
    cases = [
        ("suggest_string_length", {"module_definition_revision_id": MODULE, "inverter_instance_id": _inverter(project), "mppt_index": None}),
        ("suggest_string_length", {"module_definition_revision_id": MODULE, "inverter_instance_id": _inverter(project), "mppt_index": 1}),
        ("inspect_inverter", {"inverter_instance_id": _inverter(project)}),
    ]
    for kind, parameters in cases:
        expected = getattr(session, kind)(**parameters)
        result = _ok(project, [_command(kind, parameters, "read")], dry_run=True)
        assert result == {"command_id": "read", "command_type": kind, "result": expected}
        assert project.path.read_bytes() == before
        assert session.canonical_hash() == before_hash
    _reject(project, [_command("inspect_inverter", {"inverter_instance_id": "missing"})], contains=("command 0", "missing"))


def test_15_unknown_project_and_entity_ids(project):
    response = project.client.post("/api/projects/missing/electrical/commands", json={"commands": [
        _command("inspect_inverter", {"inverter_instance_id": "missing"})]})
    assert response.status_code == 404, response.text
    _create(project)
    for kind, params in (
        ("delete_string", {"string_id": "missing-string"}),
        ("assign_strings_to_mppt", {"string_ids": ["S001"], "mppt_instance_id": "missing-mppt"}),
        ("assign_strings", {"string_ids": ["S001"], "inverter_instance_id": "missing-inverter"}),
    ):
        _reject(project, [_command(kind, params, "unknown")], contains=(f"command 0 (unknown, {kind})", "missing"))


def test_16_consistent_electrically_invalid_draft_is_accepted_but_preflight_blocks(tmp_path):
    project = Project(tmp_path, 21, weather=True, strings=False)
    _ok(project, [_command("create_string", {"module_instance_ids": _ids(project), "string_id": "too-long"}),
                  _command("assign_strings_to_mppt", {"string_ids": ["too-long"], "mppt_instance_id": _mppts(project)[0]})])
    ready = project.readiness()
    assert not ready["ready"]
    assert any(f["rule_id"] == "STRING_VOC_EXCEEDS_INVERTER_MAX_DC" and f["severity"] == "blocking_error" for f in ready["findings"])
    before = project.path.read_bytes()
    response = project.client.post(project.url + "/simulate", json={})
    assert response.status_code == 422 and project.path.read_bytes() == before
    assert project.client.get(project.url + "/runs").json() == []
