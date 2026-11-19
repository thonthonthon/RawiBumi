import json
from copy import deepcopy
from pathlib import Path

from jsonschema import Draft202012Validator
from referencing import Registry, Resource

from engine.simulation import build_simulation_execution_plan


ROOT = Path(__file__).resolve().parents[2]


def _registry():
    registry = Registry()
    for directory in (
        ROOT / "schemas",
        ROOT / "components/schema",
        ROOT / "weather/schema",
        ROOT / "geometry/scene",
        ROOT / "geometry/coordinates",
        ROOT / "geometry/scene3d",
        ROOT / "geometry/shading",
        ROOT / "electrical/schema",
        ROOT / "apps/web/schema",
    ):
        for path in directory.glob("*.schema.json"):
            schema = json.loads(path.read_text(encoding="utf-8"))
            if "$id" in schema:
                registry = registry.with_resource(
                    schema["$id"], Resource.from_contents(schema)
                )
    return registry


def _scene(*, east_second=False, albedo_second=0.2):
    fields = [
        {
            "pv_field_id": "field-a",
            "support_surface_id": "surface-a",
            "tilt_deg": 20.0,
            "azimuth_deg": 0.0,
        },
        {
            "pv_field_id": "field-b",
            "support_surface_id": "surface-b",
            "tilt_deg": 20.0,
            "azimuth_deg": 90.0 if east_second else 0.0,
        },
    ]
    modules = []
    for prefix, field_id in (("a", "field-a"), ("b", "field-b")):
        for index in range(2):
            modules.append(
                {
                    "module_instance_id": f"module-{prefix}{index+1}",
                    "pv_field_id": field_id,
                    "module_definition_revision_id": "module-r1",
                    "enabled": True,
                }
            )
    return {
        "revision_id": "scene-r1",
        "surfaces": [
            {"surface_id": "surface-a", "albedo": 0.2},
            {"surface_id": "surface-b", "albedo": albedo_second},
        ],
        "pv_fields": fields,
        "module_instances": modules,
    }


def _electrical(*, both_strings_same_mppt=False):
    target_b = "mppt-1" if both_strings_same_mppt else "mppt-2"
    mppt1_strings = ["string-a", "string-b"] if both_strings_same_mppt else ["string-a"]
    mppt2_strings = [] if both_strings_same_mppt else ["string-b"]
    return {
        "electrical_revision_id": "electrical-r1",
        "inverter_instances": [
            {
                "inverter_instance_id": "inv-1",
                "inverter_definition_revision_id": "inverter-r1",
                "enabled": True,
            }
        ],
        "mppt_instances": [
            {
                "mppt_instance_id": "mppt-1",
                "inverter_instance_id": "inv-1",
                "index": 1,
                "enabled": True,
                "connected_string_ids": mppt1_strings,
            },
            {
                "mppt_instance_id": "mppt-2",
                "inverter_instance_id": "inv-1",
                "index": 2,
                "enabled": True,
                "connected_string_ids": mppt2_strings,
            },
        ],
        "strings": [
            {
                "string_id": "string-a",
                "module_instance_ids": ["module-a1", "module-a2"],
                "target_mppt_instance_id": "mppt-1",
                "enabled": True,
            },
            {
                "string_id": "string-b",
                "module_instance_ids": ["module-b1", "module-b2"],
                "target_mppt_instance_id": target_b,
                "enabled": True,
            },
        ],
    }


def _compiled():
    return {
        "geometry_payload_sha256": "a" * 64,
        "receivers": [
            {
                "source_entity_type": "module_instance",
                "module_instance_id": module_id,
                "receiver_id": f"receiver:module:{module_id}",
            }
            for module_id in ("module-a1", "module-a2", "module-b1", "module-b2")
        ],
    }


def _validate(plan):
    schema = json.loads(
        (ROOT / "schemas/simulation-execution-group-plan.schema.json").read_text(
            encoding="utf-8"
        )
    )
    Draft202012Validator(schema, registry=_registry()).validate(plan)


def test_phase52_homogeneous_strings_across_multiple_mppts_remain_one_group():
    plan = build_simulation_execution_plan(
        _scene(east_second=False),
        _electrical(),
        numerical_options={"albedo": 0.2},
        compiled_shading_geometry=_compiled(),
    )

    assert plan["execution_class"] == "homogeneous_single_group"
    assert plan["group_count"] == 1
    assert plan["legacy_homogeneous_backend_compatible"] is True
    group = plan["groups"][0]
    assert group["string_ids"] == ["string-a", "string-b"]
    assert group["mppt_instance_ids"] == ["mppt-1", "mppt-2"]
    assert group["mppt_indices"] == [1, 2]
    assert group["surface_azimuth_deg"] == 0.0
    assert group["receiver_ids"] == [
        "receiver:module:module-a1",
        "receiver:module:module-a2",
        "receiver:module:module-b1",
        "receiver:module:module-b2",
    ]
    assert plan["compiled_geometry_hash"] == "a" * 64
    _validate(plan)


def test_phase52_different_orientations_on_separate_mppts_are_separable_groups():
    plan = build_simulation_execution_plan(
        _scene(east_second=True),
        _electrical(),
        numerical_options={"albedo": 0.2},
    )

    assert plan["execution_class"] == "separable_multi_group"
    assert plan["group_count"] == 2
    assert plan["legacy_homogeneous_backend_compatible"] is False
    assert plan["heterogeneous_mppt_instance_ids"] == []

    by_azimuth = {
        group["surface_azimuth_deg"]: group for group in plan["groups"]
    }
    assert set(by_azimuth) == {0.0, 90.0}
    assert by_azimuth[0.0]["string_ids"] == ["string-a"]
    assert by_azimuth[0.0]["mppt_instance_ids"] == ["mppt-1"]
    assert by_azimuth[90.0]["string_ids"] == ["string-b"]
    assert by_azimuth[90.0]["mppt_instance_ids"] == ["mppt-2"]
    _validate(plan)


def test_phase52_different_orientations_on_same_mppt_are_electrically_coupled():
    plan = build_simulation_execution_plan(
        _scene(east_second=True),
        _electrical(both_strings_same_mppt=True),
    )

    assert plan["execution_class"] == "mixed_orientation_coupled"
    assert plan["group_count"] == 0
    assert len(plan["mixed_orientation"]["classes"]) == 2
    assert len(plan["mixed_orientation"]["mppts"]) == 1
    assert plan["heterogeneous_mppt_instance_ids"] == ["mppt-1"]
    assert not [f for f in plan["findings"] if f["severity"] == "error"]
    _validate(plan)


def test_phase52_one_string_spanning_orientations_is_invalid_not_split():
    scene = _scene(east_second=True)
    electrical = _electrical()
    electrical["strings"][0]["module_instance_ids"] = [
        "module-a1",
        "module-b1",
    ]
    electrical["strings"][1]["module_instance_ids"] = [
        "module-a2",
        "module-b2",
    ]

    plan = build_simulation_execution_plan(scene, electrical)

    assert plan["execution_class"] == "mixed_orientation_coupled"
    assert plan["group_count"] == 0
    counted = [mid for c in plan["mixed_orientation"]["classes"] for mid in c["module_instance_ids"]]
    assert sorted(counted) == sorted(m["module_instance_id"] for m in scene["module_instances"])
    assert len(counted) == len(set(counted))
    assert all(sum(s["composition"].values()) == 2 for m in plan["mixed_orientation"]["mppts"] for s in m["strings"])
    assert not plan["findings"]
    _validate(plan)


def test_phase52_different_albedo_is_a_distinct_irradiance_group():
    plan = build_simulation_execution_plan(
        _scene(east_second=False, albedo_second=0.35),
        _electrical(),
    )

    assert plan["execution_class"] == "separable_multi_group"
    assert {group["albedo"] for group in plan["groups"]} == {0.2, 0.35}
    _validate(plan)


def test_phase52_grouping_is_deterministic_under_collection_reordering():
    scene = _scene(east_second=True)
    electrical = _electrical()
    first = build_simulation_execution_plan(scene, electrical)

    reordered_scene = deepcopy(scene)
    reordered_scene["module_instances"] = list(
        reversed(reordered_scene["module_instances"])
    )
    reordered_scene["pv_fields"] = list(reversed(reordered_scene["pv_fields"]))
    reordered_scene["surfaces"] = list(reversed(reordered_scene["surfaces"]))

    reordered_electrical = deepcopy(electrical)
    reordered_electrical["strings"] = list(
        reversed(reordered_electrical["strings"])
    )
    reordered_electrical["mppt_instances"] = list(
        reversed(reordered_electrical["mppt_instances"])
    )

    second = build_simulation_execution_plan(
        reordered_scene,
        reordered_electrical,
    )
    assert first == second


def test_phase52_equal_resolved_albedo_can_share_group_with_mixed_provenance():
    scene = _scene(east_second=False, albedo_second=None)
    plan = build_simulation_execution_plan(
        scene,
        _electrical(),
        numerical_options={"albedo": 0.2},
    )

    assert plan["execution_class"] == "homogeneous_single_group"
    assert plan["group_count"] == 1
    assert plan["groups"][0]["albedo_sources"] == [
        "scene.support_surface.albedo",
        "simulation_configuration.numerical_options.albedo",
    ]
    _validate(plan)
