"""Parser and canonical adapter for PVsyst detailed simulation output CSV files.

Phase 3.9H treats user-supplied PVsyst detailed output as an external validation
oracle. The raw source file remains external; OpenSIMPV records its byte hash and
derives a canonical weather series without silently changing the source values.

PVsyst time semantics:
- exported hourly timestamp = beginning of the interval;
- solar geometry represents the interval midpoint.

For the current hourly oracle, the source simulation uses a 1-minute MET file but
the detailed output is hourly. The canonical series therefore has 3600-second
resolution while upstream source-resolution provenance may record 60 seconds.
"""

from __future__ import annotations

from dataclasses import dataclass
import csv
from hashlib import sha256
from io import StringIO
from pathlib import Path
import re
from typing import Any, Mapping

import numpy as np
import pandas as pd

from weather.core import (
    CanonicalWeather,
    build_time_semantics,
    build_weather_dataset,
    fingerprint_source_bytes,
)


PVSYST_DETAILED_OUTPUT_FORMAT = "pvsyst_detailed_output_csv.v0.1"

REQUIRED_HOURLY_WEATHER_COLUMNS = (
    "GlobHor",
    "DiffHor",
    "T_Amb",
    "WindVel",
)

PVSYST_COMMON_INPUT_COLUMNS = (
    "date",
    "HSol",
    "AzSol",
    "AngInc",
    "AngProf",
    "GlobHor",
    "DiffHor",
    "BeamHor",
    "T_Amb",
    "WindVel",
    "GlobHorCS",
    "DiffHorCS",
    "BeamTrp",
    "DifITrp",
    "CircTrp",
    "HBndTrp",
    "AlbTrp",
    "GlobTrp",
    "GincThr",
    "GlobInc",
    "BeamInc",
    "CircInc",
    "DifSInc",
    "Alb_Inc",
    "Bm_Gl",
    "DifA_Gl",
    "DifS_Gl",
    "Alb_Gl",
    "GlobIAM",
    "IAMLoss",
    "IAMBLss",
    "IAMCLss",
    "IAMDLss",
    "IAMALss",
    "GlobEff",
    "BeamEff",
    "CircEff",
    "DiffEff",
    "Alb_Eff",
    "FTransp",
    "FIAMGl",
    "FIAMBm",
    "FIAMCrc",
    "FIAMDif",
    "FIAMAlb",
    "FIAMShd",
    "FEffDif",
    "FEffAlb",
)

_PVSYST_INVERTER_LOSS_CHANNELS_EXCEPT_SUBHOURLY = (
    "IL_Oper",
    "IL_Pmin",
    "IL_Vmin",
    "IL_Pmax",
    "IL_Vmax",
    "IL_Imax",
    "IL_Nigh",
)


@dataclass(frozen=True)
class PVsystDetailedOutput:
    """Parsed PVsyst detailed output plus source identity."""

    frame: pd.DataFrame
    units: dict[str, str]
    metadata: dict[str, Any]
    source: dict[str, Any]


def _read_source(source: str | Path | bytes) -> tuple[bytes, str]:
    if isinstance(source, bytes):
        return source, "pvsyst-output.csv"
    path = Path(source)
    return path.read_bytes(), path.name


def _decode(data: bytes) -> str:
    # PVsyst 8.1 can emit UTF-8 BOM CSV. utf-8-sig also accepts BOM-free UTF-8.
    return data.decode("utf-8-sig")


def _metadata_row(lines: list[str], label: str) -> list[str] | None:
    for line in lines:
        parsed = next(csv.reader([line]))
        if parsed and parsed[0].strip() == label:
            return parsed
    return None


def _value(row: list[str] | None, index: int) -> str | None:
    if row is None or len(row) <= index:
        return None
    value = row[index].strip()
    return value or None


def _extract_variant_id(filename: str | None) -> str | None:
    if not filename:
        return None
    match = re.search(r"\.(VC\d+)\b", filename, flags=re.IGNORECASE)
    return match.group(1).upper() if match else None


def parse_pvsyst_detailed_output(
    source: str | Path | bytes,
    *,
    file_id: str | None = None,
) -> PVsystDetailedOutput:
    """Parse a PVsyst detailed simulation-output CSV without mutating values."""
    data, filename = _read_source(source)
    text = _decode(data)
    lines = text.splitlines()
    if not lines or not lines[0].strip().startswith("PVSYST"):
        raise ValueError("source is not a recognizable PVsyst detailed output file")

    header_index = next(
        (index for index, line in enumerate(lines) if line.startswith("date,")),
        None,
    )
    if header_index is None:
        raise ValueError("PVsyst detailed output has no date/data header")
    if header_index + 1 >= len(lines):
        raise ValueError("PVsyst detailed output is missing the units row")

    headers = next(csv.reader([lines[header_index]]))
    units = next(csv.reader([lines[header_index + 1]]))
    if len(headers) != len(units):
        raise ValueError("PVsyst column and units rows have different lengths")
    if len(set(headers)) != len(headers):
        raise ValueError("PVsyst detailed output contains duplicate column names")

    body = "\n".join(lines[header_index:])
    frame = pd.read_csv(StringIO(body), low_memory=False)

    parsed_dates = pd.to_datetime(
        frame["date"].astype(str).str.strip(),
        format="%d/%m/%y %H:%M",
        errors="coerce",
    )
    frame = frame.loc[parsed_dates.notna()].copy()
    parsed_dates = parsed_dates.loc[parsed_dates.notna()]
    if frame.empty:
        raise ValueError("PVsyst detailed output contains no parseable data rows")
    frame["date"] = parsed_dates.to_numpy()

    for column in frame.columns:
        if column == "date":
            continue
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
        if frame[column].isna().any():
            raise ValueError(
                f"PVsyst detailed output column {column!r} contains non-numeric values"
            )
        if not np.isfinite(frame[column].to_numpy(dtype=float)).all():
            raise ValueError(
                f"PVsyst detailed output column {column!r} contains non-finite values"
            )

    dates = pd.DatetimeIndex(frame["date"])
    if not dates.is_monotonic_increasing or not dates.is_unique:
        raise ValueError("PVsyst detailed output timestamps must be unique and ordered")
    if len(dates) > 1:
        deltas = dates.to_series().diff().dropna().dt.total_seconds().to_numpy()
        if not np.all(deltas == deltas[0]):
            raise ValueError("PVsyst detailed output timestep is not regular")
        interval_seconds = int(deltas[0])
    else:
        interval_seconds = None

    project = _metadata_row(lines[:header_index], "Project")
    site = _metadata_row(lines[:header_index], "Geographical Site")
    weather = _metadata_row(lines[:header_index], "Weather data")
    variant = _metadata_row(lines[:header_index], "Simulation variant")
    simulation_date = _metadata_row(lines[:header_index], "Simulation date")
    simulation = _metadata_row(lines[:header_index], "Simulation:")

    variant_filename = _value(variant, 1)
    metadata = {
        "schema_name": "PVsystDetailedOutput",
        "schema_version": "0.1",
        "pvsyst_version": lines[0].strip().removeprefix("PVSYST ").strip(),
        "project_filename": _value(project, 1),
        "project_file_date": _value(project, 2),
        "project_description": _value(project, 3),
        "site_filename": _value(site, 1),
        "site_file_date": _value(site, 2),
        "site_description": _value(site, 3),
        "weather_filename": _value(weather, 1),
        "weather_file_date": _value(weather, 2),
        "weather_description": _value(weather, 3),
        "variant_filename": variant_filename,
        "variant_id": _extract_variant_id(variant_filename),
        "variant_file_date": _value(variant, 2),
        "variant_description": _value(variant, 3),
        "simulation_date": _value(simulation_date, 2),
        "simulation_value_type": _value(simulation, 1),
        "simulation_range_start": _value(simulation, 2),
        "simulation_range_end": _value(simulation, 3),
        "interval_seconds": interval_seconds,
        "row_count": len(frame),
        "column_count": len(frame.columns),
        "timestamp_convention": "interval_start",
        "solar_representative_time_policy": "interval_midpoint",
    }

    source_meta = fingerprint_source_bytes(
        data,
        file_id=file_id or f"sha256:{sha256(data).hexdigest()}",
        filename=filename,
        media_type="text/csv",
        attribution="user-supplied PVsyst validation oracle",
    )

    return PVsystDetailedOutput(
        frame=frame.reset_index(drop=True),
        units=dict(zip(headers, units)),
        metadata=metadata,
        source=source_meta,
    )


def infer_subhourly_clipping_correction(
    output: PVsystDetailedOutput,
    *,
    reconciliation_tolerance_kw: float = 0.002,
) -> tuple[pd.Series, dict[str, Any]]:
    """Return ILPmxSH directly or infer it from PVsyst's inverter-loss identity.

    PVsyst's inverter loss identity for the current grid-connected oracle is:

      InvLoss =
          IL_Oper + IL_Pmin + IL_Vmin + IL_Pmax
          + ILPmxSH + IL_Vmax + IL_Imax + IL_Nigh

    The inference is useful when ILPmxSH was not selected in the detailed-output
    template. When the direct column exists, it is cross-checked against the same
    identity rather than trusted silently.
    """
    frame = output.frame
    required = {"InvLoss", *_PVSYST_INVERTER_LOSS_CHANNELS_EXCEPT_SUBHOURLY}
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError(
            "cannot resolve ILPmxSH; PVsyst output is missing: " + ", ".join(missing)
        )

    inferred = frame["InvLoss"].astype(float).copy()
    for column in _PVSYST_INVERTER_LOSS_CHANNELS_EXCEPT_SUBHOURLY:
        inferred = inferred - frame[column].astype(float)
    inferred.name = "ILPmxSH"

    if "ILPmxSH" in frame:
        direct = frame["ILPmxSH"].astype(float)
        residual = direct - inferred
        max_abs = float(residual.abs().max())
        if max_abs > reconciliation_tolerance_kw:
            raise ValueError(
                "direct ILPmxSH does not reconcile with inverter-loss identity; "
                f"max residual={max_abs:.6f} kW"
            )
        result = direct.copy()
        method = "source_column"
    else:
        residual = pd.Series(np.zeros(len(frame)), index=frame.index)
        max_abs = 0.0
        result = inferred
        method = "inferred_from_inverter_loss_identity"

    return result, {
        "method": method,
        "reconciliation_tolerance_kw": float(reconciliation_tolerance_kw),
        "max_direct_vs_inferred_residual_kw": max_abs,
        "signed_loss_convention": "positive_loss",
    }


def validate_hourly_oracle_balance(
    output: PVsystDetailedOutput,
    *,
    power_tolerance_kw: float = 0.002,
) -> dict[str, Any]:
    """Validate the major PVsyst interval identities used by Phase 3.9H."""
    frame = output.frame
    required = {
        "EArrNom",
        "GIncLss",
        "TempLss",
        "ModQual",
        "MisLoss",
        "OhmLoss",
        "EArrMPP",
        "EArray",
        "InvLoss",
        "EOutInv",
        "E_Grid",
        "IL_Pmin",
        "IL_Vmin",
        "IL_Pmax",
        "IL_Vmax",
        "IL_Imax",
    }
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError(
            "PVsyst output lacks required balance columns: " + ", ".join(missing)
        )

    ilpmxsh, ilpmxsh_meta = infer_subhourly_clipping_correction(output)

    mixed_orientation_loss = (
        frame["MixLoss"]
        if "MixLoss" in frame.columns
        else pd.Series(np.zeros(len(frame)), index=frame.index)
    )
    expected_mpp = (
        frame["EArrNom"]
        - frame["GIncLss"]
        - frame["TempLss"]
        - frame["ModQual"]
        - frame["MisLoss"]
        - mixed_orientation_loss
        - frame["OhmLoss"]
    )
    mpp_residual = frame["EArrMPP"] - expected_mpp

    inverter_residual = frame["InvLoss"] - (frame["EArrMPP"] - frame["EOutInv"])

    # EArray is the PV-array power at the inverter-imposed DC operating point.
    # PVsyst IL_Pmin is a low-power inverter loss after that boundary: it is
    # included in InvLoss, but it does not displace EArray away from EArrMPP.
    displacement_channels = (
        frame["IL_Vmin"]
        + frame["IL_Pmax"]
        + ilpmxsh
        + frame["IL_Vmax"]
        + frame["IL_Imax"]
    )
    displacement_residual = (
        frame["EArrMPP"] - frame["EArray"] - displacement_channels
    )

    grid_residual = frame["E_Grid"] - frame["EOutInv"]

    maxima = {
        "array_mpp_balance_max_abs_kw": float(mpp_residual.abs().max()),
        "inverter_total_loss_balance_max_abs_kw": float(
            inverter_residual.abs().max()
        ),
        "dc_operating_displacement_balance_max_abs_kw": float(
            displacement_residual.abs().max()
        ),
        "grid_boundary_balance_max_abs_kw": float(grid_residual.abs().max()),
    }
    status = (
        "passed"
        if max(maxima.values(), default=0.0) <= float(power_tolerance_kw)
        else "failed"
    )
    return {
        "status": status,
        "power_tolerance_kw": float(power_tolerance_kw),
        "max_residuals": maxima,
        "subhourly_clipping_correction": ilpmxsh_meta,
        "mixed_orientation_loss": {
            "source_column_present": "MixLoss" in frame.columns,
            "column": "MixLoss" if "MixLoss" in frame.columns else None,
            "signed_loss_convention": "positive_loss",
        },
    }


def _integral(frame: pd.DataFrame, column: str, interval_hours: float) -> float:
    return float(frame[column].sum() * interval_hours)


def extract_pvsyst_hourly_oracle_metrics(
    output: PVsystDetailedOutput,
) -> dict[str, Any]:
    """Aggregate a detailed hourly PVsyst oracle without using report totals."""
    if output.metadata.get("interval_seconds") != 3600:
        raise ValueError("Phase 3.9H oracle extraction requires hourly output")

    frame = output.frame
    interval_hours = 1.0
    required = {
        "GlobHor",
        "DiffHor",
        "BeamHor",
        "T_Amb",
        "GlobInc",
        "GlobIAM",
        "GlobEff",
        "EArrRef",
        "EArrNom",
        "GIncLss",
        "TempLss",
        "ModQual",
        "MisLoss",
        "OhmLoss",
        "EArrMPP",
        "EArray",
        "InvLoss",
        "IL_Oper",
        "IL_Pmax",
        "EOutInv",
        "E_Grid",
        "TArray",
    }
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError(
            "PVsyst hourly oracle is missing required metrics: " + ", ".join(missing)
        )

    ilpmxsh, ilpmxsh_meta = infer_subhourly_clipping_correction(output)

    timestamps = pd.DatetimeIndex(frame["date"])
    monthly_grid = pd.Series(
        frame["E_Grid"].to_numpy(dtype=float),
        index=timestamps,
    ).groupby(timestamps.strftime("%Y-%m")).sum()

    return {
        "glob_hor_kwh_m2": _integral(frame, "GlobHor", interval_hours) / 1000.0,
        "diff_hor_kwh_m2": _integral(frame, "DiffHor", interval_hours) / 1000.0,
        "beam_hor_kwh_m2": _integral(frame, "BeamHor", interval_hours) / 1000.0,
        "ambient_temp_c": float(frame["T_Amb"].mean()),
        "glob_inc_kwh_m2": _integral(frame, "GlobInc", interval_hours) / 1000.0,
        "glob_iam_kwh_m2": _integral(frame, "GlobIAM", interval_hours) / 1000.0,
        "glob_eff_kwh_m2": _integral(frame, "GlobEff", interval_hours) / 1000.0,
        "array_reference_energy_kwh": _integral(frame, "EArrRef", interval_hours),
        "array_nominal_energy_kwh": _integral(frame, "EArrNom", interval_hours),
        "irradiance_level_loss_kwh": _integral(frame, "GIncLss", interval_hours),
        "temperature_loss_kwh": _integral(frame, "TempLss", interval_hours),
        "module_quality_loss_kwh": _integral(frame, "ModQual", interval_hours),
        "mismatch_loss_kwh": _integral(frame, "MisLoss", interval_hours),
        "mixed_orientation_loss_kwh": (
            _integral(frame, "MixLoss", interval_hours)
            if "MixLoss" in frame.columns
            else None
        ),
        "dc_wiring_loss_kwh": _integral(frame, "OhmLoss", interval_hours),
        "array_virtual_mpp_kwh": _integral(frame, "EArrMPP", interval_hours),
        "e_array_kwh": _integral(frame, "EArray", interval_hours),
        "dc_operating_displacement_kwh": _integral(
            frame.assign(_disp=frame["EArrMPP"] - frame["EArray"]),
            "_disp",
            interval_hours,
        ),
        "inverter_total_loss_kwh": _integral(frame, "InvLoss", interval_hours),
        "inverter_conversion_loss_kwh": _integral(frame, "IL_Oper", interval_hours),
        "inverter_hourly_clipping_loss_kwh": _integral(
            frame,
            "IL_Pmax",
            interval_hours,
        ),
        "inverter_subhourly_clipping_correction_kwh": float(
            ilpmxsh.sum() * interval_hours
        ),
        "inverter_output_kwh": _integral(frame, "EOutInv", interval_hours),
        "e_grid_kwh": _integral(frame, "E_Grid", interval_hours),
        "module_temperature_mean_c": float(frame["TArray"].mean()),
        "monthly_e_grid_kwh": [
            float(value) for value in monthly_grid.to_numpy(dtype=float)
        ],
        "monthly_keys": [str(value) for value in monthly_grid.index],
        "subhourly_clipping_correction_provenance": ilpmxsh_meta,
    }


def pvsyst_output_to_canonical_weather(
    output: PVsystDetailedOutput,
    *,
    weather_dataset_id: str,
    revision_id: str,
    site_id: str,
    timezone: str,
    location: Mapping[str, float],
    source_utc_offset_hours: float | None = None,
    upstream_weather_resolution_seconds: int | None = None,
) -> CanonicalWeather:
    """Build exact hourly horizontal weather inputs from a PVsyst output oracle.

    DNI is intentionally not copied or reconstructed here. OpenSIMPV receives the
    same horizontal GHI/DHI inputs and derives missing DNI from its own solar geometry,
    which keeps solar-position and transposition differences observable.
    """
    frame = output.frame
    missing = sorted(set(REQUIRED_HOURLY_WEATHER_COLUMNS) - set(frame.columns))
    if missing:
        raise ValueError(
            "PVsyst output cannot form canonical weather; missing: "
            + ", ".join(missing)
        )
    if output.metadata.get("interval_seconds") != 3600:
        raise ValueError("current Phase 3.9H weather adapter requires hourly output")

    index = pd.DatetimeIndex(frame["date"])
    if index.tz is None:
        index = index.tz_localize(timezone)
    else:
        index = index.tz_convert(timezone)

    series = pd.DataFrame(
        {
            "ghi_w_m2": frame["GlobHor"].to_numpy(dtype=float),
            "dhi_w_m2": frame["DiffHor"].to_numpy(dtype=float),
            "ambient_temperature_c": frame["T_Amb"].to_numpy(dtype=float),
            "wind_speed_m_s": frame["WindVel"].to_numpy(dtype=float),
        },
        index=index,
    )
    series.index.name = "interval_start"

    time_semantics = build_time_semantics(
        canonical_timezone=timezone,
        source_timestamp_convention="interval_start",
        native_interval_seconds=3600,
        current_interval_seconds=3600,
        source_timezone=timezone,
        source_utc_offset_hours=source_utc_offset_hours,
        source_reference_kind="provider_declared_time_reference",
        source_reference_offset_minutes=0.0,
        source_reference_applied_to_canonical_timestamp=True,
        source_reference_applied_to_solar_evaluation=False,
        solar_evaluation_offset_minutes=0.0,
        solar_evaluation_offset_source="pvsyst_interval_midpoint_convention",
    )

    upstream = None
    if upstream_weather_resolution_seconds is not None:
        upstream = {
            "provider": "PVsyst/Meteonorm",
            "synthetic": True,
            "base_resolution_seconds": int(upstream_weather_resolution_seconds),
            "method": "PVsyst detailed hourly output from source MET",
            "evidence": "source_metadata",
            "evidence_detail": output.metadata.get("weather_filename"),
        }

    return build_weather_dataset(
        series,
        weather_dataset_id=weather_dataset_id,
        revision_id=revision_id,
        name=f"PVsyst hourly oracle {output.metadata.get('variant_id') or ''}".strip(),
        site_id=site_id,
        timezone=timezone,
        native_resolution_seconds=3600,
        series_resolution_seconds=3600,
        source_id=output.metadata.get("weather_filename"),
        source_format=PVSYST_DETAILED_OUTPUT_FORMAT,
        source_timestamp_convention="interval_start",
        source_files=[output.source],
        location=dict(location),
        variable_metadata={
            "ghi_w_m2": {
                "source_variable": "GlobHor",
                "source_unit": output.units.get("GlobHor"),
            },
            "dhi_w_m2": {
                "source_variable": "DiffHor",
                "source_unit": output.units.get("DiffHor"),
            },
            "ambient_temperature_c": {
                "source_variable": "T_Amb",
                "source_unit": output.units.get("T_Amb"),
            },
            "wind_speed_m_s": {
                "source_variable": "WindVel",
                "source_unit": output.units.get("WindVel"),
            },
        },
        native_series_origin="provider_generated",
        series_origin="provider_generated",
        upstream_generation=upstream,
        time_semantics=time_semantics,
        extra_metadata={
            "source_metadata": {
                "pvsyst_detailed_output": output.metadata,
                "underlying_weather_resolution_seconds": (
                    int(upstream_weather_resolution_seconds)
                    if upstream_weather_resolution_seconds is not None
                    else None
                ),
            }
        },
    )


def common_input_logical_sha256(
    output: PVsystDetailedOutput,
    *,
    columns: tuple[str, ...] = PVSYST_COMMON_INPUT_COLUMNS,
) -> str:
    """Hash common weather/geometry/optical oracle columns deterministically."""
    missing = sorted(set(columns) - set(output.frame.columns))
    if missing:
        raise ValueError("common-input hash columns are missing: " + ", ".join(missing))

    digest = sha256()
    digest.update(b"opensimpv.pvsyst.common-input.v0.1\n")
    digest.update(("|".join(columns) + "\n").encode("utf-8"))
    for row in output.frame[list(columns)].itertuples(index=False, name=None):
        rendered: list[str] = []
        for value in row:
            if isinstance(value, pd.Timestamp):
                rendered.append(value.isoformat())
            elif isinstance(value, (float, np.floating)):
                rendered.append(format(float(value), ".17g"))
            else:
                rendered.append(str(value))
        digest.update(("\x1f".join(rendered) + "\n").encode("utf-8"))
    return digest.hexdigest()
