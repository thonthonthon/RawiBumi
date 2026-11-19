import math

import numpy as np
import pandas as pd
import pytest

from engine.irradiance import (
    POA_PEREZ,
    POA_PVSYST81_PEREZ,
    PVSYST_LOW_SUN_CUTOFF_DEG,
    IrradianceCompletionResult,
    PerezCoefficientSet,
    calculate_poa,
)
from engine.solar import SolarPositionResult


def _index(periods=1, resolution_seconds=3600):
    return pd.date_range(
        "2026-03-21T05:00:00+07:00",
        periods=periods,
        freq=pd.Timedelta(seconds=resolution_seconds),
    )


def _solar(
    index,
    *,
    true_zenith,
    apparent_zenith=None,
    azimuth=180.0,
    resolution_seconds=3600,
):
    true_values = np.broadcast_to(
        np.asarray(true_zenith, dtype=float),
        len(index),
    )
    apparent_values = np.broadcast_to(
        np.asarray(
            true_zenith if apparent_zenith is None else apparent_zenith,
            dtype=float,
        ),
        len(index),
    )
    azimuth_values = np.broadcast_to(
        np.asarray(azimuth, dtype=float),
        len(index),
    )
    frame = pd.DataFrame(index=index)
    frame["evaluation_time"] = (
        index + pd.Timedelta(seconds=resolution_seconds / 2)
    )
    frame["solar_apparent_zenith_deg"] = apparent_values
    frame["solar_zenith_deg"] = true_values
    frame["solar_apparent_elevation_deg"] = 90.0 - apparent_values
    frame["solar_elevation_deg"] = 90.0 - true_values
    frame["solar_azimuth_deg"] = azimuth_values
    frame["equation_of_time_minutes"] = 0.0
    return SolarPositionResult(
        frame=frame,
        metadata={
            "model_id": "synthetic_test",
            "azimuth_convention": "0_north_90_east_180_south_270_west",
        },
    )


def _completed(index, *, ghi, dni, dhi):
    frame = pd.DataFrame(
        {
            "ghi_w_m2": np.broadcast_to(np.asarray(ghi, dtype=float), len(index)),
            "dni_w_m2": np.broadcast_to(np.asarray(dni, dtype=float), len(index)),
            "dhi_w_m2": np.broadcast_to(np.asarray(dhi, dtype=float), len(index)),
            "dni_completion_method": "source",
            "dhi_completion_method": "source",
        },
        index=index,
    )
    return IrradianceCompletionResult(frame=frame, metadata={})


def _zero_coefficients(
    *,
    timestep_seconds=300,
    verified=False,
    coefficient_set_id="synthetic-zero-perez",
):
    return PerezCoefficientSet(
        coefficient_set_id=coefficient_set_id,
        timestep_seconds=timestep_seconds,
        coefficients=tuple((0.0, 0.0, 0.0, 0.0, 0.0, 0.0) for _ in range(8)),
        source_reference="synthetic regression fixture",
        pvsyst81_production_verified=verified,
    )


def test_pvsyst81_hourly_path_matches_standard_perez_above_low_sun_cutoff():
    index = _index()
    zenith = 40.0
    dni = 700.0
    dhi = 150.0
    ghi = dni * math.cos(math.radians(zenith)) + dhi
    completed = _completed(index, ghi=ghi, dni=dni, dhi=dhi)
    solar = _solar(index, true_zenith=zenith)

    standard = calculate_poa(
        completed,
        solar,
        surface_tilt_deg=20.0,
        surface_azimuth_deg=180.0,
        albedo=0.2,
        model_id=POA_PEREZ,
    )
    compatible = calculate_poa(
        completed,
        solar,
        surface_tilt_deg=20.0,
        surface_azimuth_deg=180.0,
        albedo=0.2,
        model_id=POA_PVSYST81_PEREZ,
        simulation_timestep_seconds=3600,
    )

    columns = [
        "poa_beam_w_m2",
        "poa_sky_diffuse_w_m2",
        "poa_ground_diffuse_w_m2",
        "poa_global_w_m2",
        "poa_isotropic_w_m2",
        "poa_circumsolar_w_m2",
        "poa_horizon_w_m2",
    ]
    assert np.allclose(
        standard.frame[columns],
        compatible.frame[columns],
        atol=1e-10,
        rtol=0.0,
    )
    assert compatible.metadata["pvsyst81_perez_coefficients"]["policy"] == (
        "perez_1990_hourly_reference"
    )
    assert compatible.metadata["subhourly_coefficient_parity_status"] == (
        "not_applicable_hourly"
    )


def test_pvsyst_low_sun_cutoff_zeros_beam_and_circumsolar_only():
    index = _index()
    true_zenith = 89.0
    dni = 800.0
    # Low DHI keeps Perez F1 positive at this extreme zenith, so the
    # pre-cutoff fixture has a non-zero circumsolar term to suppress.
    dhi = 20.0
    ghi = dni * math.cos(math.radians(true_zenith)) + dhi
    completed = _completed(index, ghi=ghi, dni=dni, dhi=dhi)
    solar = _solar(index, true_zenith=true_zenith)

    standard = calculate_poa(
        completed,
        solar,
        surface_tilt_deg=60.0,
        surface_azimuth_deg=180.0,
        albedo=0.2,
        model_id=POA_PEREZ,
    )
    compatible = calculate_poa(
        completed,
        solar,
        surface_tilt_deg=60.0,
        surface_azimuth_deg=180.0,
        albedo=0.2,
        model_id=POA_PVSYST81_PEREZ,
        simulation_timestep_seconds=3600,
    )

    assert standard.frame.iloc[0]["poa_beam_w_m2"] > 0.0
    assert standard.frame.iloc[0]["poa_circumsolar_w_m2"] > 0.0
    row = compatible.frame.iloc[0]
    assert row["solar_elevation_deg"] == pytest.approx(1.0)
    assert bool(row["pvsyst_low_sun_cutoff_applied"]) is True
    assert row["poa_beam_w_m2"] == 0.0
    assert row["poa_circumsolar_w_m2"] == 0.0
    assert row["poa_sky_diffuse_w_m2"] == pytest.approx(
        row["poa_isotropic_w_m2"] + row["poa_horizon_w_m2"],
        abs=1e-10,
    )
    assert row["poa_ground_diffuse_w_m2"] == pytest.approx(
        standard.frame.iloc[0]["poa_ground_diffuse_w_m2"],
        abs=1e-10,
    )
    assert compatible.metadata["pvsyst_low_sun_cutoff_deg"] == 2.0
    assert compatible.metadata["pvsyst_low_sun_cutoff_interval_count"] == 1


def test_pvsyst_low_sun_cutoff_uses_true_elevation_not_apparent_elevation():
    index = _index()
    completed = _completed(index, ghi=120.0, dni=700.0, dhi=100.0)
    solar = _solar(
        index,
        true_zenith=89.0,
        apparent_zenith=87.0,
    )

    result = calculate_poa(
        completed,
        solar,
        surface_tilt_deg=60.0,
        surface_azimuth_deg=180.0,
        model_id=POA_PVSYST81_PEREZ,
        simulation_timestep_seconds=3600,
    )

    assert result.frame.iloc[0]["solar_elevation_deg"] == pytest.approx(1.0)
    assert bool(result.frame.iloc[0]["pvsyst_low_sun_cutoff_applied"]) is True
    assert result.frame.iloc[0]["poa_beam_w_m2"] == 0.0
    assert result.metadata["pvsyst_low_sun_cutoff_basis"] == (
        "true_solar_elevation_deg"
    )


def test_exactly_two_degree_sun_height_is_not_cut_off():
    index = _index()
    completed = _completed(index, ghi=130.0, dni=700.0, dhi=100.0)
    solar = _solar(index, true_zenith=88.0)

    result = calculate_poa(
        completed,
        solar,
        surface_tilt_deg=60.0,
        surface_azimuth_deg=180.0,
        model_id=POA_PVSYST81_PEREZ,
        simulation_timestep_seconds=3600,
    )

    assert result.frame.iloc[0]["solar_elevation_deg"] == pytest.approx(
        PVSYST_LOW_SUN_CUTOFF_DEG
    )
    assert bool(result.frame.iloc[0]["pvsyst_low_sun_cutoff_applied"]) is False
    assert result.frame.iloc[0]["poa_beam_w_m2"] > 0.0


@pytest.mark.parametrize("timestep_seconds", [60, 300, 600, 900])
def test_subhourly_pvsyst81_path_fails_closed_without_timestep_coefficients(
    timestep_seconds,
):
    index = _index(resolution_seconds=timestep_seconds)
    completed = _completed(index, ghi=700.0, dni=700.0, dhi=150.0)
    solar = _solar(
        index,
        true_zenith=40.0,
        resolution_seconds=timestep_seconds,
    )

    with pytest.raises(
        ValueError,
        match="production coefficients are timestep-specific",
    ):
        calculate_poa(
            completed,
            solar,
            surface_tilt_deg=20.0,
            surface_azimuth_deg=180.0,
            model_id=POA_PVSYST81_PEREZ,
            simulation_timestep_seconds=timestep_seconds,
        )


def test_unverified_explicit_subhourly_coefficients_require_diagnostic_override():
    index = _index(resolution_seconds=300)
    completed = _completed(index, ghi=700.0, dni=700.0, dhi=150.0)
    solar = _solar(index, true_zenith=40.0, resolution_seconds=300)
    coefficients = _zero_coefficients()

    with pytest.raises(ValueError, match="not verified as the PVsyst 8.1"):
        calculate_poa(
            completed,
            solar,
            surface_tilt_deg=20.0,
            surface_azimuth_deg=180.0,
            model_id=POA_PVSYST81_PEREZ,
            simulation_timestep_seconds=300,
            pvsyst81_perez_coefficient_set=coefficients,
        )


def test_explicit_diagnostic_coefficients_execute_without_claiming_parity():
    index = _index(resolution_seconds=300)
    dhi = 150.0
    completed = _completed(index, ghi=700.0, dni=700.0, dhi=dhi)
    solar = _solar(index, true_zenith=40.0, resolution_seconds=300)
    coefficients = _zero_coefficients()

    result = calculate_poa(
        completed,
        solar,
        surface_tilt_deg=20.0,
        surface_azimuth_deg=180.0,
        model_id=POA_PVSYST81_PEREZ,
        simulation_timestep_seconds=300,
        pvsyst81_perez_coefficient_set=coefficients,
        allow_unverified_pvsyst81_coefficients=True,
    )

    expected_isotropic = (
        dhi * (1.0 + math.cos(math.radians(20.0))) / 2.0
    )
    row = result.frame.iloc[0]
    assert row["poa_isotropic_w_m2"] == pytest.approx(
        expected_isotropic,
        abs=1e-10,
    )
    assert row["poa_circumsolar_w_m2"] == pytest.approx(0.0, abs=1e-12)
    assert row["poa_horizon_w_m2"] == pytest.approx(0.0, abs=1e-12)
    assert result.metadata["subhourly_coefficient_parity_status"] == (
        "unverified_explicit_table"
    )
    assert result.metadata["pvsyst81_perez_coefficients"][
        "unverified_execution_override"
    ] is True


def test_verified_timestep_specific_table_executes_as_parity_candidate():
    index = _index(resolution_seconds=300)
    completed = _completed(index, ghi=700.0, dni=700.0, dhi=150.0)
    solar = _solar(index, true_zenith=40.0, resolution_seconds=300)

    result = calculate_poa(
        completed,
        solar,
        surface_tilt_deg=20.0,
        surface_azimuth_deg=180.0,
        model_id=POA_PVSYST81_PEREZ,
        simulation_timestep_seconds=300,
        pvsyst81_perez_coefficient_set=_zero_coefficients(
            verified=True,
            coefficient_set_id="synthetic-verified-contract-test",
        ),
    )

    assert result.metadata["subhourly_coefficient_parity_status"] == (
        "verified_production_table"
    )
    assert result.metadata["pvsyst81_perez_coefficients"][
        "coefficient_set_id"
    ] == "synthetic-verified-contract-test"


def test_coefficient_set_timestep_must_match_simulation_timestep():
    index = _index(resolution_seconds=600)
    completed = _completed(index, ghi=700.0, dni=700.0, dhi=150.0)
    solar = _solar(index, true_zenith=40.0, resolution_seconds=600)

    with pytest.raises(ValueError, match="timestep does not match"):
        calculate_poa(
            completed,
            solar,
            surface_tilt_deg=20.0,
            surface_azimuth_deg=180.0,
            model_id=POA_PVSYST81_PEREZ,
            simulation_timestep_seconds=600,
            pvsyst81_perez_coefficient_set=_zero_coefficients(
                timestep_seconds=300,
                verified=True,
            ),
        )


def test_pvsyst81_timestep_must_divide_one_hour_exactly():
    index = _index(resolution_seconds=700)
    completed = _completed(index, ghi=700.0, dni=700.0, dhi=150.0)
    solar = _solar(index, true_zenith=40.0, resolution_seconds=700)

    with pytest.raises(ValueError, match="integer divisor of 60 minutes"):
        calculate_poa(
            completed,
            solar,
            surface_tilt_deg=20.0,
            surface_azimuth_deg=180.0,
            model_id=POA_PVSYST81_PEREZ,
            simulation_timestep_seconds=700,
        )


def test_coefficient_table_shape_is_strictly_eight_by_six():
    with pytest.raises(ValueError, match=r"shape \(8, 6\)"):
        PerezCoefficientSet(
            coefficient_set_id="bad-shape",
            timestep_seconds=300,
            coefficients=((0.0,) * 6,) * 7,
            source_reference="synthetic invalid fixture",
        )
