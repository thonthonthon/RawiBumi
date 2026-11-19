"""USE3b: the packer's row phase, per-MPPT suggestion lengths, and the projects-page system summary."""

from copy import deepcopy

import pytest

from apps.api.project_store import project_system_summary
from apps.api.stringing_suggestion import _layouts
from geometry.pvfield import packing
from tests.unit.test_rb_fix_s2_honest_preflight import Project


@pytest.fixture()
def project(tmp_path):
    return Project(tmp_path, 20, weather=False, strings=True, string_length=10)


def field_case(p, vertices, azimuth=0.0, tilt=10.0):
    bundle = p.bundle()
    scene = deepcopy(bundle["scene"])
    scene["surfaces"][0]["boundary_2d"]["vertices"] = vertices
    field = dict(scene["pv_fields"][0], azimuth_deg=azimuth, tilt_deg=tilt, row_pitch_m=2.935)
    module = bundle["pinned_components"]["modules"][field["module_definition_revision_id"]]
    return scene, field, module


def pack(scene, field, module, steps):
    original, packing.ROW_PHASE_STEPS = packing.ROW_PHASE_STEPS, steps
    try:
        return packing.pack_field(scene, field, module)
    finally:
        packing.ROW_PHASE_STEPS = original


def test_a_roof_edge_slightly_off_the_rows_no_longer_loses_a_row(project):
    # The roof's low edge rises 0.2 m across 24 m (about 0.5°), so the anchored first row crosses the setback.
    scene, field, module = field_case(project, [[0, 0], [24, -0.2], [24, 11.45], [0, 11.65]])
    anchored = pack(scene, field, module, 1)
    searched = pack(scene, field, module, 16)
    assert len(searched.pv_field["row_layouts"]) == len(anchored.pv_field["row_layouts"]) + 1
    assert len(searched.module_instances) > len(anchored.module_instances)


def test_an_aligned_roof_keeps_its_exact_placement(project):
    scene, field, module = field_case(project, [[0, 0], [24, 0], [24, 11.6], [0, 11.6]])
    anchored = pack(scene, field, module, 1)
    searched = pack(scene, field, module, 16)
    assert [m["transform"] for m in searched.module_instances] == [m["transform"] for m in anchored.module_instances]
    assert [m["module_instance_id"] for m in searched.module_instances] == [m["module_instance_id"] for m in anchored.module_instances]


def test_per_mppt_lengths_string_every_module():
    best = _layouts(list(range(4, 18)), [2.0, 2.0], 38)[0][1]
    assert best == [[13, 13], [12]]
    # One length everywhere wins whenever it strings as many modules.
    assert _layouts(list(range(4, 18)), [2.0, 2.0], 48)[0][1] == [[16, 16], [16]]


def test_a_project_summary_is_its_own_request_and_the_list_stays_unchanged(project):
    p = project
    row = next(r for r in p.client.get("/api/projects").json() if r["project_id"] == p.pid)
    assert "system" not in row  # the list costs what it did before USE3b
    system = p.client.get(f"{p.url}/summary").json()
    assert [(m["count"], m["rating_w"]) for m in system["modules"]] == [(20, 550.0)]  # D14: the datasheet nameplate
    assert system["dc_kwp"] == pytest.approx(11.0)
    assert [(i["count"], i["rating_w"]) for i in system["inverters"]] == [(1, 150000.0)]
    assert system["ac_kw"] == 150.0 and system["last_run"] is None
    assert p.client.get("/api/projects/project-missing/summary").status_code == 404


def test_the_summary_reports_the_last_successful_run_only():
    bundle = {"scene": {"module_instances": []}, "electrical_design": {"inverter_instances": []}, "pinned_components": {},
              "simulation_runs": [
                  {"simulation_run_id": "ok", "status": "completed", "summary_result": {"total_energy_wh": 2.0e6, "annual_energy_wh": 2.0e6,
                                                                                      "specific_yield_wh_per_wp": 1500.0, "performance_ratio": 0.8}},
                  {"simulation_run_id": "bad", "status": "failed", "summary_result": None}]}
    run = project_system_summary(bundle)["last_run"]
    assert (run["simulation_run_id"], run["energy_kwh"], run["annual"], run["performance_ratio"]) == ("ok", 2000.0, True, 0.8)
