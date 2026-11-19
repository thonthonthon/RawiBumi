"""Phase 6.9A pinned module inputs; no numerical dispatch is activated here.

Snapshots own canonical JSON bytes, rather than mutable caller dictionaries.
Replay revalidates both the outer content digest and the Phase 6 contracts.
"""

from __future__ import annotations

from copy import deepcopy
from functools import lru_cache
from dataclasses import dataclass, field
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError

from engine.irradiance import POA_ISOTROPIC
from engine.inverter import INVERTER_VOLTAGE_DEPENDENT, INVERTER_VOLTAGE_DEPENDENT_BOUNDED
from engine.module import MODULE_PVSYST_SDM
from engine.optical import SUPPORTED_IAM_MODELS
from engine.solar import SOLAR_POSITION_NREL_SPA
from engine.thermal import THERMAL_PVSYST
from geometry.shading import BEAM_SOLVER_ID, SKY_VISIBILITY_SOLVER_ID, GROUND_VISIBILITY_SOLVER_ID
from geometry.shading.contract import assert_geometry_aware_shading_configuration
from shading.electrical import assert_requested_fidelity_available
from shading.electrical.module_iv import MODULE_NONUNIFORM_IV_SOLVER_ID
from shading.electrical.mppt_tracker import IDEAL_GLOBAL_MPPT_MODEL_ID
from shading.electrical.parameterization import (
    REGION_PARAMETERIZATION_MODEL_ID,
    assert_electrical_parameterization_definition,
    assert_parameterization_evidence_binding,
)
from shading.electrical.string_iv import GENERAL_SERIES_STRING_IV_SOLVER_ID

ROOT = Path(__file__).resolve().parents[2]
DETAILED_SCOPE = "fixed_tilt_detailed_electrical_phase69a.v0.1"
DETAILED_FIDELITY = "level_2_bypass_substring"


class DetailedInputError(ValueError):
    """Pinned science or requested runtime cannot be executed safely."""


def _bytes(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode("utf-8")


def _schema(value: Mapping[str, Any], relative_path: str) -> None:
    schema = json.loads((ROOT / relative_path).read_text(encoding="utf-8"))
    Draft202012Validator(schema).validate(value)


@dataclass(frozen=True)
class DetailedModuleInputSnapshot:
    """Immutable serialized assets with a separately persisted expected digest."""

    canonical_payload: bytes
    scientific_input_sha256: str
    witness: AssumptionSnapshotWitness | None = field(default=None, repr=False)

    def replay(self) -> dict[str, Any]:
        error_type = DetailedInputError if self.witness is None else SnapshotWitnessError
        if self.witness is not None and type(self.witness) is not AssumptionSnapshotWitness:
            raise SnapshotWitnessError("snapshot witness type is invalid")
        if hashlib.sha256(self.canonical_payload).hexdigest() != self.scientific_input_sha256:
            raise error_type("detailed input snapshot hash mismatch")
        payload = json.loads(self.canonical_payload)
        if _bytes(payload) != self.canonical_payload:
            raise error_type("detailed input snapshot is not canonical JSON")
        if self.witness is not None:
            validate_snapshot_witness(self.witness, payload, self.scientific_input_sha256)
        _validate_payload(payload, authorization_witness=self.witness)
        return payload


def validate_synthetic_region_option(electrical: Mapping[str, Any]) -> bool:
    """Read strict scientific intent without granting execution permission."""
    from shading.electrical.contract import NumericalAssumptionInputError
    options = electrical.get("scientific_options", {})
    if not isinstance(options, Mapping):
        raise NumericalAssumptionInputError("scientific_options must be an object")
    value = options.get("allow_synthetic_regions", False)
    if type(value) is not bool:
        raise NumericalAssumptionInputError(
            "scientific_options.allow_synthetic_regions must be an explicit boolean")
    return value


def deny_selected_numerical_evidence(evidence, *, module=None, topology=None,
                                    parameterization=None, authorization_witness=None):
    """Default-deny selected numerical inputs without complete bound authority."""
    from shading.electrical.contract import (
        NumericalAssumptionInputError, assert_numerical_assumption_evidence_structure,
    )
    if evidence.get("schema_version") != "0.2" and "evidence_class" not in evidence:
        return
    prefix = "NUMERICAL_ASSUMPTION_EXECUTION_DENIED: B3 "
    if evidence.get("parameterization_scope") != "region_substring":
        raise NumericalAssumptionInputError(prefix + "unsupported numerical-assumption scope: region_substring required")
    try:
        if not all(isinstance(asset, Mapping) for asset in (module, topology, parameterization)):
            raise ValueError("selected numerical assets must be mappings")
        if (evidence.get("schema_version"), evidence.get("evidence_class")) != (
                "0.2", "NUMERICAL_ASSUMPTION"):
            raise ValueError("inconsistent evidence schema_version/evidence_class")
        assert_numerical_assumption_evidence_structure(evidence)
        if module is None or module.get("revision_id") != evidence["module_definition_revision_id"]:
            raise ValueError("selected module revision mismatch")
        if topology is None or topology.get("revision_id") != evidence["module_topology_revision_id"]:
            raise ValueError("selected topology revision mismatch")
        if (parameterization is None or
                parameterization.get("revision_id") != evidence["parameterization_revision_id"] or
                parameterization.get("parameterization_id") != evidence["parameterization_id"]):
            raise ValueError("selected parameterization identity/revision mismatch")
        assert_electrical_parameterization_definition(parameterization, topology)
        # The executable v0.1 binding validator deliberately rejects v0.2.
        # Check recorded membership here without granting executable readiness.
        _assert_numerical_parameterization_binding(parameterization, evidence)
    except (ValueError, KeyError, TypeError) as exc:
        raise NumericalAssumptionInputError(prefix + str(exc)) from exc
    if authorization_witness is None:
        raise NumericalAssumptionInputError(prefix + "authenticated execution is not enabled")
    _assert_witness_structure(authorization_witness)
    expected = build_detailed_snapshot_witness(
        authorization_witness.context, authorization_witness.module_revision_id)
    if authorization_witness != expected:
        raise SnapshotWitnessError("snapshot witness membership or digest mismatch")
    authority = NumericalAssumptionAuthority(authorization_witness)
    selected = json.loads(_selected_witness_bytes(
        authorization_witness.context, authorization_witness.module_revision_id))
    if any(selected[key] != asset for key, asset in (
            ("module", module), ("topology", topology), ("parameterization", parameterization),
            ("evidence", evidence))):
        raise SnapshotWitnessError("selected numerical asset membership mismatch")
    from shading.electrical.contract import deny_numerical_assumption_execution
    deny_numerical_assumption_execution(evidence, authority=authority)


def deny_selected_numerical_assumptions(bundle):
    from apps.api.electrical_shading_state import assert_electrical_shading_selection_state
    assert_electrical_shading_selection_state(bundle)
    assets = bundle.get("pinned_electrical_shading_assets") or {}
    registry = assets.get("electrical_parameterization_evidence") or {}
    modules = (bundle.get("pinned_components") or {}).get("modules") or {}
    for selection in (bundle.get("electrical_shading_selections") or {}).values():
        for identity_field in ("module_definition_revision_id", "module_topology_revision_id"):
            identifier = selection.get(identity_field)
            if identifier is not None and not isinstance(identifier, str):
                raise ValueError(f"selected {identity_field} must be a string")
        for field in ("region_parameterization_evidence_id", "cell_parameterization_evidence_id"):
            evidence_id = selection.get(field)
            if evidence_id is not None and not isinstance(evidence_id, str):
                raise ValueError("selected parameterization evidence identifier must be a string")
            evidence = registry.get(evidence_id)
            if isinstance(evidence, Mapping):
                deny_selected_numerical_evidence(
                    evidence, module=modules.get(selection.get("module_definition_revision_id")),
                    topology=(assets.get("module_topologies") or {}).get(
                        selection.get("module_topology_revision_id")),
                    parameterization=(assets.get("electrical_parameterization_definitions") or {}).get(
                        evidence.get("parameterization_revision_id")))


def _validate_quality_declaration(evidence, sources):
    """Validate the declaration on both module pinning and frozen/package replay."""
    declaration = evidence.get("module_quality_declaration")
    if declaration is None:
        return
    from components.topology_library import assert_library_source_bindings
    _schema(evidence, "shading/electrical/electrical-parameterization-evidence.schema.json")
    assert_library_source_bindings(declaration, sources, label="module quality declaration")
    if not set(declaration["source_ids"]).issubset(evidence["source_ids"]):
        raise DetailedInputError("module quality declaration sources must belong to parameterization evidence")
    for source_id in declaration["source_ids"]:
        if sources[source_id].get("source_id") != source_id:
            raise DetailedInputError("module quality declaration source registry identity mismatch")
        _schema(sources[source_id], "schemas/source-record.schema.json")


def _validate_payload(payload: Mapping[str, Any], *, authorization_witness=None) -> None:
    from components.topology_library import (
        assert_library_source_bindings,
        resolve_library_electrical_shading_capability,
    )
    if set(payload) != {"module", "topology", "parameterization", "evidence", "sources"}:
        raise DetailedInputError("detailed input snapshot fields are not exact")
    module, topology = payload["module"], payload["topology"]
    definition, evidence, sources = (
        payload["parameterization"], payload["evidence"], payload["sources"]
    )
    deny_selected_numerical_evidence(evidence, module=module, topology=topology,
                                    parameterization=definition,
                                    authorization_witness=authorization_witness)
    for value, schema in (
        (module, "components/schema/module-definition.schema.json"),
        (topology, "components/schema/module-topology-definition.schema.json"),
        (definition, "shading/electrical/electrical-parameterization-definition.schema.json"),
        (evidence, "shading/electrical/electrical-parameterization-evidence.schema.json"),
    ):
        _schema(value, schema)
    for source_id, source in sources.items():
        if source.get("source_id") != source_id:
            raise DetailedInputError("source registry key does not match source_id")
        _schema(source, "schemas/source-record.schema.json")
    for label, asset in (("topology", topology), ("parameterization", definition),
                         ("evidence", evidence)):
        assert_library_source_bindings(asset, sources, label=label)
    _validate_quality_declaration(evidence, sources)
    # Component-authoritative bypass models may carry additional source records.
    for device in topology["bypass_devices"]:
        model = device["forward_voltage_model"]
        if model.get("source_ids"):
            assert_library_source_bindings(model, sources, label="bypass model")
    assert_electrical_parameterization_definition(definition, topology)
    if evidence.get("schema_version") == "0.2":
        # The full selected witness gate above supplies numerical authority;
        # manufacturer/source-backed capability classifications remain unchanged.
        validate_snapshot_witness(authorization_witness, payload, hashlib.sha256(_bytes(payload)).hexdigest())
        _assert_numerical_parameterization_binding(definition, evidence)
        return
    assert_parameterization_evidence_binding(definition, evidence)
    capability = resolve_library_electrical_shading_capability(
        module, topology_definition=topology,
        region_parameterization_evidence=evidence, source_records=sources,
    )
    assert_requested_fidelity_available(DETAILED_FIDELITY, capability)


def pin_detailed_module_inputs(
    *, module: Mapping[str, Any], topology: Mapping[str, Any],
    parameterization: Mapping[str, Any], evidence: Mapping[str, Any],
    sources: Mapping[str, Mapping[str, Any]],
    authorization_witness=None,
) -> DetailedModuleInputSnapshot:
    """Copy, validate and pin exact assets; never synthesize regional parameters."""
    payload = deepcopy(dict(module=module, topology=topology,
                            parameterization=parameterization, evidence=evidence,
                            sources=sources))
    _validate_payload(payload, authorization_witness=authorization_witness)
    encoded = _bytes(payload)
    return DetailedModuleInputSnapshot(encoded, hashlib.sha256(encoded).hexdigest(), authorization_witness)


def _verify_assumption_inputs(configuration, snapshot):
    """Fresh selected-input verification; returns bytes-derived data, no permit."""
    from shading.electrical.contract import NumericalAssumptionInputError
    from shading.electrical.parameterization import validate_numerical_assumption_acceptance
    bundle = snapshot._replay_structure()
    assets = bundle["pinned_electrical_shading_assets"]
    registry = assets.get("electrical_parameterization_evidence", {})
    selected = {}
    for revision, selection in bundle["electrical_shading_selections"].items():
        for field in ("region_parameterization_evidence_id", "cell_parameterization_evidence_id"):
            evidence_id = selection.get(field)
            if evidence_id is None:
                continue
            evidence = registry[evidence_id]
            if evidence.get("schema_version") == "0.2" or "evidence_class" in evidence:
                selected[revision] = selection
    if not selected:
        return {}
    # Persisted scientific projection intentionally omits execution_options.
    # Restore the schema-only empty field; it supplies no scientific authority.
    configuration = deepcopy(configuration)
    configuration["shading_configuration"]["electrical_shading_configuration"].setdefault("execution_options", {})
    context = build_snapshot_witness_context(configuration, snapshot)
    electrical = configuration["shading_configuration"]["electrical_shading_configuration"]
    if not validate_synthetic_region_option(electrical):
        raise NumericalAssumptionInputError("verification requires scientific opt-in")
    if electrical.get("fallback_policy") != "fail_closed":
        raise NumericalAssumptionInputError("verification requires fail_closed policy")
    solver = str((configuration.get("numerical_options") or {}).get("module_solver", "lambertw"))
    payloads = {}
    for revision, selection in sorted(selected.items()):
        if selection.get("fallback_policy") != "fail_closed":
            raise NumericalAssumptionInputError("selected assumption requires fail_closed policy")
        _assert_assumption_execution_policy(configuration, selection)
        # Resolve revision-bound assets and all source relationships afresh.
        payload = _selected_witness_payload(bundle, revision)
        witness = build_detailed_snapshot_witness(context, revision)
        compare_snapshot_witness_context(witness, configuration, snapshot)
        validate_numerical_assumption_acceptance(
            payload["module"], payload["topology"], payload["parameterization"],
            payload["evidence"], payload["sources"], solver=solver, use_cache=False)
        payloads[revision] = payload
    return payloads


def validate_detailed_runtime_support(
    simulation_configuration: Mapping[str, Any],
    snapshot: DetailedModuleInputSnapshot,
) -> str:
    """Validate the first detailed reference envelope, independently of Phase 5.

    This is a preflight contract, not an execution dispatcher. Current-limit
    enforcement and canonical topology/interval validation remain downstream.
    """
    shading = simulation_configuration.get("shading_configuration") or {}
    electrical = shading.get("electrical_shading_configuration")
    if not isinstance(electrical, Mapping):
        raise DetailedInputError("explicit electrical_shading_configuration required")
    validate_synthetic_region_option(electrical)
    payload = snapshot.replay()
    _schema(electrical, "shading/electrical/electrical-shading-configuration.schema.json")
    if electrical["requested_fidelity"] != DETAILED_FIDELITY:
        raise DetailedInputError("detailed runtime supports only Level 2")
    # Validate geometric settings through the unchanged Phase-5 contract, using
    # a private geometry-only projection. Never pass detailed requests to it.
    geometry = deepcopy(dict(shading))
    geometry.pop("electrical_shading_configuration", None)
    if geometry.get("electrical_shading_method") not in (None, "none", "not_modeled"):
        raise DetailedInputError("legacy electrical_shading_method must remain disabled")
    assert_geometry_aware_shading_configuration(geometry)
    for field, expected in (("beam_method", BEAM_SOLVER_ID),
                            ("diffuse_method", SKY_VISIBILITY_SOLVER_ID),
                            ("albedo_method", GROUND_VISIBILITY_SOLVER_ID)):
        if geometry.get(field) != expected:
            raise DetailedInputError(f"unsupported detailed {field}")
    if geometry.get("sun_position_resolution_seconds") is not None:
        raise DetailedInputError("detailed execution requires canonical solar timestamps")
    if geometry.get("receiver_granularity") != "module":
        raise DetailedInputError("canonical geometry requires module receiver granularity")
    selections = simulation_configuration.get("model_selections") or {}
    optics = simulation_configuration.get("numerical_options", {}).get("optics_thermal_settings")
    allowed_transposition = POA_ISOTROPIC
    if optics is not None:
        from .optics_thermal import resolve_optics_thermal_settings, TRANSPOSITION
        allowed_transposition = TRANSPOSITION[resolve_optics_thermal_settings(optics)["values"]["transposition"]]
    for field, expected in (("transposition", allowed_transposition),
                            ("temperature", THERMAL_PVSYST),
                            ("module_electrical", MODULE_PVSYST_SDM),
                            ("solar_position", SOLAR_POSITION_NREL_SPA),
                            ("inverter", INVERTER_VOLTAGE_DEPENDENT)):
        if field == "inverter" and selections.get(field) in {INVERTER_VOLTAGE_DEPENDENT, INVERTER_VOLTAGE_DEPENDENT_BOUNDED}:
            continue
        if selections.get(field) != expected:
            raise DetailedInputError(f"unsupported detailed {field}")
    if selections.get("iam") is not None and selections["iam"] not in SUPPORTED_IAM_MODELS and not (optics is not None and selections["iam"] == "component_default"):
        raise DetailedInputError("unsupported detailed IAM model")
    models = electrical["model_selections"]
    expected_models = {
        "module_electrical_model_id": MODULE_PVSYST_SDM,
        "region_parameterization_model_id": REGION_PARAMETERIZATION_MODEL_ID,
        "cell_parameterization_model_id": None,
        "module_iv_assembly_model_id": MODULE_NONUNIFORM_IV_SOLVER_ID,
        "string_iv_assembly_model_id": GENERAL_SERIES_STRING_IV_SOLVER_ID,
        "mppt_operating_point_model_id": IDEAL_GLOBAL_MPPT_MODEL_ID,
    }
    for field, expected in expected_models.items():
        if models[field] != expected:
            raise DetailedInputError(f"unsupported detailed {field}")
    bypass_ids = {device["forward_voltage_model"]["model_id"]
                  for device in payload["topology"]["bypass_devices"]}
    if bypass_ids != {models["bypass_model_family_id"]}:
        raise DetailedInputError("bypass model selection does not match pinned models")
    if any(device["forward_voltage_model"]["model_type"] not in
           {"ideal", "constant_forward_drop"}
           for device in payload["topology"]["bypass_devices"]):
        raise DetailedInputError("unsupported detailed bypass model type")
    if set(electrical["scientific_options"]) - {"string_sample_count", "allow_synthetic_regions"} or electrical["execution_options"]:
        raise DetailedInputError("unsupported detailed numerical/execution options")
    count = electrical["scientific_options"].get("string_sample_count", 201)
    if isinstance(count, bool) or not isinstance(count, int) or count < 101:
        raise DetailedInputError("detailed string_sample_count must be an integer >= 101")
    losses = (simulation_configuration.get("numerical_options") or {}).get("losses") or {}
    for name in ("module_mismatch_loss_fraction", "string_mismatch_loss_fraction"):
        if losses.get(name, 0.0) != 0.0:
            raise DetailedInputError(f"nonzero {name} has no distinct residual semantic")
    # Quality remains pinned; no downstream quality factor is applied at this boundary.
    return DETAILED_SCOPE


def semantic_scientific_payload(value: Any) -> Any:
    """Normalize only declared unordered source sets; preserve circuit order."""
    if isinstance(value, Mapping):
        return {key: (sorted(item) if key == "source_ids" else
                      semantic_scientific_payload(item)) for key, item in value.items()}
    if isinstance(value, list):
        return [semantic_scientific_payload(item) for item in value]
    return value


@dataclass(frozen=True)
class FrozenDetailedSelectionSnapshot:
    """Workspace selection/assets frozen independently of catalog and UI state."""

    canonical_payload: bytes
    payload_sha256: str
    scientific_input_sha256: str

    def _replay_structure(self) -> dict[str, Any]:
        """Identity validation only; never an execution or readiness decision."""
        if hashlib.sha256(self.canonical_payload).hexdigest() != self.payload_sha256:
            raise DetailedInputError("frozen detailed selection payload hash mismatch")
        payload = json.loads(self.canonical_payload)
        if set(payload) != {"pinned_components", "pinned_electrical_shading_assets", "electrical_shading_selections"}:
            raise DetailedInputError("frozen selection contains non-scientific workspace fields")
        if _bytes(payload) != self.canonical_payload:
            raise DetailedInputError("frozen detailed selection is not canonical JSON")
        if hashlib.sha256(_bytes(semantic_scientific_payload(payload))).hexdigest() != self.scientific_input_sha256:
            raise DetailedInputError("frozen detailed selection scientific hash mismatch")
        # Reuse the existing exact selection identity and replay-pin checks.
        from apps.api.electrical_shading_state import assert_electrical_shading_selection_state
        assert_electrical_shading_selection_state(payload)
        return payload

    def replay(self) -> dict[str, Any]:
        payload = self._replay_structure()
        # Frozen replay is structural transport, never a module execution permit
        # (accepted traceability §5.1). Resolve all selected v0.2 membership here.
        assets = payload["pinned_electrical_shading_assets"]
        registry = assets.get("electrical_parameterization_evidence", {})
        for revision, selection in payload["electrical_shading_selections"].items():
            for field in ("region_parameterization_evidence_id", "cell_parameterization_evidence_id"):
                evidence = registry.get(selection.get(field), {})
                if evidence.get("schema_version") == "0.2" or "evidence_class" in evidence:
                    try:
                        _selected_witness_payload(payload, revision)
                    except (ValueError, KeyError, TypeError, ValidationError) as exc:
                        from shading.electrical.contract import NumericalAssumptionInputError
                        raise NumericalAssumptionInputError(
                            "NUMERICAL_ASSUMPTION_EXECUTION_DENIED: B3 " + str(exc)) from exc
        return self._validate_replay_assets(payload)

    def _validate_replay_assets(self, payload):
        """Non-denying replay checks shared by execution and verification."""
        assets = payload["pinned_electrical_shading_assets"]
        for evidence in assets.get("electrical_parameterization_evidence", {}).values():
            _validate_quality_declaration(evidence, assets.get("sources", {}))
        for key, definition in assets.get("electrical_parameterization_definitions", {}).items():
            if key != definition.get("revision_id"):
                raise DetailedInputError("parameterization registry key does not match revision_id")
        return payload

    def record(self) -> dict[str, Any]:
        return {"payload": self.replay(), "payload_sha256": self.payload_sha256,
                "scientific_input_sha256": self.scientific_input_sha256}

    @classmethod
    def from_record(cls, record: Mapping[str, Any]) -> FrozenDetailedSelectionSnapshot:
        snapshot = cls(_bytes(record["payload"]), record["payload_sha256"],
                       record["scientific_input_sha256"])
        snapshot.replay()
        return snapshot


def freeze_detailed_selection(bundle: Mapping[str, Any]) -> FrozenDetailedSelectionSnapshot:
    """Freeze science only; never copy workspace, run history or catalog state."""
    payload = deepcopy({
        "pinned_components": {"modules": (bundle.get("pinned_components") or {}).get("modules", {})},
        "pinned_electrical_shading_assets": bundle.get("pinned_electrical_shading_assets", {}),
        "electrical_shading_selections": bundle.get("electrical_shading_selections", {}),
    })
    encoded = _bytes(payload)
    snapshot = FrozenDetailedSelectionSnapshot(
        encoded, hashlib.sha256(encoded).hexdigest(),
        hashlib.sha256(_bytes(semantic_scientific_payload(payload))).hexdigest(),
    )
    snapshot.replay()
    return snapshot


class SnapshotWitnessError(ValueError):
    """Invalid witness identity; deliberately not fallback-eligible."""


@dataclass(frozen=True)
class SnapshotWitnessContext:
    """Shared content-bound context, not a signed producer or execution permit."""

    canonical_configuration: bytes = field(repr=False)
    configuration_sha256: str
    frozen_selection: FrozenDetailedSelectionSnapshot = field(repr=False)


@dataclass(frozen=True)
class AssumptionSnapshotWitness:
    """Module membership in a validated context; never independent authority."""

    context: SnapshotWitnessContext = field(repr=False)
    module_revision_id: str
    topology_revision_id: str
    parameterization_revision_id: str
    evidence_id: str
    evidence_sha256: str
    assumption_sha256: str
    consistency_sha256: str
    module_input_sha256: str
    effective_opt_in: bool


def _assert_numerical_parameterization_binding(definition, evidence):
    """Recorded B1 identity only, separate from executable v0.1 readiness."""
    for name in ("parameterization_id", "module_definition_revision_id",
                 "module_topology_revision_id", "model_id", "model_version",
                 "parameterization_payload_sha256"):
        if definition.get(name) != evidence.get(name):
            raise ValueError(f"numerical parameterization evidence does not match {name}")
    if definition.get("revision_id") != evidence.get("parameterization_revision_id"):
        raise ValueError("numerical parameterization revision mismatch")


def _scientific_configuration_bytes(configuration):
    # Lazy import: dispatch imports this module. Reuse its canonical projection.
    from engine.simulation.detailed_dispatch import scientific_configuration
    electrical = configuration["shading_configuration"]["electrical_shading_configuration"]
    validate_synthetic_region_option(electrical)
    _schema(electrical, "shading/electrical/electrical-shading-configuration.schema.json")
    return _bytes(semantic_scientific_payload(scientific_configuration(configuration)))


def _assert_witness_digest(value):
    if type(value) is not str or len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
        raise SnapshotWitnessError("snapshot witness digest must be lowercase SHA-256")


def _uncached_witness_context_inputs(context):
    if type(context) is not SnapshotWitnessContext:
        raise SnapshotWitnessError("snapshot witness context type is invalid")
    if type(context.canonical_configuration) is not bytes:
        raise SnapshotWitnessError("snapshot witness configuration must be immutable bytes")
    _assert_witness_digest(context.configuration_sha256)
    configuration = json.loads(context.canonical_configuration)
    # Execution options are excluded from the existing scientific identity.
    request = configuration["shading_configuration"]["electrical_shading_configuration"]
    if "execution_options" in request:
        raise SnapshotWitnessError("snapshot witness configuration is not scientific")
    restored = deepcopy(configuration)
    restored["shading_configuration"]["electrical_shading_configuration"]["execution_options"] = {}
    if _scientific_configuration_bytes(restored) != context.canonical_configuration:
        raise SnapshotWitnessError("snapshot witness configuration is not canonical")
    if hashlib.sha256(context.canonical_configuration).hexdigest() != context.configuration_sha256:
        raise SnapshotWitnessError("snapshot witness configuration hash mismatch")
    if type(context.frozen_selection) is not FrozenDetailedSelectionSnapshot:
        raise SnapshotWitnessError("snapshot witness frozen selection type is invalid")
    frozen = context.frozen_selection
    _assert_witness_digest(frozen.payload_sha256)
    _assert_witness_digest(frozen.scientific_input_sha256)
    if type(frozen.canonical_payload) is not bytes:
        raise SnapshotWitnessError("snapshot witness selection must be immutable bytes")
    return configuration, frozen._replay_structure()


# Structural consistency only; exact immutable bytes and implementation policy
# are keys. Oversized contexts are validated without retention.
_WITNESS_CACHE_POLICY = "b3c-context-structure.v1"
_WITNESS_CACHE_BYTE_LIMIT = 512 * 1024


@lru_cache(maxsize=16)
def _cached_witness_context_inputs(context, policy):
    return _uncached_witness_context_inputs(context)


def _witness_context_inputs(context):
    if type(context) is not SnapshotWitnessContext or type(context.frozen_selection) is not FrozenDetailedSelectionSnapshot:
        raise SnapshotWitnessError("snapshot witness context type is invalid")
    if type(context.canonical_configuration) is not bytes or type(context.frozen_selection.canonical_payload) is not bytes:
        raise SnapshotWitnessError("snapshot witness context must contain immutable bytes")
    _assert_witness_digest(context.configuration_sha256)
    _assert_witness_digest(context.frozen_selection.payload_sha256)
    _assert_witness_digest(context.frozen_selection.scientific_input_sha256)
    size = len(context.canonical_configuration) + len(context.frozen_selection.canonical_payload)
    if size > _WITNESS_CACHE_BYTE_LIMIT:
        return _uncached_witness_context_inputs(context)
    # Cached mutable structures never escape to callers.
    return deepcopy(_cached_witness_context_inputs(context, _WITNESS_CACHE_POLICY))


def build_snapshot_witness_context(configuration, frozen_selection):
    """Validate actual scientific inputs once for shared immutable storage.

    The caller owns authentication of these inputs to its run. This validates
    content identity, not origin, B2 physics acceptance, or execution permission.
    """
    try:
        encoded = _scientific_configuration_bytes(configuration)
        context = SnapshotWitnessContext(encoded, hashlib.sha256(encoded).hexdigest(),
                                         frozen_selection)
        _witness_context_inputs(context)
        return context
    except (ValueError, KeyError, TypeError, AttributeError, ValidationError) as exc:
        raise SnapshotWitnessError(f"snapshot witness context invalid: {exc}") from exc


def _selected_witness_payload(bundle, module_revision_id):
    from components.topology_library import (
        assert_numerical_assumption_source_bindings, canonical_topology_asset_sha256,
    )
    from shading.electrical.contract import assert_numerical_assumption_evidence_structure
    if not isinstance(module_revision_id, str) or not module_revision_id:
        raise SnapshotWitnessError("snapshot witness module revision must be a string")
    selection = bundle["electrical_shading_selections"][module_revision_id]
    assets = bundle["pinned_electrical_shading_assets"]
    if selection.get("cell_parameterization_evidence_id") is not None:
        raise SnapshotWitnessError("unsupported numerical-assumption scope: region_substring required")
    evidence_id = selection["region_parameterization_evidence_id"]
    if not isinstance(evidence_id, str):
        raise SnapshotWitnessError("snapshot witness selected evidence identifier is invalid")
    evidence = assets["electrical_parameterization_evidence"][evidence_id]
    assert_numerical_assumption_evidence_structure(evidence)
    module = bundle["pinned_components"]["modules"][module_revision_id]
    topology = assets["module_topologies"][selection["module_topology_revision_id"]]
    definitions = assets["electrical_parameterization_definitions"]
    revision = evidence["parameterization_revision_id"]
    if revision not in definitions:
        raise SnapshotWitnessError("selected parameterization revision mismatch: exact revision unavailable")
    definition = definitions[revision]
    if (module["revision_id"] != module_revision_id or evidence["evidence_id"] != evidence_id or
            topology["revision_id"] != selection["module_topology_revision_id"]):
        raise SnapshotWitnessError("snapshot witness selected registry identity mismatch")
    for value, path in (
        (module, "components/schema/module-definition.schema.json"),
        (topology, "components/schema/module-topology-definition.schema.json"),
        (definition, "shading/electrical/electrical-parameterization-definition.schema.json"),
    ):
        _schema(value, path)
    assert_electrical_parameterization_definition(definition, topology)
    _assert_numerical_parameterization_binding(definition, evidence)
    declaration = evidence["assumption_declaration"]
    if (declaration["module_source"]["component_id"] != module["module_definition_id"] or
            declaration["topology"]["topology_id"] != topology["module_topology_id"] or
            declaration["topology"]["topology_sha256"] != canonical_topology_asset_sha256(topology)):
        raise SnapshotWitnessError("snapshot witness selected asset identity mismatch")
    sources = assets.get("sources", {})
    assert_numerical_assumption_source_bindings(module, evidence, sources)
    _validate_quality_declaration(evidence, sources)
    return dict(module=module, topology=topology, parameterization=definition,
                evidence=evidence, sources=sources)


@lru_cache(maxsize=128)
def _cached_selected_witness_bytes(context, revision, policy):
    _, bundle = _witness_context_inputs(context)
    return _bytes(_selected_witness_payload(bundle, revision))


def _selected_witness_bytes(context, revision):
    # Bound total retained context bytes by entry count and per-entry ceiling.
    size = len(context.canonical_configuration) + len(context.frozen_selection.canonical_payload)
    if size > _WITNESS_CACHE_BYTE_LIMIT:
        _, bundle = _witness_context_inputs(context)
        return _bytes(_selected_witness_payload(bundle, revision))
    return _cached_selected_witness_bytes(context, revision, _WITNESS_CACHE_POLICY)


@lru_cache(maxsize=128)
def _cached_detailed_snapshot_witness(context, module_revision_id, policy):
    witness = _build_detailed_snapshot_witness(context, module_revision_id)
    # Cache membership values only. Equal contexts may belong to distinct runs;
    # every returned witness must retain the actual caller's context object.
    return tuple(getattr(witness, name) for name in
                 AssumptionSnapshotWitness.__dataclass_fields__ if name != "context")


def build_detailed_snapshot_witness(context, module_revision_id):
    # Cache immutable membership records only, never execution permission.
    if (type(context) is SnapshotWitnessContext and
            type(context.frozen_selection) is FrozenDetailedSelectionSnapshot and
            type(context.canonical_configuration) is bytes and
            type(context.frozen_selection.canonical_payload) is bytes and
            isinstance(module_revision_id, str) and
            len(context.canonical_configuration) + len(context.frozen_selection.canonical_payload)
            <= _WITNESS_CACHE_BYTE_LIMIT):
        return AssumptionSnapshotWitness(context, *_cached_detailed_snapshot_witness(
            context, module_revision_id, _WITNESS_CACHE_POLICY))
    return _build_detailed_snapshot_witness(context, module_revision_id)


def _build_detailed_snapshot_witness(context, module_revision_id):
    """Resolve exact membership from verified content, never a supplied boolean."""
    try:
        configuration, bundle = _witness_context_inputs(context)
        payload = json.loads(_selected_witness_bytes(context, module_revision_id))
        evidence = payload["evidence"]
        return AssumptionSnapshotWitness(
            context, module_revision_id, payload["topology"]["revision_id"],
            payload["parameterization"]["revision_id"], evidence["evidence_id"],
            hashlib.sha256(_bytes(evidence)).hexdigest(),
            evidence["assumption_declaration"]["digest_sha256"],
            evidence["consistency_record"]["digest_sha256"],
            hashlib.sha256(_bytes(payload)).hexdigest(),
            validate_synthetic_region_option(configuration["shading_configuration"][
                "electrical_shading_configuration"]))
    except (ValueError, KeyError, TypeError, AttributeError, ValidationError) as exc:
        raise SnapshotWitnessError(f"snapshot witness membership invalid: {exc}") from exc


def _assert_witness_structure(witness):
    if type(witness) is not AssumptionSnapshotWitness:
        raise SnapshotWitnessError("snapshot witness type is invalid")
    for name in ("module_revision_id", "topology_revision_id", "parameterization_revision_id", "evidence_id"):
        value = getattr(witness, name)
        if type(value) is not str or not value.strip():
            raise SnapshotWitnessError(f"snapshot witness {name} must be a nonempty string")
    for name in ("evidence_sha256", "assumption_sha256", "consistency_sha256", "module_input_sha256"):
        _assert_witness_digest(getattr(witness, name))
    if type(witness.effective_opt_in) is not bool:
        raise SnapshotWitnessError("snapshot witness opt-in must be a literal boolean")


def validate_snapshot_witness(witness, payload, module_input_sha256):
    """Replay consistency only. A self-consistent forgery still cannot execute."""
    try:
        _assert_witness_structure(witness)
        expected = build_detailed_snapshot_witness(witness.context, witness.module_revision_id)
        if witness != expected:
            raise SnapshotWitnessError("snapshot witness membership or digest mismatch")
        selected_bytes = _selected_witness_bytes(witness.context, witness.module_revision_id)
        if selected_bytes != _bytes(payload) or witness.module_input_sha256 != module_input_sha256:
            raise SnapshotWitnessError("snapshot witness module payload membership mismatch")
    except (ValueError, KeyError, TypeError, AttributeError, ValidationError) as exc:
        raise SnapshotWitnessError(f"snapshot witness invalid: {exc}") from exc


def compare_snapshot_witness_context(witness, configuration, frozen_selection):
    """Compare with independently trusted expected inputs; grant no permission."""
    try:
        _assert_witness_structure(witness)
        expected = build_snapshot_witness_context(configuration, frozen_selection)
        _witness_context_inputs(witness.context)
        if witness.context != expected:
            raise SnapshotWitnessError("snapshot witness foreign configuration or selection")
        checked = build_detailed_snapshot_witness(expected, witness.module_revision_id)
        if witness != checked:
            raise SnapshotWitnessError("snapshot witness foreign module membership")
    except (ValueError, KeyError, TypeError, AttributeError, ValidationError) as exc:
        raise SnapshotWitnessError(f"snapshot witness expected context invalid: {exc}") from exc


def resolve_selected_parameterization(assets, evidence):
    """Exact v0.2 revision; legacy IDs must have a unique frozen definition."""
    definitions = assets.get("electrical_parameterization_definitions", {})
    if evidence.get("schema_version") == "0.2" or "evidence_class" in evidence:
        revision = evidence.get("parameterization_revision_id")
        definition = definitions.get(revision)
        if (definition is None or definition.get("revision_id") != revision or
                definition.get("parameterization_id") != evidence.get("parameterization_id")):
            raise SnapshotWitnessError("selected parameterization revision mismatch")
        return definition
    matches = [d for d in definitions.values()
               if d.get("parameterization_id") == evidence.get("parameterization_id")]
    if len(matches) != 1:
        raise DetailedInputError("exact executable parameterization definition unavailable or ambiguous")
    definition = matches[0]
    if definitions.get(definition.get("revision_id")) != definition:
        raise DetailedInputError("parameterization registry revision mismatch")
    return definition


@dataclass(frozen=True)
class NumericalAssumptionAuthority:
    """Witness candidate; the contract revalidates it against exact evidence."""

    witness: AssumptionSnapshotWitness


def _assert_assumption_execution_policy(configuration, selection):
    from shading.electrical.contract import NumericalAssumptionInputError
    electrical = configuration["shading_configuration"]["electrical_shading_configuration"]
    if not validate_synthetic_region_option(electrical):
        raise NumericalAssumptionInputError("NUMERICAL_ASSUMPTION_EXECUTION_DENIED: numerical execution requires scientific opt-in")
    if (electrical.get("requested_fidelity") != DETAILED_FIDELITY or
            selection.get("requested_fidelity") != DETAILED_FIDELITY or
            selection.get("resolved_fidelity") != DETAILED_FIDELITY):
        raise NumericalAssumptionInputError("NUMERICAL_ASSUMPTION_EXECUTION_DENIED: numerical assumptions support only Level-2 region_substring")
    if (electrical.get("fallback_policy") != "fail_closed" or
            selection.get("fallback_policy") != "fail_closed"):
        raise NumericalAssumptionInputError("NUMERICAL_ASSUMPTION_EXECUTION_DENIED: numerical assumptions require fail_closed policy")


@lru_cache(maxsize=16)
def _validated_producer_physics(context, revision, implementation_identity):
    """Bounded immutable scientific validation, never configuration permission.

    The policy and selected membership are checked outside this cache on each
    call. Independent verification does not use this producer-only helper.
    """
    from shading.electrical.parameterization import validate_numerical_assumption_acceptance
    configuration, _ = _witness_context_inputs(context)
    payload = json.loads(_selected_witness_bytes(context, revision))
    solver = str((configuration.get("numerical_options") or {}).get("module_solver", "lambertw"))
    validate_numerical_assumption_acceptance(payload["module"], payload["topology"],
        payload["parameterization"], payload["evidence"], payload["sources"], solver=solver)


def _assumption_policy_bytes(context, revision):
    configuration, bundle = _witness_context_inputs(context)
    return (_bytes(configuration), _bytes(bundle["electrical_shading_selections"][revision]))


@lru_cache(maxsize=128)
def _cached_assumption_policy_bytes(context, revision, policy):
    # Immutable structural inputs only; permission is rechecked on every call.
    return _assumption_policy_bytes(context, revision)


def validate_assumption_authorization_witness(witness):
    """Reconstruct scientific authority; stored PASS and witness flags are no proof.

    B2 caches calculated physics by complete immutable input and installed kernel
    identity. Policy and membership are checked on every call independently.
    Production callers additionally compare to their separately expected context.
    """
    from shading.electrical.parameterization import _NUMERICAL_ACCEPTANCE_POLICY
    from shading.electrical.module_iv import MODULE_NONUNIFORM_IV_SOLVER_VERSION
    import pvlib
    _assert_witness_structure(witness)
    expected = build_detailed_snapshot_witness(witness.context, witness.module_revision_id)
    if witness != expected:
        raise SnapshotWitnessError("snapshot witness membership or digest mismatch")
    context = witness.context
    if len(context.canonical_configuration) + len(context.frozen_selection.canonical_payload) <= _WITNESS_CACHE_BYTE_LIMIT:
        configuration_bytes, selection_bytes = _cached_assumption_policy_bytes(
            context, witness.module_revision_id, _WITNESS_CACHE_POLICY)
    else:
        configuration_bytes, selection_bytes = _assumption_policy_bytes(context, witness.module_revision_id)
    _assert_assumption_execution_policy(json.loads(configuration_bytes), json.loads(selection_bytes))
    identity = (_NUMERICAL_ACCEPTANCE_POLICY, pvlib.__version__, MODULE_NONUNIFORM_IV_SOLVER_ID,
                MODULE_NONUNIFORM_IV_SOLVER_VERSION, "rb08b2.acceptance.1")
    from shading.electrical.contract import NumericalAssumptionInputError
    try:
        if len(witness.context.canonical_configuration) + len(witness.context.frozen_selection.canonical_payload) <= _WITNESS_CACHE_BYTE_LIMIT:
            _validated_producer_physics(witness.context, witness.module_revision_id, identity)
        else:
            _validated_producer_physics.__wrapped__(witness.context, witness.module_revision_id, identity)
    except NumericalAssumptionInputError as exc:
        raise NumericalAssumptionInputError("NUMERICAL_ASSUMPTION_EXECUTION_DENIED: B3 " + str(exc)) from exc
    return NumericalAssumptionAuthority(witness)


def authorize_selected_assumptions(configuration, frozen_selection):
    """Trusted dispatch boundary: independently provided configuration/selection."""
    bundle = frozen_selection.replay()
    assets = bundle["pinned_electrical_shading_assets"]
    context = None
    witnesses, payloads = {}, {}
    for revision, selection in sorted(bundle["electrical_shading_selections"].items()):
        registry = assets.get("electrical_parameterization_evidence", {})
        evidence = registry.get(selection.get("region_parameterization_evidence_id"), {})
        cell = registry.get(selection.get("cell_parameterization_evidence_id"), {})
        if any(e.get("schema_version") == "0.2" or "evidence_class" in e for e in (evidence, cell)):
            if context is None:
                context = build_snapshot_witness_context(configuration, frozen_selection)
            witness = build_detailed_snapshot_witness(context, revision)
            compare_snapshot_witness_context(witness, configuration, frozen_selection)
            validate_assumption_authorization_witness(witness)
            witnesses[revision] = witness
            payloads[revision] = json.loads(_selected_witness_bytes(context, revision))
    return witnesses, payloads


def prepare_execution_transport(module_inputs, configuration=None, frozen_selection=None):
    """Compare at the parent run boundary, before replay drops snapshot metadata.

    Expected inputs originate from dispatch, never from an attached witness.
    This transport establishes membership; module replay and workers enforce B2.
    """
    witnesses = {key: snapshot.witness for key, snapshot in module_inputs.items()}
    expected = None
    if any(w is not None for w in witnesses.values()):
        if configuration is None or frozen_selection is None:
            raise SnapshotWitnessError("missing independently expected run context")
        expected = build_snapshot_witness_context(configuration, frozen_selection)
        for key, witness in witnesses.items():
            if witness is not None:
                compare_snapshot_witness_context(witness, configuration, frozen_selection)
                snapshot = module_inputs[key]
                validate_snapshot_witness(witness, json.loads(snapshot.canonical_payload), snapshot.scientific_input_sha256)
    return {"module_witnesses": witnesses, "expected_witness_context": expected,
            "expected_module_revisions": {key: json.loads(snapshot.canonical_payload)["module"]["revision_id"]
                                          for key, snapshot in module_inputs.items()}}


def validate_execution_transport(context):
    """Require parent-selected membership and full numerical scientific acceptance."""
    if not isinstance(context, Mapping) or not isinstance(context.get("module_inputs"), Mapping):
        raise SnapshotWitnessError("worker transport module inputs must be a mapping")
    module_inputs = context["module_inputs"]
    witnesses = context.get("module_witnesses", {})
    if not isinstance(witnesses, Mapping):
        raise SnapshotWitnessError("worker witness transport must be a mapping")
    if set(witnesses) - set(module_inputs):
        raise SnapshotWitnessError("foreign worker module membership")
    expected = context.get("expected_witness_context")
    revisions = context.get("expected_module_revisions", {})
    if not isinstance(revisions, Mapping):
        raise SnapshotWitnessError("worker revision transport must be a mapping")
    if set(revisions) - set(module_inputs):
        raise SnapshotWitnessError("foreign worker module revision membership")
    eligible = []
    # Complete structural validation across ALL members before any B2 work.
    for key, payload in module_inputs.items():
        if (not isinstance(payload, Mapping) or
                not isinstance(payload.get("evidence"), Mapping) or
                not isinstance(payload.get("module"), Mapping)):
            raise SnapshotWitnessError("worker module payload must contain module and evidence mappings")
        witness = witnesses.get(key)
        assumed = payload["evidence"].get("schema_version") == "0.2" or "evidence_class" in payload["evidence"]
        if assumed and witness is None:
            raise SnapshotWitnessError("missing numerical-assumption worker context")
        if witness is not None:
            if revisions.get(key) != payload["module"].get("revision_id"):
                raise SnapshotWitnessError("foreign worker module revision membership")
            if type(expected) is not SnapshotWitnessContext:
                raise SnapshotWitnessError("missing independently expected worker context")
            _assert_witness_structure(witness)
            if witness.context != expected:
                raise SnapshotWitnessError("snapshot witness foreign configuration or selection")
            validate_snapshot_witness(witness, payload, hashlib.sha256(_bytes(payload)).hexdigest())
            eligible.append(witness)
    for witness in eligible:
        validate_assumption_authorization_witness(witness)


@dataclass(frozen=True)
class NumericalWorkerResult:
    """Non-persisted return binding for assumed execution only."""

    context_identity: tuple[str, str, str]
    membership_sha256: str
    result: Any = field(compare=False, repr=False)


def bind_worker_result(context, result):
    expected = context.get("expected_witness_context")
    if expected is None:
        return result
    validate_execution_transport(context)
    identity = (expected.configuration_sha256, expected.frozen_selection.payload_sha256,
                expected.frozen_selection.scientific_input_sha256)
    members = hashlib.sha256(_bytes(context["expected_module_revisions"])).hexdigest()
    return NumericalWorkerResult(identity, members, result)


def accept_worker_result(context, result):
    expected = context.get("expected_witness_context")
    if expected is None:
        return result
    identity = (expected.configuration_sha256, expected.frozen_selection.payload_sha256,
                expected.frozen_selection.scientific_input_sha256)
    members = hashlib.sha256(_bytes(context["expected_module_revisions"])).hexdigest()
    if (type(result) is not NumericalWorkerResult or result.context_identity != identity or
            result.membership_sha256 != members):
        raise SnapshotWitnessError("missing or foreign numerical worker result authority")
    validate_execution_transport(context)
    return result.result


def validate_regional_transport(witness, topology, definition, evidence):
    """Default-deny regional execution without complete selected scientific authority."""
    if witness is not None:
        _assert_witness_structure(witness)
        expected = build_detailed_snapshot_witness(witness.context, witness.module_revision_id)
        if witness != expected or (witness.topology_revision_id != topology.get("revision_id") or
                witness.parameterization_revision_id != definition.get("revision_id") or
                witness.evidence_sha256 != hashlib.sha256(_bytes(evidence)).hexdigest()):
            raise SnapshotWitnessError("regional snapshot witness membership mismatch")
    from shading.electrical.contract import NumericalAssumptionInputError, deny_numerical_assumption_execution
    if evidence.get("schema_version") == "0.2" or "evidence_class" in evidence:
        if evidence.get("parameterization_scope") != "region_substring":
            raise NumericalAssumptionInputError("unsupported numerical-assumption scope: region_substring required")
        if evidence.get("schema_version") != "0.2":
            raise NumericalAssumptionInputError("NUMERICAL_ASSUMPTION_EXECUTION_DENIED: inconsistent evidence class")
    authority = NumericalAssumptionAuthority(witness) if witness is not None else None
    deny_numerical_assumption_execution(evidence, authority=authority)
