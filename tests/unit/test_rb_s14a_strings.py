"""S14a: split, join, reverse, move and swap over the engine topology editor, serpentine stringing, live checks."""

import pytest

from apps.api.live_checks import CODES, topology_checks
from electrical.topology import ElectricalTopologyEditorSession
from tests.unit.test_rb_fix_s2_honest_preflight import MODULE, Project


@pytest.fixture
def project(tmp_path):
    return Project(tmp_path, 20, weather=False, strings=False)


def _command(kind, parameters, command_id="s14a"):
    return {"schema_name": "ElectricalTopologyCommand", "schema_version": "0.1", "command_id": command_id,
            "command_type": kind, "parameters": parameters}


def _post(project, *commands):
    return project.client.post(project.url + "/electrical/commands", json={"commands": list(commands)})


def _ok(project, *commands):
    response = _post(project, *commands)
    assert response.status_code == 200, response.text
    view = response.json()
    assert not [f for f in view["topology_consistency"]["findings"] if f["severity"] == "error"]
    return view


def _refused(project, command, message):
    before = project.path.read_bytes()
    response = _post(project, command)
    assert response.status_code == 422, response.text
    assert message in response.text
    assert project.path.read_bytes() == before


def _ids(project):
    return [m["module_instance_id"] for m in project.bundle()["scene"]["module_instances"]]


def _mppts(project):
    return [m["mppt_instance_id"] for m in sorted(project.bundle()["electrical_design"]["mppt_instances"], key=lambda m: m["index"])]


def _strings(view_or_bundle):
    bundle = view_or_bundle.get("bundle", view_or_bundle)
    return {s["string_id"]: s for s in bundle["electrical_design"]["strings"]}


def _mppt(view, mppt_id):
    return next(m for m in view["bundle"]["electrical_design"]["mppt_instances"] if m["mppt_instance_id"] == mppt_id)


def _two_strings(project, first=10, second=10, mppt=0):
    ids = _ids(project)
    target = _mppts(project)[mppt]
    _ok(project, _command("create_string", {"string_id": "S001", "module_instance_ids": ids[:first]}),
        _command("create_string", {"string_id": "S002", "module_instance_ids": ids[first:first + second]}),
        _command("assign_strings_to_mppt", {"mppt_instance_id": target, "string_ids": ["S001", "S002"]}))
    return ids, target


def _revision(project):
    return project.bundle()["electrical_design"]["electrical_revision_id"]


def test_split_names_the_tail_keeps_the_mppt_and_is_one_undo_step(project):
    ids, mppt = _two_strings(project)
    before = project.bundle()
    view = _ok(project, _command("split_string", {"string_id": "S001", "after_module_instance_id": ids[3]}))
    strings = _strings(view)
    assert view["command_results"][0]["result"] == {"string_id": "S001", "new_string_id": "S003"}
    assert strings["S001"]["module_instance_ids"] == ids[:4]
    assert strings["S003"]["module_instance_ids"] == ids[4:10]
    assert strings["S003"]["target_mppt_instance_id"] == mppt and strings["S003"]["enabled"] == strings["S001"]["enabled"]
    assert strings["S003"]["topology_source"].startswith("split_string:")
    assert set(_mppt(view, mppt)["connected_string_ids"]) == {"S001", "S002", "S003"}
    assert view["history"]["past"][-1]["entry_id"]
    entry = view["history"]["past"][-1]["entry_id"]
    undone = project.client.post(project.url + "/undo", json={
        "expected_project_revision_id": view["bundle"]["project"]["project_revision"]["project_revision_id"], "expected_entry_id": entry})
    assert undone.status_code == 200, undone.text
    assert undone.json()["bundle"]["electrical_design"]["strings"] == before["electrical_design"]["strings"]


def test_split_refusals_change_nothing(project):
    ids, mppt = _two_strings(project)
    _refused(project, _command("split_string", {"string_id": "S001", "after_module_instance_id": ids[9]}), "leaves nothing to split off")
    _refused(project, _command("split_string", {"string_id": "S001", "after_module_instance_id": ids[12]}), "is not in S001")
    _refused(project, _command("split_string", {"string_id": "S001", "after_module_instance_id": ids[3], "new_string_id": "S002"}), "S002")
    # The UAT inverter has 3 verified DC inputs per MPPT: a fourth string on it is refused.
    _ok(project, _command("split_string", {"string_id": "S001", "after_module_instance_id": ids[3]}))
    _refused(project, _command("split_string", {"string_id": "S002", "after_module_instance_id": ids[14]}), "verified DC inputs")


def test_join_appends_and_cleans_the_mppt_links(project):
    ids, mppt = _two_strings(project, 6, 6)
    view = _ok(project, _command("join_strings", {"first_string_id": "S002", "second_string_id": "S001"}))
    strings = _strings(view)
    assert list(strings) == ["S002"] and strings["S002"]["module_instance_ids"] == ids[6:12] + ids[:6]
    assert _mppt(view, mppt)["connected_string_ids"] == ["S002"]
    _refused(project, _command("join_strings", {"first_string_id": "S002", "second_string_id": "S002"}), "two different strings")
    _refused(project, _command("join_strings", {"first_string_id": "S002", "second_string_id": "S404"}), "S404")


def test_reverse_swaps_the_ends_and_keeps_everything_else(project):
    ids, mppt = _two_strings(project)
    before = _strings(project.bundle())["S001"]
    after = _strings(_ok(project, _command("reverse_string", {"string_id": "S001"})))["S001"]
    assert after["module_instance_ids"] == list(reversed(before["module_instance_ids"]))
    assert {k: v for k, v in after.items() if k != "module_instance_ids"} == {k: v for k, v in before.items() if k != "module_instance_ids"}


def test_move_within_across_and_out_of_strings(project):
    ids, mppt = _two_strings(project, 3, 3)
    strings = _strings(_ok(project, _command("move_module", {"module_instance_id": ids[0], "to_string_id": "S001", "index": 2})))
    assert strings["S001"]["module_instance_ids"] == [ids[1], ids[2], ids[0]]
    strings = _strings(_ok(project, _command("move_module", {"module_instance_id": ids[1], "to_string_id": "S002", "index": 0})))
    assert strings["S001"]["module_instance_ids"] == [ids[2], ids[0]]
    assert strings["S002"]["module_instance_ids"] == [ids[1], ids[3], ids[4], ids[5]]
    strings = _strings(_ok(project, _command("move_module", {"module_instance_id": ids[2], "to_string_id": "S002", "index": None})))
    assert strings["S002"]["module_instance_ids"][-1] == ids[2]
    # Taking the last module out deletes the emptied string and its MPPT link.
    view = _ok(project, _command("move_module", {"module_instance_id": ids[0], "to_string_id": None, "index": None}))
    assert "S001" not in _strings(view) and _mppt(view, mppt)["connected_string_ids"] == ["S002"]
    _refused(project, _command("move_module", {"module_instance_id": ids[0], "to_string_id": "S002", "index": 0}), "is not in a string")
    _refused(project, _command("move_module", {"module_instance_id": ids[3], "to_string_id": "S002", "index": -1}), "index")


def test_swap_within_and_across_strings(project):
    ids, mppt = _two_strings(project, 3, 3)
    strings = _strings(_ok(project, _command("swap_modules", {"first_module_instance_id": ids[0], "second_module_instance_id": ids[2]})))
    assert strings["S001"]["module_instance_ids"] == [ids[2], ids[1], ids[0]]
    strings = _strings(_ok(project, _command("swap_modules", {"first_module_instance_id": ids[1], "second_module_instance_id": ids[4]})))
    assert strings["S001"]["module_instance_ids"] == [ids[2], ids[4], ids[0]]
    assert strings["S002"]["module_instance_ids"] == [ids[3], ids[1], ids[5]]
    _refused(project, _command("swap_modules", {"first_module_instance_id": ids[1], "second_module_instance_id": ids[1]}), "two different modules")
    _refused(project, _command("swap_modules", {"first_module_instance_id": ids[1], "second_module_instance_id": ids[10]}), "is not in a string")


def test_several_edits_in_one_batch_are_one_revision(project):
    ids, mppt = _two_strings(project)
    revision = project.bundle()["electrical_design"]["revision_number"]
    view = _ok(project, _command("reverse_string", {"string_id": "S001"}, "a"),
               _command("swap_modules", {"first_module_instance_id": ids[0], "second_module_instance_id": ids[10]}, "b"),
               _command("split_string", {"string_id": "S002", "after_module_instance_id": ids[14]}, "c"))
    assert view["bundle"]["electrical_design"]["revision_number"] == revision + 1
    assert [r["result"].get("new_string_id") for r in view["command_results"]][2] == "S003"


def _rows_project(tmp_path):
    """A field of several rows: serpentine needs more than one."""
    p = Project(tmp_path, 20, weather=False, strings=False)
    roof = p.service.add_surface_rectangle(p.pid, name="Rows roof", origin_x_m=0, origin_y_m=20, width_m=1 + 6 * 1.154 - 0.01,
                                           height_m=3 * 3.2 + 0.4, base_elevation_m=6.1, surface_type="flat_roof", usable_for_pv=True)
    surface = next(s for s in roof["bundle"]["scene"]["surfaces"] if s["name"] == "Rows roof")
    p.service.create_pv_field(p.pid, name="Rows field", support_surface_id=surface["surface_id"], module_definition_revision_id=MODULE,
                              tilt_deg=10, row_pitch_m=3.2, perimeter_setback_m=0.5, obstacle_setback_m=0.3)
    field = next(f for f in p.bundle()["scene"]["pv_fields"] if f["name"] == "Rows field")
    return p, field["pv_field_id"]


def test_serpentine_reverses_every_other_row_of_each_field(tmp_path):
    p, field = _rows_project(tmp_path)
    modules = [m for m in p.bundle()["scene"]["module_instances"] if m["pv_field_id"] == field]
    rows = sorted({m["row_index"] for m in modules})
    assert len(rows) >= 2
    ids = [m["module_instance_id"] for m in modules]
    view = _ok(p, _command("create_strings", {"module_instance_ids": ids, "string_length": len(ids), "ordering": "serpentine"}))
    [string] = view["bundle"]["electrical_design"]["strings"]
    by_id = {m["module_instance_id"]: m for m in modules}
    expected = []
    for i, row in enumerate(rows):
        line = [m["module_instance_id"] for m in sorted((m for m in modules if m["row_index"] == row), key=lambda m: (m["column_index"], m["module_instance_id"]))]
        expected += list(reversed(line)) if i % 2 else line
    assert string["module_instance_ids"] == expected
    assert string["topology_source"].startswith("create_strings:serpentine:")
    # Consecutive modules within a row stay neighbours: the string only turns at a row end.
    turns = sum(1 for a, b in zip(expected, expected[1:]) if by_id[a]["row_index"] != by_id[b]["row_index"])
    assert turns == len(rows) - 1


def test_unknown_ordering_is_refused(project):
    _refused(project, _command("create_strings", {"module_instance_ids": _ids(project), "string_length": 5, "ordering": "spiral"}),
             "ordering must be selection, row_major or serpentine")


def _checks(view):
    return {s["string_id"]: {c["code"]: c for c in s["checks"]} for s in view["topology_checks"]["strings"]}


def test_live_checks_come_from_the_engine_validation(project):
    ids = _ids(project)
    mppt = _mppts(project)[0]
    view = _ok(project, _command("create_string", {"string_id": "S001", "module_instance_ids": ids[:4]}),
               _command("create_string", {"string_id": "S002", "module_instance_ids": ids[4:14]}),
               _command("create_string", {"string_id": "S003", "module_instance_ids": ids[14:20]}),
               _command("assign_strings_to_mppt", {"mppt_instance_id": mppt, "string_ids": ["S001", "S002"]}))
    checks = view["topology_checks"]
    assert checks["basis"].startswith("Engine design validation at -10 °C and 70 °C")
    by = {s["string_id"]: s for s in checks["strings"]}
    vmp = project.bundle()["pinned_components"]["modules"][MODULE]["stc"]["vmp_v"]
    assert by["S001"]["vmp_v"] == pytest.approx(4 * vmp) and by["S001"]["window_v"] == [200.0, 1000.0]
    c = _checks(view)
    assert [x["code"] for x in by["S001"]["checks"]] == list(CODES)
    assert c["S001"]["voltage_window"]["state"] == "fail" and "window 200–1000 V" in c["S001"]["voltage_window"]["message"]
    assert c["S002"]["voltage_window"]["state"] == "pass"
    assert c["S001"]["unequal_lengths"]["state"] == c["S002"]["unequal_lengths"]["state"] == "warn"
    assert c["S001"]["inputs"] == {"code": "inputs", "state": "pass", "message": "2 of 3 DC inputs used."}
    assert {x["state"] for x in c["S003"].values()} == {"unavailable"} and by["S003"]["window_v"] is None
    # The same view comes back from GET.
    assert project.client.get(project.url).json()["topology_checks"] == checks


def test_orientation_mismatch_across_fields_warns_the_mismatched_string(tmp_path):
    p = Project(tmp_path, 20, weather=False, strings=False)
    roof = p.service.add_surface_rectangle(p.pid, name="Steep roof", origin_x_m=0, origin_y_m=20, width_m=1 + 20 * 1.154 - 0.01,
                                           height_m=3.45, base_elevation_m=6.1, surface_type="flat_roof", usable_for_pv=True)
    surface = next(s for s in roof["bundle"]["scene"]["surfaces"] if s["name"] == "Steep roof")
    p.service.create_pv_field(p.pid, name="Steep field", support_surface_id=surface["surface_id"], module_definition_revision_id=MODULE,
                              tilt_deg=25, row_pitch_m=3.2, perimeter_setback_m=0.5, obstacle_setback_m=0.3)
    scene = p.bundle()["scene"]
    flat = [m["module_instance_id"] for m in scene["module_instances"] if m["pv_field_id"] != scene["pv_fields"][-1]["pv_field_id"]]
    steep = [m["module_instance_id"] for m in scene["module_instances"] if m["pv_field_id"] == scene["pv_fields"][-1]["pv_field_id"]]
    view = _ok(p, _command("create_string", {"string_id": "S001", "module_instance_ids": flat[:10]}),
               _command("create_string", {"string_id": "S002", "module_instance_ids": steep[:10]}),
               _command("assign_strings_to_mppt", {"mppt_instance_id": _mppts(p)[0], "string_ids": ["S001", "S002"]}))
    c = _checks(view)
    assert c["S002"]["orientation"]["state"] == "warn" and c["S001"]["orientation"]["state"] == "pass"
    # DEC-52: a string may span fields; a mixed-orientation string is checked the same way.
    view = _ok(p, _command("swap_modules", {"first_module_instance_id": flat[0], "second_module_instance_id": steep[0]}))
    assert _checks(view)["S001"]["orientation"]["state"] == "warn"


def test_validation_failure_shows_every_check_unavailable(project):
    ids, mppt = _two_strings(project)

    def broken(bundle):
        raise ValueError("component revision missing")

    result = topology_checks(project.bundle(), broken)
    assert {c["state"] for s in result["strings"] for c in s["checks"]} == {"unavailable"}
    assert result["strings"][0]["checks"][0]["message"] == "Design validation is unavailable: component revision missing"


def test_engine_session_methods_undo_in_one_step(project):
    ids, mppt = _two_strings(project)
    bundle = project.bundle()
    session = ElectricalTopologyEditorSession(bundle["scene"], bundle["electrical_design"],
                                              project_revision_id=bundle["project"]["project_revision"]["project_revision_id"],
                                              module_definitions=bundle["pinned_components"]["modules"],
                                              inverter_definitions=bundle["pinned_components"]["inverters"])
    before = session.electrical_design
    for call in (lambda: session.split_string("S001", ids[2], "S009"), lambda: session.join_strings("S001", "S002"),
                 lambda: session.reverse_string("S001"), lambda: session.move_module(ids[0], None),
                 lambda: session.swap_modules(ids[1], ids[2])):
        call()
        assert session.undo() and session.electrical_design == before
