"""Detailed-timestep PVsyst attribution for Phase 3.9H.

This layer consumes a user-supplied PVsyst detailed-output CSV as the validation
oracle and a completed OpenSIMPV standard result. Raw proprietary source data are
not stored in the repository.

The report deliberately keeps PVsyst's sub-hourly clipping correction (ILPmxSH)
separate from ordinary hourly clipping (IL_Pmax). OpenSIMPV does not currently
model ILPmxSH, so it is a named model boundary rather than a hidden residual.
"""

from __future__ import annotations

from copy import deepcopy
from math import sqrt
from typing import Any, Mapping

import numpy as np
import pandas as pd

from .pvsyst import (
    build_pvsyst_attribution_report,
    extract_opensimpv_attribution_metrics,
    load_pvsyst_attribution_campaign,
)
from .pvsyst_output import (
    PVsystDetailedOutput,
    extract_pvsyst_hourly_oracle_metrics,
    infer_subhourly_clipping_correction,
    validate_hourly_oracle_balance,
)


DETAILED_HOURLY_REPORT_SCHEMA_NAME = "PVsystDetailedHourlyAttributionReport"
DETAILED_HOURLY_REPORT_SCHEMA_VERSION = "0.1"


def _stage_effect_pct(downstream: float, upstream: float) -> float:
    if upstream == 0.0:
        return 0.0 if downstream == 0.0 else float("nan")
    return (downstream / upstream - 1.0) * 100.0


def pvsyst_detailed_hourly_reference_metrics(
    output: PVsystDetailedOutput,
    *,
    installed_dc_kwp: float,
) -> dict[str, Any]:
    """Convert detailed PVsyst channels into the Phase-3.9 comparison metrics."""
    if installed_dc_kwp <= 0:
        raise ValueError("installed_dc_kwp must be positive")

    raw = extract_pvsyst_hourly_oracle_metrics(output)
    e_nominal = raw["array_nominal_energy_kwh"]
    e_after_irradiance = e_nominal - raw["irradiance_level_loss_kwh"]
    e_after_temperature = e_after_irradiance - raw["temperature_loss_kwh"]
    e_after_quality = e_after_temperature - raw["module_quality_loss_kwh"]
    e_after_mismatch = e_after_quality - raw["mismatch_loss_kwh"]
    e_arr_mpp = raw["array_virtual_mpp_kwh"]

    conversion_downstream = e_arr_mpp - raw["inverter_conversion_loss_kwh"]
    ordinary_clip_downstream = (
        conversion_downstream - raw["inverter_hourly_clipping_loss_kwh"]
    )

    glob_inc = raw["glob_inc_kwh_m2"]
    e_grid = raw["e_grid_kwh"]
    return {
        "glob_hor_kwh_m2": raw["glob_hor_kwh_m2"],
        "diff_hor_kwh_m2": raw["diff_hor_kwh_m2"],
        "ambient_temp_c": raw["ambient_temp_c"],
        "glob_inc_kwh_m2": glob_inc,
        "glob_eff_kwh_m2": raw["glob_eff_kwh_m2"],
        "array_nominal_energy_kwh": e_nominal,
        "irradiance_level_loss_pct": _stage_effect_pct(
            e_after_irradiance, e_nominal
        ),
        "temperature_loss_pct": _stage_effect_pct(
            e_after_temperature, e_after_irradiance
        ),
        "module_quality_effect_pct": _stage_effect_pct(
            e_after_quality, e_after_temperature
        ),
        "mismatch_loss_pct": _stage_effect_pct(
            e_after_mismatch, e_after_quality
        ),
        "dc_wiring_loss_pct": _stage_effect_pct(e_arr_mpp, e_after_mismatch),
        "array_virtual_mpp_kwh": e_arr_mpp,
        "inverter_conversion_loss_pct": _stage_effect_pct(
            conversion_downstream, e_arr_mpp
        ),
        "inverter_clipping_loss_pct": _stage_effect_pct(
            ordinary_clip_downstream, conversion_downstream
        ),
        "e_grid_kwh": e_grid,
        "specific_yield_kwh_kwp": e_grid / float(installed_dc_kwp),
        "pr": (
            e_grid / (glob_inc * float(installed_dc_kwp))
            if glob_inc > 0
            else 0.0
        ),
        "monthly_e_grid_kwh": raw["monthly_e_grid_kwh"],
        "monthly_keys": raw["monthly_keys"],
        "e_array_kwh": raw["e_array_kwh"],
        "dc_operating_displacement_kwh": raw["dc_operating_displacement_kwh"],
        "inverter_subhourly_clipping_correction_kwh": raw[
            "inverter_subhourly_clipping_correction_kwh"
        ],
        "grid_energy_plus_reported_subhourly_correction_kwh": (
            e_grid + raw["inverter_subhourly_clipping_correction_kwh"]
        ),
    }


def detailed_hourly_case_from_output(
    output: PVsystDetailedOutput,
    base_case: Mapping[str, Any],
) -> dict[str, Any]:
    """Create a report-compatible case from the detailed CSV itself."""
    case = deepcopy(dict(base_case))
    installed = float(case["dc_nameplate_kwp_exact"])
    metrics = pvsyst_detailed_hourly_reference_metrics(
        output,
        installed_dc_kwp=installed,
    )
    case["report_filename"] = str(output.source.get("filename") or "pvsyst-output.csv")
    case["report_verified"] = True
    case["targets"] = {
        "annual": {
            "glob_hor_kwh_m2": metrics["glob_hor_kwh_m2"],
            "diff_hor_kwh_m2": metrics["diff_hor_kwh_m2"],
            "ambient_temp_c": metrics["ambient_temp_c"],
            "glob_inc_kwh_m2": metrics["glob_inc_kwh_m2"],
            "glob_eff_kwh_m2": metrics["glob_eff_kwh_m2"],
            "e_array_kwh": metrics["e_array_kwh"],
            "e_grid_kwh": metrics["e_grid_kwh"],
            "specific_yield_kwh_kwp": metrics["specific_yield_kwh_kwp"],
            "pr": metrics["pr"],
        },
        "monthly_e_array_kwh": [],
        "monthly_e_grid_kwh": metrics["monthly_e_grid_kwh"],
        "loss_diagram": {
            "array_nominal_energy_kwh": metrics["array_nominal_energy_kwh"],
            "irradiance_level_loss_pct": metrics["irradiance_level_loss_pct"],
            "temperature_loss_pct": metrics["temperature_loss_pct"],
            "module_quality_effect_pct": metrics["module_quality_effect_pct"],
            "mismatch_loss_pct": metrics["mismatch_loss_pct"],
            "dc_wiring_loss_pct": metrics["dc_wiring_loss_pct"],
            "array_virtual_mpp_kwh": metrics["array_virtual_mpp_kwh"],
            "inverter_conversion_loss_pct": metrics[
                "inverter_conversion_loss_pct"
            ],
            "inverter_clipping_loss_pct": metrics["inverter_clipping_loss_pct"],
            "inverter_output_kwh": metrics["e_grid_kwh"],
        },
    }
    return case


def pvsyst_azimuth_to_canonical(azimuth_deg: Any) -> np.ndarray:
    """Convert PVsyst solar azimuth (east negative/west positive) to 0=N,90=E."""
    values = np.asarray(azimuth_deg, dtype=float)
    return np.mod(-values, 360.0)


def _aligned_standard_frame(
    output: PVsystDetailedOutput,
    standard_timeseries: pd.DataFrame,
) -> pd.DataFrame:
    if "timestamp" not in standard_timeseries:
        raise ValueError("standard result requires timestamp for interval attribution")
    observed = standard_timeseries.copy()
    timestamps = pd.DatetimeIndex(pd.to_datetime(observed["timestamp"]))
    if timestamps.tz is not None:
        timestamps = timestamps.tz_localize(None)
    reference = pd.DatetimeIndex(output.frame["date"])
    if len(timestamps) != len(reference) or not timestamps.equals(reference):
        raise ValueError(
            "OpenSIMPV and PVsyst detailed intervals must align exactly in local wall time"
        )
    observed.index = reference
    return observed


def _linear_stats(observed: np.ndarray, reference: np.ndarray) -> dict[str, Any]:
    error = observed - reference
    absolute = np.abs(error)
    return {
        "sample_count": int(len(error)),
        "mean_bias": float(np.mean(error)),
        "mae": float(np.mean(absolute)),
        "rmse": float(sqrt(float(np.mean(error * error)))),
        "max_abs": float(np.max(absolute)) if len(absolute) else 0.0,
        "p50_abs": float(np.quantile(absolute, 0.50)) if len(absolute) else 0.0,
        "p95_abs": float(np.quantile(absolute, 0.95)) if len(absolute) else 0.0,
        "p99_abs": float(np.quantile(absolute, 0.99)) if len(absolute) else 0.0,
    }


def _circular_stats(observed: np.ndarray, reference: np.ndarray) -> dict[str, Any]:
    error = (observed - reference + 180.0) % 360.0 - 180.0
    absolute = np.abs(error)
    return {
        "sample_count": int(len(error)),
        "mean_bias": float(np.mean(error)),
        "mae": float(np.mean(absolute)),
        "rmse": float(sqrt(float(np.mean(error * error)))),
        "max_abs": float(np.max(absolute)) if len(absolute) else 0.0,
        "p95_abs": float(np.quantile(absolute, 0.95)) if len(absolute) else 0.0,
    }

def detailed_hourly_grid_residual_decomposition(
    output: PVsystDetailedOutput,
    standard_timeseries: pd.DataFrame,
) -> dict[str, Any]:
    """Decompose final-grid residual so cancellation cannot masquerade as parity.

    The OpenSIMPV standard result does not contain a PVsyst ILPmxSH model.
    Therefore the PVsyst sub-hourly clipping correction enters the residual
    decomposition as an explicit missing-loss contribution rather than being
    merged into ordinary hourly clipping.

    Algebra:

      dE_grid =
          dEArrMPP
          - dConversionLoss
          - dOrdinaryClipping
          + PVsyst_ILPmxSH
          - dOtherLosses

    where OtherLosses contains all remaining EArrMPP-to-grid channels (night
    loss, voltage/power thresholds, etc.) after removing conversion, ordinary
    clipping, and ILPmxSH.
    """
    observed = _aligned_standard_frame(output, standard_timeseries)
    required = {
        "interval_seconds",
        "net_dc_power_w",
        "conversion_loss_w",
        "clipping_loss_w",
        "pcc_power_w",
    }
    missing = sorted(required - set(observed.columns))
    if missing:
        raise ValueError(
            "standard result lacks residual-decomposition columns: "
            + ", ".join(missing)
        )

    hours = (
        pd.to_numeric(observed["interval_seconds"], errors="raise").to_numpy(
            dtype=float
        )
        / 3600.0
    )
    if not np.isfinite(hours).all() or (hours <= 0).any():
        raise ValueError("interval_seconds must be finite and positive")

    def integrate(column: str) -> float:
        values = pd.to_numeric(observed[column], errors="raise").to_numpy(
            dtype=float
        )
        if not np.isfinite(values).all():
            raise ValueError(f"{column} contains non-finite values")
        return float(np.sum(values * hours) / 1000.0)

    reference = extract_pvsyst_hourly_oracle_metrics(output)

    observed_earr_mpp = integrate("net_dc_power_w")
    observed_conversion = integrate("conversion_loss_w")
    observed_clipping = integrate("clipping_loss_w")
    observed_grid = integrate("pcc_power_w")
    observed_other = (
        observed_earr_mpp
        - observed_grid
        - observed_conversion
        - observed_clipping
    )

    reference_earr_mpp = float(reference["array_virtual_mpp_kwh"])
    reference_conversion = float(reference["inverter_conversion_loss_kwh"])
    reference_clipping = float(reference["inverter_hourly_clipping_loss_kwh"])
    reference_ilpmxsh = float(
        reference["inverter_subhourly_clipping_correction_kwh"]
    )
    reference_grid = float(reference["e_grid_kwh"])
    reference_other = (
        reference_earr_mpp
        - reference_grid
        - reference_conversion
        - reference_clipping
        - reference_ilpmxsh
    )

    components = {
        "array_virtual_mpp": {
            "observed_kwh": observed_earr_mpp,
            "reference_kwh": reference_earr_mpp,
            "delta_kwh": observed_earr_mpp - reference_earr_mpp,
            "grid_delta_contribution_kwh": (
                observed_earr_mpp - reference_earr_mpp
            ),
        },
        "conversion_loss": {
            "observed_kwh": observed_conversion,
            "reference_kwh": reference_conversion,
            "delta_kwh": observed_conversion - reference_conversion,
            "grid_delta_contribution_kwh": -(
                observed_conversion - reference_conversion
            ),
        },
        "ordinary_hourly_clipping": {
            "observed_kwh": observed_clipping,
            "reference_kwh": reference_clipping,
            "delta_kwh": observed_clipping - reference_clipping,
            "grid_delta_contribution_kwh": -(
                observed_clipping - reference_clipping
            ),
        },
        "pvsyst_subhourly_clipping_correction": {
            "observed_kwh": 0.0,
            "reference_kwh": reference_ilpmxsh,
            "delta_kwh": -reference_ilpmxsh,
            "grid_delta_contribution_kwh": reference_ilpmxsh,
            "model_status": "missing_from_opensimpv_named_difference",
        },
        "other_earr_mpp_to_grid_losses": {
            "observed_kwh": observed_other,
            "reference_kwh": reference_other,
            "delta_kwh": observed_other - reference_other,
            "grid_delta_contribution_kwh": -(
                observed_other - reference_other
            ),
        },
    }

    expected_delta = float(
        sum(
            float(item["grid_delta_contribution_kwh"])
            for item in components.values()
        )
    )
    actual_delta = observed_grid - reference_grid
    reconciliation = actual_delta - expected_delta
    gross = float(
        sum(
            abs(float(item["grid_delta_contribution_kwh"]))
            for item in components.values()
        )
    )
    cancellation_ratio = (
        abs(actual_delta) / gross
        if gross > 0
        else 0.0
    )

    return {
        "observed_grid_kwh": observed_grid,
        "reference_grid_kwh": reference_grid,
        "actual_grid_delta_kwh": actual_delta,
        "actual_grid_relative_error": (
            actual_delta / reference_grid if reference_grid else None
        ),
        "components": components,
        "expected_grid_delta_from_components_kwh": expected_delta,
        "reconciliation_residual_kwh": reconciliation,
        "gross_absolute_component_contribution_kwh": gross,
        "cancellation_ratio": cancellation_ratio,
        "cancellation_detected": bool(gross > 0 and cancellation_ratio < 0.25),
        "interpretation": (
            "Small final-grid residual can be caused by opposing upstream/model "
            "differences. A low cancellation_ratio must not be presented as "
            "stage-level parity."
        ),
    }



def detailed_hourly_interval_statistics(
    output: PVsystDetailedOutput,
    standard_timeseries: pd.DataFrame,
    *,
    irradiated_threshold_w_m2: float = 20.0,
) -> dict[str, Any]:
    """Compare interval-resolved stage boundaries exposed by both products."""
    observed = _aligned_standard_frame(output, standard_timeseries)
    reference = output.frame.set_index(pd.DatetimeIndex(output.frame["date"]))
    irradiated = reference["GlobHor"].to_numpy(dtype=float) > float(
        irradiated_threshold_w_m2
    )

    mappings = {
        "poa_global": ("poa_global_w_m2", "GlobInc", 1.0, "W/m2"),
        "effective_irradiance": (
            "effective_irradiance_w_m2",
            "GlobEff",
            1.0,
            "W/m2",
        ),
        "module_temperature": ("cell_temperature_c", "TArray", 1.0, "degC"),
        "array_virtual_mpp": ("net_dc_power_w", "EArrMPP", 0.001, "kW"),
        "grid_power": ("pcc_power_w", "E_Grid", 0.001, "kW"),
    }

    metrics: dict[str, Any] = {}
    for name, (observed_column, reference_column, scale, unit) in mappings.items():
        if observed_column not in observed or reference_column not in reference:
            metrics[name] = {
                "status": "not_comparable",
                "reason": "required_column_missing",
            }
            continue
        obs = pd.to_numeric(observed[observed_column], errors="raise").to_numpy(
            dtype=float
        ) * scale
        ref = pd.to_numeric(reference[reference_column], errors="raise").to_numpy(
            dtype=float
        )
        stats = _linear_stats(obs, ref)
        stats.update({"status": "compared", "unit": unit})
        metrics[name] = stats

    angle_mappings = {
        "solar_elevation": ("solar_elevation_deg", "HSol", False),
        "solar_azimuth": ("solar_azimuth_deg", "AzSol", True),
        "incidence_angle": ("aoi_deg", "AngInc", False),
    }
    for name, (observed_column, reference_column, circular) in angle_mappings.items():
        if observed_column not in observed or reference_column not in reference:
            metrics[name] = {
                "status": "not_comparable",
                "reason": "required_column_missing",
            }
            continue
        obs = pd.to_numeric(observed[observed_column], errors="raise").to_numpy(
            dtype=float
        )[irradiated]
        ref = pd.to_numeric(reference[reference_column], errors="raise").to_numpy(
            dtype=float
        )[irradiated]
        if name == "solar_azimuth":
            ref = pvsyst_azimuth_to_canonical(ref)
        stats = _circular_stats(obs, ref) if circular else _linear_stats(obs, ref)
        stats.update(
            {
                "status": "compared",
                "unit": "deg",
                "mask": f"GlobHor>{float(irradiated_threshold_w_m2):g} W/m2",
            }
        )
        metrics[name] = stats

    return {
        "alignment": "exact_local_wall_time",
        "irradiated_threshold_w_m2": float(irradiated_threshold_w_m2),
        "metrics": metrics,
    }


def build_pvsyst_detailed_hourly_attribution_report(
    output: PVsystDetailedOutput,
    simulation_run: Mapping[str, Any],
    standard_timeseries: pd.DataFrame,
    module_definition: Mapping[str, Any],
    *,
    module_count: int,
    campaign: Mapping[str, Any] | None = None,
    case_id: str | None = None,
) -> dict[str, Any]:
    """Build the detailed hourly acceptance report from one external PVsyst CSV."""
    campaign = campaign or load_pvsyst_attribution_campaign()
    resolved_case_id = case_id or output.metadata.get("variant_id")
    if not resolved_case_id or resolved_case_id not in campaign["cases"]:
        raise ValueError("PVsyst detailed output does not resolve to a campaign case")
    base_case = campaign["cases"][resolved_case_id]
    if int(base_case["simulation_timestep_seconds"]) != 3600:
        raise ValueError("detailed hourly attribution requires an hourly campaign case")
    if int(base_case["modules_total"]) != int(module_count):
        raise ValueError("module_count does not match the selected campaign case")

    balance = validate_hourly_oracle_balance(output)
    if balance["status"] != "passed":
        raise ValueError("PVsyst detailed oracle failed interval balance validation")

    detailed_case = detailed_hourly_case_from_output(output, base_case)
    observed = extract_opensimpv_attribution_metrics(
        simulation_run,
        standard_timeseries,
        module_definition,
        module_count=module_count,
    )
    acceptance = build_pvsyst_attribution_report(
        detailed_case,
        observed,
        campaign=campaign,
        same_interval_weather_series=True,
        verified_subhourly_perez_coefficients=False,
        pvsyst_detailed_timestep_export_available=True,
    )
    interval = detailed_hourly_interval_statistics(output, standard_timeseries)
    residual_decomposition = detailed_hourly_grid_residual_decomposition(
        output,
        standard_timeseries,
    )
    reference = pvsyst_detailed_hourly_reference_metrics(
        output,
        installed_dc_kwp=float(base_case["dc_nameplate_kwp_exact"]),
    )
    ilpmxsh, ilpmxsh_meta = infer_subhourly_clipping_correction(output)
    ilpmxsh_kwh = float(ilpmxsh.sum())

    return {
        "schema_name": DETAILED_HOURLY_REPORT_SCHEMA_NAME,
        "schema_version": DETAILED_HOURLY_REPORT_SCHEMA_VERSION,
        "oracle": {
            "oracle_id": "P39-HR1-PVSYST816-20260923",
            "case_id": resolved_case_id,
            "source_filename": output.source.get("filename"),
            "source_sha256": output.source.get("sha256"),
            "source_byte_size": output.source.get("byte_size"),
            "weather_filename": output.metadata.get("weather_filename"),
            "simulation_date": output.metadata.get("simulation_date"),
            "row_count": output.metadata.get("row_count"),
            "simulation_timestep_seconds": output.metadata.get("interval_seconds"),
        },
        "oracle_balance": balance,
        "reference_metrics": reference,
        "observed_metrics": observed,
        "acceptance_report": acceptance,
        "interval_statistics": interval,
        "grid_residual_decomposition": residual_decomposition,
        "subhourly_clipping_boundary": {
            "pvsyst_ilpmxsh_kwh": ilpmxsh_kwh,
            "provenance": ilpmxsh_meta,
            "opensimpv_model_status": "not_implemented_named_difference",
            "ordinary_hourly_clipping_reference_metric": "IL_Pmax",
            "final_grid_reference_metric": "E_Grid",
            "grid_energy_plus_reported_subhourly_correction_kwh": reference[
                "grid_energy_plus_reported_subhourly_correction_kwh"
            ],
            "counterfactual_warning": (
                "E_Grid + ILPmxSH is an attribution aid, not an exact rerun without "
                "sub-hourly correction because inverter conversion can depend on "
                "the displaced DC operating point."
            ),
        },
    }
