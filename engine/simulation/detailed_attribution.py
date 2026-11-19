"""Immutable explanatory DC ledger, evaluated after authoritative execution."""
from collections import deque
from concurrent.futures import ProcessPoolExecutor
from multiprocessing import get_context
from dataclasses import dataclass
from hashlib import sha256
import json
from math import fsum, isclose
from pathlib import Path

import pandas as pd
from jsonschema import Draft202012Validator, FormatChecker, ValidationError

from shading.electrical.dc_attribution import (MODEL_ID, MODEL_VERSION, POWER_ABS_W,
    POWER_REL, VOLTAGE_TOL_V, CURRENT_TOL_A, MAX_ITERATIONS, basis,
    evaluate_independent_module_bases)
from .artifacts import (canonical_object_sha256, ElectricalIntervalStore, StoredElectricalPayload,
    electrical_payload, freeze_electrical_payload, electrical_payload_bytes)

BASES = tuple("UNBSCT")
CHANNEL_PAIRS = {"regional_mismatch": ("U", "N"), "bypass_interaction": ("N", "B"),
    "series_interaction": ("B", "S"), "parallel_interaction": ("S", "C"),
    "tracker_interaction": ("C", "T"), "total_detailed_dc_delta": ("U", "T")}
POLICY = {"power_absolute_tolerance_w": POWER_ABS_W, "power_relative_tolerance": POWER_REL,
    "energy_absolute_tolerance_wh_per_second": POWER_ABS_W / 3600, "energy_relative_tolerance": POWER_REL,
    "direct_reference_absolute_tolerance_w": POWER_ABS_W, "direct_reference_relative_tolerance": POWER_REL,
    "voltage_tolerance_v": VOLTAGE_TOL_V, "current_tolerance_a": CURRENT_TOL_A,
    "max_iterations": MAX_ITERATIONS, "mpp_scope": "represented_samples_only_no_continuous_optimum_claim",
    "sample_count_policy": "same_as_actual_string_sample_count",
    "N_domain_policy": "common_branch_domain_must_cover_full_positive_generation_to_module_v_zero"}
_UNSET = object()
_DARK_ONLY_CONTEXT = object()
DARK_REASON = "inactive_dark_no_photovoltaic_operating_point"


def _bytes(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def sum_bases(values):
    # A non-generating independently optimized module contributes no power to
    # the sum, but has no invented MPP. All-not-applicable remains null.
    active = [v for v in values if v["status"] != "not_applicable"]
    if not active:
        return basis(status="not_applicable", reasons=[DARK_REASON])
    missing = [v for v in active if v["status"] != "available"]
    if missing:
        return basis(status="unavailable", reasons=sorted({r for v in missing for r in v["reason_codes"]}))
    return basis(fsum(v["power_w"] for v in active))


def explain(bases):
    channels = {}
    for name, (reference, evaluated) in CHANNEL_PAIRS.items():
        pair = [bases[reference], bases[evaluated]]
        if all(v["status"] == "available" for v in pair):
            channels[name] = {"status": "available", "value_w": pair[0]["power_w"] - pair[1]["power_w"], "reason_codes": []}
        else:
            status = "not_applicable" if all(v["status"] == "not_applicable" for v in pair) else "unavailable"
            channels[name] = {"status": status, "value_w": None,
                "reason_codes": sorted({r for v in pair for r in v["reason_codes"]})}
    components = [channels[name] for name in CHANNEL_PAIRS if name != "total_detailed_dc_delta"]
    if all(v["status"] == "available" for v in components):
        residual = fsum(v["value_w"] for v in components) - channels["total_detailed_dc_delta"]["value_w"]
        telescope = {"status": "complete", "residual_w": residual, "reason_codes": []}
    else:
        status = "not_applicable" if all(v["status"] == "not_applicable" for v in components) else "partial"
        telescope = {"status": status, "residual_w": None,
            "reason_codes": [DARK_REASON if status == "not_applicable" else "incomplete_counterfactual_chain"]}
    return {"bases": bases, "channels": channels, "telescope": telescope}


def integrate_channels(intervals):
    results = {}
    states = {name: ([], [], []) for name in CHANNEL_PAIRS}
    for interval in intervals:
        for name, (available, missing, not_applicable) in states.items():
            channel = interval["ledger"]["channels"][name]
            if channel["status"] == "available":
                available.append((channel["value_w"], interval["duration_seconds"]))
            elif channel["status"] == "not_applicable":
                not_applicable.append(interval["duration_seconds"])
            else:
                missing.append(interval["duration_seconds"])
    for name, (available, missing, not_applicable) in states.items():
        subtotal = fsum(p * seconds / 3600 for p, seconds in available) if available else None
        status = "unavailable" if missing else ("available" if available else "not_applicable")
        results[name] = {"status": status, "energy_wh": subtotal if status == "available" else None,
            "available_subtotal_wh": subtotal, "available_duration_seconds": sum(s for _, s in available),
            "unavailable_duration_seconds": sum(missing), "not_applicable_duration_seconds": sum(not_applicable),
            "reason_codes": ["incomplete_interval_coverage"] if missing else ([DARK_REASON] if not available else [])}
    return results


@dataclass(frozen=True, init=False, eq=False)
class DetailedDCAttributionResult:
    _canonical_payload: bytes | StoredElectricalPayload
    attribution_result_sha256: str
    _diagnostic_payload: bytes | ElectricalIntervalStore | None = None

    def __init__(self, _canonical_payload=None, attribution_result_sha256=None,
                 _diagnostic_payload=None, *, canonical_payload=_UNSET, diagnostic_payload=_UNSET):
        object.__setattr__(self, "_canonical_payload", _canonical_payload if canonical_payload is _UNSET else canonical_payload)
        object.__setattr__(self, "attribution_result_sha256", attribution_result_sha256)
        object.__setattr__(self, "_diagnostic_payload", _diagnostic_payload if diagnostic_payload is _UNSET else diagnostic_payload)

    def _diagnostic_sha256(self):
        if self._diagnostic_payload is None:
            return None
        if isinstance(self._diagnostic_payload, ElectricalIntervalStore):
            digest = sha256()
            for part in json.JSONEncoder(sort_keys=True, separators=(",", ":"),
                    allow_nan=False).iterencode(self._diagnostic_payload):
                digest.update(part.encode())
            return digest.hexdigest()
        return sha256(self._diagnostic_payload).hexdigest()

    def __eq__(self, other):
        if not isinstance(other, DetailedDCAttributionResult):
            return NotImplemented
        return (self.attribution_result_sha256 == other.attribution_result_sha256
            and self._canonical_payload == other._canonical_payload
            and self._diagnostic_sha256() == other._diagnostic_sha256())

    @property
    def interval_store(self):
        return self._canonical_payload.intervals if isinstance(self._canonical_payload, StoredElectricalPayload) else None

    def close(self):
        if self.interval_store is not None:
            self.interval_store.close()
        if isinstance(self._diagnostic_payload, ElectricalIntervalStore):
            self._diagnostic_payload.close()

    @property
    def canonical_payload(self):
        return electrical_payload_bytes(self._canonical_payload)

    @property
    def diagnostic_payload(self):
        if isinstance(self._diagnostic_payload, ElectricalIntervalStore):
            return "".join(json.JSONEncoder(sort_keys=True, separators=(",", ":"),
                allow_nan=False).iterencode(self._diagnostic_payload)).encode()
        return self._diagnostic_payload

    def diagnostic_rows(self):
        if isinstance(self._diagnostic_payload, ElectricalIntervalStore):
            return self._diagnostic_payload
        return json.loads(self._diagnostic_payload) if self._diagnostic_payload is not None else None

    @classmethod
    def freeze(cls, payload, diagnostics=None, *, _decoded=False):
        result = cls(freeze_electrical_payload(payload), canonical_object_sha256(payload),
                     _bytes(diagnostics) if diagnostics is not None else None)
        if _decoded or isinstance(result._canonical_payload, StoredElectricalPayload):
            result._validate_payload(payload)
        else:
            result.replay_stream()
        return result

    def replay(self):
        """Compatibility API: an isolated, fully decoded reference payload."""
        self.replay_stream()
        return json.loads(self.canonical_payload)

    def replay_stream(self):
        """Internal validated replay with a bounded interval iterator."""
        payload = electrical_payload(self._canonical_payload)
        return self._validate_payload(payload)

    def _validate_payload(self, payload):
        """Validate an operation-owned decoded document without decoding a copy."""
        if (not isinstance(self._canonical_payload, StoredElectricalPayload) and _bytes(payload) != self._canonical_payload) or canonical_object_sha256(payload) != self.attribution_result_sha256:
            raise ValueError("detailed DC attribution hash mismatch")
        schema = json.loads((Path(__file__).resolve().parents[2] / "schemas/detailed-dc-attribution.schema.json").read_text())
        Draft202012Validator(schema, format_checker=FormatChecker()).validate(payload)
        if payload["numerical_policy"] != POLICY:
            raise ValueError("unsupported detailed attribution numerical policy")
        previous, coverage = None, None
        for interval in payload["intervals"]:
            start, end, evaluation = (pd.Timestamp(interval[k]) for k in ("interval_start", "interval_end", "evaluation_time"))
            if start.tzinfo is None or end.tzinfo is None or evaluation.tzinfo is None:
                raise ValueError("attribution interval timestamp must be timezone-aware")
            if not start < end or (end-start).total_seconds() != interval["duration_seconds"] or (previous is not None and start != previous):
                raise ValueError("attribution interval alignment mismatch")
            previous = end
            ids = [(m["mppt_instance_id"], m["mppt_index"], m["string_ids"], m["module_ids"]) for m in interval["mppts"]]
            if len({i[0] for i in ids}) != len(ids) or (coverage is not None and ids != coverage):
                raise ValueError("attribution MPPT identity coverage mismatch")
            coverage = ids
            if sorted(mid for m in interval["mppts"] for mid in m["module_ids"]) != sorted(m["module_instance_id"] for m in interval["modules"]):
                raise ValueError("attribution complete module scope coverage mismatch")
            if sorted(sid for m in interval["mppts"] for sid in m["string_ids"]) != sorted(s["string_id"] for s in interval["strings"]):
                raise ValueError("attribution complete string scope coverage mismatch")
            module_ids = [m["module_instance_id"] for m in interval["modules"]]
            string_ids = [s["string_id"] for s in interval["strings"]]
            if len(module_ids) != len(set(module_ids)) or len(string_ids) != len(set(string_ids)):
                raise ValueError("duplicate attribution scope identity")
            for record in [*interval["mppts"], interval["ledger"]]:
                expected = explain(record["bases"])
                if record["channels"] != expected["channels"] or record["telescope"] != expected["telescope"]:
                    raise ValueError("attribution channel/telescope semantics mismatch")
                if record["telescope"]["status"] == "complete" and not isclose(record["telescope"]["residual_w"], 0.,
                    abs_tol=POWER_ABS_W, rel_tol=POWER_REL):
                    raise ValueError("attribution telescope does not reconcile")
            modules = {m["module_instance_id"]: m for m in interval["modules"]}
            strings = {s["string_id"]: s for s in interval["strings"]}
            for m in interval["mppts"]:
                selected = m["bases"]["T"]
                if m["actual_dc_power_w"] != (selected["power_w"] if selected["status"] == "available" else 0.):
                    raise ValueError("attribution selected DC authority mismatch")
                if m["tracker_model_id"] == "rawibumi.mppt.ideal_global_mpp.v0.1" and m["channels"]["tracker_interaction"]["status"] == "available":
                    if not isclose(m["bases"]["C"]["power_w"], selected["power_w"], abs_tol=POWER_ABS_W, rel_tol=POWER_REL):
                        raise ValueError("ideal-global-MPP tracker attribution does not match C/T")
                expected_modules = sorted(mid for sid in m["string_ids"] for mid in strings[sid]["module_ids"])
                if m["module_ids"] != expected_modules:
                    raise ValueError("attribution module/string/MPPT scope binding mismatch")
                for key in "UNB":
                    if m["bases"][key] != sum_bases([modules[mid]["bases"][key] for mid in m["module_ids"]]):
                        raise ValueError("attribution independent-module sum mismatch")
                if m["bases"]["S"] != sum_bases([strings[sid]["basis"] for sid in m["string_ids"]]):
                    raise ValueError("attribution string sum mismatch")
            for key in BASES:
                if interval["ledger"]["bases"][key] != sum_bases([m["bases"][key] for m in interval["mppts"]]):
                    raise ValueError("attribution interval sum mismatch")
        if payload["energy"] != integrate_channels(payload["intervals"]):
            raise ValueError("attribution duration-based energy mismatch")
        return payload

    def record(self, *, stream=False):
        return {"payload": self.replay_stream() if stream else self.replay(), "attribution_result_sha256": self.attribution_result_sha256}


def _attribution_context(module_inputs, module_configs, electrical_design, sample_count, retain_diagnostics,
                         scientific_configuration=None, frozen_selection=None):
    from shading.electrical.contract import NumericalAssumptionInputError
    from .detailed_inputs import (DetailedModuleInputSnapshot, SnapshotWitnessError,
        _schema, deny_selected_numerical_assumptions, prepare_execution_transport)
    # Historical abbreviated carriers are supported only for zero electrical
    # work. They never acquire a witness or an expected revision map.
    abbreviated = any(not isinstance(v, DetailedModuleInputSnapshot) for v in module_inputs.values())
    if abbreviated:
        if frozen_selection is not None:
            try:
                bundle = frozen_selection.replay() if hasattr(frozen_selection, "replay") else frozen_selection
                deny_selected_numerical_assumptions(bundle)
                registry = (bundle.get("pinned_electrical_shading_assets") or {}).get("electrical_parameterization_evidence", {})
                for selection in (bundle.get("electrical_shading_selections") or {}).values():
                    for field in ("region_parameterization_evidence_id", "cell_parameterization_evidence_id"):
                        evidence_id = selection.get(field)
                        if evidence_id is not None:
                            evidence = registry[evidence_id]
                            _schema(evidence, "shading/electrical/electrical-parameterization-evidence.schema.json")
                            if evidence["evidence_id"] != evidence_id:
                                raise SnapshotWitnessError("selected evidence registry identity mismatch")
            except (SnapshotWitnessError, NumericalAssumptionInputError):
                raise
            except (ValueError, KeyError, TypeError, AttributeError, ValidationError) as exc:
                raise SnapshotWitnessError(f"dark attribution selected evidence invalid: {exc}") from exc
        for snapshot in module_inputs.values():
            try:
                valid_shape = (not isinstance(snapshot, DetailedModuleInputSnapshot)
                    and getattr(snapshot, "witness", None) is None
                    and set(snapshot.replay()) == {"parameterization"})
            except (SnapshotWitnessError, NumericalAssumptionInputError):
                raise
            except (AttributeError, TypeError, ValueError) as exc:
                raise SnapshotWitnessError(f"dark attribution legacy input invalid: {exc}") from exc
            if not valid_shape:
                raise SnapshotWitnessError("dark attribution requires abbreviated legacy input without witness")
        transport = {"dark_only_context": _DARK_ONLY_CONTEXT}
    else:
        transport = prepare_execution_transport(module_inputs, scientific_configuration, frozen_selection)
    return {**transport, "module_inputs": {k: v.replay() for k, v in module_inputs.items()},
            "region_solvers": {k: v.module_solver for k, v in module_configs.items()},
            "strings": {s["string_id"]: s for s in electrical_design["strings"] if s["enabled"]},
            "sample_count": sample_count, "retain_diagnostics": retain_diagnostics}


def _validate_dark_attribution_interval(context, interval):
    """Classify completed physical inputs, never a caller's darkness flag."""
    from .detailed_inputs import SnapshotWitnessError
    modules = interval["modules"]
    if not modules or set(modules) != set(context["module_inputs"]):
        raise SnapshotWitnessError("dark attribution physical module coverage mismatch")
    for diagnostic in modules.values():
        regions = diagnostic["local_irradiance"]["regions"]
        if not regions or any(r["effective_irradiance_w_m2"] != 0 for r in regions):
            raise SnapshotWitnessError("abbreviated attribution requires an entirely dark interval")
    if (set(interval["strings"]) != set(context["strings"])
            or any(d["curve"] is not None for d in interval["strings"].values())
            or not interval["mppts"]
            or any(m["availability"] != "inactive_dark" or m["combined_curve"] is not None
                   or m["selected_operating_point"] is not None for m in interval["mppts"])):
        raise SnapshotWitnessError("dark attribution requires completed zero-electrical-work physical states")


def _evaluate_attribution_interval(context, interval):
    from .detailed_inputs import validate_execution_transport
    dark_only = context.get("dark_only_context") is _DARK_ONLY_CONTEXT
    if dark_only:
        _validate_dark_attribution_interval(context, interval)
    else:
        validate_execution_transport(context)
    diagnostics = []
    module_records, string_records, mppt_records = {}, {}, []
    for module_id, diagnostic in sorted(interval["modules"].items()):
        pinned = context["module_inputs"][module_id]
        if dark_only:
            bases, curves = {k: basis(status="not_applicable", reasons=[DARK_REASON]) for k in "UNB"}, {}
        else:
            bases, curves = evaluate_independent_module_bases(pinned, diagnostic,
                sample_count=context["sample_count"], region_solver=context["region_solvers"][module_id],
                authorization_witness=context.get("module_witnesses", {}).get(module_id))
        module_records[module_id] = {"module_instance_id": module_id, "bases": bases,
            "source_local_state_sha256": diagnostic["local_irradiance"]["state_payload_sha256"],
            "source_parameterization_sha256": pinned["parameterization"]["parameterization_payload_sha256"],
            "counterfactual_curve_hashes": {k: canonical_object_sha256(v) for k, v in curves.items()}}
        if context["retain_diagnostics"]:
            diagnostics.append({"interval_start": interval["interval_start"], "module_instance_id": module_id,
                "purpose": "independent_module_counterfactual_solver_curves", "curves": curves})
    for string_id, d in sorted(interval["strings"].items()):
        state = basis(d["curve"]["global_mpp"]["power_w"]) if d["curve"] is not None else basis(status="not_applicable", reasons=[DARK_REASON])
        string_records[string_id] = {"string_id": string_id, "module_ids": context["strings"][string_id]["module_instance_ids"],
            "basis": state, "source_curve_sha256": canonical_object_sha256(d["curve"]) if d["curve"] is not None else None}
    for m in interval["mppts"]:
        string_ids = m["combined_state"]["source_string_ids"]
        module_ids = sorted(mid for sid in string_ids for mid in string_records[sid]["module_ids"])
        bases = {k: sum_bases([module_records[mid]["bases"][k] for mid in module_ids]) for k in "UNB"}
        bases["S"] = sum_bases([string_records[sid]["basis"] for sid in string_ids])
        dark = m.get("availability") == "inactive_dark"
        bases["C"] = basis(status="not_applicable", reasons=[DARK_REASON]) if dark else basis(m["combined_curve"]["global_mpp"]["power_w"])
        bases["T"] = basis(status="not_applicable", reasons=[DARK_REASON]) if dark else basis(m["selected_operating_point"]["power_w"])
        mppt_records.append({"mppt_instance_id": m["mppt_instance_id"], "mppt_index": m["mppt_index"],
            "string_ids": string_ids, "module_ids": module_ids, "actual_dc_power_w": 0. if dark else bases["T"]["power_w"],
            "tracker_model_id": m["tracker_model_id"], **explain(bases)})
    ledger = explain({k: sum_bases([m["bases"][k] for m in mppt_records]) for k in BASES})
    record = {**{k: interval[k] for k in ("interval_start", "interval_end", "evaluation_time", "duration_seconds")},
        "modules": list(module_records.values()), "strings": list(string_records.values()), "mppts": mppt_records,
        "ledger": ledger, "aggregation_scope": "applicable_generating_scopes_only_dark_has_no_mpp"}
    return record, diagnostics


def _producer_module_input_hash(snapshot):
    """Match the independent selected-witness fingerprint for v0.2 only."""
    from .detailed_inputs import _selected_witness_bytes, validate_snapshot_witness
    witness = getattr(snapshot, "witness", None)
    if witness is None:
        return snapshot.scientific_input_sha256
    payload = snapshot.replay()
    validate_snapshot_witness(witness, payload, snapshot.scientific_input_sha256)
    return sha256(_selected_witness_bytes(witness.context, witness.module_revision_id)).hexdigest()


def _attribution_header(source, module_inputs, module_configs, electrical_design, sample_count):
    return {"schema_name": "DetailedDCAttributionResult", "schema_version": "0.1",
        "attribution_model_id": MODEL_ID, "attribution_model_version": MODEL_VERSION,
        "accounting_basis": "detailed_selected_mppt_dc_before_residual_losses",
        "application": "explanatory_only_never_applied_to_actual_ledger",
        "sign_convention": "reference_minus_evaluated_positive_loss_negative_recovery",
        "geometric_shading_accounting": "already_in_actual_effective_irradiance_not_rebooked",
        "scientific_input_sha256": source["scientific_input_sha256"],
        "source_electrical_design_sha256": canonical_object_sha256(electrical_design),
        "source_module_input_hashes": {k: _producer_module_input_hash(v) for k, v in sorted(module_inputs.items())},
        "region_solvers": {k: v.module_solver for k, v in sorted(module_configs.items())},
        "numerical_policy": POLICY, "sample_count": sample_count}


def execute_detailed_dc_attribution(numerical, *, module_inputs, electrical_design,
                                    module_configs, retain_diagnostics=False,
                                    scientific_configuration=None, frozen_selection=None, _context=None):
    """Consume actual diagnostics. Never feed anything back into actual execution."""
    source = numerical.replay_stream()
    sample_count = source["numerical_policy"]["string_sample_count"]
    context = _context if _context is not None else _attribution_context(module_inputs, module_configs, electrical_design, sample_count, retain_diagnostics, scientific_configuration, frozen_selection)
    if context["sample_count"] != sample_count:
        raise ValueError("attribution chunk sampling policy changed")
    intervals, diagnostics = [], []
    for interval in source["intervals"]:
        record, rows = _evaluate_attribution_interval(context, interval)
        intervals.append(record)
        diagnostics.extend(rows)
    payload = {**_attribution_header(source, module_inputs, module_configs, electrical_design, sample_count),
        "source_numerical_result_sha256": numerical.numerical_result_sha256,
        "intervals": intervals, "energy": integrate_channels(intervals)}
    return DetailedDCAttributionResult.freeze(payload, diagnostics if retain_diagnostics else None)


def verify_attribution_sources(attribution, context, compact=None, numerical=None, *, _payload=None, _compact_payload=None, _context_check=None):
    """Independently verify context, then bind attribution to physical outputs."""
    return _verify_attribution_sources_transaction(
        attribution, context, compact, numerical,
        _payload=_payload, _compact_payload=_compact_payload, _context_check=_context_check)


def _verify_attribution_sources_transaction(attribution, context, compact=None, numerical=None, *,
                                            _payload=None, _compact_payload=None,
                                            _context_check=None):
    """Bind explanation to frozen inputs and authoritative physical outputs."""
    from .detailed_inputs import pin_detailed_module_inputs, resolve_selected_parameterization
    from .detailed_dispatch import verify_detailed_context, _VerifiedContextCheck
    from .detailed_inputs import FrozenDetailedSelectionSnapshot, _bytes, _selected_witness_payload
    import hashlib
    if _context_check is not None and type(_context_check) is not _VerifiedContextCheck:
        raise ValueError("invalid detailed verification transaction result")
    raw = context["inputs"]["frozen_selection"]
    registry = (raw or {}).get("pinned_electrical_shading_assets", {}).get("electrical_parameterization_evidence", {})
    numerical_selected = any(
        registry.get(s.get(field), {}).get("schema_version") == "0.2" or
        "evidence_class" in registry.get(s.get(field), {})
        for s in (raw or {}).get("electrical_shading_selections", {}).values()
        for field in ("region_parameterization_evidence_id", "cell_parameterization_evidence_id"))
    if (context.get("selection_snapshot") is not None or numerical_selected or
            context.get("schema_name") == "DetailedExecutionContext"):
        if _context_check is None:
            verify_detailed_context(context)
        else:
            _context_check(context)
    payload = attribution.replay_stream() if _payload is None else attribution._validate_payload(_payload)
    identity, inputs = context["identity"], context["inputs"]
    if (payload["scientific_input_sha256"] != identity["scientific_input_sha256"]
        or payload["source_numerical_result_sha256"] != identity["numerical_result_sha256"]
        or payload["source_electrical_design_sha256"] != canonical_object_sha256(inputs["electrical_design"])):
        raise ValueError("attribution scientific/physical source identity mismatch")
    frozen = inputs["frozen_selection"]
    if context.get("selection_snapshot") is not None:
        record = context["selection_snapshot"]
        frozen = FrozenDetailedSelectionSnapshot(_bytes(record["payload"]),
            record["payload_sha256"], record["scientific_input_sha256"])._replay_structure()
    assets = frozen["pinned_electrical_shading_assets"]
    expected, parameterizations = {}, {}
    for module in inputs["scene"]["module_instances"]:
        if not module["enabled"]:
            continue
        revision = module["module_definition_revision_id"]
        selection = frozen["electrical_shading_selections"][revision]
        evidence = assets["electrical_parameterization_evidence"][selection["region_parameterization_evidence_id"]]
        definition = resolve_selected_parameterization(assets, evidence)
        if evidence.get("schema_version") == "0.2":
            checked = _selected_witness_payload(frozen, revision)
            expected[module["module_instance_id"]] = hashlib.sha256(_bytes(checked)).hexdigest()
        else:
            pinned = pin_detailed_module_inputs(module=frozen["pinned_components"]["modules"][revision],
                topology=assets["module_topologies"][selection["module_topology_revision_id"]],
                parameterization=definition, evidence=evidence, sources=assets["sources"])
            expected[module["module_instance_id"]] = pinned.scientific_input_sha256
        parameterizations[module["module_instance_id"]] = definition["parameterization_payload_sha256"]
    solver = str((inputs["simulation_configuration"].get("numerical_options") or {}).get("module_solver", "lambertw"))
    if payload["source_module_input_hashes"] != expected or payload["region_solvers"] != {m: solver for m in expected}:
        raise ValueError("attribution module/solver binding mismatch")
    if payload["sample_count"] != inputs["detailed_numerical_policy"]["string_sample_count"]:
        raise ValueError("attribution sampling policy source mismatch")
    design_strings = {s["string_id"]: s["module_instance_ids"]
                      for s in inputs["electrical_design"]["strings"] if s["enabled"]}
    for interval in payload["intervals"]:
        for module in interval["modules"]:
            if module["source_parameterization_sha256"] != parameterizations.get(module["module_instance_id"]):
                raise ValueError("attribution parameterization evidence binding mismatch")
        for string in interval["strings"]:
            if string["module_ids"] != design_strings.get(string["string_id"]):
                raise ValueError("attribution physical string scope binding mismatch")
    if compact is not None:
        actual = compact.replay() if _compact_payload is None else compact._validate_payload(_compact_payload)
        if len(actual["intervals"]) != len(payload["intervals"]):
            raise ValueError("attribution interval coverage source mismatch")
        for explained, physical in zip(payload["intervals"], actual["intervals"]):
            if any(explained[k] != physical[k] for k in ("interval_start", "interval_end", "evaluation_time", "duration_seconds")):
                raise ValueError("attribution interval identity source mismatch")
            if len(explained["mppts"]) != len(physical["mppts"]):
                raise ValueError("attribution MPPT coverage source mismatch")
            for m, a in zip(explained["mppts"], physical["mppts"]):
                if (m["mppt_instance_id"] != a["mppt_instance_id"] or m["mppt_index"] != a["mppt_index"]
                    or m["string_ids"] != a["string_ids"] or m["actual_dc_power_w"] != a["power_w"]
                    or m["tracker_model_id"] != a["tracker_model_id"]
                    or (m["bases"]["T"]["status"] == "not_applicable") != (a["availability"] == "inactive_dark")):
                    raise ValueError("attribution selected-MPPT source mismatch")
    if numerical is not None:
        for explained, physical in zip(payload["intervals"], numerical.replay_stream()["intervals"]):
            for m, a in zip(explained["mppts"], physical["mppts"]):
                if a["combined_curve"] is not None and m["bases"]["C"]["power_w"] != a["combined_curve"]["global_mpp"]["power_w"]:
                    raise ValueError("attribution ideal combined-curve source mismatch")
            for s in explained["strings"]:
                curve = physical["strings"][s["string_id"]]["curve"]
                if s["source_curve_sha256"] != (canonical_object_sha256(curve) if curve is not None else None):
                    raise ValueError("attribution string curve source mismatch")
                if curve is not None and s["basis"]["power_w"] != curve["global_mpp"]["power_w"]:
                    raise ValueError("attribution string MPP source mismatch")
            for m in explained["modules"]:
                if m["source_local_state_sha256"] != physical["modules"][m["module_instance_id"]]["local_irradiance"]["state_payload_sha256"]:
                    raise ValueError("attribution local-state source mismatch")


def verify_attribution_diagnostics(attribution, diagnostic_record, *, _payload=None):
    payload = attribution.replay_stream() if _payload is None else attribution._validate_payload(_payload)
    if diagnostic_record["attribution_result_sha256"] != attribution.attribution_result_sha256:
        raise ValueError("attribution diagnostic result binding mismatch")
    expected = {(i["interval_start"], m["module_instance_id"]): m["counterfactual_curve_hashes"]
                for i in payload["intervals"] for m in i["modules"]}
    actual = {}
    for row in diagnostic_record["curves"]:
        key = (row["interval_start"], row["module_instance_id"])
        if key in actual:
            raise ValueError("duplicate attribution diagnostic scope")
        actual[key] = {k: canonical_object_sha256(v) for k, v in row["curves"].items()}
    if actual != expected:
        raise ValueError("attribution counterfactual diagnostic curve hash mismatch")


class DetailedAttributionChunkCollector:
    """Interval-local explanation; final source binding uses the physical hash."""
    def __init__(self, *, chunk_size, module_inputs, electrical_design, module_configs,
                 retain_diagnostics=False, scientific_configuration=None, frozen_selection=None):
        self.intervals = ElectricalIntervalStore(chunk_size)
        self.diagnostics = ElectricalIntervalStore(chunk_size) if retain_diagnostics else None
        self.arguments = dict(module_inputs=module_inputs, electrical_design=electrical_design,
                              module_configs=module_configs, retain_diagnostics=retain_diagnostics,
                              scientific_configuration=scientific_configuration, frozen_selection=frozen_selection)
        self.header = None
        self.disabled = False
        self._execution_context = None

    def close(self):
        self.intervals.close()
        if self.diagnostics is not None:
            self.diagnostics.close()

    def __call__(self, numerical):
        if self._execution_context is None:
            sample_count = numerical.replay_stream()["numerical_policy"]["string_sample_count"]
            self._execution_context = _attribution_context(module_inputs=self.arguments["module_inputs"],
                module_configs=self.arguments["module_configs"], electrical_design=self.arguments["electrical_design"],
                sample_count=sample_count, retain_diagnostics=self.arguments["retain_diagnostics"],
                scientific_configuration=self.arguments["scientific_configuration"],
                frozen_selection=self.arguments["frozen_selection"])
        result = execute_detailed_dc_attribution(numerical, **self.arguments, _context=self._execution_context)
        if result is None:
            if self.header is not None:
                raise ValueError("attribution chunk availability changed")
            self.disabled = True
            return
        if self.disabled:
            raise ValueError("attribution chunk availability changed")
        payload = result.replay_stream()
        header = {k: v for k, v in payload.items() if k not in
                  {"intervals", "energy", "source_numerical_result_sha256"}}
        if self.header is not None and self.header != header:
            raise ValueError("attribution chunk source coverage changed")
        self.header = header
        for interval in payload["intervals"]:
            self.intervals.append(interval)
        if self.diagnostics is not None:
            for row in result.diagnostic_rows():
                self.diagnostics.append(row)

    def finish(self, numerical):
        if self.disabled:
            self.intervals.close()
            if self.diagnostics is not None:
                self.diagnostics.close()
            return None
        if self.header is None:
            raise ValueError("attribution chunk history is empty")
        self.intervals.seal()
        source = numerical.replay_stream()
        if (self.header["scientific_input_sha256"] != source["scientific_input_sha256"]
            or self.header["sample_count"] != source["numerical_policy"]["string_sample_count"]
            or len(self.intervals) != len(source["intervals"])):
            raise ValueError("attribution chunk final physical source coverage mismatch")
        for explained, physical in zip(self.intervals, source["intervals"]):
            if any(explained[k] != physical[k] for k in
                   ("interval_start", "interval_end", "evaluation_time", "duration_seconds")):
                raise ValueError("attribution chunk physical interval identity mismatch")
            if {m["module_instance_id"] for m in explained["modules"]} != set(physical["modules"]):
                raise ValueError("attribution chunk physical module coverage mismatch")
            for module in explained["modules"]:
                if module["source_local_state_sha256"] != physical["modules"][module["module_instance_id"]]["local_irradiance"]["state_payload_sha256"]:
                    raise ValueError("attribution chunk physical local-state source mismatch")
            if {s["string_id"] for s in explained["strings"]} != set(physical["strings"]):
                raise ValueError("attribution chunk physical string coverage mismatch")
            for string in explained["strings"]:
                curve = physical["strings"][string["string_id"]]["curve"]
                if string["source_curve_sha256"] != (canonical_object_sha256(curve) if curve is not None else None):
                    raise ValueError("attribution chunk physical curve source mismatch")
        payload = {**self.header, "source_numerical_result_sha256": numerical.numerical_result_sha256,
                   "intervals": self.intervals, "energy": integrate_channels(self.intervals)}
        result = DetailedDCAttributionResult.freeze(payload)
        if self.diagnostics is not None:
            self.diagnostics.seal()
            result = DetailedDCAttributionResult(result._canonical_payload,
                result.attribution_result_sha256, self.diagnostics)
        return result


_ATTRIBUTION_WORKER_CONTEXT = None


def _initialize_attribution_worker(context):
    global _ATTRIBUTION_WORKER_CONTEXT
    _ATTRIBUTION_WORKER_CONTEXT = None
    from .detailed_inputs import SnapshotWitnessError, validate_execution_transport
    if "dark_only_context" in context:
        raise SnapshotWitnessError("dark-only attribution context cannot cross worker boundary")
    validate_execution_transport(context)
    _ATTRIBUTION_WORKER_CONTEXT = context


def _evaluate_worker_attribution(interval):
    from .detailed_inputs import bind_worker_result
    return bind_worker_result(_ATTRIBUTION_WORKER_CONTEXT, _evaluate_attribution_interval(_ATTRIBUTION_WORKER_CONTEXT, interval))


def _ordered_attribution_results(context, intervals, workers):
    if workers == 1 or context.get("dark_only_context") is _DARK_ONLY_CONTEXT:
        for interval in intervals:
            yield _evaluate_attribution_interval(context, interval)
        return
    pending = deque()
    executor = ProcessPoolExecutor(max_workers=workers, mp_context=get_context("spawn"),
        initializer=_initialize_attribution_worker, initargs=(context,))
    try:
        intervals = iter(intervals)
        for _ in range(2 * workers):
            interval = next(intervals, None)
            if interval is None:
                break
            pending.append(executor.submit(_evaluate_worker_attribution, interval))
        while pending:
            from .detailed_inputs import accept_worker_result
            yield accept_worker_result(context, pending.popleft().result())
            interval = next(intervals, None)
            if interval is not None:
                pending.append(executor.submit(_evaluate_worker_attribution, interval))
    finally:
        for future in pending:
            future.cancel()
        executor.shutdown(wait=True, cancel_futures=True)


def execute_detailed_attribution_pass(numerical, *, collector, attribution_worker_count=1):
    """Evaluate sealed physical intervals, with all storage and finalization in the parent."""
    try:
        source = numerical.replay_stream()
        arguments = collector.arguments
        sample_count = source["numerical_policy"]["string_sample_count"]
        context = _attribution_context(arguments["module_inputs"], arguments["module_configs"],
            arguments["electrical_design"], sample_count, arguments["retain_diagnostics"],
            arguments.get("scientific_configuration"), arguments.get("frozen_selection"))
        results = _ordered_attribution_results(context, source["intervals"], attribution_worker_count)
        try:
            for record, rows in results:
                if collector.header is None:
                    collector.header = _attribution_header(source, arguments["module_inputs"],
                        arguments["module_configs"], arguments["electrical_design"], sample_count)
                collector.intervals.append(record)
                if collector.diagnostics is not None:
                    for row in rows:
                        collector.diagnostics.append(row)
        finally:
            results.close()
        return collector.finish(numerical)
    except BaseException:
        collector.close()
        raise
