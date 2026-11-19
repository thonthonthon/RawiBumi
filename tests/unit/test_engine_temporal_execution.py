from dataclasses import replace
from pathlib import Path

import pandas as pd
import pytest

from components.candidates import build_inverter_candidate, build_module_candidate
from components.ond import parse_ond_text
from components.ond.mapper import map_ond
from components.pan import map_pan, parse_pan_text
from engine.irradiance import POA_ISOTROPIC, POA_PVSYST81_PEREZ
from engine.optical import IAM_NONE
from engine.thermal import THERMAL_PVSYST81_TRANSIENT
from engine.simulation import (
    V1_TARGET_TIMESTEPS_SECONDS,
    UnshadedFixedTiltConfiguration,
    prepare_temporal_execution,
    run_unshaded_fixed_tilt,
)
from weather.core import (
    build_time_semantics,
    build_weather_dataset,
    interval_energy_wh_m2,
)


ROOT = Path(__file__).resolve().parents[2]


def _weather(
    *,
    resolution_seconds=3600,
    periods=3,
    start="2026-03-21T10:00:00+07:00",
    origin="measured",
    upstream_generation=None,
):
    index = pd.date_range(
        pd.Timestamp(start),
        periods=periods,
        freq=pd.Timedelta(seconds=resolution_seconds),
    )
    # Deliberately diffuse-only. On a horizontal plane this removes solar-geometry
    # dependence from the physical energy result, making it a clean temporal
    # invariance fixture.
    if resolution_seconds == 3600 and periods == 3:
        ghi = [400.0, 600.0, 800.0]
    else:
        ghi = [500.0] * periods
    series = pd.DataFrame(
        {
            "ghi_w_m2": ghi,
            "dni_w_m2": [0.0] * periods,
            "dhi_w_m2": ghi,
            "ambient_temperature_c": [30.0] * periods,
            "wind_speed_m_s": [1.0] * periods,
            "pressure_pa": [100500.0] * periods,
        },
        index=index,
    )
    semantics = build_time_semantics(
        canonical_timezone="UTC+07:00",
        source_timestamp_convention="interval_start",
        native_interval_seconds=resolution_seconds,
        current_interval_seconds=resolution_seconds,
        source_timezone="UTC+07:00",
        source_utc_offset_hours=7.0,
    )
    return build_weather_dataset(
        series,
        weather_dataset_id=f"wx-temporal-{resolution_seconds}",
        revision_id=f"wx-temporal-{resolution_seconds}-r1",
        name="Temporal execution fixture",
        site_id="site-temporal",
        timezone="UTC+07:00",
        native_resolution_seconds=resolution_seconds,
        source_format="synthetic_test",
        source_timestamp_convention="interval_start",
        location={
            "latitude_deg": -6.425,
            "longitude_deg": 106.831,
            "elevation_m": 93.0,
        },
        native_series_origin=origin,
        series_origin=origin,
        upstream_generation=upstream_generation,
        time_semantics=semantics,
    )


def _module_definition():
    mapping = map_pan(
        parse_pan_text(
            (
                ROOT / "tests/fixtures/panond/synthetic_module.pan"
            ).read_text(encoding="utf-8")
        )
    )
    return build_module_candidate(
        mapping,
        candidate_id="cand-temporal-module",
        module_definition_id="mod-temporal-module",
        revision_id="mod-temporal-module-r1",
        source_id="src-temporal-module",
    )["canonical_data"]


def _inverter_definition():
    mapping = map_ond(
        parse_ond_text(
            (
                ROOT
                / "tests/fixtures/panond/manufacturer/Huawei_Sun2000_100KTL_M1.OND"
            ).read_text(encoding="utf-8")
        )
    )
    return build_inverter_candidate(
        mapping,
        candidate_id="cand-temporal-inverter",
        inverter_definition_id="inv-temporal-huawei",
        revision_id="inv-temporal-huawei-r1",
        source_id="src-temporal-inverter",
    )["canonical_data"]


def _config(timestep_seconds):
    return UnshadedFixedTiltConfiguration(
        simulation_timestep_seconds=timestep_seconds,
        surface_tilt_deg=0.0,
        surface_azimuth_deg=0.0,
        poa_model_id=POA_ISOTROPIC,
        module_definition=_module_definition(),
        inverter_definition=_inverter_definition(),
        modules_in_series=18,
        string_ids=("S01",),
        mppt_assignments={1: ("S01",)},
        u_c_w_m2k=20.0,
        u_v_w_m2k_per_ms=0.0,
        alpha_absorption=0.90,
        albedo=0.20,
        iam_model_id=IAM_NONE,
        module_quality_loss_fraction=0.0,
        module_mismatch_loss_fraction=0.0,
        string_mismatch_loss_fraction=0.0,
        dc_array_resistance_ohm=0.0,
    )


def test_v1_target_timesteps_are_frozen():
    assert V1_TARGET_TIMESTEPS_SECONDS == (60, 300, 900, 3600)


def test_native_execution_preserves_source_cadence_and_origin():
    weather = _weather()
    context = prepare_temporal_execution(
        weather,
        simulation_timestep_seconds=3600,
    )

    assert context.metadata["native_resolution_seconds"] == 3600
    assert context.metadata["input_series_resolution_seconds"] == 3600
    assert context.metadata["simulation_timestep_seconds"] == 3600
    assert context.metadata["input_to_working_transformation"] == "unchanged"
    assert context.metadata["cadence_relation_to_native"] == "equal_to_native"
    assert context.metadata["working_series_origin"] == "measured"
    assert context.metadata["temporal_fidelity"] == "native_source_cadence"
    assert context.metadata["false_precision_warning"] is False
    assert context.weather.dataset["time_semantics"]["origin_source"][
        "interval_seconds"
    ] == 3600
    assert context.weather.dataset["time_semantics"]["canonical"][
        "interval_seconds"
    ] == 3600
    assert len(context.provenance) == 3
    assert not context.provenance["is_rawibumi_disaggregated"].any()


def test_hourly_to_minute_is_explicit_disaggregation_with_native_provenance():
    weather = _weather()
    before_ghi = interval_energy_wh_m2(weather, "ghi_w_m2")

    context = prepare_temporal_execution(
        weather,
        simulation_timestep_seconds=60,
    )

    assert len(context.weather.series) == 180
    assert context.metadata["input_to_working_transformation"] == "disaggregation"
    assert context.metadata["cadence_relation_to_native"] == "finer_than_native"
    assert context.metadata["working_series_origin"] == "opensimpv_derived"
    assert context.metadata["temporal_fidelity"] == "rawibumi_disaggregated"
    assert context.metadata["derived_subhourly"] is True
    assert context.metadata["false_precision_warning"] is True
    assert context.metadata["resolution_transform_algorithm"] == "interval_mean_hold"
    assert context.metadata["resolution_transform_algorithm_version"] == "0.1"
    assert context.metadata["irradiance_energy_preservation_check"] is not None

    assert context.weather.dataset["native_resolution_seconds"] == 3600
    assert context.weather.dataset["series_resolution_seconds"] == 60
    assert context.weather.dataset["time_semantics"]["origin_source"][
        "interval_seconds"
    ] == 3600
    assert context.weather.dataset["time_semantics"]["canonical"][
        "interval_seconds"
    ] == 60
    assert interval_energy_wh_m2(
        context.weather,
        "ghi_w_m2",
    ) == pytest.approx(before_ghi, abs=1e-12)

    first_hour = context.provenance.iloc[:60]
    assert first_hour["is_opensimpv_disaggregated"].all()
    assert (
        first_hour["input_interval_start"]
        == pd.Timestamp("2026-03-21T10:00:00+07:00")
    ).all()
    assert (
        first_hour["input_interval_end"]
        == pd.Timestamp("2026-03-21T11:00:00+07:00")
    ).all()


def test_provider_generated_native_minute_is_not_relabelled_as_rawibumi_disaggregation():
    weather = _weather(
        resolution_seconds=60,
        periods=5,
        origin="provider_generated",
        upstream_generation={
            "provider": "Meteonorm",
            "synthetic": True,
            "base_resolution_seconds": 3600,
            "method": "meteonorm_provider_subhourly_generation",
            "evidence": "source_structure",
            "evidence_detail": "Synthetic test fixture",
        },
    )

    context = prepare_temporal_execution(
        weather,
        simulation_timestep_seconds=60,
    )

    assert context.metadata["input_to_working_transformation"] == "unchanged"
    assert context.metadata["cadence_relation_to_native"] == "equal_to_native"
    assert context.metadata["native_series_origin"] == "provider_generated"
    assert context.metadata["working_series_origin"] == "provider_generated"
    assert context.metadata["provider_generated_subhourly"] is True
    assert context.metadata["provider_base_resolution_seconds"] == 3600
    assert context.metadata["temporal_fidelity"] == (
        "provider_generated_native_subhourly"
    )
    assert context.metadata["false_precision_warning"] is True
    assert not context.provenance["is_rawibumi_disaggregated"].any()
    assert not context.provenance[
        "is_working_series_opensimpv_derived"
    ].any()


def test_native_minute_can_be_explicitly_aggregated_to_fifteen_minutes():
    weather = _weather(
        resolution_seconds=60,
        periods=30,
        origin="provider_generated",
        upstream_generation={
            "provider": "Meteonorm",
            "synthetic": True,
            "base_resolution_seconds": 3600,
            "method": "meteonorm_provider_subhourly_generation",
            "evidence": "source_structure",
            "evidence_detail": "Synthetic test fixture",
        },
    )

    context = prepare_temporal_execution(
        weather,
        simulation_timestep_seconds=900,
    )

    assert len(context.weather.series) == 2
    assert context.metadata["input_to_working_transformation"] == "aggregation"
    assert context.metadata["cadence_relation_to_native"] == "coarser_than_native"
    assert context.metadata["working_series_origin"] == "opensimpv_derived"
    assert context.metadata["temporal_fidelity"] == "rawibumi_aggregated"
    assert context.provenance["is_rawibumi_aggregated"].all()
    assert (context.provenance["input_interval_count"] == 15).all()


def test_non_integer_resolution_conversion_is_rejected():
    with pytest.raises(ValueError, match="divide source resolution"):
        prepare_temporal_execution(
            _weather(),
            simulation_timestep_seconds=700,
        )


@pytest.mark.parametrize(
    ("timestep_seconds", "expected_rows"),
    [
        (60, 180),
        (300, 36),
        (900, 12),
        (3600, 3),
    ],
)
def test_complete_unshaded_chain_runs_at_all_v1_target_cadences(
    timestep_seconds,
    expected_rows,
):
    result = run_unshaded_fixed_tilt(
        _weather(),
        config=_config(timestep_seconds),
    )

    assert len(result.timeseries) == expected_rows
    assert (
        result.timeseries["duration_seconds"] == timestep_seconds
    ).all()
    assert result.metadata["simulation_timestep_seconds"] == timestep_seconds
    assert result.metadata["model_manifest"]["solar_position"]
    assert result.metadata["model_manifest"]["poa_transposition"] == POA_ISOTROPIC
    assert result.metadata["model_manifest"]["iam"] == IAM_NONE
    assert result.metadata["model_manifest"]["module"] == (
        "module.pvsyst_singlediode.v6"
    )
    assert result.metadata["model_manifest"]["inverter"] == (
        "inverter.voltage_dependent_efficiency.v0.1"
    )
    assert result.metadata["model_manifest"]["loss_ledger"] == (
        "loss_ledger.electrical_chain.v0.1"
    )
    assert result.electrical.ledger.metadata[
        "max_interval_reconciliation_residual_w"
    ] <= 1e-6
    assert abs(
        result.electrical.ledger.metadata[
            "annual_reconciliation_residual_kwh"
        ]
    ) <= 1e-9


def test_unshaded_runner_records_pvsyst81_hourly_perez_runtime_contract():
    config = replace(
        _config(3600),
        poa_model_id=POA_PVSYST81_PEREZ,
    )

    result = run_unshaded_fixed_tilt(
        _weather(),
        config=config,
    )

    assert result.metadata["model_manifest"]["poa_transposition"] == (
        POA_PVSYST81_PEREZ
    )
    poa_runtime = result.metadata["poa_runtime"]
    assert poa_runtime["pvsyst81_perez_coefficients"]["policy"] == (
        "perez_1990_hourly_reference"
    )
    assert poa_runtime["subhourly_coefficient_parity_status"] == (
        "not_applicable_hourly"
    )
    assert poa_runtime["pvsyst_low_sun_cutoff_deg"] == 2.0
    assert "pvsyst_low_sun_cutoff_applied" in result.timeseries


def test_unshaded_runner_executes_pvsyst81_transient_thermal_from_component_mass():
    config = replace(
        _config(3600),
        thermal_model_id=THERMAL_PVSYST81_TRANSIENT,
    )

    result = run_unshaded_fixed_tilt(
        _weather(),
        config=config,
    )

    module = config.module_definition
    mechanical = module["mechanical"]
    expected_unit_mass = float(mechanical["mass_kg"]) / (
        float(mechanical["width_m"]) * float(mechanical["height_m"])
    )

    assert result.metadata["model_manifest"]["thermal"] == (
        THERMAL_PVSYST81_TRANSIENT
    )
    assert result.metadata["module_unit_mass_kg_m2"] == pytest.approx(
        expected_unit_mass
    )
    assert result.coupled_module.thermal.metadata["module_unit_mass_kg_m2"] == (
        pytest.approx(expected_unit_mass)
    )
    assert result.coupled_module.thermal.metadata["module_unit_mass_source"] == (
        "component_mass_divided_by_one_sided_area"
    )
    assert "steady_state_cell_temperature_c" in result.timeseries
    assert "thermal_relaxation_time_s" in result.timeseries
    assert not result.timeseries["steady_state_cell_temperature_c"].equals(
        result.timeseries["cell_temperature_c"]
    )


def test_diffuse_horizontal_fixture_is_end_to_end_energy_invariant_across_cadences():
    energies = {}
    ghi = {}
    for timestep in V1_TARGET_TIMESTEPS_SECONDS:
        result = run_unshaded_fixed_tilt(
            _weather(),
            config=_config(timestep),
        )
        energies[timestep] = result.energy.annual["pcc_power_kwh"]
        ghi[timestep] = result.energy.annual["ghi_kwh_m2"]

    baseline_energy = energies[3600]
    baseline_ghi = ghi[3600]
    for timestep in V1_TARGET_TIMESTEPS_SECONDS:
        assert energies[timestep] == pytest.approx(
            baseline_energy,
            abs=1e-8,
        )
        assert ghi[timestep] == pytest.approx(
            baseline_ghi,
            abs=1e-12,
        )


def test_same_temporal_run_is_deterministic():
    first = run_unshaded_fixed_tilt(
        _weather(),
        config=_config(300),
    )
    second = run_unshaded_fixed_tilt(
        _weather(),
        config=_config(300),
    )

    pd.testing.assert_frame_equal(
        first.timeseries,
        second.timeseries,
        check_exact=True,
    )
    assert first.energy.annual == second.energy.annual
    assert first.kpis == second.kpis
    assert first.metadata["deterministic"] is True


def test_temporal_runner_records_specific_yield_pr_and_provenance_columns():
    result = run_unshaded_fixed_tilt(
        _weather(),
        config=_config(900),
    )

    assert result.kpis["specific_yield_kwh_per_kwp"] > 0
    assert result.kpis["reference_yield_h"] > 0
    assert 0 < result.kpis["performance_ratio"] < 1.1
    assert "native_resolution_seconds" in result.timeseries
    assert "simulation_resolution_seconds" in result.timeseries
    assert "input_to_working_transformation" in result.timeseries
    assert "pcc_power_w" in result.timeseries
    assert "pcc_power_kwh" in result.energy.annual
    assert result.metadata["resolution_conversion_stage"] == (
        "before_timeline_and_all_physics"
    )
    assert result.metadata["energy_duration_source"] == (
        "timeline.duration_seconds"
    )

def test_unshaded_runner_consumes_canonical_module_optical_and_quality_defaults():
    module = _module_definition()
    module["optical"] = {
        "absorptance_fraction": 0.87,
        "iam": {
            "model_type": "tabulated",
            "execution_model_id": "iam.tabulated.pvlib_interp.v0.1",
            "interpolation_method": "cubic",
            "normalize": True,
            "points": [
                {"angle_deg": 0.0, "modifier": 1.0},
                {"angle_deg": 30.0, "modifier": 1.0},
                {"angle_deg": 50.0, "modifier": 0.99},
                {"angle_deg": 70.0, "modifier": 0.90},
                {"angle_deg": 90.0, "modifier": 0.0},
            ],
        },
    }
    module["quality"] = {
        "default_module_quality_loss_fraction": -0.01,
        "default_module_quality_method": "fixture_component_default",
    }

    config = UnshadedFixedTiltConfiguration(
        simulation_timestep_seconds=3600,
        surface_tilt_deg=0.0,
        surface_azimuth_deg=0.0,
        poa_model_id=POA_ISOTROPIC,
        module_definition=module,
        inverter_definition=_inverter_definition(),
        modules_in_series=18,
        string_ids=("S01",),
        mppt_assignments={1: ("S01",)},
        u_c_w_m2k=20.0,
        u_v_w_m2k_per_ms=0.0,
        albedo=0.20,
        module_mismatch_loss_fraction=0.0,
        string_mismatch_loss_fraction=0.0,
        dc_array_resistance_ohm=0.0,
    )

    result = run_unshaded_fixed_tilt(_weather(), config=config)
    resolution = result.metadata["module_runtime_resolution"]

    assert resolution["alpha_absorption"] == {
        "value": pytest.approx(0.87),
        "source": "module_definition.optical.absorptance_fraction",
    }
    assert resolution["iam"]["model_id"] == "iam.tabulated.pvlib_interp.v0.1"
    assert resolution["iam"]["source"] == "module_definition.optical.iam"
    assert resolution["iam"]["profile_point_count"] == 5
    assert resolution["module_quality_loss_fraction"]["value"] == pytest.approx(-0.01)
    assert resolution["module_quality_loss_fraction"]["source"] == (
        "module_definition.quality.default_module_quality_loss_fraction"
    )
    assert result.coupled_module.thermal.metadata["alpha_absorption"] == pytest.approx(
        0.87
    )
    assert result.optical.metadata["model_id"] == "iam.tabulated.pvlib_interp.v0.1"

