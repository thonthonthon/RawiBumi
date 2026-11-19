import copy
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from referencing import Registry, Resource

from components.candidates import build_module_candidate
from components.pan import map_pan, parse_pan_text
from engine.module import (
    MODULE_PVSYST_SDM,
    calculate_pvsyst_module_electrical,
    extract_validated_pvsyst_parameter_set,
)
from engine.optical import OpticalResult
from engine.simulation.models.module_resolver import resolve_module_model
from engine.thermal import ThermalResult
from shading.electrical import (
    Level1ModuleApproximationError,
    build_module_equivalent_irradiance_from_module_shading,
    collapse_local_irradiance_to_module_equivalent,
    evaluate_level1_module_approximation,
)


ROOT = Path(__file__).resolve().parents[2]


def _registry() -> Registry:
    registry = Registry()
    for directory in (
        ROOT / "schemas",
        ROOT / "components/schema",
        ROOT / "weather/schema",
        ROOT / "geometry/scene",
        ROOT / "geometry/coordinates",
        ROOT / "geometry/scene3d",
        ROOT / "geometry/shading",
        ROOT / "shading/electrical",
        ROOT / "electrical/schema",
        ROOT / "apps/web/schema",
        ROOT / "apps/api/schema",
    ):
        if not directory.exists():
            continue
        for path in directory.glob("*.schema.json"):
            schema = json.loads(path.read_text(encoding="utf-8"))
            if "$id" in schema:
                registry = registry.with_resource(
                    schema["$id"], Resource.from_contents(schema)
                )
    return registry


def _validate(path: str, value):
    schema = json.loads((ROOT / path).read_text(encoding="utf-8"))
    Draft202012Validator(schema, registry=_registry()).validate(value)


def _module_and_evidence():
    text = (ROOT / "tests/fixtures/panond/synthetic_module.pan").read_text(
        encoding="utf-8"
    )
    mapping = map_pan(parse_pan_text(text))
    candidate = build_module_candidate(
        mapping,
        candidate_id="phase64-synthetic-module",
        module_definition_id="phase64-synthetic-module-definition",
        revision_id="phase64-synthetic-module-r1",
        source_id="phase64-synthetic-source",
    )
    module = candidate["canonical_data"]
    evidence = resolve_module_model(
        module,
        resolution_id="phase64-module-resolution",
        requested_model_id=MODULE_PVSYST_SDM,
    )
    assert evidence["status"] == "resolved"
    return module, evidence


def _module_shading(*, beam=0.5, sky=0.8, ground=1.0):
    return {
        "source_scene_revision_id": "scene-r1",
        "shading_result_id": "shading-module-m1",
        "physical_result_sha256": "a" * 64,
        "receiver_granularity": "module",
        "electrical_shading_scope": "not_modeled",
        "inline_records": [
            {
                "receiver_id": "receiver:module:m1",
                "beam_visibility_factor": beam,
                "sky_visibility_factor": sky,
                "ground_visibility_factor": ground,
                "quality_flags": [],
            }
        ],
    }


def _equivalent(module):
    return build_module_equivalent_irradiance_from_module_shading(
        _module_shading(),
        module_instance_id="m1",
        module_definition_revision_id=module["revision_id"],
        receiver_id="receiver:module:m1",
        unshaded_poa={
            "beam_w_m2": 800.0,
            "sky_diffuse_w_m2": 100.0,
            "ground_reflected_w_m2": 20.0,
        },
        optical_modifier={
            "beam": 0.9,
            "sky_diffuse": 0.95,
            "ground_reflected": 0.8,
        },
        optical_model_manifest={
            "model_id": "phase64.synthetic.optics",
            "model_version": "0.1",
        },
        module_temperature_c=45.0,
        interval_start="2026-09-27T11:00:00+07:00",
        evaluation_time="2026-09-27T11:30:00+07:00",
    )


def test_phase64_direct_module_equivalent_preserves_channel_order_without_topology():
    module, _ = _module_and_evidence()
    state = _equivalent(module)

    assert state["source_module_topology_revision_id"] is None
    assert state["source_electrical_region_map_hash"] is None
    assert state["post_geometry_poa"] == pytest.approx(
        {
            "beam_w_m2": 400.0,
            "sky_diffuse_w_m2": 80.0,
            "ground_reflected_w_m2": 20.0,
        }
    )
    assert state["post_optical_poa"] == pytest.approx(
        {
            "beam_w_m2": 360.0,
            "sky_diffuse_w_m2": 76.0,
            "ground_reflected_w_m2": 16.0,
        }
    )
    assert state["equivalent_incident_poa_global_w_m2"] == pytest.approx(500.0)
    assert state["equivalent_effective_irradiance_w_m2"] == pytest.approx(452.0)


def test_phase64_level1_executes_validated_whole_module_sdm_and_matches_direct_engine():
    module, evidence = _module_and_evidence()
    equivalent = _equivalent(module)
    result = evaluate_level1_module_approximation(
        module,
        evidence,
        equivalent,
        source_electrical_revision_id="electrical-r1",
    )

    params = extract_validated_pvsyst_parameter_set(module)
    import pandas as pd
    index = pd.DatetimeIndex([pd.Timestamp(equivalent["interval_start"])])
    optical = OpticalResult(
        frame=pd.DataFrame(
            {
                "evaluation_time": [pd.Timestamp(equivalent["evaluation_time"])],
                "effective_irradiance_w_m2": [
                    equivalent["equivalent_effective_irradiance_w_m2"]
                ],
                "incident_poa_global_w_m2": [
                    equivalent["equivalent_incident_poa_global_w_m2"]
                ],
            },
            index=index,
        ),
        metadata={"model_id": "phase64-test"},
    )
    thermal = ThermalResult(
        frame=pd.DataFrame(
            {
                "evaluation_time": [pd.Timestamp(equivalent["evaluation_time"])],
                "cell_temperature_c": [45.0],
                "module_temperature_c": [45.0],
            },
            index=index,
        ),
        metadata={"model_id": "phase64-test"},
    )
    area = module["mechanical"]["width_m"] * module["mechanical"]["height_m"]
    direct = calculate_pvsyst_module_electrical(
        optical,
        thermal,
        parameter_set=params,
        module_area_m2=area,
    ).frame.iloc[0]

    state = result.module_state
    assert state["module_mpp"]["pmp_w"] == pytest.approx(direct["pmp_w"], rel=1e-12)
    assert state["module_mpp"]["vmp_v"] == pytest.approx(direct["vmp_v"], rel=1e-12)
    assert state["module_mpp"]["imp_a"] == pytest.approx(direct["imp_a"], rel=1e-12)
    assert result.electrical_shading_result["resolved_fidelity"] == (
        "level_1_module_approximation"
    )
    assert result.electrical_shading_result["source_module_topology_revision_ids"] == []
    assert result.electrical_shading_result["source_region_map_hashes"] == []
    assert result.electrical_shading_result["attribution_channels"]["geometric_irradiance"] == {
        "status": "upstream",
        "accounting_rule": "upstream_not_rebooked",
    }
    for channel in ("electrical_mismatch", "bypass_interaction", "mppt_operating_point"):
        assert result.electrical_shading_result["attribution_channels"][channel]["status"] == "not_modeled"

    _validate(
        "shading/electrical/module-level-electrical-approximation-state.schema.json",
        state,
    )
    _validate(
        "shading/electrical/electrical-shading-result.schema.json",
        result.electrical_shading_result,
    )


def test_phase64_raw_module_boolean_or_missing_resolved_evidence_cannot_execute_level1():
    module, _ = _module_and_evidence()
    with pytest.raises(Level1ModuleApproximationError, match="requested fidelity"):
        evaluate_level1_module_approximation(
            module,
            {},
            _equivalent(module),
            source_electrical_revision_id="electrical-r1",
        )


def _regional_inputs():
    region_map = {
        "electrical_region_map_id": "map-m1",
        "mapping_payload_sha256": "b" * 64,
        "source_scene_revision_id": "scene-r1",
        "source_module_instance_id": "m1",
        "source_module_definition_revision_id": "module-r1",
        "source_module_topology_revision_id": "topology-r1",
        "source_receiver_id": "receiver:module:m1",
        "mapped_region_area_m2": 2.0,
        "mapped_region_area_fraction": 1.0,
        "regions": [
            {"region_id": "left", "area_m2": 1.0},
            {"region_id": "right", "area_m2": 1.0},
        ],
    }
    common_unshaded = {
        "beam_w_m2": 1000.0,
        "sky_diffuse_w_m2": 0.0,
        "ground_reflected_w_m2": 0.0,
    }
    local_state = {
        "state_id": "local-m1",
        "state_payload_sha256": "c" * 64,
        "source_electrical_region_map_id": "map-m1",
        "source_electrical_region_map_hash": "b" * 64,
        "source_scene_revision_id": "scene-r1",
        "source_module_instance_id": "m1",
        "source_module_definition_revision_id": "module-r1",
        "source_shading_result_id": "regional-shading-m1",
        "source_shading_physical_result_hash": "d" * 64,
        "interval_start": "2026-09-27T04:00:00Z",
        "evaluation_time": "2026-09-27T04:30:00Z",
        "irradiance_mapping_order": "unshaded_poa_by_channel_then_geometry_visibility_then_optical_treatment",
        "thermal_state_scope": "single_module_temperature",
        "module_temperature_c": 40.0,
        "optical_model_manifest": {"model_id": "unity", "model_version": "0.1"},
        "quality_flags": [],
        "regions": [
            {
                "region_id": "left",
                "unshaded_poa": common_unshaded,
                "post_geometry_poa": {
                    "beam_w_m2": 1000.0,
                    "sky_diffuse_w_m2": 0.0,
                    "ground_reflected_w_m2": 0.0,
                },
                "optical_modifier": {
                    "beam": 1.0,
                    "sky_diffuse": 1.0,
                    "ground_reflected": 1.0,
                },
                "effective_irradiance_w_m2": 1000.0,
                "quality_flags": [],
            },
            {
                "region_id": "right",
                "unshaded_poa": common_unshaded,
                "post_geometry_poa": {
                    "beam_w_m2": 500.0,
                    "sky_diffuse_w_m2": 0.0,
                    "ground_reflected_w_m2": 0.0,
                },
                "optical_modifier": {
                    "beam": 1.0,
                    "sky_diffuse": 1.0,
                    "ground_reflected": 1.0,
                },
                "effective_irradiance_w_m2": 500.0,
                "quality_flags": [],
            },
        ],
    }
    return region_map, local_state


def test_phase64_optional_phase63_adapter_is_area_weighted_and_identity_bound():
    region_map, local_state = _regional_inputs()
    equivalent = collapse_local_irradiance_to_module_equivalent(region_map, local_state)
    assert equivalent["equivalent_effective_irradiance_w_m2"] == pytest.approx(750.0)
    assert equivalent["equivalent_incident_poa_global_w_m2"] == pytest.approx(750.0)
    assert equivalent["source_module_topology_revision_id"] == "topology-r1"
    assert equivalent["source_electrical_region_map_hash"] == "b" * 64
    assert equivalent["mapped_region_area_fraction"] == pytest.approx(1.0)

    mixed = copy.deepcopy(local_state)
    mixed["source_electrical_region_map_hash"] = "e" * 64
    with pytest.raises(Level1ModuleApproximationError, match="map hash mismatch"):
        collapse_local_irradiance_to_module_equivalent(region_map, mixed)


def test_phase64_regional_adapter_fails_closed_on_incomplete_coverage():
    region_map, local_state = _regional_inputs()
    region_map["mapped_region_area_fraction"] = 0.8
    with pytest.raises(Level1ModuleApproximationError, match="complete mapped module area"):
        collapse_local_irradiance_to_module_equivalent(region_map, local_state)


def test_phase64_result_hashes_are_deterministic_for_same_inputs():
    module, evidence = _module_and_evidence()
    equivalent = _equivalent(module)
    first = evaluate_level1_module_approximation(
        module,
        evidence,
        equivalent,
        source_electrical_revision_id="electrical-r1",
    )
    second = evaluate_level1_module_approximation(
        module,
        evidence,
        equivalent,
        source_electrical_revision_id="electrical-r1",
    )
    assert first == second
