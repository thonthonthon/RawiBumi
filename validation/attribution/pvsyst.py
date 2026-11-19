"""PVsyst 8.1.6 stage-by-stage attribution for Phase 3.9.

The attribution layer deliberately separates:

- source/report verification;
- input/model readiness;
- numerical comparison;
- causal attribution.

A numerical difference is never automatically assigned to a cause. The earliest
non-passing comparable stage is reported, while known implementation differences
are listed only as candidates requiring evidence.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite, sqrt
from pathlib import Path
from typing import Any, Mapping

import numpy as np
import pandas as pd
import pvlib
import yaml

from components.pan.pvsyst_sdm import calculate_pvsyst_diode_parameters
from engine.module import extract_validated_pvsyst_parameter_set


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PHASE39_CAMPAIGN_PATH = (
    ROOT / "tests/benchmarks/phase39_pvsyst_v816_attribution.yaml"
)


@dataclass(frozen=True)
class AttributionReadiness:
    status: str
    acceptance_admissible: bool
    blockers: tuple[dict[str, Any], ...]


def load_pvsyst_attribution_campaign(
    path: str | Path = DEFAULT_PHASE39_CAMPAIGN_PATH,
) -> dict[str, Any]:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("Phase 3.9 attribution campaign must be a YAML object")
    return data


def _finite(value: Any, name: str) -> float:
    result = float(value)
    if not isfinite(result):
        raise ValueError(f"{name} must be finite")
    return result


def _relative_error(observed: float, reference: float) -> float | None:
    if reference == 0.0:
        return None
    return (observed - reference) / reference


def _within_mixed_tolerance(
    observed: float,
    reference: float,
    *,
    relative: float | None = None,
    absolute: float | None = None,
) -> bool:
    delta = abs(observed - reference)
    checks: list[bool] = []
    if absolute is not None:
        checks.append(delta <= float(absolute))
    if relative is not None and reference != 0.0:
        checks.append(delta / abs(reference) <= float(relative))
    if not checks:
        raise ValueError("at least one tolerance must be supplied")
    # Mixed tolerances are alternatives: near-zero references may use absolute,
    # while material values may satisfy the relative threshold.
    return any(checks)


def validate_pvsyst_reference_campaign(
    campaign: Mapping[str, Any],
) -> dict[str, Any]:
    """Validate report-level invariants without comparing OpenSIMPV outputs."""
    cases = campaign.get("cases") or {}
    if set(cases) != {f"VC{i}" for i in range(8)}:
        raise ValueError("Phase 3.9 reference campaign must contain VC0..VC7")

    findings: list[dict[str, Any]] = []
    for case_id, case in cases.items():
        targets = case["targets"]
        annual = targets["annual"]
        loss = targets["loss_diagram"]
        monthly_grid = targets["monthly_e_grid_kwh"]
        monthly_array = targets["monthly_e_array_kwh"]

        if len(monthly_grid) != 12 or len(monthly_array) != 12:
            findings.append(
                {
                    "case_id": case_id,
                    "rule_id": "P39_REFERENCE_MONTH_COUNT",
                    "severity": "error",
                    "message": "Reference case must contain 12 monthly values.",
                }
            )

        # Reports display monthly energy as integer kWh, so annual/monthly sums
        # are permitted the same small rounding residual frozen in Phase 3.
        if abs(sum(monthly_grid) - annual["e_grid_kwh"]) > 2:
            findings.append(
                {
                    "case_id": case_id,
                    "rule_id": "P39_REFERENCE_GRID_ANNUAL_RECONCILIATION",
                    "severity": "error",
                    "message": "Displayed monthly E_Grid does not reconcile with annual rounding.",
                }
            )
        if abs(sum(monthly_array) - annual["e_array_kwh"]) > 2:
            findings.append(
                {
                    "case_id": case_id,
                    "rule_id": "P39_REFERENCE_EARRAY_ANNUAL_RECONCILIATION",
                    "severity": "error",
                    "message": "Displayed monthly EArray does not reconcile with annual rounding.",
                }
            )

        e_arr_mpp = float(loss["array_virtual_mpp_kwh"])
        e_array = float(annual["e_array_kwh"])
        e_grid = float(annual["e_grid_kwh"])
        if not (e_arr_mpp + 1e-9 >= e_array >= e_grid - 1e-9):
            findings.append(
                {
                    "case_id": case_id,
                    "rule_id": "P39_REFERENCE_ENERGY_ORDER",
                    "severity": "error",
                    "message": "Reference energy order must satisfy EArrMPP >= EArray >= E_Grid.",
                }
            )

        if abs(float(loss["inverter_output_kwh"]) - e_grid) > 1.0:
            findings.append(
                {
                    "case_id": case_id,
                    "rule_id": "P39_REFERENCE_INVERTER_OUTPUT_GRID",
                    "severity": "error",
                    "message": "Loss-diagram inverter output must reconcile with E_Grid.",
                }
            )

        if case.get("report_verified") is not True:
            findings.append(
                {
                    "case_id": case_id,
                    "rule_id": "P39_REFERENCE_REPORT_NOT_VERIFIED",
                    "severity": "error",
                    "message": "Reference report pages 4-5 have not been verified.",
                }
            )

    # Controlled pairs must share report-level weather/optical inputs within
    # each temporal mode; only DC loading changes.
    for parity, ids in (
        ("hourly", ("VC0", "VC2", "VC4", "VC6")),
        ("minute", ("VC1", "VC3", "VC5", "VC7")),
    ):
        baseline = cases[ids[0]]["targets"]["annual"]
        for case_id in ids[1:]:
            annual = cases[case_id]["targets"]["annual"]
            for metric in (
                "glob_hor_kwh_m2",
                "diff_hor_kwh_m2",
                "ambient_temp_c",
                "glob_inc_kwh_m2",
                "glob_eff_kwh_m2",
            ):
                if annual[metric] != baseline[metric]:
                    findings.append(
                        {
                            "case_id": case_id,
                            "rule_id": "P39_REFERENCE_CONTROLLED_INPUT_FAMILY",
                            "severity": "error",
                            "message": (
                                f"{parity} reference cases do not share {metric}."
                            ),
                        }
                    )

    clipping_hourly = [
        -float(cases[item]["targets"]["loss_diagram"]["inverter_clipping_loss_pct"])
        for item in ("VC0", "VC2", "VC4", "VC6")
    ]
    clipping_minute = [
        -float(cases[item]["targets"]["loss_diagram"]["inverter_clipping_loss_pct"])
        for item in ("VC1", "VC3", "VC5", "VC7")
    ]
    if clipping_hourly != sorted(clipping_hourly):
        findings.append(
            {
                "case_id": "hourly_family",
                "rule_id": "P39_REFERENCE_CLIPPING_MONOTONIC",
                "severity": "error",
                "message": "Hourly clipping must increase with DC/AC ratio.",
            }
        )
    if clipping_minute != sorted(clipping_minute):
        findings.append(
            {
                "case_id": "minute_family",
                "rule_id": "P39_REFERENCE_CLIPPING_MONOTONIC",
                "severity": "error",
                "message": "Minute clipping must increase with DC/AC ratio.",
            }
        )

    return {
        "status": "passed" if not findings else "failed",
        "finding_count": len(findings),
        "findings": findings,
    }


def assess_pvsyst_case_readiness(
    case: Mapping[str, Any],
    *,
    same_interval_weather_series: bool,
    verified_subhourly_perez_coefficients: bool,
    pvsyst_detailed_timestep_export_available: bool = False,
) -> AttributionReadiness:
    """Return whether a report comparison is admissible as an acceptance test."""
    blockers: list[dict[str, Any]] = []
    timestep = int(case["simulation_timestep_seconds"])

    if not same_interval_weather_series:
        blockers.append(
            {
                "blocker_id": "PVSYST_METEONORM9_INTERVAL_WEATHER_NOT_ALIGNED",
                "classification": "external_input_blocker",
                "message": (
                    "Acceptance requires the same interval weather series used by "
                    "the PVsyst case; report-level monthly/annual weather is not "
                    "sufficient to reconstruct it."
                ),
            }
        )

    if timestep < 3600 and not verified_subhourly_perez_coefficients:
        blockers.append(
            {
                "blocker_id": "PVSYST81_SUBHOURLY_PEREZ_COEFFICIENTS_UNVERIFIED",
                "classification": "external_coefficient_data_blocker",
                "message": (
                    "Minute acceptance requires the timestep-specific PVsyst 8.1 "
                    "production Perez coefficients."
                ),
            }
        )

    if not blockers:
        return AttributionReadiness(
            status=(
                "acceptance_ready_with_interval_attribution"
                if pvsyst_detailed_timestep_export_available
                else "acceptance_ready_annual_monthly_only"
            ),
            acceptance_admissible=True,
            blockers=(),
        )

    classifications = {item["classification"] for item in blockers}
    if len(classifications) > 1:
        status = "blocked_multiple_external_dependencies"
    elif "external_input_blocker" in classifications:
        status = "blocked_external_input"
    else:
        status = "blocked_external_model_data"
    return AttributionReadiness(
        status=status,
        acceptance_admissible=False,
        blockers=tuple(blockers),
    )


def _integrate_power_kwh(values_w: np.ndarray, hours: np.ndarray) -> float:
    return float(np.sum(values_w * hours) / 1000.0)


def _integrate_irradiance_kwh_m2(
    values_w_m2: np.ndarray,
    hours: np.ndarray,
) -> float:
    return float(np.sum(values_w_m2 * hours) / 1000.0)


def _weighted_average(values: np.ndarray, hours: np.ndarray) -> float:
    denominator = float(np.sum(hours))
    if denominator <= 0:
        raise ValueError("executed duration must be positive")
    return float(np.sum(values * hours) / denominator)


def _pvsyst_module_pmp_w(
    effective_irradiance_w_m2: np.ndarray,
    cell_temperature_c: np.ndarray,
    *,
    parameter_set: Mapping[str, Any],
    solver: str = "lambertw",
) -> np.ndarray:
    effective = np.asarray(effective_irradiance_w_m2, dtype=float)
    temperature = np.asarray(cell_temperature_c, dtype=float)
    if effective.shape != temperature.shape:
        raise ValueError("irradiance and temperature arrays must align")
    if not np.isfinite(effective).all() or not np.isfinite(temperature).all():
        raise ValueError("module attribution inputs must be finite")
    if (effective < 0).any():
        raise ValueError("effective irradiance must be non-negative")

    result = np.zeros_like(effective, dtype=float)
    active = effective > 1e-9
    if active.any():
        diode = calculate_pvsyst_diode_parameters(
            effective_irradiance_w_m2=effective[active],
            cell_temperature_c=temperature[active],
            parameter_set=dict(parameter_set),
        )
        solved = pvlib.pvsystem.singlediode(*diode, method=solver)
        result[active] = np.asarray(solved["p_mp"], dtype=float)
    if not np.isfinite(result).all() or (result < -1e-9).any():
        raise RuntimeError("PVsyst attribution SDM produced invalid Pmp")
    return np.maximum(result, 0.0)


def _stage_effect_pct(downstream: float, upstream: float) -> float:
    if upstream == 0.0:
        return 0.0 if downstream == 0.0 else float("nan")
    return (downstream / upstream - 1.0) * 100.0


def extract_opensimpv_attribution_metrics(
    simulation_run: Mapping[str, Any],
    standard_timeseries: pd.DataFrame,
    module_definition: Mapping[str, Any],
    *,
    module_count: int,
    module_solver: str = "lambertw",
) -> dict[str, Any]:
    """Extract PVsyst-report-comparable metrics from a canonical OpenSIMPV run.

    The function reconstructs the PVsyst loss-diagram module sequence explicitly:

    effective irradiance -> model STC nominal -> low-light at 25 C -> actual
    temperature -> module quality -> mismatch -> DC wiring -> EArrMPP equivalent.

    It intentionally does not manufacture a PVsyst EArray equivalent because the
    current OpenSIMPV inverter clipping model does not back-propagate operating-point
    displacement into the DC array.
    """
    if module_count < 1:
        raise ValueError("module_count must be >= 1")
    if simulation_run.get("status") not in {"completed", "completed_with_warnings"}:
        raise ValueError("attribution requires a completed SimulationRun")

    frame = standard_timeseries.copy()
    required = {
        "timestamp",
        "interval_seconds",
        "ghi_w_m2",
        "dhi_w_m2",
        "ambient_temperature_c",
        "poa_global_w_m2",
        "effective_irradiance_w_m2",
        "cell_temperature_c",
        "gross_dc_power_w",
        "module_quality_loss_w",
        "mismatch_loss_w",
        "dc_wiring_loss_w",
        "net_dc_power_w",
        "inverter_input_power_w",
        "conversion_loss_w",
        "clipping_loss_w",
        "pcc_power_w",
    }
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError(
            "standard result lacks Phase-3.9 attribution columns: "
            + ", ".join(missing)
        )

    seconds = pd.to_numeric(frame["interval_seconds"], errors="raise").to_numpy(
        dtype=float
    )
    if not np.isfinite(seconds).all() or (seconds <= 0).any():
        raise ValueError("interval_seconds must be finite and positive")
    hours = seconds / 3600.0

    def column(name: str) -> np.ndarray:
        values = pd.to_numeric(frame[name], errors="raise").to_numpy(dtype=float)
        if not np.isfinite(values).all():
            raise ValueError(f"{name} contains non-finite values")
        return values

    effective = column("effective_irradiance_w_m2")
    actual_temp = column("cell_temperature_c")
    parameter_set = extract_validated_pvsyst_parameter_set(dict(module_definition))

    stc_pmp_w = float(
        _pvsyst_module_pmp_w(
            np.array([1000.0]),
            np.array([25.0]),
            parameter_set=parameter_set,
            solver=module_solver,
        )[0]
    )
    pmp_25c_w = _pvsyst_module_pmp_w(
        effective,
        np.full(len(frame), 25.0, dtype=float),
        parameter_set=parameter_set,
        solver=module_solver,
    )

    nominal_array_w = effective / 1000.0 * stc_pmp_w * module_count
    array_25c_w = pmp_25c_w * module_count

    e_nominal = _integrate_power_kwh(nominal_array_w, hours)
    e_25c = _integrate_power_kwh(array_25c_w, hours)
    e_raw = _integrate_power_kwh(column("gross_dc_power_w"), hours)

    quality_loss_kwh = _integrate_power_kwh(column("module_quality_loss_w"), hours)
    mismatch_loss_kwh = _integrate_power_kwh(column("mismatch_loss_w"), hours)
    wiring_loss_kwh = _integrate_power_kwh(column("dc_wiring_loss_w"), hours)
    e_after_quality = e_raw - quality_loss_kwh
    e_before_wiring = e_after_quality - mismatch_loss_kwh
    e_arr_mpp = _integrate_power_kwh(column("net_dc_power_w"), hours)

    e_inverter_input = _integrate_power_kwh(column("inverter_input_power_w"), hours)
    conversion_loss_kwh = _integrate_power_kwh(column("conversion_loss_w"), hours)
    clipping_loss_kwh = _integrate_power_kwh(column("clipping_loss_w"), hours)
    e_ac_unclipped = e_inverter_input - conversion_loss_kwh
    e_ac_available = e_ac_unclipped - clipping_loss_kwh
    e_grid = _integrate_power_kwh(column("pcc_power_w"), hours)

    ghi = _integrate_irradiance_kwh_m2(column("ghi_w_m2"), hours)
    dhi = _integrate_irradiance_kwh_m2(column("dhi_w_m2"), hours)
    glob_inc = _integrate_irradiance_kwh_m2(column("poa_global_w_m2"), hours)
    glob_eff = _integrate_irradiance_kwh_m2(effective, hours)
    ambient = _weighted_average(column("ambient_temperature_c"), hours)

    stc = module_definition.get("stc") or {}
    nominal_w = stc.get("nominal_power_w", stc.get("pmp_w"))
    if nominal_w is None:
        raise ValueError("module definition requires STC nominal power")
    installed_dc_kwp = float(nominal_w) * module_count / 1000.0
    specific_yield = e_grid / installed_dc_kwp
    pr = e_grid / (glob_inc * installed_dc_kwp) if glob_inc > 0 else 0.0

    timestamps = pd.DatetimeIndex(pd.to_datetime(frame["timestamp"], utc=False))
    if timestamps.tz is None:
        raise ValueError("standard result timestamps must remain timezone-aware")
    interval_grid_kwh = column("pcc_power_w") * hours / 1000.0
    monthly_series = pd.Series(interval_grid_kwh, index=timestamps).groupby(
        timestamps.strftime("%Y-%m")
    ).sum()

    threshold_effect_pct = _stage_effect_pct(e_inverter_input, e_arr_mpp)
    self_consumption_effect_pct = _stage_effect_pct(e_grid, e_ac_available)

    return {
        "glob_hor_kwh_m2": ghi,
        "diff_hor_kwh_m2": dhi,
        "ambient_temp_c": ambient,
        "glob_inc_kwh_m2": glob_inc,
        "glob_eff_kwh_m2": glob_eff,
        "model_stc_pmp_w_per_module": stc_pmp_w,
        "array_nominal_energy_kwh": e_nominal,
        "irradiance_level_loss_pct": _stage_effect_pct(e_25c, e_nominal),
        "temperature_loss_pct": _stage_effect_pct(e_raw, e_25c),
        "module_quality_effect_pct": _stage_effect_pct(e_after_quality, e_raw),
        "mismatch_loss_pct": _stage_effect_pct(e_before_wiring, e_after_quality),
        "dc_wiring_loss_pct": _stage_effect_pct(e_arr_mpp, e_before_wiring),
        "array_virtual_mpp_kwh": e_arr_mpp,
        "dc_threshold_effect_pct": threshold_effect_pct,
        "inverter_conversion_loss_pct": _stage_effect_pct(
            e_ac_unclipped,
            e_inverter_input,
        ),
        "inverter_clipping_loss_pct": _stage_effect_pct(
            e_ac_available,
            e_ac_unclipped,
        ),
        "inverter_self_consumption_effect_pct": self_consumption_effect_pct,
        "e_grid_kwh": e_grid,
        "specific_yield_kwh_kwp": specific_yield,
        "pr": pr,
        "monthly_e_grid_kwh": [float(value) for value in monthly_series.to_numpy()],
        "monthly_keys": [str(value) for value in monthly_series.index],
        "pvsyst_e_array_kwh": None,
        "pvsyst_e_array_mapping_status": "not_comparable_dc_operating_feedback_not_modelled",
    }


def pvsyst_reference_metrics(case: Mapping[str, Any]) -> dict[str, Any]:
    annual = case["targets"]["annual"]
    loss = case["targets"]["loss_diagram"]
    return {
        "glob_hor_kwh_m2": float(annual["glob_hor_kwh_m2"]),
        "diff_hor_kwh_m2": float(annual["diff_hor_kwh_m2"]),
        "ambient_temp_c": float(annual["ambient_temp_c"]),
        "glob_inc_kwh_m2": float(annual["glob_inc_kwh_m2"]),
        "glob_eff_kwh_m2": float(annual["glob_eff_kwh_m2"]),
        "array_nominal_energy_kwh": float(loss["array_nominal_energy_kwh"]),
        "irradiance_level_loss_pct": float(loss["irradiance_level_loss_pct"]),
        "temperature_loss_pct": float(loss["temperature_loss_pct"]),
        "module_quality_effect_pct": float(loss["module_quality_effect_pct"]),
        "mismatch_loss_pct": float(loss["mismatch_loss_pct"]),
        "dc_wiring_loss_pct": float(loss["dc_wiring_loss_pct"]),
        "array_virtual_mpp_kwh": float(loss["array_virtual_mpp_kwh"]),
        "inverter_conversion_loss_pct": float(
            loss["inverter_conversion_loss_pct"]
        ),
        "inverter_clipping_loss_pct": float(loss["inverter_clipping_loss_pct"]),
        "e_grid_kwh": float(annual["e_grid_kwh"]),
        "specific_yield_kwh_kwp": float(annual["specific_yield_kwh_kwp"]),
        "pr": float(annual["pr"]),
        "monthly_e_grid_kwh": [
            float(value) for value in case["targets"]["monthly_e_grid_kwh"]
        ],
        "e_array_kwh": float(annual["e_array_kwh"]),
        "dc_operating_displacement_kwh": float(loss["array_virtual_mpp_kwh"])
        - float(annual["e_array_kwh"]),
    }


_METRIC_RULES = (
    ("weather", "glob_hor_kwh_m2", "weather_annual", "energy"),
    ("weather", "diff_hor_kwh_m2", "weather_annual", "energy"),
    ("poa_transposition", "glob_inc_kwh_m2", "poa_annual", "energy"),
    (
        "iam_effective_irradiance",
        "glob_eff_kwh_m2",
        "effective_irradiance_annual",
        "energy",
    ),
    ("module_nominal", "array_nominal_energy_kwh", "array_nominal_energy", "energy"),
    (
        "irradiance_level",
        "irradiance_level_loss_pct",
        "stage_loss_percentage_points",
        "percentage_point",
    ),
    (
        "temperature",
        "temperature_loss_pct",
        "stage_loss_percentage_points",
        "percentage_point",
    ),
    (
        "module_quality",
        "module_quality_effect_pct",
        "stage_loss_percentage_points",
        "percentage_point",
    ),
    (
        "mismatch",
        "mismatch_loss_pct",
        "stage_loss_percentage_points",
        "percentage_point",
    ),
    (
        "dc_wiring",
        "dc_wiring_loss_pct",
        "stage_loss_percentage_points",
        "percentage_point",
    ),
    ("array_virtual_mpp", "array_virtual_mpp_kwh", "array_virtual_mpp", "energy"),
    (
        "inverter_conversion",
        "inverter_conversion_loss_pct",
        "stage_loss_percentage_points",
        "percentage_point",
    ),
    (
        "inverter_clipping",
        "inverter_clipping_loss_pct",
        "stage_loss_percentage_points",
        "percentage_point",
    ),
    ("grid_energy", "e_grid_kwh", "grid_energy", "energy"),
    ("performance_ratio", "pr", "performance_ratio", "absolute"),
    ("grid_energy", "specific_yield_kwh_kwp", "specific_yield", "energy"),
)


def _metric_tolerance(
    policy: Mapping[str, Any],
    key: str,
) -> dict[str, Any]:
    tolerance = dict(policy["acceptance_tolerances"][key])
    return tolerance


def _compare_metric(
    *,
    stage: str,
    metric: str,
    observed: float,
    reference: float,
    tolerance_name: str,
    tolerance: Mapping[str, Any],
    kind: str,
    admissible: bool,
) -> dict[str, Any]:
    delta = observed - reference
    rel = _relative_error(observed, reference)

    if kind == "percentage_point":
        passed = abs(delta) <= float(tolerance["absolute"])
    elif kind == "absolute":
        passed = abs(delta) <= float(tolerance["absolute"])
    else:
        absolute = next(
            (float(value) for key, value in tolerance.items() if key.startswith("absolute_")),
            None,
        )
        passed = _within_mixed_tolerance(
            observed,
            reference,
            relative=(
                float(tolerance["relative"])
                if tolerance.get("relative") is not None
                else None
            ),
            absolute=absolute,
        )

    return {
        "stage": stage,
        "metric": metric,
        "reference_value": reference,
        "observed_value": observed,
        "delta": delta,
        "relative_error": rel,
        "tolerance_id": tolerance_name,
        "tolerance": dict(tolerance),
        "admissible": admissible,
        "status": (
            "not_admissible" if not admissible else ("pass" if passed else "fail")
        ),
    }


def _monthly_grid_comparison(
    observed: list[float],
    reference: list[float],
    *,
    tolerance: Mapping[str, Any],
    admissible: bool,
) -> dict[str, Any]:
    if len(observed) != 12 or len(reference) != 12:
        return {
            "status": "not_comparable",
            "reason": "monthly_grid_requires_12_calendar_months",
        }
    relative: list[float] = []
    for obs, ref in zip(observed, reference):
        if ref == 0.0:
            relative.append(0.0 if obs == 0.0 else float("inf"))
        else:
            relative.append((obs - ref) / ref)
    rms = sqrt(sum(value * value for value in relative) / len(relative))
    maximum = max(abs(value) for value in relative)
    passed = (
        rms <= float(tolerance["rms_relative"])
        and maximum <= float(tolerance["maximum_absolute_relative"])
    )
    return {
        "status": (
            "not_admissible" if not admissible else ("pass" if passed else "fail")
        ),
        "rms_relative_error": rms,
        "maximum_absolute_relative_error": maximum,
        "relative_errors": relative,
        "tolerance": dict(tolerance),
    }


def build_pvsyst_attribution_report(
    case: Mapping[str, Any],
    observed_metrics: Mapping[str, Any] | None,
    *,
    campaign: Mapping[str, Any],
    same_interval_weather_series: bool,
    verified_subhourly_perez_coefficients: bool,
    pvsyst_detailed_timestep_export_available: bool = False,
) -> dict[str, Any]:
    """Build one report-level attribution result without inventing causality."""
    readiness = assess_pvsyst_case_readiness(
        case,
        same_interval_weather_series=same_interval_weather_series,
        verified_subhourly_perez_coefficients=verified_subhourly_perez_coefficients,
        pvsyst_detailed_timestep_export_available=(
            pvsyst_detailed_timestep_export_available
        ),
    )
    reference = pvsyst_reference_metrics(case)
    policy = campaign["comparison_policy"]

    comparisons: list[dict[str, Any]] = []
    monthly = None
    if observed_metrics is not None:
        for stage, metric, tolerance_name, kind in _METRIC_RULES:
            if metric not in observed_metrics:
                comparisons.append(
                    {
                        "stage": stage,
                        "metric": metric,
                        "reference_value": reference[metric],
                        "observed_value": None,
                        "delta": None,
                        "relative_error": None,
                        "tolerance_id": tolerance_name,
                        "tolerance": _metric_tolerance(policy, tolerance_name),
                        "admissible": False,
                        "status": "not_comparable",
                    }
                )
                continue
            comparisons.append(
                _compare_metric(
                    stage=stage,
                    metric=metric,
                    observed=_finite(observed_metrics[metric], metric),
                    reference=_finite(reference[metric], metric),
                    tolerance_name=tolerance_name,
                    tolerance=_metric_tolerance(policy, tolerance_name),
                    kind=kind,
                    admissible=readiness.acceptance_admissible,
                )
            )

        monthly = _monthly_grid_comparison(
            [float(value) for value in observed_metrics.get("monthly_e_grid_kwh", [])],
            reference["monthly_e_grid_kwh"],
            tolerance=policy["acceptance_tolerances"]["monthly_grid"],
            admissible=readiness.acceptance_admissible,
        )

    first_nonpassing_stage = None
    if readiness.acceptance_admissible and observed_metrics is not None:
        for item in comparisons:
            if item["status"] == "fail":
                first_nonpassing_stage = item["stage"]
                break
        if first_nonpassing_stage is None and monthly and monthly["status"] == "fail":
            first_nonpassing_stage = "monthly_grid_energy"

    if observed_metrics is None:
        acceptance_status = "not_executed"
    elif not readiness.acceptance_admissible:
        acceptance_status = "not_admissible"
    elif first_nonpassing_stage is None:
        acceptance_status = "pass"
    else:
        acceptance_status = "fail"

    known_candidates = []
    for item in campaign.get("known_differences") or []:
        applies = item.get("applies_to")
        timestep = int(case["simulation_timestep_seconds"])
        if applies == "all" or (applies == "minute" and timestep < 3600) or (
            applies == "hourly" and timestep == 3600
        ):
            known_candidates.append(dict(item))

    return {
        "schema_name": "PVsystAttributionReport",
        "schema_version": "0.1",
        "campaign_id": campaign["campaign_id"],
        "case_id": next(
            key
            for key, value in campaign["cases"].items()
            if value.get("benchmark_id") == case.get("benchmark_id")
        ),
        "benchmark_id": case["benchmark_id"],
        "reference_software": "PVsyst 8.1.6",
        "reference_report": case["report_filename"],
        "simulation_timestep_seconds": int(case["simulation_timestep_seconds"]),
        "readiness_status": readiness.status,
        "acceptance_admissible": readiness.acceptance_admissible,
        "acceptance_status": acceptance_status,
        "blockers": list(readiness.blockers),
        "metric_comparisons": comparisons,
        "monthly_grid_comparison": monthly,
        "first_nonpassing_stage": first_nonpassing_stage,
        "attribution_status": (
            "unresolved_requires_evidence"
            if first_nonpassing_stage is not None
            else "no_causal_claim"
        ),
        "known_difference_candidates": known_candidates,
        "excluded_reference_metrics": {
            "e_array_kwh": reference["e_array_kwh"],
            "reason": policy["pvsyst_e_array_reason"],
            "dc_operating_displacement_kwh": reference[
                "dc_operating_displacement_kwh"
            ],
        },
    }
