"""S15: the run time-series view and monthly table, read from a verified run package (no new physics).

Everything comes from the package's stored hourly `timeseries.parquet` (already verified by `csv_export.load_source`)
and its `summary-result.json`. Months are integrated with the engine's own `aggregate_interval_quantities` on the
site-local timestamps, so they are the engine's months; each result is reconciled against the summary before it is
returned, and a mismatch is refused rather than shown.
"""

from __future__ import annotations

from math import isclose, isfinite
from typing import Any

import pandas as pd

from engine.losses.energy import aggregate_interval_quantities
from engine.losses.staged import NEW_CHANNELS, OPTICAL_CHANNELS
from engine.losses.ledger import with_current_limit, with_orientation_mismatch

from .csv_export import ExportSource
from .csv_cells import csv_cell

SERIES_VERSION = "0.1"
# Day × hour matrices: id → (stored column, divisor, unit, label).
HOURLY = {
    "ac_kw": ("pcc_power_w", 1000.0, "kW", "PCC AC power"),
    "poa_w_m2": ("poa_global_w_m2", 1.0, "W/m²", "Plane-of-array global irradiance"),
    "ghi_w_m2": ("ghi_w_m2", 1.0, "W/m²", "Global horizontal irradiance"),
    "cell_temperature_c": ("cell_temperature_c", 1.0, "°C", "Cell temperature"),
    "ambient_temperature_c": ("ambient_temperature_c", 1.0, "°C", "Ambient temperature"),
}
MONTHLY_COLUMNS = (
    ("month", "Site-local month", "YYYY-MM"),
    ("energy_kwh", "PCC energy", "kWh"),
    ("poa_unshaded_kwh_m2", "Unshaded plane-of-array irradiation", "kWh/m²"),
    ("ghi_kwh_m2", "Global horizontal irradiation", "kWh/m²"),
    ("specific_yield_kwh_kwp", "Specific yield", "kWh/kWp"),
    ("performance_ratio", "Performance ratio (energy ÷ kWp × unshaded POA)", "1"),
)
TOLERANCE = 1e-6


def _channels(frame: pd.DataFrame) -> list[tuple[str, str]]:
    """Staged-ledger channel → its stored loss column, in ledger order (plant AC wiring and the MPPT current limit
    when present)."""
    rows = [(name, loss) for name, loss, _, _ in with_current_limit(with_orientation_mismatch((*OPTICAL_CHANNELS, *NEW_CHANNELS), frame), frame)]
    if "plant_ac_wiring_loss_w" in frame:
        at = next(i for i, (name, _) in enumerate(rows) if name == "ac_wiring") + 1
        rows.insert(at, ("plant_ac_wiring", "plant_ac_wiring_loss_w"))
    return rows


def _close(a: float, b: float) -> bool:
    return isclose(a, b, rel_tol=TOLERANCE, abs_tol=TOLERANCE)


def _value(x: Any, *, digits: int | None = 6) -> float | None:
    if x is None or pd.isna(x) or not isfinite(float(x)):
        return None
    return float(x) if digits is None else round(float(x), digits)


def monthly(source: ExportSource, summary: dict[str, Any], *, full_precision: bool = False) -> dict[str, Any]:
    """The run's monthly table and loss channels, reconciled against its summary."""
    value = lambda x: _value(x, digits=None if full_precision else 6)
    frame = source.frame.set_index("timestamp")
    poa = "poa_global_unshaded_w_m2" if "poa_global_unshaded_w_m2" in frame else "poa_global_w_m2"
    channels = _channels(frame)
    stored = [(name, column) for name, column in channels if column in frame]
    energy = aggregate_interval_quantities(
        frame, interval_seconds=frame["interval_seconds"].to_numpy(dtype=float),
        power_columns_w=["pcc_power_w", *(column for _, column in stored)],
        irradiance_columns_w_m2=[c for c in (poa, "ghi_w_m2") if c in frame],
    )
    total_wh = float(summary["total_energy_wh"])
    yield_wh_wp = float(summary.get("specific_yield_wh_per_wp") or 0.0)
    dc_kwp = total_wh / yield_wh_wp / 1000.0 if total_wh > 0 and yield_wh_wp > 0 else None
    dc_kwp_basis = "run summary: total energy ÷ specific yield (the engine's installed DC nameplate)"
    if dc_kwp is None:
        nameplate = (summary.get("resolved_loss_settings") or {}).get("simulated_dc_nameplate_w")
        if nameplate is None:
            nameplate = (summary.get("execution_breakdown") or {}).get("simulated_dc_nameplate_w")
        if nameplate is not None and isfinite(float(nameplate)) and float(nameplate) > 0:
            dc_kwp = float(nameplate) / 1000.0
            dc_kwp_basis = "run summary: recorded simulated DC nameplate"

    # Reconcile against the summary: total and monthly energy, then every stored loss channel.
    if not _close(float(energy.annual["pcc_power_kwh"]) * 1000.0, total_wh):
        raise ValueError("stored series energy does not reconcile with the run summary")
    expected = {str(m["month"]): float(m["energy_wh"]) for m in summary.get("monthly_energy") or []}
    got = {str(month): float(row["pcc_power_kwh"]) * 1000.0 for month, row in energy.monthly.iterrows()}
    if set(expected) != set(got) or any(not _close(got[m], expected[m]) for m in expected):
        raise ValueError("stored series monthly energy does not reconcile with the run summary")
    lost = {str(item["loss_type"]): float(item["lost_energy_wh"]) for item in summary.get("loss_summary") or []}
    for name, column in stored:
        if name in lost and not _close(float(energy.annual[column.replace("_w", "_kwh")]) * 1000.0, lost[name]):
            raise ValueError(f"stored loss channel {name} does not reconcile with the run summary")

    rows = []
    for month, row in energy.monthly.iterrows():
        kwh = float(row["pcc_power_kwh"])
        poa_kwh = float(row[poa.replace("_w_m2", "_kwh_m2")]) if poa in frame else None
        rows.append({
            "month": str(month),
            "energy_kwh": value(kwh),
            "poa_unshaded_kwh_m2": value(poa_kwh),
            "ghi_kwh_m2": value(row["ghi_kwh_m2"]) if "ghi_w_m2" in frame else None,
            "specific_yield_kwh_kwp": value(kwh / dc_kwp) if dc_kwp else None,
            "performance_ratio": value(kwh / (dc_kwp * poa_kwh)) if dc_kwp and poa_kwh else None,
            "losses_kwh": {name: value(row[column.replace("_w", "_kwh")]) for name, column in stored},
        })
    stages = {str(item["loss_type"]): str(item.get("stage") or "") for item in summary.get("loss_summary") or []}
    return {
        "dc_kwp": value(dc_kwp),
        "dc_kwp_basis": dc_kwp_basis,
        "pr_basis": f"energy ÷ (dc_kwp × {poa.replace('_w_m2', '')} irradiation), as the engine's annual PR",
        "monthly": rows,
        "loss_channels": [{"loss_type": name, "stage": stages.get(name, ""), "monthly": column in frame}
                          for name, column in channels if name in lost or column in frame],
    }


def run_series(source: ExportSource, summary: dict[str, Any]) -> dict[str, Any]:
    """Day × hour matrices in site-local time, plus the monthly table."""
    stamps = source.frame["timestamp"]
    dates = stamps.dt.strftime("%Y-%m-%d")
    hours = stamps.dt.hour
    days = sorted(dates.unique())
    position = {d: i for i, d in enumerate(days)}
    repeated = int(pd.DataFrame({"d": dates, "h": hours}).duplicated().sum())
    hourly: dict[str, Any] = {}
    for key, (column, divisor, unit, label) in HOURLY.items():
        if column not in source.frame:
            continue
        values = pd.DataFrame({"d": dates, "h": hours, "v": pd.to_numeric(source.frame[column], errors="coerce") / divisor})
        # A repeated local hour (daylight-saving fall-back) is averaged; a missing one stays null.
        cells = values.groupby(["d", "h"])["v"].mean()
        matrix: list[list[float | None]] = [[None] * 24 for _ in days]
        for (d, h), v in cells.items():
            matrix[position[d]][int(h)] = _value(v)
        hourly[key] = {"label": label, "unit": unit, "source_column": column, "values": matrix}
    table = monthly(source, summary)
    return {
        "schema_name": "RunTimeSeriesView",
        "schema_version": SERIES_VERSION,
        "project_id": source.project_id,
        "run_id": source.run["simulation_run_id"],
        "timezone": str(stamps.dt.tz),
        "timestamp_convention": "interval_start",
        "interval_seconds": 3600,
        "period": {"start": stamps.iloc[0].isoformat(), "end": (stamps.iloc[-1] + pd.Timedelta(hours=1)).isoformat(),
                   "hours": int(len(stamps))},
        "days": days,
        "hourly": hourly,
        "quality": {"repeated_local_hours_averaged": repeated,
                    "missing_hour_cells": sum(1 for m in hourly.values() for row in m["values"] for v in row if v is None) // max(len(hourly), 1)},
        **table,
    }


def monthly_csv(table: dict[str, Any]) -> bytes:
    """The monthly table as CSV, with every stored loss channel as a kWh column (17 significant digits)."""
    import csv
    from io import StringIO

    channels = [c["loss_type"] for c in table["loss_channels"] if c["monthly"]]
    known = {row[0] for row in (*OPTICAL_CHANNELS, *NEW_CHANNELS)} | {"mppt_current_limit", "orientation_mismatch", "plant_ac_wiring"}
    if set(channels) - known:
        raise ValueError("unsupported monthly CSV loss channel")
    out = StringIO(newline="")
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow([c for c, _, _ in MONTHLY_COLUMNS] + [f"loss_{c}_kwh" for c in channels])
    for row in table["monthly"]:
        cells = [row["month"]] + [row[c] for c, _, _ in MONTHLY_COLUMNS[1:]] + [row["losses_kwh"].get(c) for c in channels]
        writer.writerow([csv_cell(v) for v in cells])
    return out.getvalue().encode("utf-8")


def monthly_columns(table: dict[str, Any]) -> list[dict[str, str]]:
    channels = [c["loss_type"] for c in table["loss_channels"] if c["monthly"]]
    return [{"id": c, "label": label, "unit": unit} for c, label, unit in MONTHLY_COLUMNS] + [
        {"id": f"loss_{c}_kwh", "label": f"{c.replace('_', ' ').capitalize()} loss", "unit": "kWh"} for c in channels]
