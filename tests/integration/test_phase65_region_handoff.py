from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from geometry.shading import (
    GroundDomeResolution,
    SkyDomeResolution,
)
from shading.electrical import (
    build_analytical_region_reference_states,
    build_local_electrical_irradiance_state,
    derive_electrical_region_map,
    evaluate_electrical_region_visibility,
    evaluate_protected_substring_at_current,
)


ROOT = Path(__file__).resolve().parents[2]

TOPOLOGY_PATH = (
    ROOT
    / "components"
    / "reference"
    / "module-topology-uat-550.json"
)


def _topology():
    return json.loads(
        TOPOLOGY_PATH.read_text(
            encoding="utf-8"
        )
    )


def _base_compiled_geometry():
    """Synthetic module plane using real Phase-6 topology binding."""

    return {
        "source_scene_revision_id": (
            "phase65-integration-scene-r1"
        ),
        "geometry_payload_sha256": (
            "1" * 64
        ),
        "receivers": [
            {
                "receiver_id": (
                    "receiver:module:"
                    "phase65-integration"
                ),
                "source_entity_type": (
                    "module_instance"
                ),
                "source_entity_id": (
                    "phase65-module-instance"
                ),
                "receiver_type": (
                    "module_plane"
                ),

                # Canonical portrait order used by
                # the existing Phase-6.3 tests:
                # TR, TL, BL, BR.
                #
                # 3 m x 2 m provides clean thirds
                # and halves for the UAT topology.
                "vertices_3d": [
                    [1.5, 1.0, 0.0],
                    [-1.5, 1.0, 0.0],
                    [-1.5, -1.0, 0.0],
                    [1.5, -1.0, 0.0],
                ],
                "center_xyz": [
                    0.0,
                    0.0,
                    0.0,
                ],
                "normal_xyz": [
                    0.0,
                    0.0,
                    1.0,
                ],
                "area_m2": 6.0,
                "enabled": True,
                "pv_field_id": (
                    "phase65-field"
                ),
                "support_surface_id": (
                    "phase65-surface"
                ),
                "module_instance_id": (
                    "phase65-module-instance"
                ),
                "metadata": {
                    "module_definition_revision_id": (
                        "mod-rawibumi-uat-550-r1"
                    ),
                    "orientation": (
                        "portrait"
                    ),
                },
            }
        ],
        "occluders": [],
    }


def _target_region(
    region_map,
    source_topology_region_id,
):
    matches = [
        region
        for region
        in region_map["regions"]
        if region[
            "source_topology_region_id"
        ]
        == source_topology_region_id
    ]

    assert len(matches) == 1
    return matches[0]


def _occluder_from_mapped_region(
    mapped_region,
):
    """Place a horizontal occluder exactly above one mapped region."""

    lifted = [
        [
            float(vertex[0]),
            float(vertex[1]),
            float(vertex[2]) + 1.0,
        ]
        for vertex
        in mapped_region[
            "vertices_3d"
        ]
    ]

    xs = [
        vertex[0]
        for vertex
        in lifted
    ]
    ys = [
        vertex[1]
        for vertex
        in lifted
    ]
    zs = [
        vertex[2]
        for vertex
        in lifted
    ]

    return {
        "occluder_id": (
            "occluder:phase65:"
            + mapped_region[
                "source_topology_region_id"
            ]
        ),
        "source_entity_type": (
            "obstacle"
        ),
        "source_entity_id": (
            "phase65-target-obstacle"
        ),
        "geometry_type": (
            "polygon_faces"
        ),
        "faces": [
            {
                "face_id": (
                    "phase65-target-obstacle:"
                    "top"
                ),
                "vertices_3d": lifted,
                "normal_xyz": [
                    0.0,
                    0.0,
                    1.0,
                ],
            }
        ],
        "bounds_3d": {
            "min_xyz": [
                min(xs),
                min(ys),
                min(zs),
            ],
            "max_xyz": [
                max(xs),
                max(ys),
                max(zs),
            ],
        },
        "shading_enabled": True,
        "metadata": {
            "phase65_fixture": True,
        },
    }


def _local_state(
    compiled_geometry,
    topology,
):
    region_map = (
        derive_electrical_region_map(
            compiled_geometry,
            topology,
            module_instance_id=(
                "phase65-module-instance"
            ),
        )
    )

    visibility = (
        evaluate_electrical_region_visibility(
            compiled_geometry,
            region_map,
            sun_vector_xyz=[
                0.0,
                0.0,
                1.0,
            ],
            self_shading_enabled=False,
            sky_resolution=(
                SkyDomeResolution(
                    4,
                    1,
                    4,
                    1,
                    10.0,
                )
            ),
            ground_resolution=(
                GroundDomeResolution(
                    4,
                    1,
                )
            ),
            timestamp=(
                "2026-10-01T12:00:00+07:00"
            ),
        )
    )

    local = (
        build_local_electrical_irradiance_state(
            region_map,
            visibility,
            unshaded_poa={
                "beam_w_m2": 1000.0,
                "sky_diffuse_w_m2": 0.0,
                "ground_reflected_w_m2": 0.0,
            },
            optical_modifier={
                "beam": 1.0,
                "sky_diffuse": 1.0,
                "ground_reflected": 1.0,
            },
            optical_model_manifest={
                "model_id": (
                    "phase65.integration.unity"
                ),
                "model_version": "0.1",
                "notes": (
                    "Phase-6.5 integration fixture."
                ),
            },
            module_temperature_c=25.0,
            interval_start=(
                "2026-10-01T11:00:00+07:00"
            ),
            evaluation_time=(
                "2026-10-01T12:00:00+07:00"
            ),
        )
    )

    return (
        region_map,
        visibility,
        local,
    )


def _reference_states(
    topology,
    region_map,
    local_state,
):
    """Analytical parameters chosen for transparent transition truth."""

    return (
        build_analytical_region_reference_states(
            topology,
            region_map,
            local_state,
            reference_irradiance_w_m2=1000.0,

            # One parallel branch at full irradiance:
            # Isc = 5 A.
            isc_ref_a=5.0,

            # Each real UAT region declares
            # 24 equivalent series elements.
            #
            # Region Voc:
            # 24 × 0.025 = 0.6 V.
            voc_ref_v_per_element=0.025,

            # Region reverse resistance:
            # 24 × 0.01 = 0.24 ohm.
            reverse_resistance_ohm_per_element=0.01,

            current_ceiling_a=10.0,
        )
    )


def _local_effective_by_source_region(
    region_map,
    local_state,
):
    map_source = {
        region["region_id"]:
        region[
            "source_topology_region_id"
        ]
        for region
        in region_map["regions"]
    }

    return {
        map_source[
            local_region["region_id"]
        ]:
        local_region[
            "effective_irradiance_w_m2"
        ]
        for local_region
        in local_state["regions"]
    }


def test_phase65_real_phase63_handoff_reaches_reference_kernel():
    topology = _topology()
    compiled = _base_compiled_geometry()

    region_map, visibility, local = (
        _local_state(
            compiled,
            topology,
        )
    )

    assert (
        region_map[
            "source_module_topology_revision_id"
        ]
        == topology["revision_id"]
    )

    assert (
        visibility[
            "source_electrical_region_map_hash"
        ]
        == region_map[
            "mapping_payload_sha256"
        ]
    )

    assert (
        local[
            "source_electrical_region_map_hash"
        ]
        == region_map[
            "mapping_payload_sha256"
        ]
    )

    effective = (
        _local_effective_by_source_region(
            region_map,
            local,
        )
    )

    assert set(effective) == {
        region["region_id"]
        for region
        in topology[
            "physical_regions"
        ]
    }

    assert all(
        value
        == pytest.approx(
            1000.0,
            abs=1e-9,
        )
        for value
        in effective.values()
    )

    states = _reference_states(
        topology,
        region_map,
        local,
    )

    assert set(states) == set(
        effective
    )

    # s1 has two identical, fully illuminated
    # parallel branches.
    #
    # At I_total = 10 A, each branch carries
    # 5 A = Isc and therefore sits at 0 V.
    # 0 V > -0.55 V clamp, so bypass remains off.
    result = (
        evaluate_protected_substring_at_current(
            topology,
            "s1",
            states,
            current_a=10.0,
        )
    )

    assert (
        result["bypass_clamp_voltage_v"]
        == pytest.approx(
            -0.55,
            abs=1e-12,
        )
    )

    assert (
        result["unbypassed_voltage_v"]
        == pytest.approx(
            0.0,
            abs=1e-8,
        )
    )

    assert (
        result["bypass_active"]
        is False
    )

    assert (
        result["bypass_current_a"]
        == 0.0
    )


def test_phase65_real_geometry_shading_moves_bypass_transition():
    topology = _topology()

    # First derive the target region from the
    # canonical mapper. We do NOT reproduce UV
    # coordinate logic in this test.
    base = _base_compiled_geometry()

    base_map = (
        derive_electrical_region_map(
            base,
            topology,
            module_instance_id=(
                "phase65-module-instance"
            ),
        )
    )

    target = _target_region(
        base_map,
        "s1-r1",
    )

    shaded = copy.deepcopy(
        base
    )

    shaded[
        "geometry_payload_sha256"
    ] = "2" * 64

    shaded["occluders"] = [
        _occluder_from_mapped_region(
            target
        )
    ]

    region_map, visibility, local = (
        _local_state(
            shaded,
            topology,
        )
    )

    effective = (
        _local_effective_by_source_region(
            region_map,
            local,
        )
    )

    # The obstacle was generated directly from
    # mapped s1-r1 geometry.
    assert (
        effective["s1-r1"]
        == pytest.approx(
            0.0,
            abs=1e-9,
        )
    )

    # Its sibling branch remains clear.
    assert (
        effective["s1-r0"]
        == pytest.approx(
            1000.0,
            abs=1e-9,
        )
    )

    states = _reference_states(
        topology,
        region_map,
        local,
    )

    # Fixture analytical truth:
    #
    # each region:
    # R_reverse = 24 × 0.01 = 0.24 ohm
    #
    # bypass clamp = -0.55 V
    #
    # clear branch at clamp:
    # I = 5 + 0.55/0.24
    #   = 7.2916666667 A
    #
    # fully shaded branch at clamp:
    # I = 0 + 0.55/0.24
    #   = 2.2916666667 A
    #
    # total PV current at clamp:
    #   = 9.5833333333 A
    expected_transition_current = (
        5.0
        + 2.0
        * (
            0.55
            / 0.24
        )
    )

    transition = (
        evaluate_protected_substring_at_current(
            topology,
            "s1",
            states,
            current_a=(
                expected_transition_current
            ),
        )
    )

    after = (
        evaluate_protected_substring_at_current(
            topology,
            "s1",
            states,
            current_a=10.0,
        )
    )

    assert (
        transition[
            "pv_current_at_bypass_clamp_a"
        ]
        == pytest.approx(
            expected_transition_current,
            abs=1e-8,
        )
    )

    assert (
        transition[
            "transition_margin_v"
        ]
        == pytest.approx(
            0.0,
            abs=1e-8,
        )
    )

    assert (
        transition[
            "bypass_active"
        ]
        is False
    )

    assert (
        after[
            "unbypassed_voltage_v"
        ]
        == pytest.approx(
            -0.6,
            abs=1e-8,
        )
    )

    assert (
        after[
            "terminal_voltage_v"
        ]
        == pytest.approx(
            -0.55,
            abs=1e-12,
        )
    )

    assert (
        after[
            "bypass_active"
        ]
        is True
    )

    assert (
        after[
            "bypass_current_a"
        ]
        == pytest.approx(
            10.0
            - expected_transition_current,
            abs=1e-8,
        )
    )

    terminal_currents = {
        item["branch_id"]:
        item["current_a"]
        for item
        in after[
            "terminal_branch_states"
        ]
    }

    assert (
        terminal_currents["s1-b0"]
        == pytest.approx(
            5.0
            + 0.55 / 0.24,
            abs=1e-8,
        )
    )

    assert (
        terminal_currents["s1-b1"]
        == pytest.approx(
            0.55 / 0.24,
            abs=1e-8,
        )
    )


def test_phase65_real_handoff_is_deterministic():
    topology = _topology()
    compiled = _base_compiled_geometry()

    first_map, first_visibility, first_local = (
        _local_state(
            compiled,
            topology,
        )
    )

    second_map, second_visibility, second_local = (
        _local_state(
            compiled,
            topology,
        )
    )

    assert first_map == second_map
    assert first_visibility == second_visibility
    assert first_local == second_local

    first_states = _reference_states(
        topology,
        first_map,
        first_local,
    )

    second_states = _reference_states(
        topology,
        second_map,
        second_local,
    )

    first = (
        evaluate_protected_substring_at_current(
            topology,
            "s1",
            first_states,
            current_a=10.0,
        )
    )

    second = (
        evaluate_protected_substring_at_current(
            topology,
            "s1",
            second_states,
            current_a=10.0,
        )
    )

    assert first == second
