"""Independent/external IV reference dataset ingestion and model validation.

The canonical IVReferenceDataset is intentionally source-format independent. It can
represent IEC 61853-style operating-point matrices, laboratory/field measurements,
manufacturer matrices, and optional full forward-quadrant IV curves.

The validator compares a canonical PVsyst single-diode model against reference data.
It does not fit the model to the same dataset: validation and parameter estimation are
kept separate to avoid data leakage.
"""

from __future__ import annotations

import csv
import hashlib
from copy import deepcopy
from dataclasses import dataclass
import io
import json
import math
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator


ROOT = Path(__file__).resolve().parents[1]
DATASET_SCHEMA_PATH = ROOT / "components/schema/iv-reference-dataset.schema.json"
RESULT_SCHEMA_PATH = ROOT / "components/schema/iv-reference-validation.schema.json"

SUMMARY_QUANTITIES = ("isc_a", "voc_v", "imp_a", "vmp_v", "pmp_w")


@dataclass(frozen=True)
class IVReferenceValidationConfig:
    isc_relative_tolerance: float = 0.03
    voc_relative_tolerance: float = 0.02
    imp_relative_tolerance: float = 0.03
    vmp_relative_tolerance: float = 0.03
    pmp_relative_tolerance: float = 0.03
    reference_power_identity_relative_tolerance: float = 0.02
    curve_current_nrmse_tolerance: float = 0.03
    curve_min_points: int = 5
    uncertainty_policy: str = "report_only"
    uncertainty_multiplier: float = 1.0
    solver: str = "lambertw"

    def tolerance_for(self, quantity: str) -> float:
        return {
            "isc_a": self.isc_relative_tolerance,
            "voc_v": self.voc_relative_tolerance,
            "imp_a": self.imp_relative_tolerance,
            "vmp_v": self.vmp_relative_tolerance,
            "pmp_w": self.pmp_relative_tolerance,
        }[quantity]


def _schema(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def validate_reference_dataset_schema(dataset: dict[str, Any]) -> None:
    schema = _schema(DATASET_SCHEMA_PATH)
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(dataset)


def validate_reference_result_schema(result: dict[str, Any]) -> None:
    schema = _schema(RESULT_SCHEMA_PATH)
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(result)


def load_iv_reference_dataset(path: str | Path) -> dict[str, Any]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    validate_reference_dataset_schema(data)
    return data


def fingerprint_source_bytes(
    data: bytes,
    *,
    file_id: str,
    filename: str,
    media_type: str | None = None,
    source_url: str | None = None,
    source_git_blob_sha: str | None = None,
    license_spdx: str | None = None,
    license_url: str | None = None,
    attribution: str | None = None,
) -> dict[str, Any]:
    """Return a stable source-file fingerprint for provenance and deduplication."""
    return {
        "file_id": file_id,
        "filename": filename,
        "media_type": media_type,
        "byte_size": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
        "source_url": source_url,
        "source_git_blob_sha": source_git_blob_sha,
        "license_spdx": license_spdx,
        "license_url": license_url,
        "attribution": attribution,
    }


def _finite_float(value: Any, *, context: str) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{context} must be numeric") from exc
    if not math.isfinite(result):
        raise ValueError(f"{context} must be finite")
    return result


def _optional_finite_float(row: dict[str, Any], column: str, *, context: str) -> float | None:
    value = row.get(column)
    if value is None or str(value).strip() == "":
        return None
    return _finite_float(value, context=context)


def _summary_csv_dataset(
    text: str,
    *,
    dataset_id: str,
    revision_id: str,
    name: str,
    source_id: str | None,
    source_kind: str,
    measurement_context: dict[str, Any] | None,
    notes: str | None,
    source_files: list[dict[str, Any]] | None,
    ingestion: dict[str, Any] | None,
    provenance: dict[str, Any] | None,
) -> dict[str, Any]:
    required = {
        "point_id",
        "effective_irradiance_w_m2",
        "cell_temperature_c",
        "isc_a",
        "voc_v",
        "imp_a",
        "vmp_v",
        "pmp_w",
    }
    reader = csv.DictReader(io.StringIO(text))
    fieldnames = set(reader.fieldnames or [])
    missing = sorted(required - fieldnames)
    if missing:
        raise ValueError(f"missing required IV summary CSV columns: {', '.join(missing)}")

    uncertainty_columns = {
        "irradiance_w_m2": "irradiance_uncertainty_w_m2",
        "cell_temperature_c": "cell_temperature_uncertainty_c",
        "isc_a": "isc_uncertainty_a",
        "voc_v": "voc_uncertainty_v",
        "imp_a": "imp_uncertainty_a",
        "vmp_v": "vmp_uncertainty_v",
        "pmp_w": "pmp_uncertainty_w",
        "confidence_fraction": "uncertainty_confidence_fraction",
        "coverage_factor": "uncertainty_coverage_factor",
    }

    points: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for row_number, row in enumerate(reader, start=2):
        point_id = (row.get("point_id") or "").strip()
        if not point_id:
            raise ValueError(f"row {row_number}: point_id is empty")
        if point_id in seen_ids:
            raise ValueError(f"row {row_number}: duplicate point_id {point_id!r}")
        seen_ids.add(point_id)

        def number(column: str) -> float:
            return _finite_float(row.get(column), context=f"row {row_number}: {column}")

        uncertainty: dict[str, float] = {}
        for canonical_key, column in uncertainty_columns.items():
            value = _optional_finite_float(
                row, column, context=f"row {row_number}: {column}"
            )
            if value is not None:
                if value < 0 and canonical_key not in {"confidence_fraction"}:
                    raise ValueError(
                        f"row {row_number}: {column} must not be negative"
                    )
                uncertainty[canonical_key] = value

        poa = _optional_finite_float(
            row,
            "plane_of_array_irradiance_w_m2",
            context=f"row {row_number}: plane_of_array_irradiance_w_m2",
        )

        points.append({
            "point_id": point_id,
            "source_index": row_number - 2,
            "effective_irradiance_w_m2": number("effective_irradiance_w_m2"),
            "plane_of_array_irradiance_w_m2": poa,
            "cell_temperature_c": number("cell_temperature_c"),
            "summary": {
                "isc_a": number("isc_a"),
                "voc_v": number("voc_v"),
                "imp_a": number("imp_a"),
                "vmp_v": number("vmp_v"),
                "pmp_w": number("pmp_w"),
            },
            "iv_curve": None,
            "uncertainty": uncertainty,
            "source_point_reference": (
                (row.get("source_point_reference") or "").strip() or None
            ),
            "notes": ((row.get("notes") or "").strip() or None),
        })

    dataset = {
        "schema_name": "IVReferenceDataset",
        "schema_version": "0.1",
        "dataset_id": dataset_id,
        "revision_id": revision_id,
        "name": name,
        "source_id": source_id,
        "source_kind": source_kind,
        "source_files": source_files or [],
        "provenance": provenance,
        "ingestion": ingestion,
        "module_identity": None,
        "measurement_context": measurement_context,
        "points": points,
        "notes": notes,
    }
    validate_reference_dataset_schema(dataset)
    return dataset


def parse_iv_summary_csv(
    text: str,
    *,
    dataset_id: str,
    revision_id: str,
    name: str,
    source_id: str | None = None,
    source_kind: str = "other",
    measurement_context: dict[str, Any] | None = None,
    notes: str | None = None,
    provenance: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Convert summary-point CSV text into a canonical IVReferenceDataset.

    The text-only entry point is retained for convenience and backwards compatibility.
    Use :func:`parse_iv_summary_csv_bytes` when source hashing is required.
    """
    return _summary_csv_dataset(
        text,
        dataset_id=dataset_id,
        revision_id=revision_id,
        name=name,
        source_id=source_id,
        source_kind=source_kind,
        measurement_context=measurement_context,
        notes=notes,
        source_files=[],
        ingestion={
            "parser_name": "opensimpv_iv_summary_csv",
            "parser_version": "0.2",
            "encoding": "unicode-text",
            "source_record_count": None,
            "selected_source_indices": None,
            "transformations": [],
        },
        provenance=provenance,
    )


def parse_iv_summary_csv_bytes(
    data: bytes,
    *,
    dataset_id: str,
    revision_id: str,
    name: str,
    filename: str,
    source_id: str | None = None,
    source_kind: str = "other",
    measurement_context: dict[str, Any] | None = None,
    notes: str | None = None,
    provenance: dict[str, Any] | None = None,
    encoding: str = "utf-8-sig",
    source_url: str | None = None,
    source_git_blob_sha: str | None = None,
    license_spdx: str | None = None,
    license_url: str | None = None,
    attribution: str | None = None,
) -> dict[str, Any]:
    """Parse and fingerprint an uploaded summary-point CSV."""
    text = data.decode(encoding)
    fingerprint = fingerprint_source_bytes(
        data,
        file_id=f"{dataset_id}:source:0",
        filename=filename,
        media_type="text/csv",
        source_url=source_url,
        source_git_blob_sha=source_git_blob_sha,
        license_spdx=license_spdx,
        license_url=license_url,
        attribution=attribution,
    )
    dataset = _summary_csv_dataset(
        text,
        dataset_id=dataset_id,
        revision_id=revision_id,
        name=name,
        source_id=source_id,
        source_kind=source_kind,
        measurement_context=measurement_context,
        notes=notes,
        source_files=[fingerprint],
        ingestion={
            "parser_name": "opensimpv_iv_summary_csv",
            "parser_version": "0.2",
            "encoding": encoding,
            "source_record_count": None,
            "selected_source_indices": None,
            "transformations": [],
        },
        provenance=provenance,
    )
    dataset["ingestion"]["source_record_count"] = len(dataset["points"])
    return dataset


def parse_pvlib_pvsyst_demo_bytes(
    data: bytes,
    *,
    dataset_id: str,
    revision_id: str,
    name: str,
    filename: str,
    source_id: str,
    selected_indices: list[int] | tuple[int, ...] | None = None,
    source_index_map: list[int] | tuple[int, ...] | None = None,
    source_kind: str = "field_iv",
    source_url: str | None = None,
    source_git_blob_sha: str | None = None,
    license_spdx: str | None = None,
    license_url: str | None = None,
    attribution: str | None = None,
    provenance: dict[str, Any] | None = None,
    measurement_context: dict[str, Any] | None = None,
    encoding: str = "utf-8-sig",
) -> dict[str, Any]:
    """Parse the legacy pvlib/PVLIB MATLAB PVsyst-demo measured-IV text format.

    The source format consists of:
    - one header line: cells_in_series, alpha_isc, beta_voc, description;
    - one shape line: curve_count, samples_per_curve;
    - for each curve: one summary line followed by voltage and current rows.

    The summary fields are Isc, Imp, Vmp, Voc, POA irradiance, cell temperature,
    and effective irradiance. Pmp is explicitly derived as Imp*Vmp.
    """
    text = data.decode(encoding)
    lines = text.splitlines()
    if len(lines) < 2:
        raise ValueError("pvlib PVsyst demo source is too short")

    header = [item.strip() for item in lines[0].split(",")]
    if len(header) < 4:
        raise ValueError("pvlib PVsyst demo header must contain four fields")
    cells_in_series = int(header[0])
    alpha_isc = _finite_float(header[1], context="source alpha_isc")
    beta_voc = _finite_float(header[2], context="source beta_voc")
    description = ",".join(header[3:]).strip()

    shape = [item.strip() for item in lines[1].split(",")]
    if len(shape) != 2:
        raise ValueError("pvlib PVsyst demo shape line must contain curve and sample counts")
    curve_count = int(shape[0])
    samples_per_curve = int(shape[1])
    expected_lines = 2 + 3 * curve_count
    if len(lines) != expected_lines:
        raise ValueError(
            f"pvlib PVsyst demo line count mismatch: expected {expected_lines}, "
            f"found {len(lines)}"
        )

    if selected_indices is None:
        selected = set(range(curve_count))
        selected_list = list(range(curve_count))
    else:
        selected_list = list(dict.fromkeys(int(value) for value in selected_indices))
        if any(value < 0 or value >= curve_count for value in selected_list):
            raise ValueError("selected_indices contains an out-of-range curve index")
        selected = set(selected_list)

    if source_index_map is None:
        original_index_by_subset_index = list(range(curve_count))
    else:
        original_index_by_subset_index = [int(value) for value in source_index_map]
        if len(original_index_by_subset_index) != curve_count:
            raise ValueError(
                "source_index_map length must equal the source curve count"
            )
        if any(value < 0 for value in original_index_by_subset_index):
            raise ValueError("source_index_map must contain nonnegative indices")

    points: list[dict[str, Any]] = []
    cursor = 2
    for curve_index in range(curve_count):
        summary_values = [
            _finite_float(value.strip(), context=f"curve {curve_index} summary")
            for value in lines[cursor].split(",")
        ]
        voltage_values = [
            _finite_float(value.strip(), context=f"curve {curve_index} voltage")
            for value in lines[cursor + 1].split(",")
            if value.strip() != ""
        ]
        current_values = [
            _finite_float(value.strip(), context=f"curve {curve_index} current")
            for value in lines[cursor + 2].split(",")
            if value.strip() != ""
        ]
        cursor += 3

        if len(summary_values) != 7:
            raise ValueError(f"curve {curve_index}: summary must contain seven values")
        if not voltage_values or not current_values:
            raise ValueError(f"curve {curve_index}: IV curve is empty")
        if len(voltage_values) != len(current_values):
            raise ValueError(
                f"curve {curve_index}: voltage/current sample counts differ"
            )
        if len(voltage_values) > samples_per_curve:
            raise ValueError(
                f"curve {curve_index}: found more than nominal {samples_per_curve} IV samples"
            )

        if curve_index not in selected:
            continue

        isc, imp, vmp, voc, poa, tc, ee = summary_values
        original_index = original_index_by_subset_index[curve_index]
        points.append({
            "point_id": f"curve-{original_index:04d}",
            "source_index": original_index,
            "source_sample_count": len(voltage_values),
            "effective_irradiance_w_m2": ee,
            "plane_of_array_irradiance_w_m2": poa,
            "cell_temperature_c": tc,
            "summary": {
                "isc_a": isc,
                "voc_v": voc,
                "imp_a": imp,
                "vmp_v": vmp,
                "pmp_w": imp * vmp,
            },
            "iv_curve": [
                {"voltage_v": voltage, "current_a": current}
                for voltage, current in zip(voltage_values, current_values)
            ],
            "uncertainty": {},
            "source_point_reference": f"{filename}:source-curve:{original_index}",
            "notes": (
                "Pmp derived by OpenSIMPV as source Imp × source Vmp. "
                "The legacy file's nominal samples-per-curve field is a maximum; "
                "shorter source rows are preserved without NaN padding."
            ),
        })

    fingerprint = fingerprint_source_bytes(
        data,
        file_id=f"{dataset_id}:source:0",
        filename=filename,
        media_type="text/csv",
        source_url=source_url,
        source_git_blob_sha=source_git_blob_sha,
        license_spdx=license_spdx,
        license_url=license_url,
        attribution=attribution,
    )

    context = dict(measurement_context or {})
    context.setdefault("irradiance_quantity", "effective_irradiance")
    context.setdefault("temperature_quantity", "cell_temperature")
    context.setdefault("uncertainty_basis", "unknown")
    context["source_header"] = {
        "cells_in_series": cells_in_series,
        "alpha_isc_a_per_c": alpha_isc,
        "beta_voc_v_per_c": beta_voc,
        "description": description,
    }

    dataset = {
        "schema_name": "IVReferenceDataset",
        "schema_version": "0.1",
        "dataset_id": dataset_id,
        "revision_id": revision_id,
        "name": name,
        "source_id": source_id,
        "source_kind": source_kind,
        "source_files": [fingerprint],
        "provenance": provenance,
        "ingestion": {
            "parser_name": "pvlib_pvsyst_demo_legacy",
            "parser_version": "0.1",
            "encoding": encoding,
            "source_record_count": curve_count,
            "selected_source_indices": [
                original_index_by_subset_index[value] for value in selected_list
            ],
            "transformations": [
                "Pmp derived from source Imp × Vmp.",
                "POA irradiance preserved separately from effective irradiance.",
            ],
        },
        "module_identity": {
            "manufacturer": "Mitsubishi" if "Mitsubishi" in description else None,
            "model": "PV-UE125MF5N" if "PV-UE125MF5N" in description else description,
            "serial_number": None,
        },
        "measurement_context": context,
        "points": points,
        "notes": (
            "Parsed from the legacy pvlib/PVLIB MATLAB PVsyst-demo measured-IV "
            "format. Source values are preserved except explicit Pmp derivation."
        ),
    }
    validate_reference_dataset_schema(dataset)
    return dataset

def _qualification(
    dataset: dict[str, Any],
    model_source_ids: set[str],
    model_source_group_ids: set[str],
) -> str:
    source_kind = dataset.get("source_kind")
    source_id = dataset.get("source_id")
    provenance = dataset.get("provenance") or {}
    dataset_group = provenance.get("source_group_id")
    derived_from_source_ids = set(provenance.get("derived_from_source_ids") or [])

    if source_kind == "synthetic_reference":
        return "synthetic_regression"
    if source_id is not None and source_id in model_source_ids:
        return "same_source_validation"
    if derived_from_source_ids & model_source_ids:
        return "same_source_validation"
    if dataset_group is not None and dataset_group in model_source_group_ids:
        return "same_source_validation"
    if source_id is None:
        return "unqualified"
    if source_kind in {"iec61853_matrix", "laboratory_iv", "field_iv"}:
        return "independent_reference_validation"
    if source_kind == "datasheet_matrix":
        return "external_reference_validation"
    return "unqualified"


def _pvsyst_diode_parameters(
    parameter_set: dict[str, Any],
    effective_irradiance_w_m2: float,
    cell_temperature_c: float,
):
    from pvlib.pvsystem import calcparams_pvsyst

    return calcparams_pvsyst(
        effective_irradiance=effective_irradiance_w_m2,
        temp_cell=cell_temperature_c,
        alpha_sc=parameter_set["alpha_sc_a_per_c"],
        gamma_ref=parameter_set["gamma_ref"],
        mu_gamma=parameter_set["mu_gamma"],
        I_L_ref=parameter_set["photocurrent_ref_a"],
        I_o_ref=parameter_set["saturation_current_ref_a"],
        R_sh_ref=parameter_set["r_shunt_ref_ohm"],
        R_sh_0=parameter_set["r_shunt_0_ohm"],
        R_s=parameter_set["r_series_ohm"],
        cells_in_series=parameter_set["cells_in_series"],
        R_sh_exp=parameter_set["r_shunt_exp"],
        EgRef=parameter_set["energy_bandgap_ref_ev"],
        irrad_ref=parameter_set["reference_irradiance_w_m2"],
        temp_ref=parameter_set["reference_cell_temperature_c"],
    )


def _summary_from_diode_parameters(diode_parameters, solver: str) -> dict[str, float]:
    from pvlib.pvsystem import singlediode

    solved = singlediode(*diode_parameters, method=solver)
    return {
        "isc_a": float(solved["i_sc"]),
        "voc_v": float(solved["v_oc"]),
        "imp_a": float(solved["i_mp"]),
        "vmp_v": float(solved["v_mp"]),
        "pmp_w": float(solved["p_mp"]),
    }


def _reference_quality(
    point: dict[str, Any],
    config: IVReferenceValidationConfig,
) -> tuple[bool, list[dict[str, Any]]]:
    summary = point["summary"]
    findings: list[dict[str, Any]] = []

    for quantity in SUMMARY_QUANTITIES:
        value = float(summary[quantity])
        if not math.isfinite(value) or value <= 0:
            findings.append({
                "rule_id": "IVREF_NONPOSITIVE_OR_NONFINITE_SUMMARY",
                "severity": "error",
                "quantity": quantity,
                "message": f"{quantity} must be finite and greater than zero.",
                "value": value,
            })

    if float(summary["voc_v"]) <= float(summary["vmp_v"]):
        findings.append({
            "rule_id": "IVREF_VOC_NOT_ABOVE_VMP",
            "severity": "error",
            "message": "Reference Voc must be greater than Vmp.",
        })
    if float(summary["isc_a"]) < float(summary["imp_a"]):
        findings.append({
            "rule_id": "IVREF_ISC_BELOW_IMP",
            "severity": "error",
            "message": "Reference Isc must be greater than or equal to Imp.",
        })

    pmp = float(summary["pmp_w"])
    product = float(summary["vmp_v"]) * float(summary["imp_a"])
    power_error = abs(pmp - product) / max(abs(pmp), abs(product), 1e-12)
    if power_error > config.reference_power_identity_relative_tolerance:
        findings.append({
            "rule_id": "IVREF_PMP_VMP_IMP_MISMATCH",
            "severity": "error",
            "message": "Reference Pmp differs from Vmp × Imp beyond tolerance.",
            "relative_error": power_error,
            "tolerance": config.reference_power_identity_relative_tolerance,
        })

    curve = point.get("iv_curve")
    if curve:
        if len(curve) < config.curve_min_points:
            findings.append({
                "rule_id": "IVREF_CURVE_TOO_SHORT",
                "severity": "error",
                "message": (
                    f"Full IV curve has {len(curve)} points; "
                    f"at least {config.curve_min_points} are required."
                ),
            })
        voltages = [float(sample["voltage_v"]) for sample in curve]
        currents = [float(sample["current_a"]) for sample in curve]
        if not all(math.isfinite(value) for value in voltages + currents):
            findings.append({
                "rule_id": "IVREF_CURVE_NONFINITE",
                "severity": "error",
                "message": "Full IV curve contains non-finite voltage or current.",
            })
        if len(set(voltages)) != len(voltages):
            findings.append({
                "rule_id": "IVREF_CURVE_DUPLICATE_VOLTAGE",
                "severity": "warning",
                "message": (
                    "Full IV curve contains duplicate voltage samples. They are "
                    "preserved and evaluated because repeated measured voltages "
                    "can result from instrument resolution or sweep sampling."
                ),
            })

    return not any(item["severity"] == "error" for item in findings), findings


def _summary_residuals(
    reference: dict[str, Any],
    modeled: dict[str, float],
    config: IVReferenceValidationConfig,
    *,
    uncertainty: dict[str, Any] | None = None,
    uncertainty_basis: str | None = None,
) -> tuple[bool, dict[str, Any]]:
    if config.uncertainty_policy not in {"report_only", "expand_tolerance"}:
        raise ValueError(
            "uncertainty_policy must be 'report_only' or 'expand_tolerance'"
        )
    if config.uncertainty_multiplier <= 0:
        raise ValueError("uncertainty_multiplier must be greater than zero")

    uncertainty = uncertainty or {}
    residuals: dict[str, Any] = {}
    passed = True
    for quantity in SUMMARY_QUANTITIES:
        expected = float(reference[quantity])
        actual = float(modeled[quantity])
        absolute = actual - expected
        relative = absolute / expected
        relative_tolerance = config.tolerance_for(quantity)
        base_absolute_tolerance = abs(expected) * relative_tolerance

        uncertainty_value = uncertainty.get(quantity)
        uncertainty_abs = (
            float(uncertainty_value)
            if uncertainty_value is not None
            else None
        )
        if uncertainty_abs is not None and uncertainty_abs < 0:
            raise ValueError(f"measurement uncertainty for {quantity} must not be negative")

        effective_absolute_tolerance = base_absolute_tolerance
        uncertainty_used_for_acceptance = False
        if (
            config.uncertainty_policy == "expand_tolerance"
            and uncertainty_abs is not None
            and uncertainty_basis in {"standard", "expanded", "absolute_bound"}
        ):
            effective_absolute_tolerance = max(
                base_absolute_tolerance,
                config.uncertainty_multiplier * uncertainty_abs,
            )
            uncertainty_used_for_acceptance = True

        within = abs(absolute) <= effective_absolute_tolerance
        residuals[quantity] = {
            "reference": expected,
            "modeled": actual,
            "absolute": absolute,
            "relative": relative,
            "absolute_relative": abs(relative),
            "relative_tolerance": relative_tolerance,
            "base_absolute_tolerance": base_absolute_tolerance,
            "measurement_uncertainty": uncertainty_abs,
            "uncertainty_basis": uncertainty_basis,
            "uncertainty_policy": config.uncertainty_policy,
            "uncertainty_multiplier": config.uncertainty_multiplier,
            "uncertainty_used_for_acceptance": uncertainty_used_for_acceptance,
            "effective_absolute_tolerance": effective_absolute_tolerance,
            "uncertainty_normalized_absolute_error": (
                abs(absolute) / uncertainty_abs
                if uncertainty_abs is not None and uncertainty_abs > 0
                else None
            ),
            "within_tolerance": within,
        }
        passed = passed and within
    return passed, residuals


def _curve_result(
    curve: list[dict[str, Any]],
    diode_parameters,
    summary: dict[str, Any],
    config: IVReferenceValidationConfig,
) -> dict[str, Any]:
    from pvlib.pvsystem import i_from_v

    voltages = [float(sample["voltage_v"]) for sample in curve]
    measured = [float(sample["current_a"]) for sample in curve]
    modeled_values = i_from_v(
        voltages,
        *diode_parameters,
        method=config.solver,
    )
    modeled = [float(value) for value in modeled_values]

    squared = [(actual - expected) ** 2 for actual, expected in zip(modeled, measured)]
    absolute_errors = [abs(actual - expected) for actual, expected in zip(modeled, measured)]
    rmse_a = math.sqrt(sum(squared) / len(squared))
    normalizer = max(abs(float(summary["isc_a"])), 1e-12)
    nrmse = rmse_a / normalizer
    passed = nrmse <= config.curve_current_nrmse_tolerance

    return {
        "sample_count": len(curve),
        "current_rmse_a": rmse_a,
        "current_nrmse_by_isc": nrmse,
        "max_absolute_current_error_a": max(absolute_errors),
        "tolerance": config.curve_current_nrmse_tolerance,
        "passed": passed,
        "samples": [
            {
                "voltage_v": voltage,
                "reference_current_a": expected,
                "modeled_current_a": actual,
                "error_a": actual - expected,
            }
            for voltage, expected, actual in zip(voltages, measured, modeled)
        ],
    }


def validate_pvsyst_sdm_against_reference(
    module_data: dict[str, Any],
    dataset: dict[str, Any],
    *,
    validation_id: str,
    config: IVReferenceValidationConfig | None = None,
    model_index: int = 0,
) -> dict[str, Any]:
    """Compare an existing PVsyst SDM against an external/reference IV dataset."""
    config = config or IVReferenceValidationConfig()
    validate_reference_dataset_schema(dataset)

    models = module_data.get("electrical_models") or []
    if model_index >= len(models):
        raise ValueError("model_index does not exist")
    model = models[model_index]
    if model.get("model_type") != "pvsyst_singlediode":
        raise ValueError("selected electrical model is not pvsyst_singlediode")
    parameter_set = model.get("parameter_set") or {}

    required_parameters = {
        "alpha_sc_a_per_c",
        "gamma_ref",
        "mu_gamma",
        "photocurrent_ref_a",
        "saturation_current_ref_a",
        "r_shunt_ref_ohm",
        "r_shunt_0_ohm",
        "r_series_ohm",
        "cells_in_series",
        "r_shunt_exp",
        "energy_bandgap_ref_ev",
        "reference_irradiance_w_m2",
        "reference_cell_temperature_c",
    }
    missing = sorted(required_parameters - set(parameter_set))
    qualification = _qualification(
        dataset,
        set(module_data.get("source_ids") or []),
        set(module_data.get("source_group_ids") or []),
    )

    if missing:
        result = {
            "schema_name": "IVReferenceValidationResult",
            "schema_version": "0.1",
            "validation_id": validation_id,
            "dataset_id": dataset["dataset_id"],
            "dataset_revision_id": dataset.get("revision_id"),
            "dataset_source_id": dataset.get("source_id"),
            "module_definition_id": module_data["module_definition_id"],
            "module_revision_id": module_data.get("revision_id"),
            "model_type": model["model_type"],
            "model_version": model.get("model_version"),
            "status": "incomplete",
            "passed": False,
            "qualification": qualification,
            "implementation": {"name": "pvlib-python", "version": None, "solver": config.solver},
            "configuration": _config_payload(config),
            "coverage": _coverage(dataset),
            "point_results": [],
            "aggregate": {"missing_parameters": missing},
            "findings": [{
                "rule_id": "IVREF_MODEL_PARAMETER_SET_INCOMPLETE",
                "severity": "error",
                "message": "Selected PVsyst SDM lacks required parameters.",
                "missing_parameters": missing,
            }],
        }
        validate_reference_result_schema(result)
        return result

    try:
        import pvlib
        version = getattr(pvlib, "__version__", None)
    except ImportError as exc:
        result = {
            "schema_name": "IVReferenceValidationResult",
            "schema_version": "0.1",
            "validation_id": validation_id,
            "dataset_id": dataset["dataset_id"],
            "dataset_revision_id": dataset.get("revision_id"),
            "dataset_source_id": dataset.get("source_id"),
            "module_definition_id": module_data["module_definition_id"],
            "module_revision_id": module_data.get("revision_id"),
            "model_type": model["model_type"],
            "model_version": model.get("model_version"),
            "status": "unavailable",
            "passed": False,
            "qualification": qualification,
            "implementation": {"name": "pvlib-python", "version": None, "solver": config.solver},
            "configuration": _config_payload(config),
            "coverage": _coverage(dataset),
            "point_results": [],
            "aggregate": {},
            "findings": [{
                "rule_id": "IVREF_PVLIB_UNAVAILABLE",
                "severity": "error",
                "message": str(exc),
            }],
        }
        validate_reference_result_schema(result)
        return result

    point_results: list[dict[str, Any]] = []
    findings: list[dict[str, Any]] = []
    try:
        for point in dataset["points"]:
            reference_ok, reference_findings = _reference_quality(point, config)
            diode_parameters = _pvsyst_diode_parameters(
                parameter_set,
                float(point["effective_irradiance_w_m2"]),
                float(point["cell_temperature_c"]),
            )
            modeled = _summary_from_diode_parameters(diode_parameters, config.solver)
            summary_passed, residuals = _summary_residuals(
                point["summary"],
                modeled,
                config,
                uncertainty=point.get("uncertainty"),
                uncertainty_basis=(dataset.get("measurement_context") or {}).get(
                    "uncertainty_basis"
                ),
            )

            curve_result = None
            curve = point.get("iv_curve")
            if curve and reference_ok:
                curve_result = _curve_result(
                    curve, diode_parameters, point["summary"], config
                )

            point_passed = (
                reference_ok
                and summary_passed
                and (curve_result is None or curve_result["passed"])
            )
            point_results.append({
                "point_id": point["point_id"],
                "effective_irradiance_w_m2": point["effective_irradiance_w_m2"],
                "cell_temperature_c": point["cell_temperature_c"],
                "reference_quality_passed": reference_ok,
                "reference_findings": reference_findings,
                "summary_passed": summary_passed,
                "summary_residuals": residuals,
                "curve_result": curve_result,
                "passed": point_passed,
            })
            findings.extend(
                {
                    **item,
                    "point_id": point["point_id"],
                }
                for item in reference_findings
            )
    except Exception as exc:
        result = {
            "schema_name": "IVReferenceValidationResult",
            "schema_version": "0.1",
            "validation_id": validation_id,
            "dataset_id": dataset["dataset_id"],
            "dataset_revision_id": dataset.get("revision_id"),
            "dataset_source_id": dataset.get("source_id"),
            "module_definition_id": module_data["module_definition_id"],
            "module_revision_id": module_data.get("revision_id"),
            "model_type": model["model_type"],
            "model_version": model.get("model_version"),
            "status": "failed",
            "passed": False,
            "qualification": qualification,
            "implementation": {"name": "pvlib-python", "version": version, "solver": config.solver},
            "configuration": _config_payload(config),
            "coverage": _coverage(dataset),
            "point_results": point_results,
            "aggregate": {},
            "findings": findings + [{
                "rule_id": "IVREF_MODEL_EVALUATION_FAILED",
                "severity": "error",
                "message": f"{type(exc).__name__}: {exc}",
            }],
        }
        validate_reference_result_schema(result)
        return result

    passed = all(item["passed"] for item in point_results)
    curve_results = [
        item["curve_result"] for item in point_results if item["curve_result"] is not None
    ]
    aggregate = {
        "point_passed_count": sum(1 for item in point_results if item["passed"]),
        "point_total_count": len(point_results),
        "summary_passed_count": sum(1 for item in point_results if item["summary_passed"]),
        "curve_evaluated_count": len(curve_results),
        "curve_passed_count": sum(1 for item in curve_results if item["passed"]),
        "max_summary_absolute_relative_error": {
            quantity: max(
                item["summary_residuals"][quantity]["absolute_relative"]
                for item in point_results
            )
            for quantity in SUMMARY_QUANTITIES
        },
        "max_curve_current_nrmse_by_isc": (
            max(item["current_nrmse_by_isc"] for item in curve_results)
            if curve_results else None
        ),
    }

    result = {
        "schema_name": "IVReferenceValidationResult",
        "schema_version": "0.1",
        "validation_id": validation_id,
        "dataset_id": dataset["dataset_id"],
        "dataset_revision_id": dataset.get("revision_id"),
        "dataset_source_id": dataset.get("source_id"),
        "module_definition_id": module_data["module_definition_id"],
        "module_revision_id": module_data.get("revision_id"),
        "model_type": model["model_type"],
        "model_version": model.get("model_version"),
        "status": "passed" if passed else "failed",
        "passed": passed,
        "qualification": qualification,
        "implementation": {"name": "pvlib-python", "version": version, "solver": config.solver},
        "configuration": _config_payload(config),
        "coverage": _coverage(dataset),
        "point_results": point_results,
        "aggregate": aggregate,
        "findings": findings,
    }
    validate_reference_result_schema(result)
    return result


def attach_reference_validation(
    module_data: dict[str, Any],
    validation_result: dict[str, Any],
) -> dict[str, Any]:
    """Attach a validation result without changing the underlying model parameters."""
    validate_reference_result_schema(validation_result)
    if validation_result["module_definition_id"] != module_data.get("module_definition_id"):
        raise ValueError("validation result belongs to a different module definition")

    updated = deepcopy(module_data)
    models = updated.get("electrical_models") or []
    matching = [
        model for model in models
        if model.get("model_type") == validation_result["model_type"]
    ]
    if not matching:
        raise ValueError("module does not contain the validated model type")
    model = matching[0]
    model.setdefault("reference_validations", []).append(deepcopy(validation_result))

    flags = updated.setdefault("capability_flags", {})
    flags["independent_iv_validated"] = bool(
        validation_result["passed"]
        and validation_result["qualification"] == "independent_reference_validation"
    ) or bool(flags.get("independent_iv_validated"))
    return updated


def _config_payload(config: IVReferenceValidationConfig) -> dict[str, Any]:
    return {
        "isc_relative_tolerance": config.isc_relative_tolerance,
        "voc_relative_tolerance": config.voc_relative_tolerance,
        "imp_relative_tolerance": config.imp_relative_tolerance,
        "vmp_relative_tolerance": config.vmp_relative_tolerance,
        "pmp_relative_tolerance": config.pmp_relative_tolerance,
        "reference_power_identity_relative_tolerance": (
            config.reference_power_identity_relative_tolerance
        ),
        "curve_current_nrmse_tolerance": config.curve_current_nrmse_tolerance,
        "curve_min_points": config.curve_min_points,
        "uncertainty_policy": config.uncertainty_policy,
        "uncertainty_multiplier": config.uncertainty_multiplier,
        "solver": config.solver,
    }


def _coverage(dataset: dict[str, Any]) -> dict[str, Any]:
    points = dataset["points"]
    irradiances = [float(item["effective_irradiance_w_m2"]) for item in points]
    temperatures = [float(item["cell_temperature_c"]) for item in points]
    return {
        "reference_point_count": len(points),
        "curve_count": sum(1 for item in points if item.get("iv_curve")),
        "irradiance_min_w_m2": min(irradiances) if irradiances else None,
        "irradiance_max_w_m2": max(irradiances) if irradiances else None,
        "temperature_min_c": min(temperatures) if temperatures else None,
        "temperature_max_c": max(temperatures) if temperatures else None,
    }
