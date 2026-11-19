import json
from pathlib import Path

import yaml
from jsonschema import Draft202012Validator


ROOT = Path(__file__).resolve().parents[2]
SUITE_PATH = ROOT / "tests/benchmarks/phase3_unshaded.yaml"
SCHEMA_PATH = ROOT / "schemas/phase3-benchmark-suite.schema.json"
REGISTRY_PATH = ROOT / "tests/benchmarks/benchmarks.yaml"


def _suite():
    return yaml.safe_load(SUITE_PATH.read_text(encoding="utf-8"))


def _family(suite, family_id):
    return next(item for item in suite["families"] if item["family_id"] == family_id)


def test_phase3_benchmark_suite_validates_against_schema():
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(_suite())


def test_phase3_reference_families_and_case_ids_are_frozen():
    suite = _suite()
    families = {item["family_id"]: item for item in suite["families"]}

    assert set(families) == {
        "WX-MN82-NATIVE",
        "SYS-PVSYST-V816-UNSHADED",
        "WX-OSPV-DERIVED",
    }
    assert len(families["WX-MN82-NATIVE"]["cases"]) == 4
    assert len(families["SYS-PVSYST-V816-UNSHADED"]["cases"]) == 8
    assert len(families["WX-OSPV-DERIVED"]["cases"]) == 4

    ids = [
        case["benchmark_id"]
        for family in suite["families"]
        for case in family["cases"]
    ]
    assert len(ids) == len(set(ids))

    registry = yaml.safe_load(REGISTRY_PATH.read_text(encoding="utf-8"))
    registered = {item["benchmark_id"] for item in registry["benchmarks"]}
    assert set(ids).issubset(registered)
    assert "P3-BENCH-CONTRACT-001" in registered


def test_meteonorm82_native_resolution_contract_is_self_consistent():
    family = _family(_suite(), "WX-MN82-NATIVE")
    source = family["source"]

    assert source["latitude_deg"] == -6.425
    assert source["longitude_deg"] == 106.831
    assert source["timezone"] == "UTC+07:00"
    assert source["source_time_reference_minutes"] == -30

    expected = {
        "MN82-H": (3600, 8760),
        "MN82-15": (900, 35040),
        "MN82-10": (600, 52560),
        "MN82-01": (60, 525600),
    }
    for case in family["cases"]:
        resolution, rows = expected[case["case_id"]]
        assert case["native_resolution_seconds"] == resolution
        assert case["simulation_resolution_seconds"] == resolution
        assert case["targets"]["row_count"] == rows
        assert rows * resolution == 365 * 24 * 3600
        assert case["source_artifact"]["redistributed"] is False
        assert len(case["source_artifact"]["sha256"]) == 64

    ghi = [case["targets"]["annual_ghi_kwh_m2"] for case in family["cases"]]
    assert (max(ghi) - min(ghi)) / min(ghi) < 2.0e-4


def test_pvsyst_unshaded_pair_topology_and_temporal_modes_are_frozen():
    family = _family(_suite(), "SYS-PVSYST-V816-UNSHADED")
    shared = family["shared_configuration"]

    assert shared["no_3d_scene"] is True
    assert shared["near_shading"] == "none"
    assert shared["modules_per_string"] == 18
    assert shared["thermal"]["uc_w_m2k"] == 20.0
    assert shared["thermal"]["uv_w_m2k_per_ms"] == 0.0
    assert shared["thermal"]["irradiance_basis"] == (
        "incident_poa_global_before_iam"
    )
    assert shared["thermal"]["module_efficiency_policy"] == (
        "dynamic_from_module_electrical_model"
    )
    assert shared["auxiliary_losses_configured"] is False

    array_loss = shared["array_loss_execution"]
    assert array_loss["model_id"] == "array_losses.explicit_mpp_i2r.v0.1"
    assert array_loss["module_quality"]["sign_convention"] == (
        "positive_loss_negative_gain"
    )
    assert array_loss["dc_wiring"]["model"] == (
        "global_equivalent_resistance_i2r"
    )
    assert array_loss["dc_wiring"]["stc_loss_fraction_role"] == (
        "reference_only_not_runtime_multiplier"
    )
    assert array_loss["ordering"] == [
        "module_quality",
        "module_mismatch",
        "string_mismatch",
        "dc_wiring",
    ]

    aggregation = shared["result_aggregation"]
    assert aggregation["interval_energy_model"] == (
        "interval_average_times_explicit_duration"
    )
    assert aggregation["duration_source"] == (
        "case_simulation_resolution_seconds"
    )
    assert aggregation["pcc_boundary"] == (
        "net_inverter_ac_output_no_downstream_ac_stage"
    )
    assert aggregation["performance_ratio_irradiance_basis"] == (
        "incident_poa_global"
    )
    assert aggregation["pvsyst_e_array_mapping_status"] == "deferred"

    temporal = shared["temporal_execution"]
    assert temporal["schema"] == "TemporalExecutionContext.v0.1"
    assert temporal["v1_target_timestep_seconds"] == [60, 300, 900, 3600]
    assert temporal["resolution_conversion_stage"] == (
        "before_timeline_and_all_physics"
    )
    assert temporal["native_resolution_preserved"] is True
    assert temporal["source_origin_time_semantics_preserved"] is True
    assert temporal["interval_level_provenance"] is True
    assert temporal[
        "provider_generated_subhourly_distinct_from_opensimpv_disaggregation"
    ] is True
    assert temporal["opensimpv_disaggregation"]["algorithm"] == (
        "interval_mean_hold"
    )
    assert temporal["opensimpv_disaggregation"]["algorithm_version"] == "0.1"
    assert temporal["opensimpv_disaggregation"][
        "irradiance_energy_preserving"
    ] is True
    assert temporal["opensimpv_disaggregation"]["fidelity"] == (
        "conservative_baseline"
    )
    assert temporal["native_pvsyst_reference_timesteps_seconds"] == [60, 3600]
    assert temporal["meteonorm82_weather_reference_timesteps_seconds"] == [
        60,
        600,
        900,
        3600,
    ]

    inverter = shared["inverter"]
    assert inverter["electrical_model_id"] == (
        "inverter.voltage_dependent_efficiency.v0.1"
    )
    assert inverter["nominal_ac_kw"] == 100
    assert inverter["max_ac_kw"] == 110
    assert inverter["max_power_temperature_c"] == 30.0
    assert inverter["nominal_power_temperature_c"] == 40.0
    assert inverter["high_temperature_limit1_c"] == 60.0
    assert inverter["high_temperature_limit1_kw"] == 36.0
    assert inverter["absolute_temperature_limit_c"] == 62.0
    assert inverter["runtime_temperature_basis"] == "unresolved"
    assert inverter["minimum_input_power_w"] == 500.0
    assert inverter["night_loss_w"] == 2.0
    assert inverter["clipping_limit_without_runtime_temperature_w"] == 110000.0
    assert inverter["verified_mppt_operating_current_limit_a"] is None
    assert inverter["efficiency_power_interpolation"] == (
        "bounded_linear_pin_pout_v0.1"
    )
    assert inverter["efficiency_voltage_interpolation"] == (
        "bounded_quadratic_v0.1"
    )
    assert inverter["pvsyst_reported_zero_loss_channels_pct"] == {
        "max_input_current": 0.0,
        "over_nominal_input_voltage": 0.0,
        "power_threshold": 0.0,
        "voltage_threshold": 0.0,
        "night_consumption": 0.0,
    }

    cases = {case["case_id"]: case for case in family["cases"]}
    pairs = [
        ("VC0", "VC1", 12, 216, 118.8, 1.19),
        ("VC2", "VC3", 14, 252, 138.6, 1.39),
        ("VC4", "VC5", 16, 288, 158.4, 1.58),
        ("VC6", "VC7", 18, 324, 178.2, 1.78),
    ]
    for hourly_id, minute_id, strings, modules, dc_kwp, ratio in pairs:
        hourly = cases[hourly_id]
        minute = cases[minute_id]

        assert hourly["simulation_resolution_seconds"] == 3600
        assert minute["simulation_resolution_seconds"] == 60
        assert hourly["native_resolution_seconds"] == 3600
        assert minute["native_resolution_seconds"] == 60

        for case in (hourly, minute):
            config = case["configuration"]
            assert config["strings"] == strings
            assert config["modules_total"] == modules
            assert config["dc_nameplate_kwp_exact"] == dc_kwp
            assert config["dc_ac_ratio_reported"] == ratio
            assert case["source_artifact"]["redistributed"] is False

        assert hourly["targets"]["annual"]["glob_hor_kwh_m2"] == 1749.8
        assert minute["targets"]["annual"]["glob_hor_kwh_m2"] == 1749.9
        assert hourly["targets"]["annual"]["glob_inc_kwh_m2"] == 1754.9
        assert minute["targets"]["annual"]["glob_inc_kwh_m2"] == 1759.4


def test_pvsyst_monthly_energy_targets_reconcile_with_reported_annual_rounding():
    family = _family(_suite(), "SYS-PVSYST-V816-UNSHADED")

    for case in family["cases"]:
        targets = case["targets"]
        assert len(targets["monthly_e_array_kwh"]) == 12
        assert len(targets["monthly_e_grid_kwh"]) == 12

        annual = targets["annual"]
        # PVsyst report rows are displayed as integer monthly kWh, so summing displayed
        # months can differ from the separately rounded annual result by a few kWh.
        assert abs(sum(targets["monthly_e_array_kwh"]) - annual["e_array_kwh"]) <= 2
        assert abs(sum(targets["monthly_e_grid_kwh"]) - annual["e_grid_kwh"]) <= 1


def test_pvsyst_clipping_reference_increases_with_dc_ac_ratio():
    family = _family(_suite(), "SYS-PVSYST-V816-UNSHADED")
    hourly = [
        case["targets"]["annual"]["clipping_loss_pct"]
        for case in family["cases"]
        if case["case_id"] in {"VC0", "VC2", "VC4", "VC6"}
    ]
    minute = [
        case["targets"]["annual"]["clipping_loss_pct"]
        for case in family["cases"]
        if case["case_id"] in {"VC1", "VC3", "VC5", "VC7"}
    ]

    assert hourly == [0.00, 0.13, 1.90, 5.23]
    assert minute == [0.02, 0.37, 2.47, 6.35]
    assert hourly == sorted(hourly)
    assert minute == sorted(minute)


def test_derived_subhourly_family_is_not_native_minute_weather():
    suite = _suite()
    policy = suite["benchmark_policy"]
    family = _family(suite, "WX-OSPV-DERIVED")

    assert policy["source_weather_families_are_not_interchangeable"] is True
    assert family["source"]["parent_benchmark_id"] == "WX-MN82-H"
    assert family["source"]["parent_native_resolution_seconds"] == 3600
    assert family["source"]["output_series_origin"] == "opensimpv_derived"

    expected_targets = {900, 600, 300, 60}
    assert {
        case["simulation_resolution_seconds"] for case in family["cases"]
    } == expected_targets

    for case in family["cases"]:
        assert case["native_resolution_seconds"] == 3600
        assert case["targets"]["source_interval_energy_preserved"] is True
        assert case["targets"]["daylight_only_required"] is True
        assert case["targets"]["artificial_night_irradiance_allowed"] is False
