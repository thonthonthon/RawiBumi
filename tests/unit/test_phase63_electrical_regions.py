import copy
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from referencing import Registry, Resource

from geometry.shading import GroundDomeResolution, SkyDomeResolution
from shading.electrical import (
    ElectricalRegionMapError,
    LocalElectricalIrradianceError,
    build_local_electrical_irradiance_state,
    derive_electrical_region_map,
    evaluate_electrical_region_visibility,
)


ROOT = Path(__file__).resolve().parents[2]
HASH = "a" * 64


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


def _topology():
    return {
        "schema_name": "ModuleTopologyDefinition",
        "schema_version": "0.1",
        "contract_version": "0.1",
        "module_topology_id": "topo-two-region",
        "revision_id": "topo-two-region-r1",
        "module_definition_revision_id": "module-r1",
        "topology_version": "0.1",
        "orientation_reference": "viewed_from_module_front",
        "coordinate_convention": "module_front_uv_normalized_width_height",
        "topology_class": "series_substrings_parallel_branches",
        "region_resolution": "grouped_cells",
        "physical_regions": [
            {
                "region_id": "left",
                "region_type": "grouped_cells",
                "polygon_normalized": [[0, 0], [0.5, 0], [0.5, 1], [0, 1]],
                "electrical_substring_id": "s0",
                "equivalent_element_count": 30,
            },
            {
                "region_id": "right",
                "region_type": "grouped_cells",
                "polygon_normalized": [[0.5, 0], [1, 0], [1, 1], [0.5, 1]],
                "electrical_substring_id": "s1",
                "equivalent_element_count": 30,
            },
        ],
        "electrical_substrings": [
            {
                "substring_id": "s0",
                "series_order": 0,
                "physical_region_ids": ["left"],
                "parallel_branches": [
                    {"branch_id": "s0-b0", "series_region_ids": ["left"]}
                ],
                "bypass_device_id": "d0",
            },
            {
                "substring_id": "s1",
                "series_order": 1,
                "physical_region_ids": ["right"],
                "parallel_branches": [
                    {"branch_id": "s1-b0", "series_region_ids": ["right"]}
                ],
                "bypass_device_id": "d1",
            },
        ],
        "bypass_devices": [
            {
                "bypass_device_id": "d0",
                "device_type": "bypass_diode",
                "protects_substring_ids": ["s0"],
                "forward_voltage_model": {
                    "model_type": "ideal",
                    "model_id": "bypass.ideal.test",
                    "model_version": "0.1",
                    "model_authority": "explicit_simulation_assumption",
                    "verification_state": "not_applicable",
                    "model_provenance": "simulation_assumption",
                    "validation_record_id": None,
                    "assumption_id": "assumption-d0",
                    "assumption_rationale": "Synthetic geometry test only.",
                    "parameters": {},
                    "source_ids": [],
                    "model_payload_sha256": "b" * 64,
                },
            },
            {
                "bypass_device_id": "d1",
                "device_type": "bypass_diode",
                "protects_substring_ids": ["s1"],
                "forward_voltage_model": {
                    "model_type": "ideal",
                    "model_id": "bypass.ideal.test",
                    "model_version": "0.1",
                    "model_authority": "explicit_simulation_assumption",
                    "verification_state": "not_applicable",
                    "model_provenance": "simulation_assumption",
                    "validation_record_id": None,
                    "assumption_id": "assumption-d1",
                    "assumption_rationale": "Synthetic geometry test only.",
                    "parameters": {},
                    "source_ids": [],
                    "model_payload_sha256": "c" * 64,
                },
            },
        ],
        "bypass_coverage_complete": True,
        "verification_state": "reviewed",
        "topology_provenance": "manual_verified",
        "source_ids": ["source-test"],
        "notes": None,
        "metadata": {},
    }


def _compiled(*, orientation="portrait", obstacle=True):
    if orientation == "portrait":
        # canonical generated order: TR, TL, BL, BR when viewed from module front
        corners = [[1, 2, 0], [-1, 2, 0], [-1, -2, 0], [1, -2, 0]]
    else:
        corners = [[2, 1, 0], [-2, 1, 0], [-2, -1, 0], [2, -1, 0]]
    occluders = []
    if obstacle:
        occluders.append(
            {
                "occluder_id": "occluder:left-half",
                "source_entity_type": "obstacle",
                "source_entity_id": "left-half",
                "geometry_type": "polygon_faces",
                "faces": [
                    {
                        "face_id": "left-half:top",
                        "vertices_3d": [
                            [-1, -2, 1], [0, -2, 1], [0, 2, 1], [-1, 2, 1]
                        ],
                        "normal_xyz": [0, 0, 1],
                    }
                ],
                "bounds_3d": {"min_xyz": [-1, -2, 1], "max_xyz": [0, 2, 1]},
                "shading_enabled": True,
                "metadata": {},
            }
        )
    return {
        "source_scene_revision_id": "scene-r1",
        "geometry_payload_sha256": HASH,
        "receivers": [
            {
                "receiver_id": "receiver:module:m1",
                "source_entity_type": "module_instance",
                "source_entity_id": "m1",
                "receiver_type": "module_plane",
                "vertices_3d": corners,
                "center_xyz": [0, 0, 0],
                "normal_xyz": [0, 0, 1],
                "area_m2": 8.0,
                "enabled": True,
                "pv_field_id": "field-1",
                "support_surface_id": "surface-1",
                "module_instance_id": "m1",
                "metadata": {
                    "module_definition_revision_id": "module-r1",
                    "orientation": orientation,
                },
            }
        ],
        "occluders": occluders,
    }


def _region(map_value, source_id):
    return next(
        item for item in map_value["regions"]
        if item["source_topology_region_id"] == source_id
    )


def test_phase63_portrait_region_map_is_deterministic_area_preserving_and_schema_valid():
    first = derive_electrical_region_map(_compiled(obstacle=False), _topology(), module_instance_id="m1")
    second = derive_electrical_region_map(_compiled(obstacle=False), _topology(), module_instance_id="m1")
    assert first == second
    assert first["mapped_region_area_m2"] == pytest.approx(8.0)
    assert first["mapped_region_area_fraction"] == pytest.approx(1.0)
    assert first["source_compiled_geometry_hash"] == HASH
    assert first["mapper_manifest"]["landscape_rotation_convention"] == (
        "clockwise_90_viewed_from_module_front"
    )

    left = _region(first, "left")
    assert left["vertices_3d"] == [
        [-1.0, -2.0, 0.0],
        [0.0, -2.0, 0.0],
        [0.0, 2.0, 0.0],
        [-1.0, 2.0, 0.0],
    ]
    assert left["source_electrical_substring_id"] == "s0"
    _validate("shading/electrical/electrical-region-map.schema.json", first)


def test_phase63_landscape_rotation_is_frozen_clockwise_from_module_front():
    mapped = derive_electrical_region_map(
        _compiled(orientation="landscape", obstacle=False),
        _topology(),
        module_instance_id="m1",
    )
    left = _region(mapped, "left")
    # Intrinsic left half becomes the upper half after the frozen CW 90° placement.
    assert left["vertices_3d"] == [
        [-2.0, 1.0, 0.0],
        [-2.0, 0.0, 0.0],
        [2.0, 0.0, 0.0],
        [2.0, 1.0, 0.0],
    ]
    assert mapped["placement_orientation"] == "landscape"


def test_phase63_stale_module_topology_binding_fails_closed():
    topology = copy.deepcopy(_topology())
    topology["module_definition_revision_id"] = "other-module-r1"
    with pytest.raises(ElectricalRegionMapError, match="exact ModuleDefinition revision"):
        derive_electrical_region_map(_compiled(obstacle=False), topology, module_instance_id="m1")


def test_phase63_region_visibility_uses_phase5_geometry_without_booking_electrical_loss():
    mapped = derive_electrical_region_map(_compiled(), _topology(), module_instance_id="m1")
    visibility = evaluate_electrical_region_visibility(
        _compiled(),
        mapped,
        sun_vector_xyz=[0, 0, 1],
        self_shading_enabled=False,
        sky_resolution=SkyDomeResolution(4, 1, 4, 1, 10.0),
        ground_resolution=GroundDomeResolution(4, 1),
        timestamp="2026-09-27T12:00:00+07:00",
    )
    records = {item["receiver_id"]: item for item in visibility["inline_records"]}
    left_id = _region(mapped, "left")["region_id"]
    right_id = _region(mapped, "right")["region_id"]

    assert records[left_id]["beam_visibility_factor"] == pytest.approx(0.0)
    assert records[right_id]["beam_visibility_factor"] == pytest.approx(1.0)
    assert visibility["receiver_granularity"] == "electrical_region"
    assert visibility["electrical_shading_scope"] == "not_modeled"
    assert visibility["source_electrical_region_map_hash"] == mapped["mapping_payload_sha256"]
    _validate("geometry/shading/shading-result.schema.json", visibility)


def test_phase63_local_irradiance_preserves_channels_and_applies_optics_after_geometry():
    compiled = _compiled()
    mapped = derive_electrical_region_map(compiled, _topology(), module_instance_id="m1")
    visibility = evaluate_electrical_region_visibility(
        compiled,
        mapped,
        sun_vector_xyz=[0, 0, 1],
        self_shading_enabled=False,
        sky_resolution=SkyDomeResolution(4, 1, 4, 1, 10.0),
        ground_resolution=GroundDomeResolution(4, 1),
        timestamp="2026-09-27T12:00:00+07:00",
    )
    state = build_local_electrical_irradiance_state(
        mapped,
        visibility,
        unshaded_poa={
            "beam_w_m2": 800.0,
            "sky_diffuse_w_m2": 100.0,
            "ground_reflected_w_m2": 20.0,
        },
        optical_modifier={"beam": 0.9, "sky_diffuse": 0.95, "ground_reflected": 0.8},
        optical_model_manifest={
            "model_id": "optics.synthetic.explicit",
            "model_version": "0.1",
            "notes": "Synthetic Phase-6.3 contract test.",
        },
        module_temperature_c=45.0,
        interval_start="2026-09-27T11:00:00+07:00",
        evaluation_time="2026-09-27T12:00:00+07:00",
    )

    for region in state["regions"]:
        vis = region["visibility_factor"]
        assert region["post_geometry_poa"]["beam_w_m2"] == pytest.approx(800.0 * vis["beam"])
        expected = (
            800.0 * vis["beam"] * 0.9
            + 100.0 * vis["sky_diffuse"] * 0.95
            + 20.0 * vis["ground"] * 0.8
        )
        assert region["effective_irradiance_w_m2"] == pytest.approx(expected)
        assert region["unshaded_poa"] == {
            "beam_w_m2": 800.0,
            "sky_diffuse_w_m2": 100.0,
            "ground_reflected_w_m2": 20.0,
        }

    _validate("shading/electrical/local-electrical-irradiance-state.schema.json", state)


def test_phase63_local_state_rejects_region_set_or_map_identity_mixing():
    compiled = _compiled(obstacle=False)
    mapped = derive_electrical_region_map(compiled, _topology(), module_instance_id="m1")
    visibility = evaluate_electrical_region_visibility(
        compiled,
        mapped,
        sun_vector_xyz=[0, 0, 1],
        self_shading_enabled=False,
        sky_resolution=SkyDomeResolution(4, 1, 4, 1, 10.0),
        ground_resolution=GroundDomeResolution(4, 1),
    )
    bad = copy.deepcopy(visibility)
    bad["inline_records"] = bad["inline_records"][:-1]
    with pytest.raises(LocalElectricalIrradianceError, match="exactly match"):
        build_local_electrical_irradiance_state(
            mapped,
            bad,
            unshaded_poa={"beam_w_m2": 1, "sky_diffuse_w_m2": 1, "ground_reflected_w_m2": 1},
            optical_modifier={"beam": 1, "sky_diffuse": 1, "ground_reflected": 1},
            optical_model_manifest={"model_id": "unity", "model_version": "0.1"},
            module_temperature_c=25,
            interval_start="2026-09-27T00:00:00Z",
            evaluation_time="2026-09-27T00:00:00Z",
        )
