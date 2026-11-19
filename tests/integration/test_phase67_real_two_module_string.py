from __future__ import annotations

import copy
import json
from pathlib import Path
import runpy

import pytest
from jsonschema import Draft202012Validator

from geometry.shading import (
    GroundDomeResolution,
    SkyDomeResolution,
)

from shading.electrical import (
    assemble_general_series_string_iv,
    assemble_nonuniform_module_iv,
    build_local_electrical_irradiance_state,
    build_phase66_series_module_operating_model,
    derive_electrical_region_map,
    evaluate_electrical_region_visibility,
)


ROOT = Path(
    __file__
).resolve().parents[2]


# Reuse only controlled Phase-6.6 validation
# parameterization/evidence helpers.
_PHASE66 = runpy.run_path(
    str(
        ROOT
        / "tests"
        / "integration"
        / "test_phase66_module_iv_handoff.py"
    )
)

_topology = _PHASE66[
    "_topology"
]

_parameterization = _PHASE66[
    "_parameterization"
]

_evidence = _PHASE66[
    "_evidence"
]


def _receiver(
    module_id: str,
    *,
    center_x: float,
):
    half_x = 1.5
    half_y = 1.0

    left = (
        center_x
        - half_x
    )

    right = (
        center_x
        + half_x
    )

    return {
        "receiver_id": (
            "receiver:"
            + module_id
        ),
        "source_entity_type": (
            "module_instance"
        ),
        "source_entity_id": (
            module_id
        ),
        "receiver_type": (
            "module_plane"
        ),
        "vertices_3d": [
            [
                right,
                half_y,
                0.0,
            ],
            [
                left,
                half_y,
                0.0,
            ],
            [
                left,
                -half_y,
                0.0,
            ],
            [
                right,
                -half_y,
                0.0,
            ],
        ],
        "center_xyz": [
            center_x,
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
            "phase67-field"
        ),
        "support_surface_id": (
            "phase67-surface"
        ),
        "module_instance_id": (
            module_id
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


def _base_geometry():
    # The modules are physically separated.
    #
    # Strong module:
    # x = -5.5 .. -2.5
    #
    # Weak module:
    # x = +2.5 .. +5.5
    #
    # This makes it straightforward to prove that
    # the weak-module occluder does not affect the
    # strong module.
    return {
        "source_scene_revision_id": (
            "phase67-two-module-scene-r1"
        ),
        "geometry_payload_sha256": (
            "7" * 64
        ),
        "receivers": [
            _receiver(
                "module-strong",
                center_x=-4.0,
            ),
            _receiver(
                "module-weak",
                center_x=4.0,
            ),
        ],
        "occluders": [],
    }


def _mapped_region(
    region_map,
    source_region_id,
):
    matches = [
        region
        for region
        in region_map[
            "regions"
        ]
        if region[
            "source_topology_region_id"
        ]
        == source_region_id
    ]

    assert len(matches) == 1

    return matches[0]


def _occluder_over_region(
    mapped_region,
):
    lifted = [
        [
            float(
                vertex[0]
            ),
            float(
                vertex[1]
            ),
            float(
                vertex[2]
            ) + 1.0,
        ]
        for vertex
        in mapped_region[
            "vertices_3d"
        ]
    ]

    xs = [
        item[0]
        for item
        in lifted
    ]

    ys = [
        item[1]
        for item
        in lifted
    ]

    zs = [
        item[2]
        for item
        in lifted
    ]

    return {
        "occluder_id": (
            "phase67-weak-target-occluder"
        ),
        "source_entity_type": (
            "obstacle"
        ),
        "source_entity_id": (
            "phase67-weak-target-obstacle"
        ),
        "geometry_type": (
            "polygon_faces"
        ),
        "faces": [
            {
                "face_id": (
                    "phase67-weak-target-top"
                ),
                "vertices_3d": (
                    lifted
                ),
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
            "phase67_fixture": True,
            "target_module": (
                "module-weak"
            ),
            "target_region": (
                mapped_region[
                    "source_topology_region_id"
                ]
            ),
        },
    }


def _module_handoff(
    compiled_geometry,
    topology,
    module_id,
):
    region_map = (
        derive_electrical_region_map(
            compiled_geometry,
            topology,
            module_instance_id=(
                module_id
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
                    "phase67.integration.unity"
                ),
                "model_version": "0.1",
                "notes": (
                    "Phase-6.7 real two-module "
                    "geometry integration fixture."
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


def _effective_by_source_region(
    region_map,
    local_state,
):
    source_by_local = {
        region[
            "region_id"
        ]:
        region[
            "source_topology_region_id"
        ]
        for region
        in region_map[
            "regions"
        ]
    }

    return {
        source_by_local[
            region[
                "region_id"
            ]
        ]:
        float(
            region[
                "effective_irradiance_w_m2"
            ]
        )
        for region
        in local_state[
            "regions"
        ]
    }


def _string_circuit():
    # This exact order is the canonical
    # engineer-defined electrical series order.
    return {
        "string_id": (
            "S67-REAL-001"
        ),
        "project_revision_id": (
            "phase67-real-project-r1"
        ),
        "name": (
            "Phase 6.7 real two-module string"
        ),
        "module_instance_ids": [
            "module-weak",
            "module-strong",
        ],
        "target_mppt_instance_id": (
            "phase67-real-mppt-1"
        ),
        "enabled": True,
        "polarity": "normal",
        "cable_definition_id": None,
        "notes": None,
        "topology_source": (
            "manual"
        ),
    }


def _validate_schema(
    filename,
    value,
):
    schema = json.loads(
        (
            ROOT
            / "shading"
            / "electrical"
            / filename
        ).read_text(
            encoding="utf-8"
        )
    )

    Draft202012Validator(
        schema
    ).validate(
        value
    )


@pytest.fixture(scope="module")
def real_two_module_results():
    topology = (
        _topology()
    )

    parameterization = (
        _parameterization(
            topology
        )
    )

    evidence = (
        _evidence(
            parameterization
        )
    )

    # --------------------------------------------------------
    # First derive the weak module mapping from the real
    # two-module geometry, before introducing any occluder.
    # --------------------------------------------------------

    clear_geometry = (
        _base_geometry()
    )

    (
        weak_clear_map,
        _weak_clear_visibility,
        weak_clear_local,
    ) = _module_handoff(
        clear_geometry,
        topology,
        "module-weak",
    )

    target = (
        _mapped_region(
            weak_clear_map,
            "s1-r1",
        )
    )

    # --------------------------------------------------------
    # Build final scene using the exact mapped weak-region
    # polygon as the shading target.
    # --------------------------------------------------------

    shaded_geometry = copy.deepcopy(
        clear_geometry
    )

    shaded_geometry[
        "geometry_payload_sha256"
    ] = "8" * 64

    shaded_geometry[
        "occluders"
    ] = [
        _occluder_over_region(
            target
        )
    ]

    # --------------------------------------------------------
    # Recompute both module handoffs from the SAME final
    # physical scene.
    # --------------------------------------------------------

    (
        strong_map,
        strong_visibility,
        strong_local,
    ) = _module_handoff(
        shaded_geometry,
        topology,
        "module-strong",
    )

    (
        weak_map,
        weak_visibility,
        weak_local,
    ) = _module_handoff(
        shaded_geometry,
        topology,
        "module-weak",
    )

    # --------------------------------------------------------
    # Also retain all-clear module physics for counterfactual
    # string comparison.
    # --------------------------------------------------------

    (
        strong_clear_map,
        _strong_clear_visibility,
        strong_clear_local,
    ) = _module_handoff(
        clear_geometry,
        topology,
        "module-strong",
    )

    strong_model = (
        build_phase66_series_module_operating_model(
            topology,
            strong_map,
            strong_local,
            parameterization,
            evidence,
        )
    )

    weak_model = (
        build_phase66_series_module_operating_model(
            topology,
            weak_map,
            weak_local,
            parameterization,
            evidence,
        )
    )

    strong_clear_model = (
        build_phase66_series_module_operating_model(
            topology,
            strong_clear_map,
            strong_clear_local,
            parameterization,
            evidence,
        )
    )

    weak_clear_model = (
        build_phase66_series_module_operating_model(
            topology,
            weak_clear_map,
            weak_clear_local,
            parameterization,
            evidence,
        )
    )

    # Standalone weak-module positive-generation boundary.
    weak_standalone = (
        assemble_nonuniform_module_iv(
            topology,
            weak_map,
            weak_local,
            parameterization,
            evidence,
            sample_count=51,
        )
    )

    circuit = (
        _string_circuit()
    )

    shaded_string = (
        assemble_general_series_string_iv(
            circuit,
            {
                "module-weak": (
                    weak_model
                ),
                "module-strong": (
                    strong_model
                ),
            },
            sample_count=101,
        )
    )

    clear_string = (
        assemble_general_series_string_iv(
            circuit,
            {
                "module-weak": (
                    weak_clear_model
                ),
                "module-strong": (
                    strong_clear_model
                ),
            },
            sample_count=101,
        )
    )

    repeat = (
        assemble_general_series_string_iv(
            circuit,
            {
                "module-weak": (
                    weak_model
                ),
                "module-strong": (
                    strong_model
                ),
            },
            sample_count=101,
        )
    )

    return {
        "topology": topology,
        "strong_map": strong_map,
        "strong_visibility": (
            strong_visibility
        ),
        "strong_local": strong_local,
        "weak_map": weak_map,
        "weak_visibility": (
            weak_visibility
        ),
        "weak_local": weak_local,
        "strong_model": strong_model,
        "weak_model": weak_model,
        "weak_standalone": (
            weak_standalone
        ),
        "shaded_string": (
            shaded_string
        ),
        "clear_string": (
            clear_string
        ),
        "repeat": repeat,
    }


def test_phase67c_real_scene_isolates_shading_to_weak_module(
    real_two_module_results,
):
    data = real_two_module_results

    strong = (
        _effective_by_source_region(
            data[
                "strong_map"
            ],
            data[
                "strong_local"
            ],
        )
    )

    weak = (
        _effective_by_source_region(
            data[
                "weak_map"
            ],
            data[
                "weak_local"
            ],
        )
    )

    assert all(
        value
        == pytest.approx(
            1000.0,
            abs=1e-9,
        )
        for value
        in strong.values()
    )

    assert weak[
        "s1-r1"
    ] == pytest.approx(
        0.0,
        abs=1e-9,
    )

    assert weak[
        "s1-r0"
    ] == pytest.approx(
        1000.0,
        abs=1e-9,
    )

    # All unrelated weak-module regions stay clear.
    for region_id, value in weak.items():
        if region_id == "s1-r1":
            continue

        assert value == pytest.approx(
            1000.0,
            abs=1e-9,
        )


def test_phase67c_real_string_operates_weak_module_beyond_standalone_isc(
    real_two_module_results,
):
    data = real_two_module_results

    weak_isc = float(
        data[
            "weak_standalone"
        ].curve[
            "isc_a"
        ]
    )

    string_isc = float(
        data[
            "shaded_string"
        ].curve[
            "isc_a"
        ]
    )

    assert (
        string_isc
        > weak_isc
        + 1e-7
    )

    probe_current = (
        0.5
        * (
            weak_isc
            + string_isc
        )
    )

    weak = (
        data[
            "weak_model"
        ].voltage_at_current(
            probe_current
        )
    )

    strong = (
        data[
            "strong_model"
        ].voltage_at_current(
            probe_current
        )
    )

    weak_voltage = float(
        weak[
            "terminal_voltage_v"
        ]
    )

    strong_voltage = float(
        strong[
            "terminal_voltage_v"
        ]
    )

    assert weak_voltage < 0.0

    assert strong_voltage > 0.0

    assert (
        weak_voltage
        + strong_voltage
        > 0.0
    )

    assert any(
        substring[
            "bypass_active"
        ]
        for substring
        in weak[
            "protected_substrings"
        ]
    )


def test_phase67c_real_shading_changes_string_physical_curve(
    real_two_module_results,
):
    shaded = real_two_module_results[
        "shaded_string"
    ].curve

    clear = real_two_module_results[
        "clear_string"
    ].curve

    assert (
        shaded[
            "physical_result_sha256"
        ]
        != clear[
            "physical_result_sha256"
        ]
    )

    assert (
        shaded[
            "scientific_input_sha256"
        ]
        != clear[
            "scientific_input_sha256"
        ]
    )

    assert (
        shaded[
            "global_mpp"
        ][
            "power_w"
        ]
        < clear[
            "global_mpp"
        ][
            "power_w"
        ]
    )


def test_phase67c_real_string_preserves_canonical_order_and_identity(
    real_two_module_results,
):
    result = real_two_module_results[
        "shaded_string"
    ]

    repeat = real_two_module_results[
        "repeat"
    ]

    expected_order = [
        "module-weak",
        "module-strong",
    ]

    assert result.state[
        "source_module_instance_ids"
    ] == expected_order

    assert [
        item[
            "module_instance_id"
        ]
        for item
        in result.state[
            "module_sources"
        ]
    ] == expected_order

    for sample in result.state[
        "current_samples"
    ]:
        assert [
            item[
                "module_instance_id"
            ]
            for item
            in sample[
                "modules"
            ]
        ] == expected_order

        assert [
            item[
                "series_order"
            ]
            for item
            in sample[
                "modules"
            ]
        ] == [
            0,
            1,
        ]

    assert (
        result.curve
        == repeat.curve
    )

    assert (
        result.state
        == repeat.state
    )

    _validate_schema(
        "electrical-iv-curve.schema.json",
        result.curve,
    )

    _validate_schema(
        "string-series-iv-state.schema.json",
        result.state,
    )
