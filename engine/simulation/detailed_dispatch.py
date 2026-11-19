"""Phase 6.9A canonical dispatch through the selected MPPT boundary."""

from contextlib import contextmanager
from copy import deepcopy
import json
from typing import Any, Mapping

from jsonschema import ValidationError

from .artifacts import canonical_json_bytes, canonical_object_sha256, persist_run_package, weather_series_logical_sha256
from .detailed_inputs import (
    resolve_selected_parameterization, ROOT, DETAILED_SCOPE, DETAILED_FIDELITY, DetailedInputError, _schema,
    FrozenDetailedSelectionSnapshot, pin_detailed_module_inputs,
    semantic_scientific_payload, validate_detailed_runtime_support,
    validate_synthetic_region_option, deny_selected_numerical_assumptions, authorize_selected_assumptions,
)
from shading.electrical import assert_requested_fidelity_available
from shading.electrical.contract import NumericalAssumptionInputError
from .detailed_inputs import SnapshotWitnessError
from geometry.shading.contract import ShadingContractError

LIMITATIONS = [
    "Detailed PCC module quality requires signed-value-bound parameterization evidence; unknown nonzero quality is blocked.",
    "One temperature per module, from shaded incident POA before IAM; regional temperature gradients are not modeled.",
    "Module quality is excluded from selected-MPPT physics; downstream application depends on the bound declaration.",
    "Tracker constraints are flags, not clipping; binding current limits require fail-closed downstream handling.",
    "Fully dark MPPTs are inactive with no operating point; mixed dark/active strings on one MPPT require a dark-branch model.",
]


def scientific_configuration(configuration: Mapping[str, Any]) -> dict[str, Any]:
    value = deepcopy(dict(configuration))
    value.pop("output_configuration", None)
    shading = value.get("shading_configuration") or {}
    shading.pop("cache_policy", None)
    electrical = shading.get("electrical_shading_configuration")
    if isinstance(electrical, dict):
        electrical.pop("execution_options", None)
    return value


def verify_detailed_context(context: Mapping[str, Any]) -> None:
    if context.get("schema_name") != "DetailedExecutionContext" or context.get("schema_version") != "0.1":
        raise DetailedInputError("unsupported detailed execution context")
    inputs = context["inputs"]
    base_fields = {"project_revision", "simulation_configuration", "scene", "electrical_design",
                   "weather_dataset", "weather_series_logical_sha256", "component_revisions",
                   "frozen_selection", "engine_version"}
    # Increment-2 scaffolding packages have no numerical policy/result. Retain
    # verification of that exact historical shape without accepting unknown fields.
    if set(inputs) not in (base_fields, base_fields | {"detailed_numerical_policy"}):
        raise DetailedInputError("detailed execution scientific input fields are not exact")
    if context["identity"].get("numerical_result_sha256") is not None and "detailed_numerical_policy" not in inputs:
        raise DetailedInputError("numerical detailed execution requires pinned numerical policy")
    expected = {key: canonical_object_sha256(semantic_scientific_payload(value))
                for key, value in inputs.items()}
    if expected != context["input_hashes"]:
        raise DetailedInputError("detailed scientific input hash mismatch")
    identity = context["identity"]
    if canonical_object_sha256(expected) != identity["scientific_input_sha256"]:
        raise DetailedInputError("detailed combined scientific hash mismatch")
    body = dict(identity)
    digest = body.pop("execution_identity_sha256")
    if canonical_object_sha256(body) != digest:
        raise DetailedInputError("detailed execution identity hash mismatch")
    from jsonschema import Draft202012Validator
    Draft202012Validator(json.loads((ROOT / "schemas/detailed-execution-identity.schema.json").read_text())).validate(identity)
    record = context.get("selection_snapshot")
    from .detailed_inputs import _bytes, _verify_assumption_inputs
    frozen = inputs["frozen_selection"]
    # Structural replay resolves every selection, including dark/unused modules.
    # A raw mapping can establish no numerical scientific authority.
    if record is None and frozen is not None:
        deny_selected_numerical_assumptions(frozen)
    if record is not None:
        snapshot = FrozenDetailedSelectionSnapshot(
            _bytes(record["payload"]), record["payload_sha256"], record["scientific_input_sha256"])
        if semantic_scientific_payload(snapshot._replay_structure()) != frozen:
            raise DetailedInputError("detailed selection does not match scientific inputs")
        assumed = _verify_assumption_inputs(inputs["simulation_configuration"], snapshot)
        if assumed:
            bundle = snapshot._validate_replay_assets(snapshot._replay_structure())
            for module in inputs["scene"]["module_instances"]:
                if not module["enabled"]:
                    continue
                revision = module["module_definition_revision_id"]
                pinned = bundle["pinned_components"]["modules"].get(revision)
                if pinned is None or pinned != inputs["component_revisions"].get(revision):
                    raise DetailedInputError("frozen module does not match canonical component revision")
                if revision not in bundle["electrical_shading_selections"]:
                    raise DetailedInputError("active module has no frozen electrical selection")
            if (identity["requested_fidelity"] != DETAILED_FIDELITY or
                    identity["resolved_fidelity"] != DETAILED_FIDELITY or
                    identity["fallback_applied"] is not False or
                    identity["fallback_reason"] is not None):
                raise DetailedInputError("assumption identity requires Level-2 fidelity without fallback")
            if identity["fallback_policy"] != "fail_closed":
                raise DetailedInputError("assumption identity requires fail_closed policy")
            if identity["limitations"] != derive_assumption_limitations(assumed, inputs["scene"], inputs["simulation_configuration"]):
                raise DetailedInputError("assumption scientific limitations mismatch")
        else:
            snapshot.replay()


class _VerifiedContextCheck:
    """Private scoped result, produced only by _detailed_verification_transaction."""
    __slots__ = ("_bound", "_active")

    def __init__(self):
        raise TypeError("use _detailed_verification_transaction")

    def __call__(self, candidate):
        if not self._active or canonical_json_bytes(candidate) != self._bound:
            raise DetailedInputError("detailed verification transaction context mismatch or expired")


@contextmanager
def _detailed_verification_transaction(context):
    """One completed check, reusable only while this private scope is active.

    Full canonical bytes include provenance, limitations and storage references.
    This scoped result is never serialized or shared with another verifier invocation.
    """
    if context.get("schema_name") != "DetailedExecutionContext" or context.get("schema_version") != "0.1":
        raise DetailedInputError("unsupported detailed execution context")
    bound = canonical_json_bytes(context)
    verify_detailed_context(context)
    if canonical_json_bytes(context) != bound:
        raise DetailedInputError("detailed context changed during verification")
    check = object.__new__(_VerifiedContextCheck)
    check._bound = bound
    check._active = True
    try:
        yield check
    finally:
        check._active = False


def detailed_limitations(configuration=None):
    limitations = list(LIMITATIONS)
    settings = ((configuration or {}).get("numerical_options") or {}).get("optics_thermal_settings")
    if settings is not None:
        from .optics_thermal import resolve_optics_thermal_settings
        basis = resolve_optics_thermal_settings(settings)["values"]["thermal"]["irradiance_basis"]
        description = "effective irradiance after IAM and soiling" if basis == "effective" else "shaded incident POA before IAM"
        limitations[1] = f"One temperature per module, from {description} (irradiance_basis={basis}); regional temperature gradients are not modeled."
    return limitations


def derive_assumption_limitations(payloads, scene, configuration=None):
    """Complete disclosure slices, once per active revision, in revision order."""
    active = {m["module_definition_revision_id"] for m in scene["module_instances"] if m["enabled"]}
    limitations = detailed_limitations(configuration)
    for revision in sorted(active & payloads.keys()):
        limitations.extend(payloads[revision]["evidence"]["assumption_declaration"]["scientific_limitations"])
    return limitations


def _deny_selected_numerical_assumptions(bundle):
    deny_selected_numerical_assumptions(bundle)


def _resolve(configuration, store, scene, electrical_design):
    electrical = configuration["shading_configuration"]["electrical_shading_configuration"]
    runtime_configuration = configuration
    execution_options = electrical.get("execution_options") or {}
    for option in ("electrical_chunk_size", "electrical_worker_count", "attribution_worker_count"):
        if option in execution_options:
            value = execution_options[option]
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise DetailedInputError(f"{option} must be a positive integer")
            if runtime_configuration is configuration:
                runtime_configuration = deepcopy(configuration)
            # Unknown options remain for the scientific support validator to reject.
            runtime_configuration["shading_configuration"]["electrical_shading_configuration"]["execution_options"].pop(option)
    snapshot = store.detailed_electrical_inputs
    if snapshot is None:
        raise DetailedInputError("detailed selection snapshot is unavailable")
    bundle = snapshot.replay()
    witnesses, _ = authorize_selected_assumptions(configuration, snapshot)
    inverters = [item for item in electrical_design["inverter_instances"] if item["enabled"]]
    if len(inverters) != 1:
        raise DetailedInputError("detailed runtime requires exactly one enabled inverter")
    inverter = store.component_revisions.get(inverters[0]["inverter_definition_revision_id"])
    if inverter is None or inverter.get("revision_id") != inverters[0]["inverter_definition_revision_id"]:
        raise ValueError("detailed inverter component revision is missing or mismatched")
    _schema(inverter, "components/schema/inverter-definition.schema.json")
    from engine.inverter.model import _runtime_ready
    try:
        _runtime_ready(inverter)
    except ValueError as exc:
        raise DetailedInputError(str(exc)) from exc
    strings = [item for item in electrical_design["strings"] if item["enabled"]]
    active_modules = {item["module_instance_id"] for item in scene["module_instances"] if item["enabled"]}
    assigned_modules = [module_id for string in strings for module_id in string["module_instance_ids"]]
    if set(assigned_modules) != active_modules or len(assigned_modules) != len(set(assigned_modules)):
        raise ValueError("detailed strings require exact active-module coverage")
    if any(item["polarity"] != "normal" for item in strings):
        raise DetailedInputError("detailed runtime supports only normal string polarity")
    mppts = [item for item in electrical_design["mppt_instances"] if item["enabled"]]
    assigned_strings = [string_id for mppt in mppts for string_id in mppt["connected_string_ids"]]
    if set(assigned_strings) != {item["string_id"] for item in strings} or len(assigned_strings) != len(set(assigned_strings)):
        raise ValueError("detailed MPPTs require exact active-string coverage")
    if len({item["index"] for item in mppts}) != len(mppts) or any(item["index"] < 1 for item in mppts):
        raise DetailedInputError("detailed MPPT indices must match the unique 1-based downstream contract")
    for mppt in mppts:
        if mppt["inverter_instance_id"] != inverters[0]["inverter_instance_id"]:
            raise ValueError("detailed MPPT inverter binding mismatch")
        if any(string["target_mppt_instance_id"] != mppt["mppt_instance_id"]
               for string in strings if string["string_id"] in mppt["connected_string_ids"]):
            raise ValueError("detailed string target MPPT binding mismatch")
    numerical = configuration.get("numerical_options") or {}
    from engine.losses.settings import resolve_circuit_loss_settings, resolve_detailed_circuit_quality
    circuit_resolution = resolve_circuit_loss_settings(numerical.get("loss_settings"), scene, electrical_design,
        store.component_revisions, module_quality_override=numerical.get("module_overrides", {}).get("module_quality_loss_fraction"), detailed=True)
    if circuit_resolution is not None and circuit_resolution["active"]:
        inputs = {}
        for instance in scene["module_instances"]:
            revision = instance["module_definition_revision_id"]
            selection = bundle["electrical_shading_selections"].get(revision)
            if selection:
                inputs[instance["module_instance_id"]] = {"evidence": bundle["pinned_electrical_shading_assets"]["electrical_parameterization_evidence"][selection["region_parameterization_evidence_id"]]}
        resolve_detailed_circuit_quality(circuit_resolution, inputs)
    if "loss_settings" in numerical:
        from engine.losses.settings import resolve_loss_settings, resolve_detailed_losses, assert_compatible_wiring_modes
        assert_compatible_wiring_modes(per_circuit=True,
            global_resistance_ohm=(numerical.get("losses") or {}).get("dc_array_resistance_ohm", 0))
        settings = resolve_loss_settings(numerical["loss_settings"])
        modules = {item["module_instance_id"]: store.component_revisions[item["module_definition_revision_id"]]
                   for item in scene["module_instances"] if item["enabled"]}
        for mppt in mppts:
            resolve_detailed_losses(settings,
                strings=[string for string in strings if string["string_id"] in mppt["connected_string_ids"]],
                modules=modules, inverter_name=str(inverters[0].get("name") or inverters[0]["inverter_instance_id"]),
                mppt_name=str(mppt.get("name") or mppt["index"]))
    if any(f["layout_mode"] != "fixed_tilt" for f in scene["pv_fields"]
           if f["pv_field_id"] in {m["pv_field_id"] for m in scene["module_instances"] if m["enabled"]}):
        raise DetailedInputError("detailed runtime supports only fixed-tilt module fields")
    revisions = {item["module_definition_revision_id"]
                 for item in scene["module_instances"] if item.get("enabled") is True}
    if not revisions:
        raise ValueError("detailed scene has no active modules")
    assets = bundle["pinned_electrical_shading_assets"]
    for revision in sorted(revisions):
        module = bundle["pinned_components"]["modules"].get(revision)
        if module != store.component_revisions.get(revision):
            raise ValueError("frozen module does not match canonical component revision")
        selection = bundle["electrical_shading_selections"].get(revision)
        if selection is None:
            raise DetailedInputError("active module has no frozen electrical selection")
        if (selection["requested_fidelity"] != electrical["requested_fidelity"] or
            selection["fallback_policy"] != electrical["fallback_policy"]):
            raise ValueError("request does not match frozen selection fidelity/policy")
        topology = assets["module_topologies"].get(selection["module_topology_revision_id"])
        evidence = assets["electrical_parameterization_evidence"].get(selection["region_parameterization_evidence_id"])
        if topology is None or evidence is None:
            raise DetailedInputError("detailed topology/parameterization evidence unavailable")
        definition = resolve_selected_parameterization(assets, evidence)
        pinned = pin_detailed_module_inputs(module=module, topology=topology,
                                           parameterization=definition, evidence=evidence,
                                           sources=assets["sources"], authorization_witness=witnesses.get(revision))
        try:
            validate_detailed_runtime_support(runtime_configuration, pinned)
        except ShadingContractError as exc:
            raise DetailedInputError(str(exc)) from exc
    return DETAILED_FIDELITY


def run_detailed_dispatch(project, configuration, *, revision_store, output_directory,
                          simulation_run_id, engine_version, executed_at, findings,
                          design_validation_evidence):
    from .canonical import (
        CanonicalSimulationExecutionResult, _failed_run, _finding, _has_blocker,
        _assert_output_schema, _output_registry, _revision_inputs, run_canonical_simulation,
    )
    raw_request = (configuration.get("shading_configuration") or {}).get("electrical_shading_configuration")
    request = raw_request if isinstance(raw_request, Mapping) else {}
    requested = request.get("requested_fidelity")
    policy = request.get("fallback_policy")
    scene, electrical_design, weather = _revision_inputs(
        project, configuration, revision_store, run_id=simulation_run_id,
        generated_at=executed_at, findings=findings,
    )
    errors = [item["message"] for item in findings
              if item.get("severity") in {"blocking_error", "error"}]
    invalid = _has_blocker(findings)
    try:
        validate_synthetic_region_option(request)
    except ValueError as exc:
        errors.append(str(exc))
        invalid = True
    for value, filename in ((scene, "geometry/scene/scene.schema.json"),
                            (electrical_design, "electrical/schema/electrical-design.schema.json")):
        if value is None:
            errors.append(f"missing canonical {filename}")
            invalid = True
        else:
            from jsonschema import Draft202012Validator
            try:
                Draft202012Validator(json.loads((ROOT / filename).read_text()),
                                     registry=_output_registry()).validate(value)
            except ValidationError as exc:
                errors.append(exc.message)
                invalid = True
    if weather is None:
        errors.append("missing canonical weather revision")
        invalid = True
    else:
        from jsonschema import Draft202012Validator
        try:
            Draft202012Validator(json.loads((ROOT / "weather/schema/weather-dataset.schema.json").read_text()),
                                 registry=_output_registry()).validate(weather.dataset)
        except ValidationError as exc:
            errors.append(exc.message)
            invalid = True
    diagnostic_option = (configuration.get("output_configuration") or {}).get("detailed_diagnostics", False)
    if not isinstance(diagnostic_option, bool):
        errors.append("output_configuration.detailed_diagnostics must be an explicit boolean")
        invalid = True
    frozen = None
    assumption_payloads = {}
    if revision_store.detailed_electrical_inputs is not None:
        try:
            # Freeze is structural; publish a numerical selection into the run
            # only after the trusted configuration-bound boundary accepts it.
            selected_record = revision_store.detailed_electrical_inputs.record()
            _, assumption_payloads = authorize_selected_assumptions(configuration, revision_store.detailed_electrical_inputs)
            frozen = selected_record
        except (ValueError, ValidationError) as exc:
            errors.append(str(exc))
            invalid = True
    resolved = None
    status = "blocked"
    if not invalid:
        try:
            if requested == "level_0_geometric_only":
                resolved = requested
                status = "geometry_only"
            else:
                resolved = _resolve(configuration, revision_store, scene, electrical_design)
                status = "backend_not_connected"
        except DetailedInputError as exc:
            errors.append(str(exc))
        except (ValueError, KeyError, ValidationError) as exc:
            errors.append(str(exc))
            invalid = True
    fallback_reason = None
    # Only Level 0 is executable in this increment. Integrity/validation failures
    # never downgrade; unsupported or unavailable runtime inputs may explicitly do so.
    if status == "blocked" and not invalid and policy == "explicit_lower_fidelity":
        resolved = assert_requested_fidelity_available(
            requested, {"available_fidelity_levels": ["level_0_geometric_only"]},
            fallback_policy=policy,
        )
        status = "fallback_to_geometry_only"
        fallback_reason = "; ".join(errors)
    numerical = None
    attribution_collector = None
    attribution = None
    completed_numerical = None
    compact = None
    downstream = None
    downstream_error = None
    if status == "backend_not_connected":
        try:
            numerical_arguments = _prepare_backend(configuration, revision_store, scene, electrical_design, findings,
                simulation_run_id, project["project_revision_id"], executed_at)
        except (NumericalAssumptionInputError, SnapshotWitnessError):
            raise
        except (ValueError, KeyError, RuntimeError, TypeError, ValidationError) as exc:
            errors.append(str(exc))
            status = "numerical_failed"
    from .detailed_backend import NUMERICAL_POLICY, TEMPERATURE_APPROXIMATION, resolved_numerical_policy
    try:
        numerical_policy = resolved_numerical_policy(configuration["shading_configuration"])
    except (ValueError, KeyError, TypeError):
        numerical_policy = NUMERICAL_POLICY
    inputs = {
        "project_revision": project, "simulation_configuration": scientific_configuration(configuration),
        "scene": scene, "electrical_design": electrical_design,
        "weather_dataset": weather.dataset if weather is not None else None,
        "weather_series_logical_sha256": weather_series_logical_sha256(weather.series) if weather is not None else None,
        "component_revisions": dict(revision_store.component_revisions),
        "frozen_selection": semantic_scientific_payload(frozen["payload"]) if frozen else None,
        "engine_version": engine_version,
        "detailed_numerical_policy": {**numerical_policy, "temperature_approximation": TEMPERATURE_APPROXIMATION},
    }
    hashes = {key: canonical_object_sha256(semantic_scientific_payload(value)) for key, value in inputs.items()}
    if status == "backend_not_connected":
        from .detailed_backend import execute_detailed_mppt_backend
        try:
            from .canonical import _select_weather_period, _weather_findings
            from .detailed_attribution import DetailedAttributionChunkCollector, execute_detailed_attribution_pass
            execution_options = request.get("execution_options") or {}
            chunk_size = execution_options.get("electrical_chunk_size", 1)
            attribution_collector = DetailedAttributionChunkCollector(chunk_size=chunk_size,
                module_inputs=numerical_arguments["module_inputs"],
                module_configs=numerical_arguments["module_configs"],
                electrical_design=numerical_arguments["electrical_design"],
                retain_diagnostics=diagnostic_option,
                scientific_configuration=configuration, frozen_selection=revision_store.detailed_electrical_inputs)
            attribution_workers = execution_options.get("attribution_worker_count", 1)
            completed_numerical = execute_detailed_mppt_backend(_select_weather_period(weather, configuration),
                scientific_input_sha256=canonical_object_sha256(hashes),
                scientific_configuration=configuration, frozen_selection=revision_store.detailed_electrical_inputs,
                electrical_chunk_size=chunk_size,
                completed_chunk=attribution_collector if attribution_workers == 1 else None,
                electrical_worker_count=execution_options.get("electrical_worker_count", 1),
                **numerical_arguments)
            if attribution_workers > 1:
                try:
                    attribution = execute_detailed_attribution_pass(completed_numerical,
                        collector=attribution_collector, attribution_worker_count=attribution_workers)
                except BaseException:
                    completed_numerical.close()
                    raise
            numerical = completed_numerical
            payload = numerical.replay_stream()
            findings.extend(_weather_findings(payload["weather_qc"], run_id=simulation_run_id,
                project_revision_id=project["project_revision_id"], weather_revision_id=weather.dataset["revision_id"],
                generated_at=executed_at, existing_count=len(findings)))
            binding = any(m["constraint_flags"]["selected_point_violates_known_constraints"]
                for i in payload["intervals"] for m in i["mppts"] if m.get("availability") != "inactive_dark")
            status = "constraint_blocked" if binding else "mppt_complete"
            errors.append("Known MPPT constraint binds; selected diagnostic state is not clipped." if binding else
                          "Detailed MPPT execution complete; downstream loss/inverter/PCC continuation unavailable.")
        except (NumericalAssumptionInputError, SnapshotWitnessError):
            if attribution_collector is not None:
                attribution_collector.close()
            if completed_numerical is not None:
                completed_numerical.close()
            raise
        except (ValueError, KeyError, RuntimeError, TypeError, ValidationError) as exc:
            if attribution_collector is not None:
                attribution_collector.close()
            if completed_numerical is not None:
                completed_numerical.close()
            numerical = None
            attribution = None
            status = "numerical_failed"
            errors.append(str(exc))
    if numerical is not None:
        from .detailed_downstream import compact_selected_states, execute_detailed_downstream, DetailedModuleQualityUnavailable
        try:
            compact = compact_selected_states(numerical)
            downstream = execute_detailed_downstream(compact,
                module_configs=numerical_arguments["module_configs"], module_inputs=numerical_arguments["module_inputs"])
            status = "pcc_complete"
            errors.clear()
        except (NumericalAssumptionInputError, SnapshotWitnessError):
            numerical.close()
            if attribution_collector is not None:
                attribution_collector.close()
            raise
        except (ValueError, KeyError, RuntimeError, TypeError, ValidationError) as exc:
            downstream_error = str(exc)
            # Preserve the established valid-MPPT boundary status for quality-
            # blocked runs; physical selected states remain available.
            if status != "constraint_blocked":
                status = "mppt_complete" if isinstance(exc, DetailedModuleQualityUnavailable) else "downstream_failed"
            errors = [downstream_error]
    # Serial callback records receive their final physical binding here.
    # Parallel attribution was finalized before downstream execution.
    if numerical is not None and attribution is None:
        attribution = attribution_collector.finish(numerical)

    identity = {
        "schema_name": "DetailedExecutionIdentity", "schema_version": "0.1",
        "requested_fidelity": requested, "resolved_fidelity": resolved,
        "fallback_policy": policy, "fallback_applied": status == "fallback_to_geometry_only",
        "fallback_reason": fallback_reason, "failure_reasons": errors,
        "runtime_support_result": status, "execution_scope": DETAILED_SCOPE,
        "limitations": derive_assumption_limitations(assumption_payloads, scene, configuration) if assumption_payloads else detailed_limitations(configuration),
        "scientific_input_sha256": canonical_object_sha256(hashes),
    }
    identity["numerical_result_sha256"] = numerical.numerical_result_sha256 if numerical else None
    identity["compact_result_sha256"] = compact.compact_result_sha256 if compact else None
    identity["execution_identity_sha256"] = canonical_object_sha256(identity)
    context = {"schema_name": "DetailedExecutionContext", "schema_version": "0.1",
               "inputs": inputs, "input_hashes": hashes, "selection_snapshot": frozen,
               "identity": identity}
    if status in {"fallback_to_geometry_only", "geometry_only"}:
        legacy = deepcopy(configuration)
        legacy["shading_configuration"].pop("electrical_shading_configuration")
        return run_canonical_simulation(
            project, legacy, revision_store=revision_store, output_directory=output_directory,
            simulation_run_id=simulation_run_id, engine_version=engine_version,
            executed_at=executed_at, preflight_findings=findings,
            design_validation_evidence=design_validation_evidence, _detailed_context=context,
        )
    if status == "pcc_complete":
        from .detailed_downstream import complete_detailed_run
        from .canonical import _select_weather_period
        run = _failed_run(simulation_run_id=simulation_run_id, project_revision=project,
            simulation_configuration=configuration, engine_version=engine_version, timestamp=executed_at,
            findings=findings, assumptions=[], model_resolution=None, component_manifest={},
            input_hash=identity["scientific_input_sha256"], design_validation_evidence=design_validation_evidence)
        return complete_detailed_run(run=run, context=context, compact=compact, downstream=downstream,
            numerical=numerical, configuration=configuration, project=project,
            weather=_select_weather_period(weather, configuration), store=revision_store,
            numerical_arguments=numerical_arguments, output_directory=output_directory, attribution=attribution)
    rule = {"downstream_failed": "DETAILED_DOWNSTREAM_EXECUTION_BLOCKED", "mppt_complete": "DETAILED_DOWNSTREAM_CONTINUATION_UNAVAILABLE",
            "constraint_blocked": "DETAILED_MPPT_CONSTRAINT_BLOCKED",
            "numerical_failed": "DETAILED_NUMERICAL_EXECUTION_FAILED"}.get(status, "DETAILED_EXECUTION_UNSUPPORTED")
    if status == "mppt_complete" and downstream_error:
        rule = "DETAILED_MODULE_QUALITY_CALIBRATION_UNRESOLVED"
    findings.append(_finding(
        ordinal=len(findings) + 1, run_id=simulation_run_id,
        project_revision_id=project.get("project_revision_id", "unresolved-project-revision"),
        entity_id=configuration.get("simulation_configuration_id", "unresolved-simulation-configuration"),
        rule_id=rule, severity="blocking_error", category="execution_scope",
        message="; ".join(errors),
        generated_at=executed_at,
    ))
    run = _failed_run(
        simulation_run_id=simulation_run_id, project_revision=project,
        simulation_configuration=configuration, engine_version=engine_version,
        timestamp=executed_at, findings=findings, assumptions=[], model_resolution=None,
        component_manifest={}, input_hash=identity["scientific_input_sha256"],
        design_validation_evidence=design_validation_evidence,
    )
    _assert_output_schema(run, "simulation-run.schema.json")
    directory = persist_run_package(
        output_directory=output_directory, simulation_run_id=simulation_run_id,
        simulation_run=run, summary_result=None, reproducibility_manifest=None,
        validation_findings=findings, model_resolution=None, detailed_context=context, detailed_backend_result=numerical, detailed_compact_result=compact,
        detailed_diagnostics=configuration.get("output_configuration", {}).get("detailed_diagnostics", False),
        detailed_attribution_result=attribution,
    )
    return CanonicalSimulationExecutionResult(run, None, None, None, directory, numerical, attribution)


def _prepare_backend(configuration, store, scene, electrical, findings, run_id, project_revision_id, generated_at):
    """Bind canonical module geometry and existing runtime-option resolution."""
    from .canonical import _build_runtime_config, _has_blocker
    from geometry.shading import compile_shading_geometry
    compiled = compile_shading_geometry(scene)
    errors = [f["message"] for f in compiled.get("findings", []) if f["severity"] in {"error", "blocking_error"}]
    if errors:
        raise ValueError("Detailed geometry compilation failed: " + "; ".join(errors))
    receivers = {r["source_entity_id"]: r for r in compiled["receivers"] if r["source_entity_type"] == "module_instance"}
    modules = {m["module_instance_id"]: m for m in scene["module_instances"] if m["enabled"]}
    if set(receivers) != set(modules):
        raise ValueError("Detailed compiled receivers require exact active-module coverage")
    bundle = store.detailed_electrical_inputs.replay()
    witnesses, _ = authorize_selected_assumptions(configuration, store.detailed_electrical_inputs)
    assets = bundle["pinned_electrical_shading_assets"]
    inverter_instance = next(i for i in electrical["inverter_instances"] if i["enabled"])
    inverter = store.component_revisions[inverter_instance["inverter_definition_revision_id"]]
    from engine.losses.settings import resolve_circuit_loss_settings
    numerical = configuration.get("numerical_options") or {}
    circuit_resolution = resolve_circuit_loss_settings(numerical.get("loss_settings"), scene, electrical,
        store.component_revisions, module_quality_override=numerical.get("module_overrides", {}).get("module_quality_loss_fraction"), detailed=True)
    runtime_configs, module_inputs, model_resolutions = {}, {}, {}
    surfaces = {s["surface_id"]: s for s in scene["surfaces"]}
    for module_id in sorted(modules):
        receiver = receivers[module_id]
        revision = modules[module_id]["module_definition_revision_id"]
        module = store.component_revisions[revision]
        selection = bundle["electrical_shading_selections"][revision]
        topology = assets["module_topologies"][selection["module_topology_revision_id"]]
        evidence = assets["electrical_parameterization_evidence"][selection["region_parameterization_evidence_id"]]
        definition = resolve_selected_parameterization(assets, evidence)
        module_inputs[module_id] = pin_detailed_module_inputs(module=module, topology=topology,
            parameterization=definition, evidence=evidence, sources=assets["sources"],
            authorization_witness=witnesses.get(revision))
        numerical = configuration.get("numerical_options") or {}
        if next(f for f in scene["pv_fields"] if f["pv_field_id"] == receiver["pv_field_id"]).get("field_kind") == "explicit_layout":
            support = surfaces.get(receiver.get("support_surface_id"))
            albedo = numerical.get("albedo", (support or {}).get("albedo"))
        else:
            albedo = numerical.get("albedo", surfaces[receiver["support_surface_id"]].get("albedo"))
        if albedo is None:
            albedo = 0.20
        # Resolve the existing options with a per-module geometry descriptor.
        # No identical-string runner or electrical loss kernel is invoked.
        descriptor = {"module": module, "inverter": inverter, "module_revision_id": revision,
            "inverter_instance_id": inverter_instance["inverter_instance_id"], "circuit_loss_resolution": circuit_resolution,
            "inverter_revision_id": inverter["revision_id"], "modules_in_series": 1,
            "string_ids": (), "mppt_assignments": {}, "albedo": albedo,
            "albedo_source": "numerical_options" if "albedo" in numerical else "scene.surfaces",
            "surface_tilt_deg": receiver["metadata"]["tilt_deg"],
            "surface_azimuth_deg": receiver["metadata"]["azimuth_deg"]}
        from .models import resolve_simulation_models
        resolution_hash = canonical_object_sha256({"module_revision_id": revision,
            "inverter_revision_id": inverter["revision_id"], "requested_models": configuration["model_selections"]})
        resolved = resolve_simulation_models(module, inverter, resolution_id=f"model-resolution:{resolution_hash[:16]}",
            requested_module_model_id=configuration["model_selections"]["module_electrical"],
            requested_inverter_model_id=configuration["model_selections"]["inverter"])
        if resolved["status"] == "blocked":
            raise ValueError("Detailed canonical component model resolution blocked: " + str(resolved["warnings"]))
        model_resolutions[module_id] = resolved
        runtime = _build_runtime_config(configuration, descriptor, resolved, run_id=run_id,
            project_revision_id=project_revision_id, generated_at=generated_at, findings=findings, assumptions=[])
        if runtime is None or _has_blocker(findings):
            raise ValueError("Detailed runtime options failed existing canonical validation")
        runtime_configs[module_id] = runtime
    templates = {}
    for mppt in electrical["mppt_instances"]:
        if mppt["enabled"]:
            explicit = inverter.get("mppts") or []
            template = next((t for t in explicit if t["mppt_index"] == mppt["index"]), None) if explicit else inverter.get("mppt_template")
            if template is None or (not explicit and mppt["index"] > template["count"]):
                raise ValueError("Detailed MPPT index has no pinned inverter constraint template")
            # Keep unknown as None, and invalid known values as invalid. The
            # legacy inverter adapter converts nonpositive current to unknown;
            # Phase 6.8 explicitly rejects such a known current limit.
            from shading.electrical.mppt_tracker import _constraints
            templates[mppt["mppt_instance_id"]] = _constraints(template)
    return {"compiled_geometry": compiled, "electrical_design": electrical,
            "module_inputs": module_inputs, "module_configs": runtime_configs,
            "model_resolution_metadata": model_resolutions,
            "shading_configuration": configuration["shading_configuration"], "mppt_templates": templates}
