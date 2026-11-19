"""RB-FIX-A regressions for solved points, complete searches and verified reporting."""

from copy import deepcopy
from hashlib import sha256
from itertools import product
import json
import random
from time import perf_counter
from types import SimpleNamespace

import pandas as pd
import pvlib
import pytest

from apps.api.catalog import load_reference_catalog
from apps.api.stringing_suggestion import _layouts, suggest_mppt_layout
from apps.api.study import _validation_configuration
from engine.inverter.model import constrain_mppt_current, simulate_voltage_dependent_inverter
from engine.losses.chain import simulate_electrical_loss_chain
from engine.simulation.artifacts import canonical_json_bytes
from engine.simulation.detailed_downstream import (
    CompactDetailedMPPTResult, _current_limit_branch, execute_detailed_downstream,
)
from engine.simulation.unshaded import UnshadedFixedTiltConfiguration
from geometry.pvfield import packing
from reporting.exports.csv_export import ExportSource
from reporting.exports.series import monthly
from tests.unit.test_phase43_pvfield_packing import MODULE as PACK_MODULE, _roof_scene
from tests.unit.test_rb_fix_s2_honest_preflight import INVERTER, MODULE, Project
from tests.unit.test_rb_unc1_annual_pxx import annual, project_ledger  # noqa: F401 (fixture)
from tests.unit.test_rb_use1_usable import NS, NP, SDM, bank, inverter, mppt_frame, tracker
from validation.engineering.electrical import module_design_state

from apps.api.stringing_suggestion import _distribute
from engine.simulation.canonical import _assert_output_schema
from tests.unit.test_phase7_csv_export import REQUEST, persisted, reseal  # noqa: F401 (fixture)


def test_a1_codex_case_rejected_by_voltage_window():
    frame = mppt_frame(resistance=3.0)
    limit = float(frame.mppt_imp_a[0]) * 0.99
    power, voltage, current, binding = constrain_mppt_current(frame, limit)
    solved = NS * pvlib.pvsystem.v_from_i(limit / (0.95 * NP), *SDM.values()) - limit * 3.0
    assert binding[0] and voltage[0] == pytest.approx(solved, abs=1e-9)
    assert voltage[0] > 777.0
    assert current[0] == limit and power[0] == pytest.approx(solved * limit)
    definition = inverter(limit)
    definition["mppt_template"]["max_operating_voltage_v"] = 777.0
    result = simulate_voltage_dependent_inverter(bank(frame), definition)
    assert result.frame.dc_voltage_window_accepted_w.iloc[0] == 0
    assert result.frame.dc_voltage_threshold_loss_w.iloc[0] == pytest.approx(power[0])
    assert result.metadata["mppt_current_limit"]["1"] == {"binding_intervals": 1}


def test_a1_near_mpp_gives_signed_gain_and_ledger_closes():
    raw = mppt_frame(k=1.0, resistance=0.0)
    limit = float(raw.mppt_imp_a[0]) * 0.95 * 0.9999
    result = simulate_electrical_loss_chain(bank(raw), inverter(limit), interval_seconds=3600,
                                          module_quality_loss_fraction=0.05, dc_array_resistance_ohm=0.4)
    frame = result.ledger.frame
    gain = float(frame.mppt_current_limit_loss_w.iloc[0])
    assert -float(frame.array_virtual_mpp_w.iloc[0]) * 0.001 < gain < 0
    post = result.array_losses.mppt_bank[1].frame
    _, voltage, current, _ = constrain_mppt_current(post, limit)
    assert frame.after_mppt_current_limit_w.iloc[0] == pytest.approx(voltage[0] * current[0])
    assert result.ledger.metadata["max_interval_reconciliation_residual_w"] < 1e-6
    assert result.ledger.metadata["annual_reconciliation_residual_kwh"] == pytest.approx(0, abs=1e-9)


@pytest.mark.parametrize("inputs", [(1, 2), (2, 1)])
def test_a2_unequal_explicit_input_counts_use_all_38_modules(tmp_path, inputs):
    p = Project(tmp_path, 38, weather=False, strings=False)
    bundle = p.bundle()
    definition = bundle["pinned_components"]["inverters"][INVERTER]
    state = module_design_state(bundle["pinned_components"]["modules"][MODULE],
                                _validation_configuration(bundle["electrical_design"]))
    low = 11.9 * state.vmp_max_temp_v * (1 - state.voltage_uncertainty_fraction)
    high = 13.1 * state.vmp_min_temp_v * (1 + state.voltage_uncertainty_fraction)
    definition.pop("mppt_template", None)
    definition["mppts"] = [
        {"mppt_index": index, "min_operating_voltage_v": low, "max_operating_voltage_v": high,
         "nominal_voltage_v": (low + high) / 2, "max_operating_current_a": 100.0,
         "max_short_circuit_current_a": 100.0, "input_count": count}
        for index, count in enumerate(inputs, 1)
    ]
    instance = bundle["electrical_design"]["inverter_instances"][0]["inverter_instance_id"]
    session = p.service._electrical_session(bundle)
    session.change_inverter_definition(instance, INVERTER)
    bundle["electrical_design"] = session.electrical_design
    result = suggest_mppt_layout(p.service, bundle, instance)
    assert result["status"] == "suggestion_available", result
    assert result["modules_used"] == 38 and result["modules_left"] == 0
    assert result["inputs_per_mppt"] == inputs[0]
    assert [len(mppt) for mppt in result["layout"]] == list(inputs)
    assert result["layout"] == ([[12], [13, 13]] if inputs == (1, 2) else [[13, 13], [12]])


def test_a3_negative_30pct_quality_gain_no_refusal():
    # Synthetic selected curve/evidence; the real compact adapter, quality, inverter and PCC ledger execute below.
    curve = {"voc_v": 700.0, "points": [{"voltage_v": v, "current_a": i}
                                          for v, i in ((600, 16), (650, 10), (700, 0))]}
    selected = {"mppt_instance_id": "mppt-1", "mppt_index": 1, "string_ids": ["S1"],
                "voltage_v": 600.0, "current_a": 16.0, "power_w": 9600.0, "isc_a": 20.0,
                "voc_v": 700.0, "active": True, "tracker_model_id": "rawibumi.mppt.ideal_global_mpp.v0.1",
                "availability": "selected_unconstrained_state", "combined_curve_sha256": "0" * 64,
                "constraint_flags": {"operating_current_limit_known": True, "operating_current_above_limit": False},
                **_current_limit_branch(tracker(16.0), curve)}
    compact = CompactDetailedMPPTResult.freeze({
        "schema_name": "CompactDetailedMPPTResult", "schema_version": "0.1",
        "scientific_input_sha256": "0" * 64, "diagnostic_result_sha256": "1" * 64,
        "temperature_metadata": {"module-1": {}}, "intervals": [{
            "interval_start": "2025-01-01T12:00:00+07:00", "interval_end": "2025-01-01T13:00:00+07:00",
            "evaluation_time": "2025-01-01T12:30:00+07:00", "duration_seconds": 3600,
            "mppts": [selected], "modules": [{"module_instance_id": "module-1", "incident_poa_w_m2": 1000.,
                "unshaded_poa_w_m2": 1000., "effective_irradiance_w_m2": 1000., "cell_temperature_c": 25.}]}],
    })
    module = load_reference_catalog()["modules"][MODULE]
    config = UnshadedFixedTiltConfiguration(simulation_timestep_seconds=3600, surface_tilt_deg=10.,
        surface_azimuth_deg=0., poa_model_id="unused", module_definition=module, inverter_definition=inverter(20.),
        modules_in_series=1, string_ids=("S1",), mppt_assignments={1: ("S1",)}, u_c_w_m2k=29.,
        u_v_w_m2k_per_ms=0., module_quality_loss_fraction=-0.30)
    evidence = {"module": module, "evidence": {"evidence_id": "synthetic-independent-quality",
        "module_quality_declaration": {"relationship": "separate_from_parameterization", "module_quality_loss_fraction": -0.30}}}
    result = execute_detailed_downstream(compact, module_configs={"module-1": config},
                                        module_inputs={"module-1": SimpleNamespace(replay=lambda: evidence)})
    assert result.timeseries.module_quality_loss_w.iloc[0] == pytest.approx(-2880.)
    assert result.timeseries.mppt_current_limit_loss_w.iloc[0] > 0
    assert result.timeseries.pcc_power_w.iloc[0] > 0
    assert result.electrical.ledger.metadata["annual_reconciliation_residual_kwh"] == pytest.approx(0, abs=1e-9)


def test_a4_binding_case_lists_mppt_current_limit_in_stage_order():
    result = simulate_electrical_loss_chain(bank(mppt_frame(k=1., resistance=0.)), inverter(22.),
                                          interval_seconds=3600, dc_array_resistance_ohm=0.4)
    order = result.metadata["stage_order"]
    assert result.ledger.frame.mppt_current_limit_loss_w.iloc[0] > 0
    assert order == result.ledger.metadata["channel_order"]
    assert order[order.index("dc_wiring") + 1:order.index("dc_wiring") + 3] == ["mppt_current_limit", "mppt_voltage_threshold"]


def packing_case(vertices):
    scene = _roof_scene()
    next(s for s in scene["surfaces"] if s["surface_id"] == "roof")["boundary_2d"]["vertices"] = vertices
    field = {"pv_field_id": "field-1", "support_surface_id": "roof", "module_definition_revision_id": PACK_MODULE["revision_id"],
             "orientation": "portrait", "azimuth_deg": 0., "tilt_deg": 10., "row_pitch_m": 2.,
             "module_gap_x_m": 0., "module_gap_y_m": 0., "mounting_height_m": 0.2}
    return scene, field


def exact_phase_counts(scene, field):
    """Enumerate every phase with the canonical exact placement guard, independently of the estimator."""
    support = packing._surface(scene, field["support_surface_id"])
    vertices = packing._surface_vertices(support)
    exclusions, obstacles = packing._resolved_exclusions(scene, field, support)
    footprint = packing.ModuleFootprint.from_definition(PACK_MODULE, field["orientation"], field["tilt_deg"])
    azimuth = field["azimuth_deg"]
    min_x, min_y, max_x, max_y = packing.field_bounds(vertices, azimuth)
    setbacks = field.get("setback_configuration") or {}
    perimeter, obstacle = setbacks.get("perimeter_setback_m", 0.), setbacks.get("obstacle_setback_m", 0.)
    xs = packing._x_positions(min_x, max_x, width_m=footprint.plan_projection_width_m,
        module_gap_m=field["module_gap_x_m"], perimeter_setback_m=perimeter, row_alignment="start", table_configuration=None)
    first = min_y + perimeter + footprint.plan_projection_height_m / 2
    last = max_y - perimeter - footprint.plan_projection_height_m / 2
    parameters = field.get("packing_parameters") or {}
    estimator = packing._phase_estimator(vertices, support["boundary_2d"].get("holes", []), exclusions, obstacles,
        perimeter, obstacle, xs, azimuth, footprint, parameters.get("requested_row_count"), parameters.get("requested_modules_per_row"))
    counts = []
    for step in range(packing.ROW_PHASE_STEPS):
        y = first + field["row_pitch_m"] * step / packing.ROW_PHASE_STEPS
        rows = []
        while y <= last + 1e-12:
            rows.append(y)
            y += field["row_pitch_m"]
        occupied = []
        for y in rows:
            accepted = sum(packing._candidate_valid(
                packing.rectangle_polygon(packing.field_to_scene((x, y), azimuth), footprint.plan_projection_width_m,
                                          footprint.plan_projection_height_m, azimuth), vertices, exclusions, obstacles,
                support_holes=support["boundary_2d"].get("holes", []), perimeter_setback_m=perimeter,
                obstacle_setback_m=obstacle) for x in xs)
            if accepted:
                occupied.append(min(accepted, parameters.get("requested_modules_per_row", accepted)))
        count = sum(occupied[:parameters.get("requested_row_count")])
        assert estimator(rows) >= count, (step, estimator(rows), count)
        counts.append(count)
    return counts


def test_a5_narrow_roof_3_modules():
    scene, field = packing_case([[0, 0], [1, -.2], [1, 6.1], [0, 6.3]])
    assert exact_phase_counts(scene, field)[2] == 3
    assert len(packing.pack_field(scene, field, PACK_MODULE).module_instances) == 3


def test_a5_concave_support_estimate_bounds_the_exact_probe_rule():
    scene, field = packing_case([[0, 0], [4, 0], [4, 6], [0, 6], [0, 2.6], [.3, 2.5], [0, 2.4]])
    exact = exact_phase_counts(scene, field)
    assert len(packing.pack_field(scene, field, PACK_MODULE).module_instances) == max(exact)


def test_a5_aligned_roof_placement_unchanged(monkeypatch):
    scene, field = packing_case([[0, 0], [10, 0], [10, 8], [0, 8]])
    with monkeypatch.context() as patch:
        patch.setattr(packing, "ROW_PHASE_STEPS", 1)
        anchored = packing.pack_field(scene, field, PACK_MODULE)
    searched = packing.pack_field(scene, field, PACK_MODULE)
    assert searched.module_instances == anchored.module_instances
    assert searched.pv_field["row_layouts"] == anchored.pv_field["row_layouts"]


def test_a5_small_random_roofs_match_exhaustive():
    rng = random.Random(20261113)
    for index in range(24):
        width, height, skew = rng.uniform(1, 7), rng.uniform(3, 9), rng.uniform(-.4, .4)
        scene, field = packing_case([[0, 0], [width, skew], [width, height + skew], [0, height]])
        if index % 6 == 0:
            field["azimuth_deg"] = 17.
        if index % 3 == 0:
            field["setback_configuration"] = {"perimeter_setback_m": .1, "obstacle_setback_m": .15}
        if index % 4 == 0:
            support = packing._surface(scene, "roof")
            support["boundary_2d"]["holes"] = [[[.3, 2.1], [.6, 2.1], [.6, 2.4], [.3, 2.4]]]
        if index % 5 == 0:
            scene.setdefault("obstacles", []).append({"obstacle_id": "packing-obstacle",
                "footprint": {"vertices": [[.1, .2], [.4, .2], [.4, .5], [.1, .5]]}})
        if index % 2 == 0:
            field["packing_parameters"] = {"requested_row_count": 2, "requested_modules_per_row": 3}
        exact = exact_phase_counts(scene, field)
        assert len(packing.pack_field(scene, field, PACK_MODULE).module_instances) == max(exact)


def test_a5_timing_10000_module_aligned_roof(monkeypatch, record_property):
    scene, field = packing_case([[0, 0], [100, 0], [100, 200], [0, 200]])
    with monkeypatch.context() as patch:
        patch.setattr(packing, "_phase_estimator", lambda *args: None)
        start = perf_counter()
        anchored = packing.pack_field(scene, field, PACK_MODULE)
        baseline = perf_counter() - start
    start = perf_counter()
    searched = packing.pack_field(scene, field, PACK_MODULE)
    elapsed = perf_counter() - start
    assert len(searched.module_instances) == 10000
    assert searched.module_instances == anchored.module_instances
    for key, value in {"anchored_seconds": baseline, "searched_seconds": elapsed, "ratio": elapsed / baseline}.items():
        record_property(key, value)
    print({"modules": 10000, "anchored_seconds": baseline, "searched_seconds": elapsed, "ratio": elapsed / baseline})


@pytest.mark.parametrize("lengths,caps,modules,expected", [
    ([12, 13], [1, 2], 38, 38), ([4, 5], [1, 2], 14, 14), ([4, 5], [2, 1], 13, 13),
    ([4, 5], [1, float("inf")], 14, 14),
])
def test_a6_layout_cases_from_review(lengths, caps, modules, expected):
    assert -_layouts(lengths, caps, modules)[0][0][0] == expected


def test_a6_brute_force_comparison_small_random():
    rng = random.Random(20261113)
    for _ in range(50):
        lengths = sorted(rng.sample(range(2, 8), rng.randint(1, 4)))
        caps = [rng.randint(0, 3) for _ in range(rng.randint(1, 4))]
        modules = rng.randint(1, 35)
        best = 0
        choices = [[(0, 0)] + [(n, c) for n in lengths for c in range(1, cap + 1)] for cap in caps]
        for layout in product(*choices):
            used = sum(n * c for n, c in layout)
            if used <= modules and len({n for n, c in layout if c}) <= 2:
                best = max(best, used)
        actual = _layouts(lengths, caps, modules)
        assert (-actual[0][0][0] if actual else 0) == best, (lengths, caps, modules)
        for _, layout in actual:
            assert all(len([n for n in row if n]) <= cap for row, cap in zip(layout, caps))
            assert all(len(set(row)) == 1 for row in layout)
            assert len({n for row in layout for n in row if n}) <= 2


@pytest.fixture(scope="module")
def day_run(tmp_path_factory):
    p = Project(tmp_path_factory.mktemp("rev-a-day"), 20, weather=True, strings=True)
    response = p.client.post(p.url + "/simulate", json={})
    assert response.status_code == 200, response.text
    return p, response.json()


def test_a8_tampered_bundle_24h_run_unavailable(day_run):
    p, run = day_run
    original = p.bundle()
    bundle = deepcopy(original)
    bundle["uncertainty_assumptions"] = project_ledger()
    summary = bundle["simulation_runs"][0]["summary_result"]
    summary["annual_energy_wh"] = 1e9
    summary["period_duration_hours"] = 8760
    p.service.store.save(bundle)
    try:
        view = p.study.annual_pxx(p.pid, run["simulation_run_id"])
        assert view["status"] == "unavailable" and view["result"] is None
        assert [r["code"] for r in view["reasons"]] == ["RUN_NOT_ANNUAL"]
        verified = p.study._verified_summary(p.pid, run["simulation_run_id"])
        assert view["basis"]["mean_source_sha256"] == sha256(canonical_json_bytes(verified)).hexdigest()
        assert verified["period_duration_hours"] == 24 and verified["annual_energy_wh"] is None
    finally:
        p.service.store.save(original)


@pytest.mark.parametrize("missing", ["omitted", "directory", "manifest"])
def test_a8_package_omitted_gives_package_omitted(day_run, missing):
    p, run = day_run
    original = p.bundle()
    bundle = deepcopy(original)
    bundle["uncertainty_assumptions"] = project_ledger()
    directory = p.study.run_root / p.pid / run["simulation_run_id"]
    target = directory if missing == "directory" else directory / "run-package-manifest.json"
    moved = target.with_name(target.name + ".held")
    if missing == "omitted":
        bundle["simulation_runs"][0]["package_omitted"] = True
    else:
        target.rename(moved)
    p.service.store.save(bundle)
    try:
        view = p.study.annual_pxx(p.pid, run["simulation_run_id"])
        assert view["status"] == "unavailable" and view["result"] is None
        assert [r["code"] for r in view["reasons"]] == ["PACKAGE_OMITTED"]
        assert view["basis"]["mean_source_sha256"] is None
    finally:
        if missing != "omitted":
            moved.rename(target)
        p.service.store.save(original)


def test_a8_honest_annual_run_unchanged(annual):
    p, run = annual
    original = p.bundle()
    bundle = deepcopy(original)
    bundle["uncertainty_assumptions"] = project_ledger()
    p.service.store.save(bundle)
    try:
        honest = p.study.annual_pxx(p.pid, run["simulation_run_id"])
        assert honest["status"] == "available"
        assert honest["result"]["annual_mean_kwh"] == run["summary_result"]["annual_energy_wh"] / 1000
        bundle["simulation_runs"][0]["summary_result"]["annual_energy_wh"] *= 10
        p.service.store.save(bundle)
        assert p.study.annual_pxx(p.pid, run["simulation_run_id"]) == honest
    finally:
        p.service.store.save(original)


def test_a8_damaged_package_is_refused(day_run):
    p, run = day_run
    path = p.study.run_root / p.pid / run["simulation_run_id"] / "summary-result.json"
    original = path.read_bytes()
    path.write_bytes(original + b" ")
    try:
        with pytest.raises(ValueError, match="hash|size"):
            p.study.annual_pxx(p.pid, run["simulation_run_id"])
    finally:
        path.write_bytes(original)


@pytest.mark.parametrize("power", [0., -100.])
@pytest.mark.parametrize("basis", ["resolved_loss_settings", "execution_breakdown"])
def test_a9_nonpositive_output_keeps_recorded_nameplate(power, basis):
    frame = pd.DataFrame({"timestamp": pd.date_range("2025-01-01T12:00:00+07:00", periods=1),
                          "interval_seconds": [3600.], "pcc_power_w": [power], "poa_global_unshaded_w_m2": [1000.]})
    source = ExportSource("p", {"simulation_run_id": "r"}, {}, {}, frame, [])
    summary = {"total_energy_wh": power, "specific_yield_wh_per_wp": power / 1000.,
               "monthly_energy": [{"month": "2025-01", "energy_wh": power}], "loss_summary": [],
               basis: {"simulated_dc_nameplate_w": 1000.}}
    if basis == "resolved_loss_settings":
        summary["execution_breakdown"] = {"simulated_dc_nameplate_w": 2000.}
    result = monthly(source, summary)
    assert result["dc_kwp"] == 1.
    assert result["monthly"][0]["specific_yield_kwh_kwp"] == power / 1000.
    assert result["monthly"][0]["performance_ratio"] == power / 1000.


def test_a9_zero_output_without_recorded_nameplate_keeps_previous_basis():
    frame = pd.DataFrame({"timestamp": pd.date_range("2025-01-01T12:00:00+07:00", periods=1),
                          "interval_seconds": [3600.], "pcc_power_w": [0.], "poa_global_unshaded_w_m2": [1000.]})
    source = ExportSource("p", {"simulation_run_id": "r"}, {}, {}, frame, [])
    summary = {"total_energy_wh": 0., "specific_yield_wh_per_wp": 0.,
               "monthly_energy": [{"month": "2025-01", "energy_wh": 0.}], "loss_summary": []}
    result = monthly(source, summary)
    assert result["dc_kwp"] is None
    assert result["dc_kwp_basis"] == "run summary: total energy ÷ specific yield (the engine's installed DC nameplate)"


def _layouts_before_fix_b(lengths: list[int], caps: list[float], modules: int) -> list[tuple[tuple, list[list[int]]]]:
    """Frozen RB-FIX-A implementation: oracle for ranking, de-duplication and stable ties."""
    found: dict[str, tuple[tuple, list[list[int]]]] = {}

    def add(layout: list[list[int]]) -> None:
        strings = [n for mppt in layout for n in mppt if n]
        if not strings or sum(strings) > modules:
            return
        per_mppt = [sum(1 for n in mppt if n) for mppt in layout]
        key = (-sum(strings), len(set(strings)), -min(strings), -sum(strings) / len(strings), max(per_mppt) - min(per_mppt))
        found.setdefault(" ; ".join(",".join(map(str, m)) for m in layout), (key, layout))

    def fill(length: int, strings: int, mppt_caps: list[float]) -> list[list[int]]:
        return [[length] * c if c else [0] for c in _distribute(strings, mppt_caps)]

    for n in lengths:
        add(fill(n, int(min(modules // n, sum(caps))), caps))
    for long in lengths:
        for short in lengths:
            if short >= long:
                continue
            # String totals, used lengths and count extremes determine all remaining ranking ties.
            states = {(0, 0, modules, 0, 0): []}
            for cap in caps:
                choices = [(n, c, bit) for n, bit in ((long, 1), (short, 2))
                           for c in range(int(min(cap, modules // n)), 0, -1)] + [(0, 0, 0)]
                following = {}
                for (used, strings, least, most, mask), layout in states.items():
                    for n, c, bit in choices:
                        total = used + n * c
                        if total <= modules:
                            state = (total, strings + c, min(least, c), max(most, c), mask | bit)
                            following.setdefault(state, layout + [[n] * c if c else [0]])
                states = following
            for state, layout in states.items():
                if state[-1] == 3:
                    add(layout)
    return sorted(found.values(), key=lambda item: item[0])


def test_b2_layout_top_eight_matches_frozen_oracle():
    rng = random.Random(20261113)
    for _ in range(240):
        lengths = rng.sample(range(2, 12), rng.randint(2, 4))
        caps = [rng.randint(1, 3) for _ in range(rng.randint(1, 4))]
        modules = rng.randint(1, 60)
        assert _layouts(lengths, caps, modules, limit=8) == _layouts_before_fix_b(lengths, caps, modules)[:8], (
            lengths, caps, modules)


@pytest.mark.parametrize("lengths,caps,modules", [
    ([], [1, 2], 38), ([12, 13], [], 38), ([4, 5], [0, 2, 0], 14),
    ([4, 5], [1, float("inf")], 14), ([5, 4, 5, 4], [2, 2], 19), ([4, 5], [2, 2], 0),
])
@pytest.mark.parametrize("limit", [0, 1, 3, 8])
def test_b2_layout_limits_and_edge_cases_match_oracle(lengths, caps, modules, limit):
    assert _layouts(lengths, caps, modules, limit=limit) == _layouts_before_fix_b(lengths, caps, modules)[:limit]


def test_b2_twelve_mppt_search_under_two_seconds(record_property):
    start = perf_counter()
    result = _layouts(list(range(8, 25)), [4.0] * 12, 750, limit=8)
    elapsed = perf_counter() - start
    record_property("layout_search_seconds", elapsed)
    print({"layout_search_seconds": elapsed, "layouts": len(result)})
    assert len(result) == 8 and -result[0][0][0] == 750
    assert elapsed < 2.0


@pytest.fixture
def subhourly_annual(persisted):
    """A synthetic constant-power year persisted through the existing package writer."""
    frame = pd.DataFrame({
        "timestamp": pd.date_range("2023-01-01", periods=35040, freq="15min", tz="Asia/Jakarta"),
        "interval_seconds": 900.0, "pcc_power_w": 1000.0, "interval_energy_wh": 250.0,
    })
    case = persisted(frame=frame)
    run_path = case.directory / "simulation-run.json"
    run = json.loads(run_path.read_text())
    reproduction = run["reproducibility_manifest"]
    for key in ("simulation_timestep_seconds", "native_weather_resolution_seconds", "working_weather_resolution_seconds"):
        reproduction[key] = 900
    summary = {
        "schema_name": "SummaryResult", "schema_version": "0.1", "simulation_run_id": case.run_id,
        "annual_energy_wh": 8760000.0, "total_energy_wh": 8760000.0,
        "specific_yield_wh_per_wp": 8760.0, "performance_ratio": 1.0, "capacity_factor": 1.0,
        "monthly_energy": [{"month": str(month), "energy_wh": float(len(rows) * 250)}
            for month, rows in frame.groupby(frame.timestamp.dt.strftime("%Y-%m"))],
        "loss_summary": [], "peak_dc_power_w": 1000.0, "peak_ac_power_w": 1000.0,
        "clipping_energy_wh": 0.0, "shading_energy_loss_wh": None, "data_quality_summary": {},
        "period_start_time": frame.timestamp.iloc[0].isoformat(),
        "period_end_time": "2024-01-01T00:00:00+07:00", "period_duration_hours": 8760,
        "capacity_factor_basis": "installed_dc_nameplate_over_executed_period",
    }
    _assert_output_schema(summary, "summary-result.schema.json")
    run["summary_result"] = summary
    run_path.write_text(json.dumps(run))
    (case.directory / "summary-result.json").write_text(json.dumps(summary))
    (case.directory / "reproducibility-manifest.json").write_text(json.dumps(reproduction))
    reseal(case)
    service = case.app.state.project_service
    bundle = service.get_bundle(case.project_id)
    bundle["simulation_runs"] = [run]
    bundle["uncertainty_assumptions"] = project_ledger()
    service.save_bundle(bundle)
    return case


def test_b1_verified_subhourly_annual_pxx_available_but_csv_refused(subhourly_annual):
    case = subhourly_annual
    study = case.app.state.study_service
    result = study.annual_pxx(case.project_id, case.run_id)
    assert result["status"] == "available", result
    summary = study._verified_summary(case.project_id, case.run_id)
    assert result["result"]["annual_mean_kwh"] == summary["annual_energy_wh"] / 1000.0
    assert result["basis"]["mean_source_sha256"] == sha256(canonical_json_bytes(summary)).hexdigest()
    with pytest.raises(ValueError, match="CSV export requires stored hourly"):
        study.csv_export(case.project_id, case.run_id, REQUEST["columns"])


@pytest.mark.parametrize("kind,message", [
    ("duplicate", "strictly increasing and unique"), ("reversed", "strictly increasing and unique"),
    ("timezone", "timezone does not match"), ("duration", "numeric and non-missing"),
    ("input_hash", "input hash"), ("damaged", "hash|size"),
])
def test_b1_subhourly_keeps_other_source_checks(persisted, kind, message):
    stamps = list(pd.date_range("2023-01-01", periods=3, freq="15min", tz="Asia/Jakarta"))
    if kind == "duplicate":
        stamps[1] = stamps[0]
    if kind == "reversed":
        stamps.reverse()
    frame = pd.DataFrame({"timestamp": stamps, "interval_seconds": 900.0, "pcc_power_w": 1000.0})
    if kind == "duration":
        frame.loc[1, "interval_seconds"] = float("nan")
    case = persisted(frame=frame)
    run_path = case.directory / "simulation-run.json"
    run = json.loads(run_path.read_text())
    reproduction = run["reproducibility_manifest"]
    reproduction["simulation_timestep_seconds"] = reproduction["working_weather_resolution_seconds"] = 900
    if kind == "timezone":
        reproduction["timezone"] = "UTC"
    if kind == "input_hash":
        run["input_hash"] = "b" * 64
    run_path.write_text(json.dumps(run))
    (case.directory / "reproducibility-manifest.json").write_text(json.dumps(reproduction))
    reseal(case)
    if kind == "damaged":
        path = case.directory / "timeseries.parquet"
        path.write_bytes(path.read_bytes() + b"damaged")
    with pytest.raises(ValueError, match=message):
        case.app.state.study_service.csv_export_source(case.project_id, case.run_id, require_hourly=False)
