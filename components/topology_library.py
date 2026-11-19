"""Phase-6.2 canonical topology-library and capability integration.

This module is an orchestration layer over the frozen Phase-6.1 contracts. It does
not infer topology, derive region electrical parameters, or implement mismatch
physics.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from engine.simulation.models.module_resolver import resolve_module_model
from shading.electrical import (
    resolve_bypass_model_evidence,
    resolve_electrical_shading_capability,
    resolve_module_capability_snapshot,
    validate_parameterization_for_electrical_shading,
    validate_topology_for_electrical_shading,
)


TOPOLOGY_LIBRARY_VERSION = "opensimpv-module-topology-library-0.1"


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def canonical_topology_asset_sha256(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def index_source_records(
    source_records: Sequence[Mapping[str, Any]],
) -> dict[str, dict[str, Any]]:
    """Index source records by exact source ID and reject conflicting duplicates."""
    indexed: dict[str, dict[str, Any]] = {}
    for source in source_records:
        source_id = str(source.get("source_id") or "")
        if not source_id:
            raise ValueError("SourceRecord requires source_id")
        payload = deepcopy(dict(source))
        previous = indexed.get(source_id)
        if previous is not None and previous != payload:
            raise ValueError(f"conflicting SourceRecord payloads for {source_id!r}")
        indexed[source_id] = payload
    return indexed


def assert_library_source_bindings(
    asset: Mapping[str, Any],
    source_records: Mapping[str, Mapping[str, Any]],
    *,
    label: str,
) -> None:
    source_ids = asset.get("source_ids")
    if not isinstance(source_ids, list) or not source_ids:
        raise ValueError(f"{label} requires at least one source_id")
    missing = sorted(
        str(source_id)
        for source_id in source_ids
        if str(source_id) not in source_records
    )
    if missing:
        raise ValueError(
            f"{label} references unavailable SourceRecord ids: {missing}"
        )


def load_topology_asset(path: str | Path) -> dict[str, Any]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if value.get("schema_name") != "ModuleTopologyDefinition":
        raise ValueError("topology asset must be ModuleTopologyDefinition")
    return value


def index_module_topologies(
    topology_definitions: Sequence[Mapping[str, Any]],
) -> dict[str, dict[str, Any]]:
    """Index immutable topology revisions by exact topology revision id.

    Duplicate revision ids with different payloads are rejected. No module topology
    is synthesized from ModuleDefinition metadata.
    """
    indexed: dict[str, dict[str, Any]] = {}
    hashes: dict[str, str] = {}
    for topology in topology_definitions:
        revision_id = str(topology.get("revision_id") or "")
        if not revision_id:
            raise ValueError("ModuleTopologyDefinition requires revision_id")
        payload = deepcopy(dict(topology))
        digest = canonical_topology_asset_sha256(payload)
        if revision_id in indexed and hashes[revision_id] != digest:
            raise ValueError(
                f"conflicting topology payloads for revision {revision_id!r}"
            )
        indexed[revision_id] = payload
        hashes[revision_id] = digest
    return indexed


def topology_revisions_for_module(
    module_revision_id: str,
    topology_definitions: Mapping[str, Mapping[str, Any]],
) -> list[str]:
    result = [
        revision_id
        for revision_id, topology in topology_definitions.items()
        if str(topology.get("module_definition_revision_id") or "")
        == str(module_revision_id)
    ]
    return sorted(result)


def select_module_topology(
    module_definition: Mapping[str, Any],
    topology_definitions: Mapping[str, Mapping[str, Any]],
    *,
    topology_revision_id: str | None,
) -> dict[str, Any] | None:
    """Return an explicitly selected exact-revision topology.

    Absence means lower fidelity. Multiple available topologies are never silently
    ranked or auto-selected.
    """
    if topology_revision_id is None:
        return None
    try:
        topology = deepcopy(dict(topology_definitions[topology_revision_id]))
    except KeyError as exc:
        raise ValueError(
            f"module topology revision not available: {topology_revision_id}"
        ) from exc
    expected = str(module_definition.get("revision_id") or "")
    actual = str(topology.get("module_definition_revision_id") or "")
    if not expected or actual != expected:
        raise ValueError(
            "selected topology is not bound to the exact ModuleDefinition revision"
        )
    return topology


def _index_evidence(
    evidence_items: Sequence[Mapping[str, Any]],
) -> dict[str, dict[str, Any]]:
    indexed: dict[str, dict[str, Any]] = {}
    for evidence in evidence_items:
        evidence_id = str(evidence.get("evidence_id") or "")
        if not evidence_id:
            raise ValueError("ElectricalParameterizationEvidence requires evidence_id")
        payload = deepcopy(dict(evidence))
        previous = indexed.get(evidence_id)
        if previous is not None and previous != payload:
            raise ValueError(f"conflicting parameterization evidence {evidence_id!r}")
        indexed[evidence_id] = payload
    return indexed


def resolve_library_electrical_shading_capability(
    module_definition: Mapping[str, Any],
    *,
    topology_definition: Mapping[str, Any] | None = None,
    region_parameterization_evidence: Mapping[str, Any] | None = None,
    cell_parameterization_evidence: Mapping[str, Any] | None = None,
    resolved_component_model: Mapping[str, Any] | None = None,
    source_records: Mapping[str, Mapping[str, Any]] | None = None,
    resolution_id: str | None = None,
) -> dict[str, Any]:
    """Resolve product-facing fidelity from existing validated authorities.

    When `resolved_component_model` is omitted, the normal module-model resolver is
    invoked. Raw component capability flags are never used as the authority for
    detailed SDM readiness.
    """
    module = deepcopy(dict(module_definition))
    if topology_definition is not None:
        if source_records is None:
            raise ValueError(
                "selected ModuleTopologyDefinition requires a SourceRecord registry"
            )
        assert_library_source_bindings(
            topology_definition, source_records, label="ModuleTopologyDefinition"
        )
    for label, evidence in (
        ("region ElectricalParameterizationEvidence", region_parameterization_evidence),
        ("cell ElectricalParameterizationEvidence", cell_parameterization_evidence),
    ):
        if evidence is None:
            continue
        if source_records is None:
            raise ValueError(f"{label} requires a SourceRecord registry")
        assert_library_source_bindings(evidence, source_records, label=label)

    if resolved_component_model is None:
        rid = resolution_id or (
            "phase62-capability-" + str(module.get("revision_id") or "unbound")
        )
        resolved_component_model = resolve_module_model(
            module,
            resolution_id=rid,
        )

    module_snapshot = resolve_module_capability_snapshot(
        module,
        resolved_component_model,
    )
    topology_result = validate_topology_for_electrical_shading(
        module,
        topology_definition,
    )
    bypass_evidence = resolve_bypass_model_evidence(
        topology_definition,
        topology_result,
    )
    region_evidence = validate_parameterization_for_electrical_shading(
        region_parameterization_evidence,
        expected_scope="region_substring",
        module_definition=module,
        topology_definition=topology_definition,
    )
    cell_evidence = validate_parameterization_for_electrical_shading(
        cell_parameterization_evidence,
        expected_scope="cell",
        module_definition=module,
        topology_definition=topology_definition,
    )
    capability = resolve_electrical_shading_capability(
        module_snapshot,
        topology_result,
        bypass_model_evidence=bypass_evidence,
        region_parameterization_evidence=region_evidence,
        cell_parameterization_evidence=cell_evidence,
    )
    return {
        **deepcopy(capability),
        "library_integration_version": TOPOLOGY_LIBRARY_VERSION,
        "module_capability_snapshot": asdict(module_snapshot),
        "topology_validation": (
            asdict(topology_result) if topology_result is not None else None
        ),
        "bypass_model_evidence": (
            asdict(bypass_evidence) if bypass_evidence is not None else None
        ),
        "region_parameterization_evidence": (
            asdict(region_evidence) if region_evidence is not None else None
        ),
        "cell_parameterization_evidence": (
            asdict(cell_evidence) if cell_evidence is not None else None
        ),
    }


def build_module_capability_catalog_entry(
    module_definition: Mapping[str, Any],
    *,
    topology_definitions: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    """Summarize available topology revisions without silently selecting one."""
    revision_id = str(module_definition.get("revision_id") or "")
    topology_ids = topology_revisions_for_module(revision_id, topology_definitions)
    baseline = resolve_library_electrical_shading_capability(module_definition)
    return {
        "module_revision_id": revision_id,
        "topology_revision_ids": topology_ids,
        "topology_selection_required": bool(topology_ids),
        "maximum_fidelity_without_topology_selection": baseline[
            "maximum_fidelity_level"
        ],
        "available_fidelity_without_topology_selection": baseline[
            "available_fidelity_levels"
        ],
        "findings": deepcopy(baseline["findings"]),
    }


def resolve_selected_library_assets(
    module_definition: Mapping[str, Any],
    *,
    topology_definitions: Mapping[str, Mapping[str, Any]],
    parameterization_evidence: Sequence[Mapping[str, Any]] = (),
    topology_revision_id: str | None = None,
    region_parameterization_evidence_id: str | None = None,
    cell_parameterization_evidence_id: str | None = None,
    source_records: Mapping[str, Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Resolve one explicit product selection to the Phase-6.1 capability result."""
    topology = select_module_topology(
        module_definition,
        topology_definitions,
        topology_revision_id=topology_revision_id,
    )
    evidence = _index_evidence(parameterization_evidence)

    def pick(evidence_id: str | None) -> Mapping[str, Any] | None:
        if evidence_id is None:
            return None
        try:
            return evidence[evidence_id]
        except KeyError as exc:
            raise ValueError(
                f"parameterization evidence not available: {evidence_id}"
            ) from exc

    return resolve_library_electrical_shading_capability(
        module_definition,
        topology_definition=topology,
        region_parameterization_evidence=pick(
            region_parameterization_evidence_id
        ),
        cell_parameterization_evidence=pick(
            cell_parameterization_evidence_id
        ),
        source_records=source_records,
    )


def assert_numerical_assumption_source_bindings(
    module_definition: Mapping[str, Any],
    evidence: Mapping[str, Any],
    source_records: Mapping[str, Mapping[str, Any]],
    *, source_bytes: Mapping[str, bytes] | None = None,
) -> dict[str, Any]:
    """Resolve the three hash anchors from the caller's authenticated registry.

    Bytes are optional evidence, keyed by source ID. Hash declarations alone
    never establish possession of original bytes or manufacturer authenticity.
    """
    from jsonschema import Draft202012Validator
    from shading.electrical.contract import assert_numerical_assumption_evidence_structure

    assert_numerical_assumption_evidence_structure(evidence)
    indexed = index_source_records(list(source_records.values()))
    schema = json.loads((Path(__file__).resolve().parents[1] /
                         "schemas/source-record.schema.json").read_text())
    validator = Draft202012Validator(schema)
    for key, record in source_records.items():
        if record.get("source_id") != key:
            raise ValueError("SourceRecord registry identity mismatch")
        validator.validate(record)
    assert_library_source_bindings(evidence, indexed, label="numerical assumption evidence")
    declaration = evidence["assumption_declaration"]
    assumption_id = declaration["assumption_source_id"]
    if assumption_id not in evidence["source_ids"]:
        raise ValueError("assumption SourceRecord must belong to evidence.source_ids")
    assumption = indexed[assumption_id]
    if assumption["source_type"] not in {"user_input", "manual_entry"}:
        raise ValueError("assumption SourceRecord source_type must be user_input or manual_entry")
    for field in ("title", "source_notes"):
        value = assumption.get(field)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"assumption SourceRecord requires nonempty {field}")
    if "manufacturer" not in assumption or assumption["manufacturer"] is not None:
        raise ValueError("assumption SourceRecord manufacturer must be explicitly null")
    if assumption.get("file_hash") != declaration["digest_sha256"]:
        raise ValueError("assumption SourceRecord file_hash does not match declaration digest")

    anchors = declaration["module_source"]
    available = [indexed[key] for key in evidence["source_ids"] if key != assumption_id]
    original = [s for s in available if s.get("file_hash") == anchors["original_pan_sha256"]]
    retained = [s for s in available if s.get("file_hash") == anchors["retained_pan_sha256"]]
    pairs = [(a, b) for a in original for b in retained if a["source_id"] != b["source_id"]]
    if not pairs:
        raise ValueError("original and retained PAN hashes require two distinct resolved SourceRecords")
    # Cross-check the current Jinko reference convention without imposing
    # hash-as-ID source semantics on future modules.
    module_sources = set(module_definition.get("source_ids") or [])
    if anchors["retained_pan_sha256"] == "aff43dc4f6b5213abd87a14e0814fda47b8bb51bf7cb439bfa5fa590190229f3":
        if anchors["retained_pan_sha256"] not in module_sources:
            raise ValueError("Jinko retained PAN digest does not match module source identity")
    original_record, retained_record = sorted(
        pairs, key=lambda pair: (pair[0]["source_id"], pair[1]["source_id"])
    )[0]
    bytes_by_id = dict(source_bytes or {})
    # SourceRecord.filename is descriptive provenance, not filesystem authority.
    # The authenticated caller supplies accessible raw bytes by exact source ID;
    # this resolver never opens paths supplied by scientific input.
    strengths = {}
    for role, record, digest in (
        ("original", original_record, anchors["original_pan_sha256"]),
        ("retained", retained_record, anchors["retained_pan_sha256"]),
    ):
        raw = bytes_by_id.get(record["source_id"])
        if raw is not None:
            if not isinstance(raw, bytes) or hashlib.sha256(raw).hexdigest() != digest:
                raise ValueError(f"{role} PAN available bytes do not match declared digest")
            strengths[role] = "available bytes hash verified; no manufacturer signature asserted"
        else:
            strengths[role] = "source-record hash only; original-byte authenticity not independently verified" if role == "original" else "source-record hash only; retained bytes unavailable"
    return {"original_source_id": original_record["source_id"],
            "retained_source_id": retained_record["source_id"],
            "assumption_source_id": assumption_id, "byte_evidence": strengths}
