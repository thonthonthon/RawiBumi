"""Small real-kernel B2 candidate gates; no Level-2 execution permission."""
from copy import deepcopy
from dataclasses import replace
import hashlib
import json
from types import SimpleNamespace

import pvlib
import pytest

from components.topology_library import (
    assert_numerical_assumption_source_bindings, canonical_topology_asset_sha256,
)
from components.pan.pvsyst_sdm import calculate_pvsyst_diode_parameters
from engine.module.pvsyst import extract_validated_pvsyst_parameter_set
from engine.simulation.detailed_inputs import pin_detailed_module_inputs
from shading.electrical.contract import (
    NumericalAssumptionInputError, assert_numerical_assumption_evidence_structure,
    numerical_assumption_object_sha256, REQUIRED_NUMERICAL_ASSUMPTION_LIMITATIONS,
)
from shading.electrical.parameterization import (
    _acceptance_states, _cached_numerical_candidate, _check_numerical_conservation,
    _resolve_uniform_mpp_for_temperature_gate, evaluate_numerical_assumption_acceptance,
    validate_numerical_assumption_acceptance, finalize_parameterization_payload,
    ElectricalParameterizationError,
)
from tests.unit.test_phase69a_detailed_inputs import _inputs
from tests.unit.test_phase66_nonuniform_module_iv import _parameterization, _evidence


def _source(key, digest, source_type="pan"):
    return dict(schema_name="SourceRecord", schema_version="0.1", source_id=key,
                source_type=source_type, title="B2 synthetic numerical provenance",
                source_notes="Hypothetical equal-series regions; no manufacturer topology or yield validation.",
                manufacturer=None, file_hash=digest, imported_by="Fixture importer")


def _seal(candidate, *, update_assets=True):
    module, topology, definition, evidence, sources = candidate
    declaration = evidence["assumption_declaration"]
    if update_assets:
        definition.update(finalize_parameterization_payload(definition))
        declaration["topology"]["topology_sha256"] = canonical_topology_asset_sha256(topology)
        declaration["parameterization"]["parameterization_sha256"] = definition["parameterization_payload_sha256"]
        evidence["parameterization_payload_sha256"] = definition["parameterization_payload_sha256"]
    declaration["digest_sha256"] = numerical_assumption_object_sha256(declaration)
    sources["b2-assumption"]["file_hash"] = declaration["digest_sha256"]
    record = evidence["consistency_record"]
    record["assumption_digest_sha256"] = declaration["digest_sha256"]
    record["digest_sha256"] = numerical_assumption_object_sha256(record)
    return candidate


def _candidate():
    inputs = _inputs()
    module, topology = deepcopy(inputs["module"]), deepcopy(inputs["topology"])
    # Canonical module source SDM is retained; only the assumed regional assets
    # are authored. NCelP is never interpreted as physical internal wiring.
    params = extract_validated_pvsyst_parameter_set(module)
    topology["physical_regions"] = [r for r in topology["physical_regions"] if r["region_id"].endswith("r0")]
    for region in topology["physical_regions"]:
        region["polygon_normalized"][2][1] = 1.0
        region["polygon_normalized"][3][1] = 1.0
        region["equivalent_element_count"] = params["cells_in_series"] // 3
        region["active_area_fraction"] = 1/3
    for substring in topology["electrical_substrings"]:
        substring["physical_region_ids"] = substring["physical_region_ids"][:1]
        substring["parallel_branches"] = substring["parallel_branches"][:1]
    topology.update(verification_state="unverified", topology_provenance="inferred",
                    source_ids=["b2-retained", "b2-assumption"])
    metadata = dict(assumption_id="b2-equal-series", assumption_revision_id="b2-equal-series-r1",
                    evidence_class="NUMERICAL_ASSUMPTION")
    topology["metadata"]["numerical_assumption"] = metadata.copy()
    definition = _parameterization(topology)
    definition["metadata"]["numerical_assumption"] = metadata.copy()
    definition["source_ids"] = ["b2-retained", "b2-assumption"]
    for entry in definition["region_parameterizations"]:
        entry["parameter_set"] = dict(params)
        for key in ("cells_in_series", "r_series_ohm", "r_shunt_ref_ohm", "r_shunt_0_ohm"):
            entry["parameter_set"][key] /= 3
        entry["parameter_set"]["cells_in_series"] = params["cells_in_series"] // 3
        entry["current_domain_max_a"] = params["photocurrent_ref_a"] * 2
        entry["reverse_bias"]["minimum_supported_voltage_v"] = -5.0
    definition = finalize_parameterization_payload(definition)
    evidence = _evidence(definition)
    evidence.update(schema_version="0.2", evidence_class="NUMERICAL_ASSUMPTION",
                    parameterization_revision_id=definition["revision_id"],
                    parameterization_provenance="simulation_assumption", verification_state="not_applicable",
                    validation_status="not_applicable", validation_record_id=None,
                    source_ids=["b2-original", "b2-retained", "b2-assumption"])
    evidence["assumption_declaration"] = dict(
        **metadata, assumption_source_id="b2-assumption", author="Fixture scientific author",
        rationale="Three equal-series equivalent regions using canonical PVsyst semantics, with independently assumed reverse and bypass domains.",
        module_source=dict(component_id=module["module_definition_id"], revision_id=module["revision_id"],
                           original_pan_sha256="b"*64, retained_pan_sha256="c"*64),
        topology=dict(topology_id=topology["module_topology_id"], topology_revision_id=topology["revision_id"],
                      topology_sha256=canonical_topology_asset_sha256(topology)),
        parameterization=dict(parameterization_id=definition["parameterization_id"],
                              parameterization_revision_id=definition["revision_id"],
                              parameterization_sha256=definition["parameterization_payload_sha256"]),
        region_count=3, scientific_limitations=list(REQUIRED_NUMERICAL_ASSUMPTION_LIMITATIONS))
    evidence["assumption_declaration"]["digest_sha256"] = numerical_assumption_object_sha256(evidence["assumption_declaration"])
    sources = {key: _source(key, digest, kind) for key, digest, kind in (
        ("b2-original", "b"*64, "pan"), ("b2-retained", "c"*64, "pan"),
        ("b2-assumption", evidence["assumption_declaration"]["digest_sha256"], "manual_entry"))}
    module["source_ids"] = list(module["source_ids"]) + ["b2-retained"]
    record = dict(policy_id="rawibumi.level2.uniform_iv_equal_series", policy_version="1.0.0",
                  assumption_digest_sha256=evidence["assumption_declaration"]["digest_sha256"],
                  model_family="pvsyst_sdm", voltage_tolerance_v=0.0001, cases=[])
    for g, t in ((1000, 25), (800, 45), (400, 15)):
        diode = calculate_pvsyst_diode_parameters(effective_irradiance_w_m2=g,
                    cell_temperature_c=t, parameter_set=params)
        isc = float(pvlib.pvsystem.singlediode(*diode, method="lambertw")["i_sc"])
        _, adapter = _acceptance_states(topology, definition, evidence,
            {r["region_id"]: float(g) for r in topology["physical_regions"]}, float(t), "lambertw")
        samples = []
        for fraction in (0.10, 0.30, 0.50, 0.70, 0.90):
            current = fraction * isc
            whole = float(pvlib.pvsystem.v_from_i(current, *diode, method="lambertw"))
            assembled = adapter.voltage_at_current(current)["terminal_voltage_v"]
            samples.append(dict(current_a=current, module_voltage_v=whole,
                                assembled_voltage_v=assembled, residual_v=assembled-whole))
        record["cases"].append(dict(irradiance_w_m2=g, cell_temperature_c=t, samples=samples))
    record["max_abs_residual_v"] = max(abs(s["residual_v"]) for case in record["cases"] for s in case["samples"])
    record["passed"] = record["max_abs_residual_v"] <= 1e-4
    evidence["consistency_record"] = record
    return _seal((module, topology, definition, evidence, sources))


@pytest.fixture(scope="module")
def candidate():
    return _candidate()


def _evaluate(candidate, **kwargs):
    return evaluate_numerical_assumption_acceptance(*candidate, **kwargs)


def _assert_rejected(candidate, match):
    result = _evaluate(candidate)
    assert not result["accepted"], result
    assert not result["execution_allowed"]
    assert match in "; ".join(result["failures"]), result
    return result


def test_real_equal_series_all_gates_and_b1_record_unchanged(candidate):
    before = deepcopy(candidate)
    assert_numerical_assumption_evidence_structure(candidate[3])
    result = _evaluate(candidate)
    assert result["accepted"], result
    assert result["consistency_record"] == candidate[3]["consistency_record"]
    assert result["consistency_record"]["max_abs_residual_v"] <= 1e-4
    assert len(result["conservation"]) == 15
    assert len(result["bypass"]) == 3
    assert all(s["states"] == [False, False, True] for s in result["bypass"])
    assert all(s["absolute_error"] <= s["tolerance"] for s in result["temperature_responses"].values())
    assert not result["execution_allowed"]
    assert result["source_provenance"]["byte_evidence"]["original"].startswith("source-record hash only")
    assert candidate == before


@pytest.mark.parametrize("key", ["b2-original", "b2-retained", "b2-assumption"])
def test_all_three_source_records_required(candidate, key):
    changed = deepcopy(candidate)
    del changed[4][key]
    _assert_rejected(changed, "unavailable SourceRecord")


@pytest.mark.parametrize("field,value,message", [
    ("title", "", "title"), ("title", None, "title"),
    ("source_notes", "  ", "source_notes"), ("source_notes", None, "source_notes"),
    ("source_type", "manufacturer_submission", "source_type"),
    ("manufacturer", "Manufacturer", "manufacturer"),
    ("file_hash", "f"*64, "file_hash"), ("source_id", "wrong", "registry identity"),
])
def test_assumption_source_content(candidate, field, value, message):
    changed = deepcopy(candidate)
    changed[4]["b2-assumption"][field] = value
    _assert_rejected(changed, message)


@pytest.mark.parametrize("field", ["title", "source_notes", "manufacturer"])
def test_missing_assumption_source_fields(candidate, field):
    changed = deepcopy(candidate)
    del changed[4]["b2-assumption"][field]
    _assert_rejected(changed, field)


@pytest.mark.parametrize("role", ["original", "retained"])
def test_pan_hash_relationships(candidate, role):
    changed = deepcopy(candidate)
    changed[4]["b2-"+role]["file_hash"] = "f"*64
    _assert_rejected(changed, "two distinct resolved SourceRecords")


def test_source_bytes_mismatch_and_importer_independent(candidate):
    provenance = assert_numerical_assumption_source_bindings(candidate[0], candidate[3], candidate[4])
    assert provenance["assumption_source_id"] == "b2-assumption"
    assert candidate[4]["b2-assumption"]["imported_by"] != candidate[3]["assumption_declaration"]["author"]
    _assert_rejected_with_bytes = _evaluate(candidate, source_bytes={"b2-retained": b"wrong bytes"})
    assert not _assert_rejected_with_bytes["accepted"]
    assert "available bytes" in str(_assert_rejected_with_bytes["failures"])


@pytest.mark.parametrize("index", [1, 2])
@pytest.mark.parametrize("change", ["missing", "id", "revision", "class", "extra"])
def test_typed_asset_metadata(candidate, index, change):
    changed = deepcopy(candidate)
    metadata = changed[index]["metadata"]
    if change == "missing":
        del metadata["numerical_assumption"]
    else:
        field = {"id": "assumption_id", "revision": "assumption_revision_id",
                 "class": "evidence_class", "extra": "unexpected"}[change]
        metadata["numerical_assumption"][field] = "wrong"
    _seal(changed)
    _assert_rejected(changed, "exact linkage mismatch")


@pytest.mark.parametrize("path", ["module_id", "module_revision", "topology_id", "topology_revision",
                                  "topology_digest", "parameterization_revision", "parameterization_digest"])
def test_actual_revision_and_payload_substitution(candidate, path):
    changed = deepcopy(candidate)
    module, topology, definition, evidence, _ = changed
    declaration = evidence["assumption_declaration"]
    if path == "module_id":
        module["module_definition_id"] += "-wrong"
    elif path == "module_revision":
        module["revision_id"] += "-wrong"
    elif path == "topology_id":
        declaration["topology"]["topology_id"] += "-wrong"
    elif path == "topology_revision":
        topology["revision_id"] += "-wrong"
        definition["module_topology_revision_id"] = topology["revision_id"]
        definition.update(finalize_parameterization_payload(definition))
    elif path == "topology_digest":
        topology["notes"] += " modified"
    elif path == "parameterization_revision":
        # Same parameterization ID with another revision is insufficient.
        definition["revision_id"] += "-wrong"
        definition.update(finalize_parameterization_payload(definition))
    else:
        definition["notes"] += " modified"
        definition.update(finalize_parameterization_payload(definition))
    _seal(changed, update_assets=False)
    _assert_rejected(changed, "mismatch")


@pytest.mark.parametrize("field,factor", [("r_series_ohm", 3), ("r_shunt_ref_ohm", 3),
    ("r_shunt_0_ohm", 3), ("alpha_sc_a_per_c", 3), ("mu_gamma", 0)])
def test_wrong_transform_real_kernel_rejected(candidate, field, factor):
    changed = deepcopy(candidate)
    for entry in changed[2]["region_parameterizations"]:
        value = entry["parameter_set"][field]
        entry["parameter_set"][field] = value*factor if field != "mu_gamma" else value + 0.001
    _seal(changed)
    result = _assert_rejected(changed, "G1")
    assert result["consistency_record"]["max_abs_residual_v"] > 1e-4
    assert not result["consistency_record"]["passed"]


@pytest.mark.parametrize("change", ["current", "voltage", "false_pass", "maximum"])
def test_forged_record_recomputed_even_when_self_signed(candidate, change):
    changed = deepcopy(candidate)
    record = changed[3]["consistency_record"]
    sample = record["cases"][0]["samples"][0]
    if change == "current":
        sample["current_a"] *= 1.00001
    elif change == "voltage":
        sample["module_voltage_v"] += 0.001
        sample["assembled_voltage_v"] += 0.001
        sample["residual_v"] = sample["assembled_voltage_v"] - sample["module_voltage_v"]
        record["max_abs_residual_v"] = max(abs(s["residual_v"]) for case in record["cases"] for s in case["samples"])
    elif change == "false_pass":
        record["passed"] = False
    else:
        # B1 will reject the inconsistent maximum before kernels are needed.
        record["max_abs_residual_v"] = 0.0001
    _seal(changed)
    _assert_rejected(changed, "consistency" if change == "maximum" else "recomputation")


def test_real_conservation_bypass_and_negative_reverse(candidate):
    _, topology, definition, evidence, _ = candidate
    irradiances = {r["region_id"]: 1000. for r in topology["physical_regions"]}
    irradiances["s0-r0"] = 100.
    states, adapter = _acceptance_states(topology, definition, evidence, irradiances, 25., "lambertw")
    checks, solved = _check_numerical_conservation(topology, states, adapter, states["s1-r0"].isc_a * 0.7)
    assert any(s["bypass_active"] for s in solved)
    assert checks["current_residual_a"] <= 1e-6
    assert checks["voltage_residual_v"] <= 1e-6
    assert checks["power_residual_w"] <= 1e-5
    region = states["s0-r0"]
    assert region.voltage_at_current(region.isc_a + 0.1) == pytest.approx(-region.reverse_resistance_ohm * 0.1)


@pytest.mark.parametrize("corruption,gate", [("terminal", "G3"), ("branch", "G3"),
                                             ("current", "G2"), ("power", "G4")])
def test_conservation_rejects_corrupted_real_results(candidate, monkeypatch, corruption, gate):
    import shading.electrical.substring_reference as substring
    _, topology, definition, evidence, _ = candidate
    states, adapter = _acceptance_states(topology, definition, evidence,
        {r["region_id"]: 1000. for r in topology["physical_regions"]}, 25., "lambertw")
    current = states["s0-r0"].isc_a * (0.95 if corruption == "power" else 0.5)
    if corruption == "terminal":
        real = adapter.voltage_at_current
        adapter = replace(adapter, voltage_at_current=lambda i: {**real(i), "terminal_voltage_v": real(i)["terminal_voltage_v"] + 1.0})
    else:
        real = substring.evaluate_protected_substring_at_current
        def tampered(*args, **kwargs):
            result = deepcopy(real(*args, **kwargs))
            if corruption == "branch":
                result["terminal_branch_states"][0]["voltage_v"] += 1.0
            elif corruption == "current":
                result["terminal_branch_states"][0]["current_a"] += 0.001
            else:
                # Tiny voltage corruption passes G3 but exceeds signed-power G4.
                if result["substring_id"] == "s0":
                    result["terminal_voltage_v"] += 9e-7
            return result
        monkeypatch.setattr(substring, "evaluate_protected_substring_at_current", tampered)
    # Positive conservation is real above; deliberate result corruption only
    # establishes independent rejection arithmetic, not physical equivalence.
    with pytest.raises(ElectricalParameterizationError, match=gate):
        _check_numerical_conservation(topology, states, adapter, current)


def test_golden_precision_real_kernel(candidate):
    _, topology, definition, evidence, _ = candidate
    states, adapter = _acceptance_states(topology, definition, evidence,
        {r["region_id"]: 1000. for r in topology["physical_regions"]}, 25., "lambertw")
    isc = states["s0-r0"].isc_a
    coarse = _resolve_uniform_mpp_for_temperature_gate(adapter, isc)
    tight = _resolve_uniform_mpp_for_temperature_gate(adapter, isc, bracket_scale=1e-11)
    assert coarse["bracket_width_a"] <= 1e-10 * max(1, isc)
    assert tight["bracket_width_a"] <= 1e-11 * max(1, isc)
    assert max(coarse["evaluations"], tight["evaluations"]) <= 256
    for key in ("i_mp", "v_mp", "p_mp"):
        assert abs(coarse[key] - tight[key]) <= 1e-8


def test_unresolved_mpp_rejected():
    adapter = SimpleNamespace(voltage_at_current=lambda i: dict(
        terminal_voltage_v=0., protected_substrings=[]))
    with pytest.raises(ElectricalParameterizationError, match="flat MPP"):
        _resolve_uniform_mpp_for_temperature_gate(adapter, 10.)


@pytest.mark.parametrize("condition", ["nonfinite", "connectivity", "reverse_domain", "solver", "temperature", "negative_g"])
def test_unsupported_domain_rejected(candidate, condition):
    changed = deepcopy(candidate)
    if condition == "nonfinite":
        changed[0]["electrical_models"] = deepcopy(changed[0]["electrical_models"])
        model = next(m for m in changed[0]["electrical_models"] if m["model_type"] == "pvsyst_singlediode")
        model["parameter_set"]["gamma_ref"] = float("nan")
        _assert_rejected(changed, "finite")
    elif condition == "connectivity":
        changed[1]["electrical_substrings"][0]["parallel_branches"][0]["series_region_ids"] = ["unknown"]
        _seal(changed)
        _assert_rejected(changed, "region")
    elif condition == "reverse_domain":
        for entry in changed[2]["region_parameterizations"]:
            entry["reverse_bias"]["minimum_supported_voltage_v"] = -0.001
        _seal(changed)
        _assert_rejected(changed, "reference current ceiling is too low to reach requested branch voltage")
    elif condition == "solver":
        assert not _evaluate(changed, solver="unsupported")["accepted"]
    else:
        irradiances = {r["region_id"]: 1000. for r in changed[1]["physical_regions"]}
        if condition == "negative_g":
            irradiances["s0-r0"] = -1.
        with pytest.raises(ElectricalParameterizationError, match="absolute zero|non-negative"):
            _acceptance_states(changed[1], changed[2], changed[3], irradiances,
                               -273.15 if condition == "temperature" else 25., "lambertw")


def test_cache_full_fingerprints_and_no_mutable_result_authority(candidate):
    _cached_numerical_candidate.cache_clear()
    first = _evaluate(candidate)
    assert first["accepted"], first
    first["accepted"] = False
    second = _evaluate(candidate)
    assert second["accepted"]
    assert _cached_numerical_candidate.cache_info().hits == 1
    changed = deepcopy(candidate)
    changed[4]["b2-assumption"]["source_notes"] += " Changed provenance."
    third = _evaluate(changed)
    assert third["accepted"], third
    assert _cached_numerical_candidate.cache_info().misses == 2
    assert second["input_fingerprint_sha256"] != third["input_fingerprint_sha256"]
    assert _evaluate(candidate, use_cache=False) == second


def test_acceptance_does_not_authorize_pin_or_public_builder(candidate):
    module, topology, definition, evidence, sources = candidate
    with pytest.raises(NumericalAssumptionInputError, match="B3"):
        pin_detailed_module_inputs(module=module, topology=topology,
            parameterization=definition, evidence=evidence, sources=sources)
    from shading.electrical.parameterization import build_pvsyst_region_electrical_states
    with pytest.raises(NumericalAssumptionInputError, match="B3 authorization boundary"):
        build_pvsyst_region_electrical_states(topology, {}, {}, definition, evidence)
    bad = deepcopy(candidate)
    bad[4]["b2-assumption"]["title"] = ""
    with pytest.raises(NumericalAssumptionInputError, match="title"):
        validate_numerical_assumption_acceptance(*bad)


@pytest.mark.parametrize("malformation", ["quality", "missing_definition", "duplicate_definition"])
def test_actual_dispatch_v02_no_fallback(tmp_path, malformation):
    from engine.simulation.detailed_inputs import FrozenDetailedSelectionSnapshot, _bytes, semantic_scientific_payload
    from tests.unit.test_phase69a_canonical_dispatch import _context, _run
    project, config, store, bundle = _context("explicit_lower_fidelity")
    frozen = store.detailed_electrical_inputs.replay()
    assets = frozen["pinned_electrical_shading_assets"]
    evidence = next(iter(assets["electrical_parameterization_evidence"].values()))
    evidence["schema_version"] = "0.2"
    if malformation == "quality":
        evidence["module_quality_declaration"] = dict(
            relationship="separate_from_parameterization",
            module_quality_loss_fraction=0.0,
            source_ids=["quality-source-outside-evidence"],
            rationale="Schema-valid quality declaration with an unbound source.")
    elif malformation == "missing_definition":
        assets["electrical_parameterization_definitions"] = {}
    else:
        definitions = assets["electrical_parameterization_definitions"]
        duplicate = deepcopy(next(iter(definitions.values())))
        duplicate["revision_id"] += "-duplicate"
        definitions[duplicate["revision_id"]] = duplicate
    # Construct authentic hashes for malformed scientific content. Production
    # replay/dispatch must refuse it without producing a geometry-only run.
    encoded = _bytes(frozen)
    store = replace(store, detailed_electrical_inputs=FrozenDetailedSelectionSnapshot(
        encoded, hashlib.sha256(encoded).hexdigest(),
        hashlib.sha256(_bytes(semantic_scientific_payload(frozen))).hexdigest()))
    result = _run(tmp_path, project, config, store)
    assert result.simulation_run["status"] == "failed"
    identity = result.simulation_run["detailed_execution_identity"]
    assert identity["runtime_support_result"] == "blocked"
    assert identity["resolved_fidelity"] is None
    assert identity["fallback_applied"] is False
    assert "NUMERICAL_ASSUMPTION_EXECUTION_DENIED" in "; ".join(identity["failure_reasons"])


def test_legacy_v01_pin_and_hash_unchanged():
    inputs = _inputs()
    first = pin_detailed_module_inputs(**inputs)
    inputs["evidence"]["metadata"] = {"numerical_assumption": {"allow_synthetic_regions": True}}
    second = pin_detailed_module_inputs(**inputs)
    assert first.replay()["evidence"]["schema_version"] == "0.1"
    assert second.replay()["evidence"]["metadata"] == inputs["evidence"]["metadata"]
    assert second == pin_detailed_module_inputs(**inputs)
    assert set(first.replay()) == {"module", "topology", "parameterization", "evidence", "sources"}


def test_two_distinct_pan_records_even_when_byte_digests_equal(candidate):
    changed = deepcopy(candidate)
    changed[3]["assumption_declaration"]["module_source"]["original_pan_sha256"] = "c"*64
    changed[4]["b2-original"]["file_hash"] = "c"*64
    _seal(changed)
    bindings = assert_numerical_assumption_source_bindings(changed[0], changed[3], changed[4])
    assert bindings["original_source_id"] != bindings["retained_source_id"]
    del changed[4]["b2-original"]
    changed[3]["source_ids"].remove("b2-original")
    _assert_rejected(changed, "two distinct")


def test_available_pan_bytes_evidence_strength(candidate, tmp_path):
    changed = deepcopy(candidate)
    raw = b"retained fixture\n"
    original = b"original fixture\r\n"
    declaration = changed[3]["assumption_declaration"]
    declaration["module_source"]["retained_pan_sha256"] = hashlib.sha256(raw).hexdigest()
    declaration["module_source"]["original_pan_sha256"] = hashlib.sha256(original).hexdigest()
    changed[4]["b2-retained"]["file_hash"] = hashlib.sha256(raw).hexdigest()
    changed[4]["b2-original"]["file_hash"] = hashlib.sha256(original).hexdigest()
    path = tmp_path / "retained.PAN"
    path.write_bytes(raw)
    changed[4]["b2-retained"]["filename"] = str(path)
    _seal(changed)
    result = _evaluate(changed, source_bytes={"b2-original": original, "b2-retained": path.read_bytes()})
    assert result["accepted"], result
    assert all(value.startswith("available bytes hash verified") for value in
               result["source_provenance"]["byte_evidence"].values())
    # An existing physics cache entry must not bypass fresh file-byte checks.
    path.write_bytes(raw + b"tampered")
    rejected = _evaluate(changed, source_bytes={"b2-original": original,
                                               "b2-retained": path.read_bytes()})
    assert not rejected["accepted"]
    assert "available bytes" in "; ".join(rejected["failures"])


def test_jinko_retained_hash_module_identity_crosscheck(candidate):
    changed = deepcopy(candidate)
    digest = "aff43dc4f6b5213abd87a14e0814fda47b8bb51bf7cb439bfa5fa590190229f3"
    changed[3]["assumption_declaration"]["module_source"]["retained_pan_sha256"] = digest
    changed[4]["b2-retained"]["file_hash"] = digest
    _seal(changed)
    _assert_rejected(changed, "Jinko retained PAN digest")


def test_real_kernel_nonconvergence_rejected(candidate, monkeypatch):
    import shading.electrical.parameterization as parameterization
    def fail(*args, **kwargs):
        raise RuntimeError("controlled kernel convergence failure")
    monkeypatch.setattr(parameterization.pvlib.pvsystem, "singlediode", fail)
    result = _evaluate(candidate, use_cache=False)
    assert not result["accepted"]
    assert "convergence failure" in str(result["failures"])


def test_legacy_dispatch_fallback_unchanged(tmp_path):
    from tests.unit.test_phase69a_canonical_dispatch import (
        _context, _run, _legacy_configuration,
    )
    project, config, store, _ = _context("explicit_lower_fidelity")
    request = config["shading_configuration"]["electrical_shading_configuration"]
    config["shading_configuration"] = _legacy_configuration()["shading_configuration"]
    config["shading_configuration"]["electrical_shading_configuration"] = request
    config["numerical_options"]["losses"]["module_mismatch_loss_fraction"] = 0.01
    result = _run(tmp_path, project, config, store)
    identity = result.simulation_run["detailed_execution_identity"]
    assert identity["runtime_support_result"] == "fallback_to_geometry_only"
    assert identity["fallback_applied"] is True


def test_temperature_response_gate_rejects_perturbed_regional_mpp(candidate, monkeypatch):
    import shading.electrical.parameterization as parameterization
    real_states = parameterization._acceptance_states
    real_mpp = parameterization._resolve_uniform_mpp_for_temperature_gate
    temperatures = {}

    def tracked_states(*args, **kwargs):
        states, adapter = real_states(*args, **kwargs)
        temperatures[id(adapter)] = args[4]
        return states, adapter

    def perturbed_mpp(adapter, isc, **kwargs):
        result = dict(real_mpp(adapter, isc, **kwargs))
        # Perturb both precision runs identically only at the thermal endpoint.
        # G1 and the three characteristic cases remain real and unchanged.
        if temperatures[id(adapter)] == 26:
            result["i_mp"] += 0.01
        return result

    monkeypatch.setattr(parameterization, "_acceptance_states", tracked_states)
    monkeypatch.setattr(parameterization, "_resolve_uniform_mpp_for_temperature_gate", perturbed_mpp)
    result = _evaluate(candidate, use_cache=False)
    assert not result["accepted"]
    assert "G8 temperature response i_mp" in "; ".join(result["failures"])


def test_source_filename_is_not_filesystem_authority(candidate, tmp_path):
    changed = deepcopy(candidate)
    path = tmp_path / "untrusted.PAN"
    path.write_bytes(b"not retained evidence")
    changed[4]["b2-retained"]["filename"] = str(path)
    result = _evaluate(changed)
    assert result["accepted"], result
    assert result["source_provenance"]["byte_evidence"]["retained"] == (
        "source-record hash only; retained bytes unavailable")
