import json
import math
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from referencing import Registry, Resource

from geometry.shading import (
    BEAM_SOLVER_ID,
    BEAM_SOLVER_VERSION,
    BeamShadowError,
    calculate_direct_beam_shadow,
)


ROOT = Path(__file__).resolve().parents[2]
HASH = "a" * 64


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


def _validate(result):
    schema = json.loads(
        (
            ROOT
            / "geometry/shading/beam-shadow-query-result.schema.json"
        ).read_text(encoding="utf-8")
    )
    Draft202012Validator(schema, registry=_registry()).validate(result)


def _area3(vertices):
    nx = ny = nz = 0.0
    for current, following in zip(vertices, vertices[1:] + vertices[:1]):
        nx += (current[1] - following[1]) * (current[2] + following[2])
        ny += (current[2] - following[2]) * (current[0] + following[0])
        nz += (current[0] - following[0]) * (current[1] + following[1])
    return 0.5 * math.sqrt(nx * nx + ny * ny + nz * nz)


def _receiver(
    vertices=None,
    *,
    normal=(0.0, 0.0, 1.0),
    receiver_id="receiver:r1",
    source_entity_type="module_instance",
    source_entity_id="r1",
):
    vertices = vertices or [
        [0.0, 0.0, 0.0],
        [2.0, 0.0, 0.0],
        [2.0, 2.0, 0.0],
        [0.0, 2.0, 0.0],
    ]
    return {
        "receiver_id": receiver_id,
        "source_entity_type": source_entity_type,
        "source_entity_id": source_entity_id,
        "receiver_type": "module_plane",
        "vertices_3d": vertices,
        "center_xyz": [
            sum(point[0] for point in vertices) / len(vertices),
            sum(point[1] for point in vertices) / len(vertices),
            sum(point[2] for point in vertices) / len(vertices),
        ],
        "normal_xyz": list(normal),
        "area_m2": _area3(vertices),
        "enabled": True,
        "pv_field_id": "field-1",
        "support_surface_id": "surface-1",
        "module_instance_id": source_entity_id,
        "metadata": {},
    }


def _plane_occluder(
    occluder_id,
    vertices,
    *,
    source_entity_type="obstacle",
    source_entity_id=None,
    shading_enabled=True,
):
    return {
        "occluder_id": occluder_id,
        "source_entity_type": source_entity_type,
        "source_entity_id": source_entity_id or occluder_id,
        "geometry_type": "polygon_faces",
        "faces": [
            {
                "face_id": f"{occluder_id}:face",
                "vertices_3d": vertices,
                "normal_xyz": [0.0, 0.0, 1.0],
            }
        ],
        "bounds_3d": {
            "min_xyz": [
                min(point[0] for point in vertices),
                min(point[1] for point in vertices),
                min(point[2] for point in vertices),
            ],
            "max_xyz": [
                max(point[0] for point in vertices),
                max(point[1] for point in vertices),
                max(point[2] for point in vertices),
            ],
        },
        "shading_enabled": shading_enabled,
        "metadata": {},
    }


def _compiled(receiver=None, occluders=()):
    return {
        "geometry_payload_sha256": HASH,
        "receivers": [receiver or _receiver()],
        "occluders": list(occluders),
    }


def _query(compiled, *, sun=(0.0, 0.0, 1.0), self_shading=True):
    result = calculate_direct_beam_shadow(
        compiled,
        receiver_id=compiled["receivers"][0]["receiver_id"],
        sun_vector_xyz=sun,
        self_shading_enabled=self_shading,
    )
    _validate(result)
    assert result["solver_id"] == BEAM_SOLVER_ID
    assert result["solver_version"] == BEAM_SOLVER_VERSION
    return result


def test_phase53_no_occluder_is_fully_visible():
    result = _query(_compiled())
    assert result["status"] == "evaluated"
    assert result["receiver_area_m2"] == pytest.approx(4.0)
    assert result["shaded_area_m2"] == pytest.approx(0.0)
    assert result["beam_visibility_factor"] == pytest.approx(1.0)
    assert result["beam_shaded_fraction"] == pytest.approx(0.0)
    assert result["contributing_occluder_ids"] == []


def test_phase53_full_rectangular_block_is_zero_visibility():
    occ = _plane_occluder(
        "occ-full",
        [
            [0.0, 0.0, 1.0],
            [2.0, 0.0, 1.0],
            [2.0, 2.0, 1.0],
            [0.0, 2.0, 1.0],
        ],
    )
    result = _query(_compiled(occluders=[occ]))
    assert result["shaded_area_m2"] == pytest.approx(4.0)
    assert result["beam_visibility_factor"] == pytest.approx(0.0)
    assert result["beam_shaded_fraction"] == pytest.approx(1.0)
    assert result["contributing_occluder_ids"] == ["occ-full"]


def test_phase53_half_rectangular_overlap_is_exactly_half_shaded():
    occ = _plane_occluder(
        "occ-half",
        [
            [0.0, 0.0, 1.0],
            [1.0, 0.0, 1.0],
            [1.0, 2.0, 1.0],
            [0.0, 2.0, 1.0],
        ],
    )
    result = _query(_compiled(occluders=[occ]))
    assert result["shaded_area_m2"] == pytest.approx(2.0)
    assert result["beam_visibility_factor"] == pytest.approx(0.5)
    assert result["beam_shaded_fraction"] == pytest.approx(0.5)


def test_phase53_diagonal_triangle_has_analytical_half_area():
    occ = _plane_occluder(
        "occ-triangle",
        [
            [0.0, 0.0, 1.0],
            [2.0, 0.0, 1.0],
            [0.0, 2.0, 1.0],
        ],
    )
    result = _query(_compiled(occluders=[occ]))
    assert result["shaded_area_m2"] == pytest.approx(2.0)
    assert result["beam_visibility_factor"] == pytest.approx(0.5)


def test_phase53_overlapping_occluders_are_unioned_not_double_counted():
    left = _plane_occluder(
        "occ-left",
        [
            [0.0, 0.0, 1.0],
            [1.5, 0.0, 1.0],
            [1.5, 2.0, 1.0],
            [0.0, 2.0, 1.0],
        ],
    )
    right = _plane_occluder(
        "occ-right",
        [
            [0.5, 0.0, 2.0],
            [2.0, 0.0, 2.0],
            [2.0, 2.0, 2.0],
            [0.5, 2.0, 2.0],
        ],
    )
    result = _query(_compiled(occluders=[left, right]))
    assert result["shaded_area_m2"] == pytest.approx(4.0)
    assert result["beam_visibility_factor"] == pytest.approx(0.0)
    assert result["contributing_occluder_ids"] == ["occ-left", "occ-right"]


def test_phase53_rotated_horizontal_receiver_preserves_area_and_full_shadow():
    root2 = math.sqrt(2.0)
    vertices = [
        [0.0, root2, 0.0],
        [root2, 0.0, 0.0],
        [0.0, -root2, 0.0],
        [-root2, 0.0, 0.0],
    ]
    receiver = _receiver(vertices)
    occ = _plane_occluder(
        "occ-rotated",
        [[x, y, z + 1.0] for x, y, z in vertices],
    )
    result = _query(_compiled(receiver, [occ]))
    assert result["receiver_area_m2"] == pytest.approx(4.0)
    assert result["shaded_area_m2"] == pytest.approx(4.0)
    assert result["beam_visibility_factor"] == pytest.approx(0.0)


def test_phase53_tilted_receiver_full_shadow_uses_receiver_plane_projection():
    root2 = math.sqrt(2.0)
    normal = (0.0, -1.0 / root2, 1.0 / root2)
    vertices = [
        [0.0, 0.0, 0.0],
        [2.0, 0.0, 0.0],
        [2.0, root2, root2],
        [0.0, root2, root2],
    ]
    receiver = _receiver(vertices, normal=normal)
    occ_vertices = [
        [
            point[0] + normal[0],
            point[1] + normal[1],
            point[2] + normal[2],
        ]
        for point in vertices
    ]
    occ = _plane_occluder("occ-tilted", occ_vertices)
    result = _query(
        _compiled(receiver, [occ]),
        sun=normal,
    )
    assert result["receiver_area_m2"] == pytest.approx(4.0)
    assert result["shaded_area_m2"] == pytest.approx(4.0)
    assert result["beam_visibility_factor"] == pytest.approx(0.0)


def test_phase53_low_solar_altitude_projects_shadow_laterally():
    sun = (math.sqrt(3.0) / 2.0, 0.0, 0.5)
    shift = math.sqrt(3.0)
    occ = _plane_occluder(
        "occ-low-sun",
        [
            [shift, 0.0, 1.0],
            [shift + 1.0, 0.0, 1.0],
            [shift + 1.0, 2.0, 1.0],
            [shift, 2.0, 1.0],
        ],
    )
    result = _query(_compiled(occluders=[occ]), sun=sun)
    assert result["shaded_area_m2"] == pytest.approx(2.0)
    assert result["beam_visibility_factor"] == pytest.approx(0.5)


def test_phase53_occluder_behind_receiver_cannot_cast_forward_shadow():
    occ = _plane_occluder(
        "occ-behind",
        [
            [0.0, 0.0, -1.0],
            [2.0, 0.0, -1.0],
            [2.0, 2.0, -1.0],
            [0.0, 2.0, -1.0],
        ],
    )
    result = _query(_compiled(occluders=[occ]))
    assert result["shaded_area_m2"] == 0.0
    assert result["beam_visibility_factor"] == 1.0
    assert result["contributing_occluder_ids"] == []


def test_phase53_boundary_touch_has_zero_shadow_area():
    occ = _plane_occluder(
        "occ-touch",
        [
            [2.0, 0.0, 1.0],
            [3.0, 0.0, 1.0],
            [3.0, 2.0, 1.0],
            [2.0, 2.0, 1.0],
        ],
    )
    result = _query(_compiled(occluders=[occ]))
    assert result["shaded_area_m2"] == 0.0
    assert result["beam_visibility_factor"] == 1.0


def test_phase53_sun_below_horizon_returns_no_direct_beam_status():
    result = _query(_compiled(), sun=(0.0, 1.0, -0.1))
    assert result["status"] == "no_direct_beam_sun_below_horizon"
    assert result["beam_visibility_factor"] == 1.0
    assert result["shaded_area_m2"] == 0.0
    assert result["projected_face_count"] == 0


def test_phase53_receiver_backside_returns_no_direct_beam_status():
    receiver = _receiver(normal=(0.0, 0.0, -1.0))
    result = _query(_compiled(receiver), sun=(0.0, 0.0, 1.0))
    assert result["status"] == "no_direct_beam_receiver_backside"
    assert result["beam_visibility_factor"] == 1.0
    assert result["shaded_area_m2"] == 0.0


def test_phase53_receiver_never_self_occludes():
    receiver = _receiver(
        source_entity_type="module_instance",
        source_entity_id="module-1",
    )
    self_occ = _plane_occluder(
        "occluder:module:module-1",
        [
            [0.0, 0.0, 1.0],
            [2.0, 0.0, 1.0],
            [2.0, 2.0, 1.0],
            [0.0, 2.0, 1.0],
        ],
        source_entity_type="module_instance",
        source_entity_id="module-1",
    )
    result = _query(_compiled(receiver, [self_occ]), self_shading=True)
    assert result["beam_visibility_factor"] == 1.0
    assert result["contributing_occluder_ids"] == []


def test_phase53_other_module_occlusion_obeys_self_shading_switch():
    other_module = _plane_occluder(
        "occluder:module:module-2",
        [
            [0.0, 0.0, 1.0],
            [2.0, 0.0, 1.0],
            [2.0, 2.0, 1.0],
            [0.0, 2.0, 1.0],
        ],
        source_entity_type="module_instance",
        source_entity_id="module-2",
    )
    compiled = _compiled(occluders=[other_module])

    disabled = _query(compiled, self_shading=False)
    enabled = _query(compiled, self_shading=True)

    assert disabled["beam_visibility_factor"] == 1.0
    assert enabled["beam_visibility_factor"] == 0.0


def test_phase53_disabled_occluder_is_ignored():
    occ = _plane_occluder(
        "occ-disabled",
        [
            [0.0, 0.0, 1.0],
            [2.0, 0.0, 1.0],
            [2.0, 2.0, 1.0],
            [0.0, 2.0, 1.0],
        ],
        shading_enabled=False,
    )
    result = _query(_compiled(occluders=[occ]))
    assert result["beam_visibility_factor"] == 1.0
    assert result["contributing_occluder_ids"] == []


def test_phase53_non_normalized_sun_vector_is_normalized_deterministically():
    result = _query(_compiled(), sun=(0.0, 0.0, 5.0))
    assert result["sun_vector_xyz"] == pytest.approx([0.0, 0.0, 1.0])


def test_phase53_missing_geometry_hash_fails_closed():
    compiled = _compiled()
    compiled["geometry_payload_sha256"] = ""
    with pytest.raises(BeamShadowError, match="geometry_payload_sha256"):
        calculate_direct_beam_shadow(
            compiled,
            receiver_id="receiver:r1",
            sun_vector_xyz=(0.0, 0.0, 1.0),
            self_shading_enabled=True,
        )


def test_phase53_unknown_receiver_fails_closed():
    with pytest.raises(BeamShadowError, match="resolve exactly once"):
        calculate_direct_beam_shadow(
            _compiled(),
            receiver_id="receiver:missing",
            sun_vector_xyz=(0.0, 0.0, 1.0),
            self_shading_enabled=True,
        )

def test_phase53_closed_box_face_set_projects_to_expected_half_shadow():
    box = {
        "occluder_id": "occ-box",
        "source_entity_type": "obstacle",
        "source_entity_id": "box-1",
        "geometry_type": "polygon_faces",
        "faces": [
            {
                "face_id": "box:base",
                "vertices_3d": [
                    [0.0, 0.0, 0.0],
                    [0.0, 2.0, 0.0],
                    [1.0, 2.0, 0.0],
                    [1.0, 0.0, 0.0],
                ],
                "normal_xyz": [0.0, 0.0, -1.0],
            },
            {
                "face_id": "box:top",
                "vertices_3d": [
                    [0.0, 0.0, 1.0],
                    [1.0, 0.0, 1.0],
                    [1.0, 2.0, 1.0],
                    [0.0, 2.0, 1.0],
                ],
                "normal_xyz": [0.0, 0.0, 1.0],
            },
            {
                "face_id": "box:side:0",
                "vertices_3d": [
                    [0.0, 0.0, 0.0],
                    [1.0, 0.0, 0.0],
                    [1.0, 0.0, 1.0],
                    [0.0, 0.0, 1.0],
                ],
                "normal_xyz": [0.0, -1.0, 0.0],
            },
            {
                "face_id": "box:side:1",
                "vertices_3d": [
                    [1.0, 0.0, 0.0],
                    [1.0, 2.0, 0.0],
                    [1.0, 2.0, 1.0],
                    [1.0, 0.0, 1.0],
                ],
                "normal_xyz": [1.0, 0.0, 0.0],
            },
            {
                "face_id": "box:side:2",
                "vertices_3d": [
                    [1.0, 2.0, 0.0],
                    [0.0, 2.0, 0.0],
                    [0.0, 2.0, 1.0],
                    [1.0, 2.0, 1.0],
                ],
                "normal_xyz": [0.0, 1.0, 0.0],
            },
            {
                "face_id": "box:side:3",
                "vertices_3d": [
                    [0.0, 2.0, 0.0],
                    [0.0, 0.0, 0.0],
                    [0.0, 0.0, 1.0],
                    [0.0, 2.0, 1.0],
                ],
                "normal_xyz": [-1.0, 0.0, 0.0],
            },
        ],
        "bounds_3d": {
            "min_xyz": [0.0, 0.0, 0.0],
            "max_xyz": [1.0, 2.0, 1.0],
        },
        "shading_enabled": True,
        "metadata": {},
    }
    result = _query(_compiled(occluders=[box]))
    assert result["shaded_area_m2"] == pytest.approx(2.0)
    assert result["beam_visibility_factor"] == pytest.approx(0.5)
    assert result["contributing_occluder_ids"] == ["occ-box"]


def test_phase53_nonplanar_receiver_fails_closed():
    receiver = _receiver(
        [
            [0.0, 0.0, 0.0],
            [2.0, 0.0, 0.0],
            [2.0, 2.0, 0.01],
            [0.0, 2.0, 0.0],
        ],
        normal=(0.0, 0.0, 1.0),
    )
    with pytest.raises(BeamShadowError, match="not coplanar"):
        calculate_direct_beam_shadow(
            _compiled(receiver),
            receiver_id=receiver["receiver_id"],
            sun_vector_xyz=(0.0, 0.0, 1.0),
            self_shading_enabled=True,
        )


def test_phase53_future_triangle_mesh_input_fails_explicitly():
    occ = _plane_occluder(
        "occ-mesh",
        [
            [0.0, 0.0, 1.0],
            [2.0, 0.0, 1.0],
            [2.0, 2.0, 1.0],
            [0.0, 2.0, 1.0],
        ],
    )
    occ["geometry_type"] = "triangle_mesh"
    with pytest.raises(BeamShadowError, match="unsupported occluder geometry_type"):
        calculate_direct_beam_shadow(
            _compiled(occluders=[occ]),
            receiver_id="receiver:r1",
            sun_vector_xyz=(0.0, 0.0, 1.0),
            self_shading_enabled=True,
        )

