"""First Phase 6.9A increment: pinned science and separate runtime preflight."""

from copy import deepcopy
from dataclasses import replace
import json

import pytest

from apps.api.catalog import load_reference_catalog
from engine.irradiance import POA_ISOTROPIC
from engine.inverter import INVERTER_VOLTAGE_DEPENDENT
from engine.module import MODULE_PVSYST_SDM
from engine.solar import SOLAR_POSITION_NREL_SPA
from engine.simulation.detailed_inputs import (
    DETAILED_SCOPE,
    DetailedInputError,
    pin_detailed_module_inputs,
    validate_detailed_runtime_support,
)
from engine.thermal import THERMAL_PVSYST
from geometry.shading import BEAM_SOLVER_ID, SKY_VISIBILITY_SOLVER_ID, GROUND_VISIBILITY_SOLVER_ID
from geometry.shading.contract import ShadingContractError, assert_geometry_aware_shading_configuration
from shading.electrical.module_iv import MODULE_NONUNIFORM_IV_SOLVER_ID
from shading.electrical.mppt_tracker import IDEAL_GLOBAL_MPPT_MODEL_ID
from shading.electrical.parameterization import (
    ElectricalParameterizationError,
    REGION_PARAMETERIZATION_MODEL_ID,
    finalize_parameterization_payload,
)
from shading.electrical.string_iv import GENERAL_SERIES_STRING_IV_SOLVER_ID
from tests.unit.test_phase61_electrical_shading_contract import _phase5_configuration
from tests.unit.test_phase66_nonuniform_module_iv import _parameterization, _evidence


def _inputs():
    catalog = load_reference_catalog()
    module = catalog["modules"]["mod-rawibumi-uat-550-r1"]
    topology = catalog["module_topologies"]["topology-rawibumi-uat-550-r1"]
    definition = _parameterization(topology)
    evidence = _evidence(definition)
    source = deepcopy(next(iter(catalog["sources"].values())))
    source["source_id"] = "phase66-synthetic-region-source"
    source["title"] = "Synthetic regional parameterization test source"
    sources = {**catalog["sources"], source["source_id"]: source}
    return dict(module=module, topology=topology, parameterization=definition,
                evidence=evidence, sources=sources)


def _configuration():
    shading = _phase5_configuration()
    shading.update(beam_method=BEAM_SOLVER_ID, diffuse_method=SKY_VISIBILITY_SOLVER_ID,
                   albedo_method=GROUND_VISIBILITY_SOLVER_ID)
    shading["electrical_shading_configuration"] = {
        "schema_name": "ElectricalShadingConfiguration", "schema_version": "0.1",
        "contract_version": "0.1", "requested_fidelity": "level_2_bypass_substring",
        "fallback_policy": "fail_closed", "thermal_state_scope": "single_module_temperature",
        "loss_accounting_boundary": "geometry_then_electrical_mismatch_then_mppt",
        "model_selections": {
            "module_electrical_model_id": MODULE_PVSYST_SDM,
            "region_parameterization_model_id": REGION_PARAMETERIZATION_MODEL_ID,
            "cell_parameterization_model_id": None,
            "bypass_model_family_id": "bypass.constant_drop.synthetic_assumption",
            "module_iv_assembly_model_id": MODULE_NONUNIFORM_IV_SOLVER_ID,
            "string_iv_assembly_model_id": GENERAL_SERIES_STRING_IV_SOLVER_ID,
            "mppt_operating_point_model_id": IDEAL_GLOBAL_MPPT_MODEL_ID,
        },
        "scientific_options": {}, "execution_options": {},
    }
    return {
        "shading_configuration": shading,
        "model_selections": {"transposition": POA_ISOTROPIC,
                             "temperature": THERMAL_PVSYST,
                             "solar_position": SOLAR_POSITION_NREL_SPA,
                             "inverter": INVERTER_VOLTAGE_DEPENDENT,
                             "module_electrical": MODULE_PVSYST_SDM},
        "numerical_options": {},
    }


def test_phase69a_snapshot_owns_inputs_and_replays_deterministically():
    inputs = _inputs()
    before = deepcopy(inputs)
    first = pin_detailed_module_inputs(**inputs)
    second = pin_detailed_module_inputs(**inputs)
    assert inputs == before
    assert first == second
    inputs["parameterization"]["notes"] = "caller mutation"
    assert first.replay()["parameterization"] == before["parameterization"]
    replay = first.replay()
    replay["module"]["revision_id"] = "caller mutation"
    assert first.replay()["module"] == before["module"]


def test_phase69a_snapshot_detects_outer_payload_tamper():
    snapshot = pin_detailed_module_inputs(**_inputs())
    payload = json.loads(snapshot.canonical_payload)
    payload["sources"]["phase66-synthetic-region-source"]["title"] = "tampered"
    with pytest.raises(DetailedInputError, match="hash mismatch"):
        replace(snapshot, canonical_payload=json.dumps(payload).encode()).replay()


def test_phase69a_rejects_parameter_tamper_and_rehashed_unbound_parameters():
    inputs = _inputs()
    inputs["parameterization"]["region_parameterizations"][0]["parameter_set"]["r_series_ohm"] = 0.08
    with pytest.raises(ElectricalParameterizationError):
        pin_detailed_module_inputs(**inputs)
    inputs["parameterization"] = finalize_parameterization_payload(inputs["parameterization"])
    with pytest.raises(ElectricalParameterizationError, match="evidence does not match"):
        pin_detailed_module_inputs(**inputs)


def test_phase69a_rejects_cross_revision_binding():
    inputs = _inputs()
    inputs["evidence"]["module_definition_revision_id"] = "stale-module-r1"
    with pytest.raises(ElectricalParameterizationError, match="evidence does not match"):
        pin_detailed_module_inputs(**inputs)


def test_phase69a_rejects_missing_or_miskeyed_sources():
    inputs = _inputs()
    del inputs["sources"]["phase66-synthetic-region-source"]
    with pytest.raises(ValueError, match="unavailable SourceRecord"):
        pin_detailed_module_inputs(**inputs)
    inputs = _inputs()
    inputs["sources"]["phase66-synthetic-region-source"]["source_id"] = "different"
    with pytest.raises(DetailedInputError, match="registry key"):
        pin_detailed_module_inputs(**inputs)


def test_phase69a_preflight_is_separate_and_preserves_phase5_rejection():
    configuration = _configuration()
    before = deepcopy(configuration)
    snapshot = pin_detailed_module_inputs(**_inputs())
    assert validate_detailed_runtime_support(configuration, snapshot) == DETAILED_SCOPE
    assert configuration == before
    with pytest.raises(ShadingContractError, match="does not consume the Phase-6"):
        assert_geometry_aware_shading_configuration(configuration["shading_configuration"])


@pytest.mark.parametrize("name", ["module_mismatch_loss_fraction", "string_mismatch_loss_fraction"])
def test_phase69a_nonzero_configured_mismatch_fails_closed(name):
    configuration = _configuration()
    configuration["numerical_options"] = {"losses": {name: 0.01}}
    with pytest.raises(DetailedInputError, match="no distinct residual semantic"):
        validate_detailed_runtime_support(configuration, pin_detailed_module_inputs(**_inputs()))


def test_phase69a_nonzero_quality_is_preserved_for_pending_downstream_semantics():
    configuration = _configuration()
    configuration["numerical_options"] = {"module_overrides": {"module_quality_loss_fraction": -0.0075}}
    assert validate_detailed_runtime_support(configuration, pin_detailed_module_inputs(**_inputs())) == DETAILED_SCOPE
    assert configuration["numerical_options"]["module_overrides"]["module_quality_loss_fraction"] == -0.0075


@pytest.mark.parametrize("field,value", [
    ("transposition", "poa.perez.pvlib.v0.1"),
    ("temperature", "thermal.pvsyst81.prilliman_adapted.v0.1"),
])
def test_phase69a_unsupported_physics_fails_closed(field, value):
    configuration = _configuration()
    configuration["model_selections"][field] = value
    with pytest.raises(DetailedInputError, match="unsupported detailed"):
        validate_detailed_runtime_support(configuration, pin_detailed_module_inputs(**_inputs()))


@pytest.mark.parametrize("field,value", [
    ("sun_position_resolution_seconds", 3600),
    ("diffuse_method", "none"),
    ("receiver_granularity", "electrical_region"),
])
def test_phase69a_unsupported_geometry_fails_closed(field, value):
    configuration = _configuration()
    configuration["shading_configuration"][field] = value
    with pytest.raises((DetailedInputError, ShadingContractError)):
        validate_detailed_runtime_support(configuration, pin_detailed_module_inputs(**_inputs()))


def test_phase69a_nonzero_component_quality_is_not_silently_discarded():
    inputs = _inputs()
    inputs["module"].setdefault("quality", {})["default_module_quality_loss_fraction"] = -0.0075
    snapshot = pin_detailed_module_inputs(**inputs)
    assert validate_detailed_runtime_support(_configuration(), snapshot) == DETAILED_SCOPE
    assert snapshot.replay()["module"]["quality"]["default_module_quality_loss_fraction"] == -0.0075


@pytest.mark.parametrize("count", [True, 0, 100, 101.0])
def test_phase69a_invalid_string_sampling_fails_closed(count):
    config = _configuration()
    config["shading_configuration"]["electrical_shading_configuration"]["scientific_options"] = {"string_sample_count": count}
    with pytest.raises(DetailedInputError, match="integer >= 101"):
        validate_detailed_runtime_support(config, pin_detailed_module_inputs(**_inputs()))


@pytest.mark.parametrize("count", [101, 201])
def test_phase69a_explicit_string_sampling_is_scientific(count):
    config = _configuration()
    config["shading_configuration"]["electrical_shading_configuration"]["scientific_options"] = {"string_sample_count": count}
    assert validate_detailed_runtime_support(config, pin_detailed_module_inputs(**_inputs())) == DETAILED_SCOPE
