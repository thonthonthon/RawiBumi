"""Phase-6.2 project persistence for electrical-shading asset selections.

The bundle state here is product/simulation selection state, not Scene or
ElectricalDesignRevision authority. It pins exact topology/evidence/source assets
and derives capability through the frozen Phase-6.1 boundary.
"""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from typing import Any, Mapping

from components.topology_library import resolve_selected_library_assets
from shading.electrical import assert_requested_fidelity_available


STATE_VERSION = "0.1"
ASSET_KINDS = {
    "module_topologies",
    "electrical_parameterization_definitions",
    "electrical_parameterization_evidence",
    "sources",
}


def _canonical_sha256(value: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def ensure_electrical_shading_bundle_state(bundle: dict[str, Any]) -> None:
    pinned = bundle.setdefault("pinned_electrical_shading_assets", {})
    for kind in sorted(ASSET_KINDS):
        pinned.setdefault(kind, {})
    bundle.setdefault("electrical_shading_selections", {})




_SELECTION_IDENTITY_FIELDS = (
    "state_version",
    "module_definition_revision_id",
    "module_topology_revision_id",
    "region_parameterization_evidence_id",
    "cell_parameterization_evidence_id",
    "requested_fidelity",
    "resolved_fidelity",
    "fallback_policy",
)

def assert_electrical_shading_selection_state(bundle: Mapping[str, Any]) -> None:
    """Validate persisted Phase-6.2 selection identity and replay pins.

    Pre-6.2 bundles with no selection state remain valid. Once a selection exists,
    all referenced topology/evidence/source assets must be pinned in the project so
    replay does not depend on a mutable catalog.
    """
    selections = bundle.get("electrical_shading_selections")
    if selections is None:
        return
    if not isinstance(selections, Mapping):
        raise ValueError("electrical_shading_selections must be an object")

    pinned_components = bundle.get("pinned_components") or {}
    pinned_modules = pinned_components.get("modules") or {}
    pinned = bundle.get("pinned_electrical_shading_assets") or {}
    topologies = pinned.get("module_topologies") or {}
    evidence = pinned.get("electrical_parameterization_evidence") or {}
    sources = pinned.get("sources") or {}

    def require_sources(asset: Mapping[str, Any], label: str) -> None:
        source_ids = asset.get("source_ids") or []
        missing = sorted(str(s) for s in source_ids if str(s) not in sources)
        if missing:
            raise ValueError(f"{label} has unpinned SourceRecord ids: {missing}")

    for module_key, raw in selections.items():
        if not isinstance(raw, Mapping):
            raise ValueError(f"electrical shading selection {module_key!r} must be an object")
        selection = dict(raw)
        module_revision_id = str(selection.get("module_definition_revision_id") or "")
        if not module_revision_id or str(module_key) != module_revision_id:
            raise ValueError("electrical shading selection key must equal module_definition_revision_id")
        if module_revision_id not in pinned_modules:
            raise ValueError(f"selected module revision is not project-pinned: {module_revision_id}")
        if selection.get("state_version") != STATE_VERSION:
            raise ValueError("unsupported electrical shading selection state_version")
        identity = {field: selection.get(field) for field in _SELECTION_IDENTITY_FIELDS}
        expected_hash = _canonical_sha256(identity)
        if selection.get("selection_payload_sha256") != expected_hash:
            raise ValueError("electrical shading selection identity hash mismatch")

        topology_id = selection.get("module_topology_revision_id")
        if topology_id is not None:
            topology = topologies.get(str(topology_id))
            if not isinstance(topology, Mapping):
                raise ValueError(f"selected topology revision is not project-pinned: {topology_id}")
            if str(topology.get("module_definition_revision_id") or "") != module_revision_id:
                raise ValueError("pinned topology is not bound to selected module revision")
            require_sources(topology, f"topology {topology_id}")

        for field, expected_scope in (
            ("region_parameterization_evidence_id", "region_substring"),
            ("cell_parameterization_evidence_id", "cell"),
        ):
            evidence_id = selection.get(field)
            if evidence_id is None:
                continue
            item = evidence.get(str(evidence_id))
            if not isinstance(item, Mapping):
                raise ValueError(f"selected parameterization evidence is not project-pinned: {evidence_id}")
            if item.get("parameterization_scope") != expected_scope:
                raise ValueError(f"{field} does not have scope {expected_scope!r}")
            if str(item.get("module_definition_revision_id") or "") != module_revision_id:
                raise ValueError("pinned parameterization evidence has stale module revision binding")
            if str(item.get("module_topology_revision_id") or "") != str(topology_id or ""):
                raise ValueError("pinned parameterization evidence has stale topology revision binding")
            require_sources(item, f"parameterization evidence {evidence_id}")


def _asset_definitions(
    bundle: Mapping[str, Any],
    catalog: Mapping[str, Any],
    kind: str,
) -> dict[str, dict[str, Any]]:
    if kind not in ASSET_KINDS:
        raise ValueError(f"unsupported electrical-shading asset kind {kind!r}")
    merged = deepcopy(dict(catalog.get(kind) or {}))
    pinned = (bundle.get("pinned_electrical_shading_assets") or {}).get(kind) or {}
    merged.update(deepcopy(dict(pinned)))
    return merged


def _module_definitions(
    bundle: Mapping[str, Any],
    catalog: Mapping[str, Any],
) -> dict[str, dict[str, Any]]:
    merged = deepcopy(dict(catalog.get("modules") or {}))
    pinned = (bundle.get("pinned_components") or {}).get("modules") or {}
    merged.update(deepcopy(dict(pinned)))
    return merged


def pin_electrical_shading_asset(
    bundle: dict[str, Any],
    catalog: Mapping[str, Any],
    *,
    kind: str,
    asset_id: str,
) -> dict[str, Any]:
    """Pin one exact library asset and its referenced SourceRecords."""
    ensure_electrical_shading_bundle_state(bundle)
    definitions = _asset_definitions(bundle, catalog, kind)
    try:
        asset = deepcopy(definitions[str(asset_id)])
    except KeyError as exc:
        raise ValueError(f"{kind} asset not available: {asset_id}") from exc

    bundle["pinned_electrical_shading_assets"][kind][str(asset_id)] = deepcopy(asset)
    if kind != "sources":
        for source_id in asset.get("source_ids") or []:
            pin_electrical_shading_asset(
                bundle,
                catalog,
                kind="sources",
                asset_id=str(source_id),
            )
    return asset


def import_project_electrical_shading_asset(
    bundle: dict[str, Any],
    *,
    asset_kind: str,
    asset: Mapping[str, Any],
    sources: list[Mapping[str, Any]],
) -> dict[str, Any]:
    """Validate and pin a user/local JSON topology or parameterization asset.

    Import is explicit and never creates topology from module counts. Source records
    travel with the asset and become project-pinned replay evidence.
    """
    from components.topology_library import (
        assert_library_source_bindings,
        index_source_records,
    )
    from shading.electrical import (
        assert_electrical_parameterization_evidence,
        assert_module_topology_definition,
    )

    ensure_electrical_shading_bundle_state(bundle)
    source_index = index_source_records(sources)
    for source_id, source in source_index.items():
        if source.get("schema_name") != "SourceRecord" or source.get("schema_version") != "0.1":
            raise ValueError("imported source must be SourceRecord v0.1")
        existing = bundle["pinned_electrical_shading_assets"]["sources"].get(source_id)
        if existing is not None and existing != source:
            raise ValueError(f"conflicting pinned SourceRecord {source_id!r}")
        bundle["pinned_electrical_shading_assets"]["sources"][source_id] = deepcopy(source)

    payload = deepcopy(dict(asset))
    if asset_kind == "module_topology":
        assert_module_topology_definition(payload)
        assert_library_source_bindings(payload, source_index, label="imported ModuleTopologyDefinition")
        asset_id = str(payload["revision_id"])
        target_kind = "module_topologies"
    elif asset_kind == "electrical_parameterization_evidence":
        assert_electrical_parameterization_evidence(payload)
        assert_library_source_bindings(payload, source_index, label="imported ElectricalParameterizationEvidence")
        asset_id = str(payload["evidence_id"])
        target_kind = "electrical_parameterization_evidence"
    elif asset_kind == "electrical_parameterization_definition":
        from shading.electrical.parameterization import assert_electrical_parameterization_definition
        topology_id = str(payload.get("module_topology_revision_id") or "")
        topology = bundle["pinned_electrical_shading_assets"]["module_topologies"].get(topology_id)
        if topology is None:
            raise ValueError("parameterization definition requires an exact pinned topology")
        assert_electrical_parameterization_definition(payload, topology)
        assert_library_source_bindings(payload, source_index, label="imported parameterization definition")
        asset_id = str(payload["revision_id"])
        target_kind = "electrical_parameterization_definitions"
    else:
        raise ValueError("unsupported electrical-shading asset_kind")

    target = bundle["pinned_electrical_shading_assets"][target_kind]
    existing = target.get(asset_id)
    if existing is not None and existing != payload:
        raise ValueError(f"conflicting pinned electrical-shading asset {asset_id!r}")
    target[asset_id] = payload
    return {"asset_kind": asset_kind, "asset_id": asset_id, "asset": deepcopy(payload), "sources": deepcopy(source_index)}


def pin_module_definition(
    bundle: dict[str, Any],
    catalog: Mapping[str, Any],
    module_revision_id: str,
) -> dict[str, Any]:
    modules = _module_definitions(bundle, catalog)
    try:
        module = deepcopy(modules[str(module_revision_id)])
    except KeyError as exc:
        raise ValueError(
            f"module component revision not available: {module_revision_id}"
        ) from exc
    bundle.setdefault("pinned_components", {}).setdefault("modules", {})[
        str(module_revision_id)
    ] = deepcopy(module)
    return module


def resolve_project_module_electrical_shading_capability(
    bundle: Mapping[str, Any],
    catalog: Mapping[str, Any],
    *,
    module_revision_id: str,
    topology_revision_id: str | None = None,
    region_parameterization_evidence_id: str | None = None,
    cell_parameterization_evidence_id: str | None = None,
) -> dict[str, Any]:
    modules = _module_definitions(bundle, catalog)
    try:
        module = modules[str(module_revision_id)]
    except KeyError as exc:
        raise ValueError(
            f"module component revision not available: {module_revision_id}"
        ) from exc

    topologies = _asset_definitions(bundle, catalog, "module_topologies")
    evidence = _asset_definitions(
        bundle, catalog, "electrical_parameterization_evidence"
    )
    sources = _asset_definitions(bundle, catalog, "sources")
    return resolve_selected_library_assets(
        module,
        topology_definitions=topologies,
        parameterization_evidence=list(evidence.values()),
        topology_revision_id=topology_revision_id,
        region_parameterization_evidence_id=region_parameterization_evidence_id,
        cell_parameterization_evidence_id=cell_parameterization_evidence_id,
        source_records=sources,
    )


def set_project_module_electrical_shading_selection(
    bundle: dict[str, Any],
    catalog: Mapping[str, Any],
    *,
    module_revision_id: str,
    requested_fidelity: str,
    fallback_policy: str = "fail_closed",
    topology_revision_id: str | None = None,
    region_parameterization_evidence_id: str | None = None,
    cell_parameterization_evidence_id: str | None = None,
) -> dict[str, Any]:
    """Pin explicit assets and persist one explicit module-revision selection."""
    ensure_electrical_shading_bundle_state(bundle)
    pin_module_definition(bundle, catalog, module_revision_id)

    if topology_revision_id is not None:
        pin_electrical_shading_asset(
            bundle,
            catalog,
            kind="module_topologies",
            asset_id=topology_revision_id,
        )
    for evidence_id in (
        region_parameterization_evidence_id,
        cell_parameterization_evidence_id,
    ):
        if evidence_id is not None:
            pin_electrical_shading_asset(
                bundle,
                catalog,
                kind="electrical_parameterization_evidence",
                asset_id=evidence_id,
            )

    capability = resolve_project_module_electrical_shading_capability(
        bundle,
        catalog,
        module_revision_id=module_revision_id,
        topology_revision_id=topology_revision_id,
        region_parameterization_evidence_id=region_parameterization_evidence_id,
        cell_parameterization_evidence_id=cell_parameterization_evidence_id,
    )
    resolved_fidelity = assert_requested_fidelity_available(
        requested_fidelity,
        capability,
        fallback_policy=fallback_policy,
    )
    fallback_applied = resolved_fidelity != requested_fidelity
    selection_identity = {
        "state_version": STATE_VERSION,
        "module_definition_revision_id": str(module_revision_id),
        "module_topology_revision_id": topology_revision_id,
        "region_parameterization_evidence_id": region_parameterization_evidence_id,
        "cell_parameterization_evidence_id": cell_parameterization_evidence_id,
        "requested_fidelity": requested_fidelity,
        "resolved_fidelity": resolved_fidelity,
        "fallback_policy": fallback_policy,
    }
    selection = {
        **selection_identity,
        "fallback_applied": fallback_applied,
        "fallback_reason": (
            None
            if not fallback_applied
            else (
                f"requested {requested_fidelity} unavailable; explicitly resolved "
                f"to {resolved_fidelity}"
            )
        ),
        "selection_payload_sha256": _canonical_sha256(selection_identity),
        "capability_snapshot": {
            "available_fidelity_levels": deepcopy(
                capability["available_fidelity_levels"]
            ),
            "maximum_fidelity_level": capability["maximum_fidelity_level"],
            "bypass_assumption_ids": deepcopy(
                capability.get("bypass_assumption_ids") or []
            ),
            "findings": deepcopy(capability.get("findings") or []),
        },
    }
    bundle["electrical_shading_selections"][str(module_revision_id)] = deepcopy(
        selection
    )
    return {
        "selection": deepcopy(selection),
        "capability": deepcopy(capability),
    }
