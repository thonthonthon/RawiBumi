"""Deterministic numerical exports from immutable, verified canonical packages."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from hashlib import sha256
from io import BytesIO, StringIO
import json
from math import isfinite
from pathlib import Path
from urllib.parse import unquote, urlsplit
from zipfile import ZIP_STORED, ZipFile, ZipInfo

import pandas as pd
import pyarrow
from jsonschema import ValidationError

from engine.simulation.artifacts import (
    canonical_json_bytes,
    dataframe_logical_sha256,
    verify_run_package,
)
from engine.simulation.canonical import _assert_output_schema
from .csv_cells import csv_cell


# Explicit subset of artifacts.build_standard_timeseries. Never infer units from
# suffixes or expose detailed MPPT columns added by detailed_downstream.
FIELDS = {
    "timestamp": ("Interval start", "ISO 8601"),
    "interval_seconds": ("Interval duration", "s"),
    "ghi_w_m2": ("Global horizontal irradiance", "W/m²"),
    "dni_w_m2": ("Direct normal irradiance", "W/m²"),
    "dhi_w_m2": ("Diffuse horizontal irradiance", "W/m²"),
    "ambient_temperature_c": ("Ambient temperature", "°C"),
    "wind_speed_m_s": ("Wind speed", "m/s"),
    "poa_beam_w_m2": ("Plane-of-array beam irradiance", "W/m²"),
    "poa_sky_diffuse_w_m2": ("Plane-of-array sky diffuse irradiance", "W/m²"),
    "poa_ground_diffuse_w_m2": ("Plane-of-array ground diffuse irradiance", "W/m²"),
    "poa_global_w_m2": ("Plane-of-array global irradiance", "W/m²"),
    "poa_global_unshaded_w_m2": ("Unshaded plane-of-array global irradiance", "W/m²"),
    "effective_irradiance_w_m2": ("Effective irradiance", "W/m²"),
    "module_temperature_c": ("Module temperature", "°C"),
    "cell_temperature_c": ("Cell temperature", "°C"),
    "gross_dc_power_w": ("Gross array DC MPP power", "W"),
    "net_dc_power_w": ("Array virtual MPP power after DC wiring", "W"),
    "inverter_input_power_w": ("DC power to inverter converter", "W"),
    "inverter_output_power_w": ("Net inverter AC output power", "W"),
    "pcc_power_w": ("PCC power (net inverter AC boundary)", "W"),
    "interval_energy_wh": ("PCC interval energy", "Wh"),
}
REQUIRED = {"timestamp", "interval_seconds"}


@dataclass(frozen=True)
class ExportSource:
    project_id: str
    run: dict
    reference: dict
    package: dict
    frame: pd.DataFrame
    columns: list[dict]

    def schema(self) -> dict:
        return {
            "project_id": self.project_id,
            "run_id": self.run["simulation_run_id"],
            "format": "csv", "resolution": "hourly", "level": "project",
            "row_count": len(self.frame),
            "timestamp_convention": "interval_start",
            "timezone": str(self.frame["timestamp"].dt.tz),
            "interval_seconds": 3600,
            "columns": self.columns,
        }


def load_source(directory: Path, *, project_id: str, run_id: str, saved: dict,
                require_hourly: bool = True) -> ExportSource:
    """Reuse canonical verification; additionally bind and decode its dataset ref.

    All reads stay in the selected package. Parquet is decoded from the exact
    bytes checked against both the completion manifest and ResultDatasetReference.
    """
    try:
        # The canonical verifier rejects lexical traversal; reject symlinks too,
        # before it opens any package artifact.
        if directory.is_symlink() or any(p.is_symlink() for p in directory.rglob("*")):
            raise ValueError("export source package must not contain symlinks")
        package = verify_run_package(directory)
        _assert_output_schema(package, "run-package-manifest.schema.json")
        run = json.loads((directory / "simulation-run.json").read_text(encoding="utf-8"))
        _assert_output_schema(run, "simulation-run.schema.json")
        if run["simulation_run_id"] != run_id or package["simulation_run_id"] != run_id:
            raise ValueError("run ID does not match verified package")
        if run["status"] not in {"completed", "completed_with_warnings"} or not run["completed_at"]:
            raise ValueError("CSV export requires a completed run")
        if saved.get("input_hash") != run.get("input_hash"):
            raise ValueError("saved run does not match verified package input hash")
        expected_package = (saved.get("detailed_electrical_shading") or {}).get("package_manifest_sha256")
        if expected_package and expected_package != package["manifest_payload_sha256"]:
            raise ValueError("run package does not match saved completion reference")
        reference = run.get("result_reference")
        _assert_output_schema(reference, "result-dataset-reference.schema.json")
        uri = urlsplit(reference["uri"])
        path = directory / "timeseries.parquet"
        if uri.scheme != "file" or uri.netloc or uri.query or uri.fragment or Path(unquote(uri.path)).resolve() != path.resolve():
            raise ValueError("result dataset URI must reference this run's timeseries.parquet")
        entry = next((a for a in package["artifacts"] if a["relative_path"] == "timeseries.parquet"), None)
        if entry is None or entry["role"] != "standard_timeseries":
            raise ValueError("standard dataset is absent from the completed package")
        raw = path.read_bytes()
        digest = sha256(raw).hexdigest()
        if any(r["sha256"] != digest or r["byte_size"] != len(raw) for r in (entry, reference)):
            raise ValueError("result dataset byte hash/size mismatch")
        frame = pd.read_parquet(BytesIO(raw), engine="pyarrow")
        if (list(frame.columns) != reference["columns"] or len(frame.columns) != reference["column_count"]
                or len(frame) != reference["row_count"] or not frame.columns.is_unique):
            raise ValueError("result dataset row/column reference mismatch")
        if dataframe_logical_sha256(frame) != reference["logical_content_sha256"]:
            raise ValueError("result dataset logical-content hash mismatch")
        reproduction = run.get("reproducibility_manifest")
        if not isinstance(reproduction, dict):
            raise ValueError("run has no reproducibility manifest")
        if json.loads((directory / "reproducibility-manifest.json").read_text()) != reproduction:
            raise ValueError("persisted reproducibility manifest does not match run")
        if (reproduction.get("result_file_sha256") != digest
                or reproduction.get("result_logical_content_sha256") != reference["logical_content_sha256"]):
            raise ValueError("reproducibility dataset identity mismatch")
        if not REQUIRED.issubset(frame.columns) or frame.empty:
            raise ValueError("dataset has no interpretable intervals")
        stamps = frame["timestamp"]
        if not isinstance(stamps.dtype, pd.DatetimeTZDtype) or stamps.isna().any():
            raise ValueError("stored timestamps must be timezone-aware and non-missing")
        if not stamps.is_monotonic_increasing or stamps.duplicated().any():
            raise ValueError("stored timestamps must be strictly increasing and unique")
        if (not pd.api.types.is_numeric_dtype(frame["interval_seconds"])
                or frame["interval_seconds"].isna().any()):
            raise ValueError("stored interval durations must be numeric and non-missing")
        if require_hourly and (not (stamps.diff().dropna() == pd.Timedelta(hours=1)).all()
                or not (frame["interval_seconds"] == 3600).all()
                or reproduction.get("simulation_timestep_seconds") != 3600
                or reproduction.get("working_weather_resolution_seconds") != 3600):
            raise ValueError("CSV export requires stored hourly intervals and hourly timestamp cadence")
        # Parquet may restore a fixed offset under a different timezone name.
        # Compare the declared zone's offset at each instant without changing
        # any stored/exported timestamp (also covers daylight-saving offsets).
        if any(pd.Timestamp(stamp.value, tz=reproduction["timezone"]).utcoffset() != stamp.utcoffset()
               for stamp in stamps):
            raise ValueError("stored timestamp timezone does not match source manifest")
        columns = []
        for name in frame.columns:
            if name not in FIELDS:
                continue
            if name != "timestamp":
                values = frame[name]
                if not pd.api.types.is_numeric_dtype(values) or pd.api.types.is_bool_dtype(values):
                    raise ValueError(f"export field is not numeric: {name}")
                if any(not isfinite(float(v)) for v in values.dropna()):
                    raise ValueError(f"export field contains infinite values: {name}")
            label, unit = FIELDS[name]
            columns.append({"id": name, "label": label, "unit": unit, "required": name in REQUIRED})
        return ExportSource(project_id, run, reference, package, frame, columns)
    except ValidationError as exc:
        raise ValueError(f"invalid persisted export source: {exc.message}") from exc
    except (OSError, KeyError, TypeError, AttributeError, IndexError, OverflowError, pyarrow.ArrowException) as exc:
        raise ValueError(f"export source is missing, unreadable or malformed: {exc}") from exc


@dataclass(frozen=True)
class Deliverable:
    """S15: the rest of the full export, already read from the verified package and the saved run record."""
    monthly: dict
    package_files: dict[str, bytes]
    run_record: dict
    # UNC1: the run's annual Pxx view, only when the project has an uncertainty ledger.
    annual_pxx: dict | None = None


_DESCRIPTIONS = {
    "timeseries.csv": "Hourly results, selected columns (CSV)",
    "timeseries.parquet": "Hourly results, selected columns (Parquet)",
    "monthly.csv": "Monthly energy, irradiation, specific yield, PR and staged-ledger losses (site-local months)",
    "summary-result.json": "Run summary, copied from the verified package",
    "design-validation-report.json": "Engineering design validation, copied from the verified package",
    "validation-findings.json": "Run validation findings, copied from the verified package",
    "run-record.json": "The project's saved run record, including the readiness warnings at launch",
    "annual-pxx.json": "Annual P50–P95 under the project's uncertainty ledger (model-based, assumption-based); P99 not qualified",
}


def _parquet_bytes(frame: pd.DataFrame) -> bytes:
    import pyarrow.parquet as pq

    out = BytesIO()
    pq.write_table(pyarrow.Table.from_pandas(frame, preserve_index=False), out, compression="zstd")
    return out.getvalue()


def _zip(files: list[tuple[str, bytes]]) -> bytes:
    archive = BytesIO()
    with ZipFile(archive, "w", compression=ZIP_STORED) as bundle:
        for name, content in files:
            entry = ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            entry.create_system = 3
            entry.external_attr = 0o100644 << 16
            bundle.writestr(entry, content)
    return archive.getvalue()


def source_provenance(source: ExportSource) -> dict:
    reproduction = source.run["reproducibility_manifest"]
    return {
        "source_dataset": {k: v for k, v in source.reference.items() if k != "uri"},
        "source_package_manifest_sha256": source.package["manifest_payload_sha256"],
        "source_interval": {
            "interval_seconds": 3600,
            "simulation_timestep_seconds": reproduction["simulation_timestep_seconds"],
            "native_weather_resolution_seconds": reproduction.get("native_weather_resolution_seconds"),
            "working_weather_resolution_seconds": reproduction["working_weather_resolution_seconds"],
            "source_timestamp_convention": reproduction.get("source_timestamp_convention"),
            "representative_time_policy": reproduction.get("representative_time_policy"),
            "solar_evaluation_offset_minutes": reproduction.get("solar_evaluation_offset_minutes"),
        },
        "source_timezone": reproduction["timezone"],
        "source_input_hashes": reproduction["input_hashes"],
        "source_weather_transformations": reproduction["weather_transformations"],
        "source_identities": {key: source.run.get(key) for key in (
            "input_hash", "project_revision_id", "scene_revision_id", "electrical_revision_id",
            "weather_revision_id", "simulation_configuration_id", "engine_version",
            "component_revision_manifest", "model_manifest", "detailed_execution_identity",
        )},
        "missing_value_serialization": "empty CSV field (never zero)",
        "numeric_serialization": "17 significant digits, decimal point, no grouping",
        "timestamp_serialization": "ISO 8601 with stored timezone offset; no conversion",
    }


def export_zip(source: ExportSource, columns: list[str], *, formats: tuple[str, ...] = ("csv",),
               deliverable: Deliverable | None = None) -> bytes:
    """The numerical export. With the defaults it is exactly the S7 CSV export; Parquet and the S15 deliverable
    (monthly table, package documents, run record) are opt-in and listed with hashes in the manifest."""
    available = {c["id"] for c in source.columns if c["id"] in FIELDS}
    if not columns or len(columns) != len(set(columns)):
        raise ValueError("select at least one column; duplicate columns are unsupported")
    unavailable = set(columns) - available
    if unavailable:
        raise ValueError(f"unsupported or unavailable export columns: {', '.join(sorted(unavailable))}")
    # Required interpretive columns are always included, in persisted order.
    selected_ids = set(columns) | REQUIRED
    selected = [c for c in source.columns if c["id"] in selected_ids]
    output = StringIO(newline="")
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow([c["id"] for c in selected])
    for row in source.frame[[c["id"] for c in selected]].itertuples(index=False, name=None):
        writer.writerow([csv_cell(value) for value in row])
    csv_bytes = output.getvalue().encode("utf-8")
    manifest = {
        **source.schema(), **source_provenance(source),
        "columns": selected,
        "csv_sha256": sha256(csv_bytes).hexdigest(), "csv_byte_size": len(csv_bytes),
        "column_order": "source dataset order; timestamp and interval_seconds always included",
    }
    if tuple(formats) == ("csv",) and deliverable is None:
        return _zip([("timeseries.csv", csv_bytes), ("export-manifest.json", canonical_json_bytes(manifest) + b"\n")])

    if not formats or len(set(formats)) != len(formats) or set(formats) - {"csv", "parquet"}:
        raise ValueError("formats must be one or both of csv and parquet, without repeats")
    files: list[tuple[str, bytes]] = []
    if "csv" in formats:
        files.append(("timeseries.csv", csv_bytes))
    else:
        for key in ("csv_sha256", "csv_byte_size"):
            manifest.pop(key)
    if "parquet" in formats:
        files.append(("timeseries.parquet", _parquet_bytes(source.frame[[c["id"] for c in selected]])))
    if deliverable is not None:
        from .series import monthly_columns, monthly_csv

        files.append(("monthly.csv", monthly_csv(deliverable.monthly)))
        for name in ("summary-result.json", "design-validation-report.json", "validation-findings.json"):
            files.append((name, deliverable.package_files[name]))
        files.append(("run-record.json", canonical_json_bytes(deliverable.run_record) + b"\n"))
        if deliverable.annual_pxx is not None:
            files.append(("annual-pxx.json", canonical_json_bytes(deliverable.annual_pxx) + b"\n"))
        warnings = deliverable.run_record.get("readiness_warnings")
        manifest["deliverable"] = {
            "monthly_columns": monthly_columns(deliverable.monthly),
            "dc_kwp": deliverable.monthly["dc_kwp"], "dc_kwp_basis": deliverable.monthly["dc_kwp_basis"],
            "pr_basis": deliverable.monthly["pr_basis"],
            "loss_channels": deliverable.monthly["loss_channels"],
            "readiness_warnings": warnings if warnings is not None else "not recorded for this run",
            **({"annual_pxx_status": deliverable.annual_pxx["status"]} if deliverable.annual_pxx is not None else {}),
        }
    manifest["formats"] = list(formats)
    manifest["files"] = [{"path": name, "sha256": sha256(content).hexdigest(), "byte_size": len(content),
                          "description": _DESCRIPTIONS[name]} for name, content in files]
    return _zip([*files, ("export-manifest.json", canonical_json_bytes(manifest) + b"\n")])
