"""Machine-readable PAN/OND semantic mapping support.

The mapper is intentionally conservative:
- rules live in versioned YAML ledgers;
- only rules marked auto_map=true are applied;
- duplicate source paths are treated as ambiguous, not last-write-wins;
- conversion is explicit per rule;
- every mapped value produces an auditable FieldMappingRecord;
- unmapped source fields are retained.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from pathlib import Path
from typing import Any, Iterable

import yaml

from components.panond_raw import RawPanOndDocument, RawPanOndLine


@dataclass(frozen=True)
class MappingRule:
    source_path: tuple[str, ...]
    canonical_field: str | None
    source_unit: str | None
    canonical_unit: str | None
    conversion_rule: str
    semantic_description: str
    required_for_model: bool
    confidence: str
    auto_map: bool
    scope: str | None
    notes: str | None
    evidence: tuple[dict[str, Any], ...]


@dataclass(frozen=True)
class SemanticMappingResult:
    values_by_canonical_path: dict[str, Any]
    mapped_fields: tuple[dict[str, Any], ...]
    unmapped_fields: tuple[dict[str, Any], ...]
    warnings: tuple[str, ...]

    def as_import_record_payload(self) -> dict[str, Any]:
        return {
            "mapped_fields": list(self.mapped_fields),
            "unmapped_fields": list(self.unmapped_fields),
            "mapping_warnings": list(self.warnings),
        }


def load_mapping_ledger(path: str | Path) -> tuple[str, tuple[MappingRule, ...]]:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    rules = tuple(
        MappingRule(
            source_path=tuple(item["source_path"]),
            canonical_field=item["canonical_field"],
            source_unit=item["source_unit"],
            canonical_unit=item["canonical_unit"],
            conversion_rule=item["conversion_rule"],
            semantic_description=item["semantic_description"],
            required_for_model=bool(item["required_for_model"]),
            confidence=item["confidence"],
            auto_map=bool(item["auto_map"]),
            scope=item.get("scope"),
            notes=item.get("notes"),
            evidence=tuple(item.get("evidence", [])),
        )
        for item in data["rules"]
    )
    return data["format"], rules


def _convert(value_raw: str | None, rule: MappingRule) -> Any:
    if value_raw is None:
        raise ValueError("source value is missing")

    conversion = rule.conversion_rule
    if conversion == "string":
        return value_raw
    if conversion == "abs_float":
        value = abs(float(value_raw))
        if not isfinite(value):
            raise ValueError("absolute numeric value must be finite")
        return value
    if conversion == "float":
        return float(value_raw)
    if conversion == "int":
        return int(value_raw)
    if conversion == "kw_to_w":
        return float(value_raw) * 1000.0
    if conversion == "ma_to_a":
        return float(value_raw) / 1000.0
    if conversion == "mv_to_v":
        return float(value_raw) / 1000.0
    if conversion == "percent_to_fraction":
        return float(value_raw) / 100.0
    if conversion == "loss_percent_to_fraction":
        value = float(value_raw)
        if not isfinite(value) or not 0 <= value < 100:
            raise ValueError("loss percentage must be finite and within [0, 100)")
        return value / 100.0
    if conversion == "csv_float_list":
        return [
            float(item.strip())
            for item in value_raw.split(",")
            if item.strip() != ""
        ]
    if conversion == "power_pair_w":
        parts = [
            float(item.strip())
            for item in value_raw.split(",")
            if item.strip() != ""
        ]
        if len(parts) != 2:
            raise ValueError(f"expected Pin,Pout pair, got {value_raw!r}")
        return {"dc_power_w": parts[0], "ac_power_w": parts[1]}
    if conversion == "angle_modifier_pair":
        parts = [
            float(item.strip())
            for item in value_raw.split(",")
            if item.strip() != ""
        ]
        if len(parts) != 2:
            raise ValueError(f"expected angle,IAM pair, got {value_raw!r}")
        return {"angle_deg": parts[0], "modifier": parts[1]}
    if conversion == "mono_tri_to_phase":
        normalized = value_raw.strip().lower()
        if normalized in {"tri", "three", "three_phase", "3"}:
            return "three_phase"
        if normalized in {"mono", "single", "single_phase", "1"}:
            return "single_phase"
        raise ValueError(f"unsupported MonoTri value: {value_raw!r}")
    if conversion == "pvsyst_technology_code":
        normalized = value_raw.strip()
        known = {
            "mtSiMono": "crystalline_silicon_mono",
            "mtSiPoly": "crystalline_silicon_poly",
        }
        if normalized not in known:
            raise ValueError(f"unsupported PVsyst technology code: {value_raw!r}")
        return known[normalized]
    if conversion == "identity_unmapped":
        return value_raw
    raise ValueError(f"unknown conversion rule: {conversion}")


def _field_record(line: RawPanOndLine) -> dict[str, Any]:
    return line.as_field_record()


def semantic_map_document(
    document: RawPanOndDocument,
    rules: Iterable[MappingRule],
) -> SemanticMappingResult:
    fields_by_path: dict[tuple[str, ...], list[RawPanOndLine]] = {}
    for field in document.fields:
        fields_by_path.setdefault(field.path, []).append(field)

    values: dict[str, Any] = {}
    mapped: list[dict[str, Any]] = []
    consumed_line_numbers: set[int] = set()
    warnings: list[str] = list(document.warnings)

    for rule in rules:
        if not rule.auto_map or rule.canonical_field is None:
            continue

        matches = fields_by_path.get(rule.source_path, [])
        if not matches:
            continue

        if len(matches) > 1:
            warnings.append(
                "Ambiguous duplicate source path "
                f"{'/'.join(rule.source_path)} occurs {len(matches)} times; "
                f"{rule.canonical_field} was not auto-mapped."
            )
            continue

        field = matches[0]
        try:
            converted = _convert(field.value_raw, rule)
        except (TypeError, ValueError) as exc:
            warnings.append(
                f"Could not map {'/'.join(rule.source_path)} to "
                f"{rule.canonical_field}: {exc}"
            )
            continue

        if rule.canonical_field in values:
            warnings.append(
                f"Canonical path {rule.canonical_field} received more than one mapping; "
                "later value was not applied."
            )
            continue

        values[rule.canonical_field] = converted
        consumed_line_numbers.add(field.line_number)
        mapped.append(
            {
                "source_path": list(rule.source_path),
                "source_value": field.value_raw,
                "source_unit": rule.source_unit,
                "canonical_path": rule.canonical_field,
                "canonical_value": converted,
                "canonical_unit": rule.canonical_unit,
                "conversion": rule.conversion_rule,
                "mapping_confidence": rule.confidence,
                "notes": rule.notes,
            }
        )

    unmapped = [
        _field_record(field)
        for field in document.fields
        if field.line_number not in consumed_line_numbers
    ]

    return SemanticMappingResult(
        values_by_canonical_path=values,
        mapped_fields=tuple(mapped),
        unmapped_fields=tuple(unmapped),
        warnings=tuple(warnings),
    )
