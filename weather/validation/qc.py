"""Deterministic Phase-2 weather quality control.

The checks here intentionally avoid solar-geometry-dependent tests so this layer remains
usable before the simulation engine. Phase-3 solar-aware checks are implemented separately
in weather.validation.solar_qc and consume the same SolarPositionResult used by simulation.
"""

from __future__ import annotations

from collections import Counter
from typing import Any

import pandas as pd

from weather.core import CanonicalWeather


ERROR_SEVERITIES = {"error", "blocking_error"}


def _finding(
    rule_id: str,
    severity: str,
    category: str,
    message: str,
    *,
    variable: str | None = None,
    count: int | None = None,
    examples: list[str] | None = None,
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "rule_id": rule_id,
        "severity": severity,
        "category": category,
        "message": message,
        "variable": variable,
        "count": count,
        "examples": examples or [],
        "context": context or {},
    }


def _example_times(mask: pd.Series, limit: int = 5) -> list[str]:
    return [
        pd.Timestamp(value).isoformat()
        for value in mask.index[mask.fillna(False)][:limit]
    ]


def _numeric_mask(series: pd.Series, predicate) -> pd.Series:
    numeric = pd.to_numeric(series, errors="coerce")
    return predicate(numeric) & numeric.notna()


def _irradiance_completion_finding(data: pd.DataFrame) -> dict[str, Any] | None:
    """Summarize DNI/DHI completion needs without generating missing values."""
    if "ghi_w_m2" not in data:
        return None

    ghi = pd.to_numeric(data["ghi_w_m2"], errors="coerce")
    ghi_available = ghi.notna()
    eligible_count = int(ghi_available.sum())
    total_intervals = int(len(data))
    components: dict[str, dict[str, Any]] = {}
    union_completion_mask = pd.Series(False, index=data.index)
    missing_components: list[str] = []

    for variable in ("dni_w_m2", "dhi_w_m2"):
        if variable not in data:
            missing = pd.Series(True, index=data.index)
            availability = "absent"
            column_present = False
        else:
            missing = data[variable].isna()
            column_present = True
            availability = "partial" if missing.any() else "complete"

        completion_mask = missing & ghi_available
        missing_count = int(missing.sum())
        completion_count = int(completion_mask.sum())
        if availability != "complete":
            missing_components.append(variable)
            union_completion_mask |= completion_mask

        components[variable] = {
            "availability": availability,
            "column_present": column_present,
            "missing_count": missing_count,
            "missing_fraction": (
                missing_count / total_intervals if total_intervals else 0.0
            ),
            "completion_count": completion_count,
            "completion_fraction_of_ghi_available": (
                completion_count / eligible_count if eligible_count else 0.0
            ),
            "examples": _example_times(completion_mask),
        }

    if not missing_components:
        return None

    intervals_requiring_completion = int(union_completion_mask.sum())
    if intervals_requiring_completion == 0:
        return None

    completion_scope = (
        "full_ghi_available_series"
        if eligible_count > 0 and intervals_requiring_completion == eligible_count
        else "partial_intervals"
    )

    return _finding(
        "WX_IRRADIANCE_DECOMPOSITION_REQUIRED",
        "warning",
        "irradiance",
        (
            "GHI is available but DNI and/or DHI are absent or incomplete. Phase 3 "
            "must apply and record an explicit irradiance decomposition/completion "
            "model only for the affected intervals."
        ),
        count=intervals_requiring_completion,
        examples=_example_times(union_completion_mask),
        context={
            "total_intervals": total_intervals,
            "ghi_available_intervals": eligible_count,
            "intervals_requiring_completion": intervals_requiring_completion,
            "completion_scope": completion_scope,
            "missing_components": missing_components,
            "components": components,
        },
    )


def run_weather_qc(weather: CanonicalWeather) -> dict[str, Any]:
    data = weather.series
    dataset = weather.dataset
    findings: list[dict[str, Any]] = []

    if not isinstance(data.index, pd.DatetimeIndex) or data.index.tz is None:
        findings.append(
            _finding(
                "WX_TIMEZONE_MISSING",
                "blocking_error",
                "time",
                "Canonical weather timestamps must be timezone-aware.",
            )
        )

    duplicate_mask = data.index.duplicated(keep=False)
    if duplicate_mask.any():
        examples = [
            pd.Timestamp(value).isoformat()
            for value in data.index[duplicate_mask][:5]
        ]
        findings.append(
            _finding(
                "WX_DUPLICATE_TIMESTAMPS",
                "error",
                "time",
                "Duplicate interval-start timestamps are present.",
                count=int(duplicate_mask.sum()),
                examples=examples,
            )
        )

    if not data.index.is_monotonic_increasing:
        findings.append(
            _finding(
                "WX_TIMESTAMPS_NOT_MONOTONIC",
                "error",
                "time",
                "Weather timestamps are not monotonically increasing.",
            )
        )

    expected_seconds = int(dataset["series_resolution_seconds"])
    # S10 stores the requested local period even when the response covers less.
    # Other importers continue to use their existing coverage/QC semantics.
    local_window_trim = any(
        item.get("transformation_type") == "timezone_normalization"
        and item.get("algorithm") == "local_window_trim"
        for item in dataset.get("transformations", [])
    )
    if local_window_trim and isinstance(data.index, pd.DatetimeIndex) and data.index.tz is not None:
        window_start = pd.Timestamp(dataset["start_time"]).tz_convert(dataset["timezone"])
        window_end = pd.Timestamp(dataset["end_time"]).tz_convert(dataset["timezone"])
        cadence = pd.Timedelta(seconds=expected_seconds)
        # Keep the source cadence's phase: UTC-hourly rows can be at :30/:45
        # locally. An empty retained window uses the provider's UTC-hour grid.
        origin = data.index.min() if len(data.index) else pd.Timestamp(0, tz="UTC")
        first_expected = window_start + (origin - window_start) % cadence
        expected = pd.date_range(
            first_expected,
            window_end,
            freq=cadence,
            inclusive="left",
        )
        # Count only boundary gaps here; internal gaps retain the rule below.
        missing_boundary = expected if not len(data.index) else expected[
            (expected < data.index.min()) | (expected > data.index.max())
        ]
        if len(missing_boundary):
            findings.append(_finding(
                "WX_TIME_GAPS",
                "error",
                "time",
                "The requested local window has missing leading or trailing intervals.",
                count=len(missing_boundary),
                examples=[value.isoformat() for value in missing_boundary[:5]],
                context={
                    "expected_resolution_seconds": expected_seconds,
                    "missing_boundary_intervals": len(missing_boundary),
                },
            ))
    if len(data.index) > 1 and data.index.is_monotonic_increasing:
        diffs = data.index.to_series().diff().dt.total_seconds()
        gap_mask = diffs > expected_seconds + 1e-9
        short_mask = (diffs < expected_seconds - 1e-9) & diffs.notna()
        if gap_mask.any():
            findings.append(
                _finding(
                    "WX_TIME_GAPS",
                    "error",
                    "time",
                    "One or more intervals are missing from the expected cadence.",
                    count=int(gap_mask.sum()),
                    examples=_example_times(gap_mask),
                    context={"expected_resolution_seconds": expected_seconds},
                )
            )
        if short_mask.any():
            findings.append(
                _finding(
                    "WX_IRREGULAR_OR_OVERLAPPING_INTERVALS",
                    "error",
                    "time",
                    "One or more timestamp steps are shorter than the declared cadence.",
                    count=int(short_mask.sum()),
                    examples=_example_times(short_mask),
                    context={"expected_resolution_seconds": expected_seconds},
                )
            )

    required_for_base = ("ghi_w_m2", "ambient_temperature_c")
    for variable in required_for_base:
        if variable not in data:
            findings.append(
                _finding(
                    f"WX_{variable.upper()}_MISSING",
                    "error",
                    "completeness",
                    f"{variable} is required for the Phase-3 horizontal-irradiance base pipeline.",
                    variable=variable,
                )
            )
        else:
            missing = data[variable].isna()
            if missing.any():
                findings.append(
                    _finding(
                        f"WX_{variable.upper()}_MISSING_VALUES",
                        "error",
                        "completeness",
                        f"{variable} contains missing values.",
                        variable=variable,
                        count=int(missing.sum()),
                        examples=_example_times(missing),
                    )
                )

    for variable in data.columns:
        if variable in required_for_base or variable in {"dni_w_m2", "dhi_w_m2"}:
            continue
        missing = data[variable].isna()
        if missing.any():
            findings.append(
                _finding(
                    "WX_OPTIONAL_VARIABLE_MISSING_VALUES",
                    "warning",
                    "completeness",
                    f"Optional variable {variable} contains missing values.",
                    variable=variable,
                    count=int(missing.sum()),
                    examples=_example_times(missing),
                )
            )

    irradiance_variables = [
        variable
        for variable in (
            "ghi_w_m2",
            "dni_w_m2",
            "dhi_w_m2",
            "poa_irradiance_w_m2",
        )
        if variable in data
    ]
    for variable in irradiance_variables:
        negative = _numeric_mask(data[variable], lambda values: values < 0)
        if negative.any():
            findings.append(
                _finding(
                    "WX_NEGATIVE_IRRADIANCE",
                    "error",
                    "irradiance",
                    "Irradiance cannot be negative in the canonical weather series.",
                    variable=variable,
                    count=int(negative.sum()),
                    examples=_example_times(negative),
                )
            )

        gross_high = _numeric_mask(data[variable], lambda values: values > 2000)
        if gross_high.any():
            findings.append(
                _finding(
                    "WX_IRRADIANCE_GROSS_HIGH",
                    "warning",
                    "irradiance",
                    (
                        "Irradiance exceeds the Phase-2 gross screening threshold of "
                        "2000 W/m2. Solar-geometry plausibility is deferred to Phase 3."
                    ),
                    variable=variable,
                    count=int(gross_high.sum()),
                    examples=_example_times(gross_high),
                    context={"gross_screening_threshold_w_m2": 2000},
                )
            )

    if "ghi_w_m2" in data and "dhi_w_m2" in data:
        ghi = pd.to_numeric(data["ghi_w_m2"], errors="coerce")
        dhi = pd.to_numeric(data["dhi_w_m2"], errors="coerce")
        mask = (dhi > ghi + 50.0) & ghi.notna() & dhi.notna()
        if mask.any():
            findings.append(
                _finding(
                    "WX_DHI_ABOVE_GHI",
                    "warning",
                    "irradiance",
                    (
                        "DHI exceeds GHI by more than 50 W/m2. Small departures may reflect "
                        "measurement uncertainty, but larger differences should be reviewed."
                    ),
                    count=int(mask.sum()),
                    examples=_example_times(mask),
                    context={"screening_margin_w_m2": 50.0},
                )
            )

    completion_finding = _irradiance_completion_finding(data)
    if completion_finding is not None:
        findings.append(completion_finding)

    if "ambient_temperature_c" in data:
        temp = pd.to_numeric(data["ambient_temperature_c"], errors="coerce")
        mask = ((temp < -90) | (temp > 70)) & temp.notna()
        if mask.any():
            findings.append(
                _finding(
                    "WX_AMBIENT_TEMPERATURE_GROSS_RANGE",
                    "warning",
                    "meteorology",
                    "Ambient temperature lies outside the Phase-2 gross range -90..70 degC.",
                    variable="ambient_temperature_c",
                    count=int(mask.sum()),
                    examples=_example_times(mask),
                )
            )

    if "wind_speed_m_s" in data:
        wind = pd.to_numeric(data["wind_speed_m_s"], errors="coerce")
        negative = (wind < 0) & wind.notna()
        if negative.any():
            findings.append(
                _finding(
                    "WX_NEGATIVE_WIND_SPEED",
                    "error",
                    "meteorology",
                    "Wind speed cannot be negative.",
                    variable="wind_speed_m_s",
                    count=int(negative.sum()),
                    examples=_example_times(negative),
                )
            )
        high = (wind > 75) & wind.notna()
        if high.any():
            findings.append(
                _finding(
                    "WX_WIND_SPEED_GROSS_HIGH",
                    "warning",
                    "meteorology",
                    "Wind speed exceeds the Phase-2 gross screening threshold of 75 m/s.",
                    variable="wind_speed_m_s",
                    count=int(high.sum()),
                    examples=_example_times(high),
                )
            )

    if "pressure_pa" in data:
        pressure = pd.to_numeric(data["pressure_pa"], errors="coerce")
        nonpositive = (pressure <= 0) & pressure.notna()
        if nonpositive.any():
            findings.append(
                _finding(
                    "WX_PRESSURE_NONPOSITIVE",
                    "error",
                    "meteorology",
                    "Atmospheric pressure must be positive.",
                    variable="pressure_pa",
                    count=int(nonpositive.sum()),
                    examples=_example_times(nonpositive),
                )
            )
        gross = ((pressure < 30000) | (pressure > 110000)) & pressure.notna()
        if gross.any():
            findings.append(
                _finding(
                    "WX_PRESSURE_GROSS_RANGE",
                    "warning",
                    "meteorology",
                    "Atmospheric pressure lies outside the Phase-2 gross range 30..110 kPa.",
                    variable="pressure_pa",
                    count=int(gross.sum()),
                    examples=_example_times(gross),
                )
            )

    for variable in ("albedo", "relative_humidity_fraction"):
        if variable in data:
            values = pd.to_numeric(data[variable], errors="coerce")
            invalid = ((values < 0) | (values > 1)) & values.notna()
            if invalid.any():
                findings.append(
                    _finding(
                        "WX_FRACTION_OUT_OF_RANGE",
                        "error",
                        "meteorology",
                        f"{variable} must lie within 0..1.",
                        variable=variable,
                        count=int(invalid.sum()),
                        examples=_example_times(invalid),
                    )
                )

    location = dataset.get("location") or {}
    latitude = location.get("latitude_deg")
    longitude = location.get("longitude_deg")
    if latitude is not None and not (-90 <= latitude <= 90):
        findings.append(
            _finding(
                "WX_LATITUDE_OUT_OF_RANGE",
                "error",
                "location",
                "Latitude must lie within -90..90 degrees.",
                context={"latitude_deg": latitude},
            )
        )
    if longitude is not None and not (-180 <= longitude <= 180):
        findings.append(
            _finding(
                "WX_LONGITUDE_OUT_OF_RANGE",
                "error",
                "location",
                "Longitude must lie within -180..180 degrees.",
                context={"longitude_deg": longitude},
            )
        )

    counts = Counter(item["severity"] for item in findings)
    has_errors = any(item["severity"] in ERROR_SEVERITIES for item in findings)
    base_ready = (
        not has_errors
        and "ghi_w_m2" in data
        and "ambient_temperature_c" in data
    )
    status = "failed" if has_errors else ("warning" if findings else "passed")

    report = {
        "schema_name": "WeatherQCReport",
        "schema_version": "0.1",
        "weather_dataset_id": dataset["weather_dataset_id"],
        "weather_revision_id": dataset["revision_id"],
        "status": status,
        "base_simulation_input_ready": base_ready,
        "finding_counts": {
            "blocking_error": counts.get("blocking_error", 0),
            "error": counts.get("error", 0),
            "warning": counts.get("warning", 0),
            "info": counts.get("info", 0),
        },
        "findings": findings,
    }
    return report


def attach_weather_qc(weather: CanonicalWeather) -> tuple[CanonicalWeather, dict[str, Any]]:
    """Return a copy with QC summary attached; source series are never mutated."""
    report = run_weather_qc(weather)
    result = weather.copy()
    result.dataset["data_quality_status"] = report["status"]
    result.dataset["qc_summary"] = {
        "status": report["status"],
        "base_simulation_input_ready": report["base_simulation_input_ready"],
        "finding_counts": report["finding_counts"],
    }
    return result, report
