"""USE1: the MPPT current limit (standard and detailed curves), inverter lifecycle, suggest stringing, shading-free
pitch, catalog inputs and successors, and the live-check severity."""

from copy import deepcopy
import json
import math

import numpy as np
import pandas as pd
import pvlib
import pytest

from apps.api.catalog import catalog_summaries, load_reference_catalog
from apps.api.live_checks import topology_checks
from components.design_integration import inverter_inputs_per_mppt
from engine.inverter.model import _branch_point, constrain_mppt_current, simulate_voltage_dependent_inverter
from engine.losses.ledger import _LEDGER_CHANNELS, with_current_limit
from engine.simulation.detailed_downstream import CURRENT_LIMIT_BRANCH_FRACTION, _current_limit_branch
from engine.simulation.multi_group import _sum_power_frames
from geometry.pvfield.pitch import shading_free_row_pitch
from tests.unit.test_rb_fix_s10_weather_window import payload
from tests.unit.test_rb_fix_s2_honest_preflight import INVERTER, MODULE, Project

SDM = dict(sdm_photocurrent_a=14.0, sdm_saturation_current_a=2e-10, sdm_series_resistance_ohm=0.25,
           sdm_shunt_resistance_ohm=450.0, sdm_nnsvth_v=2.9)
NS, NP, K, R = 14, 2, 0.95, 0.4


def mppt_frame(limit_case="sdm", k=K, resistance=R):
    """One interval of an MPPT after the loss chain: raw MPP from the single-diode curve, current × k, minus I·R."""
    params = tuple(SDM.values())
    sd = pvlib.pvsystem.singlediode(*params)
    imp_raw, vmp_raw = NP * float(sd["i_mp"]), NS * float(sd["v_mp"])
    imp, vmp = k * imp_raw, vmp_raw - k * imp_raw * resistance
    frame = pd.DataFrame({"mppt_pmp_w": [vmp * imp], "mppt_vmp_v": [vmp], "mppt_imp_a": [imp], "active": [True],
                          "source_mpp_vmp_v": [vmp_raw], "source_mpp_imp_a": [imp_raw]})
    if limit_case == "sdm":
        frame = frame.assign(modules_in_series=NS, string_count=NP, **{name: [value] for name, value in SDM.items()})
    else:
        v = np.linspace(float(sd["v_mp"]), float(sd["v_oc"]), 4000)
        i = np.maximum(pvlib.pvsystem.i_from_v(v, *params), 0.0)
        frame["current_limit_branch"] = [(tuple(NS * v), tuple(NP * i))]
    return frame


# --- the constrained operating point -------------------------------------------------------------------------------

def test_standard_point_is_the_single_diode_voltage_at_the_limit():
    frame = mppt_frame()
    pmp, vmp, imp, binding = constrain_mppt_current(frame, 22.0)
    # Independent: bisection on i_from_v for one module at I_max / (k·N_p).
    sd = pvlib.pvsystem.singlediode(*SDM.values())
    target, lo, hi = 22.0 / (K * NP), float(sd["v_mp"]), float(sd["v_oc"])
    for _ in range(200):
        mid = (lo + hi) / 2
        lo, hi = (mid, hi) if pvlib.pvsystem.i_from_v(mid, *SDM.values()) > target else (lo, mid)
    expected_v = NS * lo - 22.0 * R
    assert binding.tolist() == [True]
    assert imp[0] == 22.0 and vmp[0] == pytest.approx(expected_v, rel=1e-9) and pmp[0] == pytest.approx(expected_v * 22.0, rel=1e-9)
    assert vmp[0] > frame.mppt_vmp_v[0] and pmp[0] < frame.mppt_pmp_w[0]


def test_a_limit_that_does_not_bind_changes_nothing():
    frame = mppt_frame()
    pmp, vmp, imp, binding = constrain_mppt_current(frame, float(frame.mppt_imp_a[0]) * 1.001)
    assert not binding.any()
    assert (pmp[0], vmp[0], imp[0]) == (frame.mppt_pmp_w[0], frame.mppt_vmp_v[0], frame.mppt_imp_a[0])


def test_lower_limits_give_less_power_and_never_a_gain():
    frame = mppt_frame()
    powers = [constrain_mppt_current(frame, limit)[0][0] for limit in (25.0, 22.0, 18.0, 10.0)]
    assert all(a > b for a, b in zip(powers, powers[1:]))


def test_sampled_branch_agrees_with_the_single_diode_solution():
    sdm = constrain_mppt_current(mppt_frame("sdm"), 22.0)[0][0]
    branch = constrain_mppt_current(mppt_frame("branch"), 22.0)[0][0]
    assert branch == pytest.approx(sdm, rel=1e-6)


def test_a_shaded_branch_takes_a_higher_secondary_peak():
    # Boundary at I = 25 A gives 15.6 kW; the second peak at 900 V, 19.9 A gives 17.9 kW and is admissible.
    assert _branch_point([600, 620, 640, 900, 950], [30, 26, 20, 19.9, 0], 1.0, 0.0, 25.0) == (900.0, 19.9)
    assert _branch_point([600, 650, 700, 750], [30, 27, 20, 0], 1.0, 0.0, 25.0)[1] == 25.0


def test_a_binding_mppt_without_an_iv_model_is_refused():
    frame = mppt_frame().drop(columns=list(SDM))
    with pytest.raises(ValueError, match="full IV operating-point"):
        constrain_mppt_current(frame, 22.0)


# --- the inverter stage and the ledgers ------------------------------------------------------------------------------

def inverter(limit):
    definition = deepcopy(load_reference_catalog()["inverters"][INVERTER])
    definition["mppt_template"]["max_operating_current_a"] = limit
    definition["mppt_template"]["max_short_circuit_current_a"] = None
    return definition


def bank(frame):
    from electrical.mppt import MPPTAggregationResult
    index = pd.DatetimeIndex(["2025-01-01T12:00:00+07:00"], name="interval_start")
    frame = frame.copy().set_index(index)
    sd = pvlib.pvsystem.singlediode(*SDM.values())
    frame["mppt_isc_a"] = NP * float(sd["i_sc"])
    frame["mppt_voc_v"] = NS * float(sd["v_oc"])
    return {1: MPPTAggregationResult(1, ("S1", "S2"), frame, {})}


def test_the_inverter_reports_the_limit_as_its_own_reconciled_channel():
    frame = mppt_frame()
    result = simulate_voltage_dependent_inverter(bank(frame), inverter(22.0))
    f = result.frame
    assert f["mppt_current_limit_loss_w"].iloc[0] > 0
    assert f["after_mppt_current_limit_w"].iloc[0] + f["mppt_current_limit_loss_w"].iloc[0] == pytest.approx(f["dc_mpp_available_w"].iloc[0])
    assert f["dc_to_converter_w"].iloc[0] + f["dc_voltage_threshold_loss_w"].iloc[0] + f["dc_power_threshold_loss_w"].iloc[0] == pytest.approx(f["after_mppt_current_limit_w"].iloc[0])
    assert result.metadata["binding_current_limit_policy"] == "sdm_constrained_operating_point.v1"
    assert result.metadata["mppt_current_limit"]["1"]["binding_intervals"] == 1


def test_no_known_limit_keeps_the_column_set():
    assert "mppt_current_limit_loss_w" not in simulate_voltage_dependent_inverter(bank(mppt_frame()), inverter(None)).frame


def test_the_channel_sits_between_dc_wiring_and_the_voltage_window():
    channels = with_current_limit(_LEDGER_CHANNELS, pd.DataFrame(columns=["mppt_current_limit_loss_w"]))
    names = [c[0] for c in channels]
    assert names[names.index("dc_wiring") + 1] == "mppt_current_limit"
    assert channels[names.index("mppt_voltage_threshold")][2] == "after_mppt_current_limit_w"
    assert with_current_limit(_LEDGER_CHANNELS, pd.DataFrame()) == _LEDGER_CHANNELS


def test_multi_inverter_sum_fills_a_zero_limit_channel():
    with_limit = pd.DataFrame({"dc_mpp_available_w": [10.0], "mppt_current_limit_loss_w": [2.0], "after_mppt_current_limit_w": [8.0]})
    without = pd.DataFrame({"dc_mpp_available_w": [5.0]})
    total = _sum_power_frames([without, with_limit])
    assert total.to_dict("list") == {"dc_mpp_available_w": [15.0], "mppt_current_limit_loss_w": [2.0], "after_mppt_current_limit_w": [13.0]}


# --- the detailed path's carried branch --------------------------------------------------------------------------------

def tracker(current, limit=20.0):
    return {"tracker_state": {"constraints": {"max_operating_current_a": limit}},
            "selected_operating_point": {"voltage_v": 600.0, "current_a": current, "power_w": 600.0 * current}}


def test_the_branch_is_carried_only_near_the_limit():
    curve = {"voc_v": 720.0, "points": [{"voltage_v": v, "current_a": i} for v, i in ((500, 25), (600, 18), (650, 10), (700, 2))]}
    assert _current_limit_branch(tracker(CURRENT_LIMIT_BRANCH_FRACTION * 20.0), curve) == {}
    branch = _current_limit_branch(tracker(18.0), curve)["current_limit_branch"]
    assert branch == {"voltage_v": [600.0, 650, 700, 720.0], "current_a": [18.0, 10, 2, 0.0]}
    assert _current_limit_branch(tracker(18.0, None), curve) == {}


# --- a real standard run --------------------------------------------------------------------------------------------

def clear_sky_days():
    """Entirely fictional three local days at the test site: a pvlib Ineichen clear sky, not ERA5."""
    value = payload("2024-12-31T00:00Z", 24 * 5)
    stamps = pd.to_datetime(value["hourly"]["time"], unit="s", utc=True)
    sky = pvlib.location.Location(-6.2, 106.8, altitude=25).get_clearsky(stamps - pd.Timedelta(minutes=30), model="ineichen")
    for column, key in (("ghi", "shortwave_radiation"), ("dni", "direct_normal_irradiance"), ("dhi", "diffuse_radiation")):
        value["hourly"][key] = sky[column].round(3).tolist()
    value["_opensimpv_fixture_note"] = "Entirely fictional USE1 test days: pvlib Ineichen clear sky; not ERA5."
    return json.dumps(value).encode()


@pytest.fixture(scope="module")
def runs(tmp_path_factory):
    p = Project(tmp_path_factory.mktemp("use1"), 20, weather=False, strings=True, string_length=10)
    p.study.acquire_weather(p.pid, source_id="open_meteo_archive_era5", start_date="2025-01-01",
                            end_date="2025-01-03", raw_response=clear_sky_days())
    out = {}
    for label, limit in (("loose", 1000.0), ("tight", 10.0)):
        bundle = p.service.get_bundle(p.pid)
        bundle["pinned_components"]["inverters"][INVERTER]["mppt_template"]["max_operating_current_a"] = limit
        p.service._save(bundle)
        response = p.client.post(p.url + "/simulate", json={})
        assert response.status_code == 200, response.text
        out[label] = response.json()
    return p, out


def test_a_binding_limit_runs_with_a_warning_and_a_reconciled_loss_line(runs):
    _, out = runs
    losses = {l["loss_type"]: l for l in out["tight"]["summary_result"]["loss_summary"]}
    assert losses["mppt_current_limit"]["lost_energy_wh"] > 0 and losses["mppt_current_limit"]["stage"] == "mppt_dc"
    order = [l["loss_type"] for l in out["tight"]["summary_result"]["loss_summary"]]
    assert order.index("mppt_current_limit") == order.index("dc_wiring") + 1
    loose = out["loose"]["summary_result"]["total_energy_wh"]
    assert out["tight"]["summary_result"]["total_energy_wh"] < loose
    assert {l["loss_type"]: l for l in out["loose"]["summary_result"]["loss_summary"]}["mppt_current_limit"]["lost_energy_wh"] == 0


def test_the_operating_current_rule_warns_and_the_isc_rule_still_blocks(runs):
    p, _ = runs
    findings = p.readiness()["findings"]
    exceeded = [f for f in findings if f["rule_id"] == "MPPT_OPERATING_CURRENT_EXCEEDED"]
    assert exceeded and all(f["severity"] == "warning" for f in exceeded)


# --- inverter lifecycle, suggestion, pitch ------------------------------------------------------------------------------

@pytest.fixture()
def project(tmp_path):
    return Project(tmp_path, 20, weather=False, strings=True, string_length=10)


def inverter_id(p):
    return p.bundle()["electrical_design"]["inverter_instances"][0]["inverter_instance_id"]


def test_remove_keeps_the_strings_unassigned_and_undo_restores(project):
    p = project
    assigned = sorted(s["string_id"] for s in p.bundle()["electrical_design"]["strings"] if s.get("target_mppt_instance_id"))
    view = p.client.delete(f"{p.url}/inverters/{inverter_id(p)}").json()
    design = view["bundle"]["electrical_design"]
    assert view["command_results"][0]["unassigned_string_ids"] == assigned
    assert not design["inverter_instances"] and not design["connections"] and not design.get("mppt_instances")
    assert all(not s.get("target_mppt_instance_id") for s in design["strings"])
    fence = {"expected_project_revision_id": view["bundle"]["workspace_state"]["active_project_revision_id"],
             "expected_entry_id": view["history"]["past"][-1]["entry_id"]}
    assert p.client.post(f"{p.url}/undo", json=fence).status_code == 200
    restored = p.bundle()["electrical_design"]
    assert sorted(s["string_id"] for s in restored["strings"] if s.get("target_mppt_instance_id")) == assigned


def test_change_model_keeps_strings_on_existing_mppt_indices(project):
    p = project
    before = {s["string_id"]: s["target_mppt_instance_id"] for s in p.bundle()["electrical_design"]["strings"]}
    response = p.client.put(f"{p.url}/inverters/{inverter_id(p)}", json={"inverter_definition_revision_id": "inv-rawibumi-ref-150k-r1"})
    assert response.status_code == 200, response.text
    result = response.json()["command_results"][0]
    design = response.json()["bundle"]["electrical_design"]
    assert design["inverter_instances"][0]["inverter_definition_revision_id"] == "inv-rawibumi-ref-150k-r1"
    assert "inv-rawibumi-ref-150k-r1" in p.bundle()["pinned_components"]["inverters"]
    assert result["unassigned_string_ids"] == [] and {s["string_id"]: s["target_mppt_instance_id"] for s in design["strings"]} == before
    assert all(m["mppt_definition_id"].startswith("inv-rawibumi-ref-150k-r1:") for m in design["mppt_instances"])


def test_suggest_stringing_returns_a_layout_the_validation_accepts(project):
    p = project
    response = p.client.post(f"{p.url}/inverters/{inverter_id(p)}/suggest-layout", json={})
    assert response.status_code == 200, response.text
    s = response.json()
    assert s["status"] == "suggestion_available" and s["modules_used"] + s["modules_left"] == 20
    assert all(len(m) <= 3 for m in s["layout"]) and s["inputs_per_mppt"] == 3 and s["inputs_per_mppt_source"] == "definition"
    assert len({n for m in s["layout"] for n in m if n}) == 1
    # Applying it commits without a structural error, and nothing it suggested is INVALID.
    applied = p.client.post(f"{p.url}/electrical/commands", json={"commands": [{"schema_name": "ElectricalTopologyCommand", "schema_version": "0.1",
        "command_id": "use1-apply", "command_type": "apply_mppt_layout", "parameters": {"inverter_instance_id": inverter_id(p), "layout": s["layout"]}}]})
    assert applied.status_code == 200, applied.text
    assert not [f for f in p.direct_validation()["findings"] if f["classification"] == "INVALID"]


def test_suggest_reuses_strings_when_it_can_and_restrings_only_for_more_modules(tmp_path):
    # Strings of 10 already fill the 20 modules: the suggestion reuses them.
    reuse = Project(tmp_path / "reuse", 20, weather=False, strings=True, string_length=10)
    s = reuse.client.post(f"{reuse.url}/inverters/{inverter_id(reuse)}/suggest-layout", json={}).json()
    assert s["status"] == "suggestion_available" and s["replace_string_ids"] == [] and s["modules_used"] == 20
    # Strings of 9 (9 + 9 + 2) would leave modules over: the suggestion restrings, naming what it replaces, in one commit.
    # (USE3b, approved 2026-11-12: strings of 7 are now kept as 7,7 ; 6, which strings all 20 with per-MPPT lengths.)
    short = Project(tmp_path / "restring", 20, weather=False, strings=True, string_length=9)
    s = short.client.post(f"{short.url}/inverters/{inverter_id(short)}/suggest-layout", json={}).json()
    existing = sorted(x["string_id"] for x in short.bundle()["electrical_design"]["strings"])
    assert s["modules_used"] == 20 and s["replace_string_ids"] == existing
    commands = [{"schema_name": "ElectricalTopologyCommand", "schema_version": "0.1", "command_id": f"del-{sid}",
                 "command_type": "delete_string", "parameters": {"string_id": sid}} for sid in s["replace_string_ids"]]
    commands.append({"schema_name": "ElectricalTopologyCommand", "schema_version": "0.1", "command_id": "apply",
                     "command_type": "apply_mppt_layout", "parameters": {"inverter_instance_id": inverter_id(short), "layout": s["layout"]}})
    applied = short.client.post(f"{short.url}/electrical/commands", json={"commands": commands})
    assert applied.status_code == 200, applied.text
    strung = [x for x in applied.json()["bundle"]["electrical_design"]["strings"] if x.get("target_mppt_instance_id")]
    assert sum(len(x["module_instance_ids"]) for x in strung) == 20


def test_suggest_stringing_says_why_when_nothing_fits(project):
    p = project
    bundle = p.service.get_bundle(p.pid)
    bundle["pinned_components"]["inverters"][INVERTER]["mppt_template"]["max_operating_voltage_v"] = 30.0
    p.service._save(bundle)
    s = p.client.post(f"{p.url}/inverters/{inverter_id(p)}/suggest-layout", json={}).json()
    assert s["status"] == "no_solution" and s["reasons"][0]["code"] == "NO_STRING_LENGTH"


def test_shading_free_pitch_route_matches_the_geometry(project):
    p = project
    body = {"module_definition_revision_id": MODULE, "orientation": "portrait", "tilt_deg": 10, "design_sun_elevation_deg": 30}
    r = p.client.post(f"{p.url}/pv-fields/shading-free-pitch", json=body).json()
    module = load_reference_catalog()["modules"][MODULE]
    depth = module["mechanical"]["height_m"]
    expected = depth * math.cos(math.radians(10)) + depth * math.sin(math.radians(10)) / math.tan(math.radians(30))
    assert r["row_pitch_m"] == pytest.approx(expected, rel=1e-12)
    side = p.client.post(f"{p.url}/pv-fields/shading-free-pitch", json={**body, "sun_azimuth_offset_deg": 90}).json()
    assert side["row_pitch_m"] == pytest.approx(depth * math.cos(math.radians(10)), rel=1e-12)
    assert p.client.post(f"{p.url}/pv-fields/shading-free-pitch", json={**body, "design_sun_elevation_deg": 0}).status_code == 422


def test_pitch_refuses_a_sun_on_the_horizon():
    with pytest.raises(ValueError, match="design_sun_elevation_deg"):
        shading_free_row_pitch(load_reference_catalog()["modules"][MODULE], orientation="portrait", tilt_deg=10, design_sun_elevation_deg=90)


# --- catalog and live checks ------------------------------------------------------------------------------------------

def test_inputs_per_mppt_are_stated_or_derived_only_when_even():
    assert inverter_inputs_per_mppt({"mppt_template": {"count": 2, "input_count_per_mppt": 3}}) == (3, "definition")
    assert inverter_inputs_per_mppt({"mppt_template": {"count": 2, "total_input_count": 4}}) == (2, "derived: 4 inputs on 2 MPPTs")
    assert inverter_inputs_per_mppt({"mppt_template": {"count": 2, "total_input_count": 5}}) == (None, None)


def test_a_completed_revision_supersedes_the_hidden_original():
    catalog = load_reference_catalog()
    original = deepcopy(catalog["inverters"][INVERTER]); completed = deepcopy(original)
    original["revision_id"], completed["revision_id"] = "lib-inv-x-r1", "lib-inv-x-r2"
    catalog["inverters"] = {"lib-inv-x-r1": original, "lib-inv-x-r2": completed}
    entries = {"lib-inv-x-r1": {"library": {"hidden": True}}, "lib-inv-x-r2": {"library": {"hidden": False, "completed_from": "lib-inv-x-r1"}}}
    summaries = {i["revision_id"]: i for i in catalog_summaries(catalog, library_entries=entries, pinned_revision_ids={"lib-inv-x-r1"})["inverters"]}
    assert summaries["lib-inv-x-r1"]["superseded_by"] == "lib-inv-x-r2"
    assert "superseded_by" not in summaries["lib-inv-x-r2"]


def test_live_checks_warn_on_operating_current_and_fail_on_isc(project):
    p = project
    bundle = p.bundle()
    target = next(s for s in bundle["electrical_design"]["strings"] if s.get("target_mppt_instance_id"))
    mppt = target["target_mppt_instance_id"]

    def report(*rules):
        return {"findings": [{"rule_id": r, "entity_id": mppt, "classification": "WARNING", "message": r} for r in rules]}

    def state(*rules):
        checks = topology_checks(bundle, validate=lambda _: report(*rules))
        return next(c for s in checks["strings"] if s["string_id"] == target["string_id"] for c in s["checks"] if c["code"] == "current")["state"]

    assert state("MPPT_OPERATING_CURRENT_EXCEEDED") == "warn"
    assert state("MPPT_OPERATING_CURRENT_EXCEEDED", "MPPT_SHORT_CIRCUIT_CURRENT_EXCEEDED") == "fail"


def test_electrical_dry_run_returns_the_live_checks(project):
    p = project
    response = p.client.post(f"{p.url}/electrical/commands", json={"dry_run": True, "commands": [{"schema_name": "ElectricalTopologyCommand",
        "schema_version": "0.1", "command_id": "use1-dry", "command_type": "apply_mppt_layout",
        "parameters": {"inverter_instance_id": inverter_id(p), "layout": [[10], [10]]}}]})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["dry_run"] is True and {"basis", "strings"} <= set(body["topology_checks"])
    assert len(body["topology_checks"]["strings"]) == 2
