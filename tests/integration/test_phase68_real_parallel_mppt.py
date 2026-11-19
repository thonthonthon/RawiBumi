from __future__ import annotations

import copy
import json
from pathlib import Path
import runpy

import pytest
from jsonschema import Draft202012Validator

from shading.electrical import (
    IDEAL_GLOBAL_MPPT_MODEL_ID,
    assemble_general_series_string_iv,
    assemble_parallel_mppt_iv,
    build_phase66_series_module_operating_model,
    select_mppt_operating_point,
)


ROOT = Path(
    __file__
).resolve().parents[2]


# Reuse the validated Phase-6.7 real-geometry
# fixture utilities. Production code remains
# independent of test code.
_PHASE67 = runpy.run_path(
    str(
        ROOT
        / "tests"
        / "integration"
        / "test_phase67_real_two_module_string.py"
    )
)


for _required in (
    "_topology",
    "_parameterization",
    "_evidence",
    "_receiver",
    "_mapped_region",
    "_occluder_over_region",
    "_module_handoff",
    "_effective_by_source_region",
):
    if _required not in _PHASE67:
        raise RuntimeError(
            "Required validated Phase-6.7 "
            f"fixture helper missing: {_required}"
        )


_topology = _PHASE67[
    "_topology"
]

_parameterization = _PHASE67[
    "_parameterization"
]

_evidence = _PHASE67[
    "_evidence"
]

_receiver = _PHASE67[
    "_receiver"
]

_mapped_region = _PHASE67[
    "_mapped_region"
]

_occluder_over_region = _PHASE67[
    "_occluder_over_region"
]

_module_handoff = _PHASE67[
    "_module_handoff"
]

_effective_by_source_region = _PHASE67[
    "_effective_by_source_region"
]


MODULE_A_WEAK = (
    "module-a-weak"
)

MODULE_A_CLEAR = (
    "module-a-clear"
)

MODULE_B_CLEAR_1 = (
    "module-b-clear-1"
)

MODULE_B_CLEAR_2 = (
    "module-b-clear-2"
)

STRING_A = (
    "string-a"
)

STRING_B = (
    "string-b"
)

MPPT_ID = (
    "mppt-phase68-real-1"
)


def _four_module_geometry():
    return {
        "source_scene_revision_id": (
            "phase68-four-module-scene-r1"
        ),
        "geometry_payload_sha256": (
            "9" * 64
        ),
        "receivers": [
            _receiver(
                MODULE_A_WEAK,
                center_x=-12.0,
            ),
            _receiver(
                MODULE_A_CLEAR,
                center_x=-7.0,
            ),
            _receiver(
                MODULE_B_CLEAR_1,
                center_x=7.0,
            ),
            _receiver(
                MODULE_B_CLEAR_2,
                center_x=12.0,
            ),
        ],
        "occluders": [],
    }


def _string_circuit(
    string_id,
    module_ids,
):
    return {
        "string_id": (
            string_id
        ),
        "project_revision_id": (
            "phase68-real-project-r1"
        ),
        "name": (
            "Phase 6.8 real "
            + string_id
        ),
        "module_instance_ids": list(
            module_ids
        ),
        "target_mppt_instance_id": (
            MPPT_ID
        ),
        "enabled": True,
        "polarity": "normal",
        "cable_definition_id": None,
        "notes": None,
        "topology_source": "manual",
    }


def _mppt_instance():
    return {
        "mppt_instance_id": (
            MPPT_ID
        ),
        "inverter_instance_id": (
            "inverter-phase68-real-1"
        ),
        "index": 0,
        # Deliberately non-sorted input order.
        # Parallel ordering has no physical meaning
        # and Phase 6.8A normalizes it.
        "connected_string_ids": [
            STRING_B,
            STRING_A,
        ],
        "enabled": True,
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
def real_parallel_mppt_results():

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
    # 1. Start with four real module receivers in one scene.
    # --------------------------------------------------------

    clear_geometry = (
        _four_module_geometry()
    )

    # --------------------------------------------------------
    # 2. Derive the actual electrical-region polygon of
    #    module-a-weak / s1-r1.
    # --------------------------------------------------------

    (
        weak_clear_map,
        _weak_clear_visibility,
        _weak_clear_local,
    ) = _module_handoff(
        clear_geometry,
        topology,
        MODULE_A_WEAK,
    )

    target_region = (
        _mapped_region(
            weak_clear_map,
            "s1-r1",
        )
    )

    # --------------------------------------------------------
    # 3. Add one real occluder exactly over that mapped region.
    # --------------------------------------------------------

    final_geometry = copy.deepcopy(
        clear_geometry
    )

    final_geometry[
        "source_scene_revision_id"
    ] = (
        "phase68-four-module-scene-r2"
    )

    final_geometry[
        "geometry_payload_sha256"
    ] = "a" * 64

    final_geometry[
        "occluders"
    ] = [
        _occluder_over_region(
            target_region
        )
    ]

    # --------------------------------------------------------
    # 4. Compute independent geometry -> irradiance handoffs
    #    for all four module instances from the same scene.
    # --------------------------------------------------------

    handoffs = {}

    for module_id in (
        MODULE_A_WEAK,
        MODULE_A_CLEAR,
        MODULE_B_CLEAR_1,
        MODULE_B_CLEAR_2,
    ):
        handoffs[
            module_id
        ] = _module_handoff(
            final_geometry,
            topology,
            module_id,
        )

    # --------------------------------------------------------
    # 5. Convert every module into validated Phase-6.6
    #    series-context V(I) physics.
    # --------------------------------------------------------

    module_models = {}

    for (
        module_id,
        (
            region_map,
            _visibility,
            local_state,
        ),
    ) in handoffs.items():

        module_models[
            module_id
        ] = (
            build_phase66_series_module_operating_model(
                topology,
                region_map,
                local_state,
                parameterization,
                evidence,
            )
        )

    # --------------------------------------------------------
    # 6. Build two real Phase-6.7 strings.
    #
    # String A = one shaded + one clear module.
    # String B = two clear modules.
    # --------------------------------------------------------

    string_a = (
        assemble_general_series_string_iv(
            _string_circuit(
                STRING_A,
                [
                    MODULE_A_WEAK,
                    MODULE_A_CLEAR,
                ],
            ),
            {
                MODULE_A_WEAK: (
                    module_models[
                        MODULE_A_WEAK
                    ]
                ),
                MODULE_A_CLEAR: (
                    module_models[
                        MODULE_A_CLEAR
                    ]
                ),
            },
            sample_count=101,
        )
    )

    string_b = (
        assemble_general_series_string_iv(
            _string_circuit(
                STRING_B,
                [
                    MODULE_B_CLEAR_1,
                    MODULE_B_CLEAR_2,
                ],
            ),
            {
                MODULE_B_CLEAR_1: (
                    module_models[
                        MODULE_B_CLEAR_1
                    ]
                ),
                MODULE_B_CLEAR_2: (
                    module_models[
                        MODULE_B_CLEAR_2
                    ]
                ),
            },
            sample_count=101,
        )
    )

    # --------------------------------------------------------
    # 7. Physical Phase-6.8A common-voltage combination.
    # --------------------------------------------------------

    combined = (
        assemble_parallel_mppt_iv(
            _mppt_instance(),
            {
                STRING_A: (
                    string_a.curve
                ),
                STRING_B: (
                    string_b.curve
                ),
            },
            source_electrical_revision_id=(
                "phase68-real-electrical-r1"
            ),
        )
    )

    # --------------------------------------------------------
    # 8. Explicit Phase-6.8B tracker selection.
    #
    # Constraints are deliberately non-binding in this
    # integration fixture. Constraint violation behavior is
    # already covered by the 6.8B analytical unit tests.
    # --------------------------------------------------------

    combined_voc = float(
        combined.curve[
            "voc_v"
        ]
    )

    combined_isc = float(
        combined.curve[
            "isc_a"
        ]
    )

    tracker = (
        select_mppt_operating_point(
            combined.curve,
            source_electrical_revision_id=(
                "phase68-real-electrical-r1"
            ),
            mppt_operating_point_model_id=(
                IDEAL_GLOBAL_MPPT_MODEL_ID
            ),
            mppt_template={
                "min_operating_voltage_v": 0.0,
                "max_operating_voltage_v": (
                    1.10
                    * combined_voc
                ),
                "max_operating_current_a": (
                    1.10
                    * combined_isc
                ),
            },
        )
    )

    repeat_combined = (
        assemble_parallel_mppt_iv(
            _mppt_instance(),
            {
                STRING_A: (
                    string_a.curve
                ),
                STRING_B: (
                    string_b.curve
                ),
            },
            source_electrical_revision_id=(
                "phase68-real-electrical-r1"
            ),
        )
    )

    repeat_tracker = (
        select_mppt_operating_point(
            repeat_combined.curve,
            source_electrical_revision_id=(
                "phase68-real-electrical-r1"
            ),
            mppt_operating_point_model_id=(
                IDEAL_GLOBAL_MPPT_MODEL_ID
            ),
            mppt_template={
                "min_operating_voltage_v": 0.0,
                "max_operating_voltage_v": (
                    1.10
                    * combined_voc
                ),
                "max_operating_current_a": (
                    1.10
                    * combined_isc
                ),
            },
        )
    )

    return {
        "handoffs": handoffs,
        "string_a": string_a,
        "string_b": string_b,
        "combined": combined,
        "tracker": tracker,
        "repeat_combined": (
            repeat_combined
        ),
        "repeat_tracker": (
            repeat_tracker
        ),
    }


def test_phase68c_real_geometry_isolates_one_shaded_region(
    real_parallel_mppt_results,
):
    data = (
        real_parallel_mppt_results
    )

    handoffs = data[
        "handoffs"
    ]

    # Target module.
    weak_map = handoffs[
        MODULE_A_WEAK
    ][0]

    weak_local = handoffs[
        MODULE_A_WEAK
    ][2]

    weak = (
        _effective_by_source_region(
            weak_map,
            weak_local,
        )
    )

    assert weak[
        "s1-r1"
    ] == pytest.approx(
        0.0,
        abs=1e-9,
    )

    for region_id, value in weak.items():
        if region_id == "s1-r1":
            continue

        assert value == pytest.approx(
            1000.0,
            abs=1e-9,
        )

    # All three other physical modules remain clear.
    for module_id in (
        MODULE_A_CLEAR,
        MODULE_B_CLEAR_1,
        MODULE_B_CLEAR_2,
    ):
        region_map = handoffs[
            module_id
        ][0]

        local_state = handoffs[
            module_id
        ][2]

        effective = (
            _effective_by_source_region(
                region_map,
                local_state,
            )
        )

        assert all(
            value
            == pytest.approx(
                1000.0,
                abs=1e-9,
            )
            for value
            in effective.values()
        )


def test_phase68c_real_strings_are_electrically_mismatched(
    real_parallel_mppt_results,
):
    string_a = (
        real_parallel_mppt_results[
            "string_a"
        ].curve
    )

    string_b = (
        real_parallel_mppt_results[
            "string_b"
        ].curve
    )

    assert (
        string_a[
            "physical_result_sha256"
        ]
        != string_b[
            "physical_result_sha256"
        ]
    )

    # The shaded-string and clear-string MPPs should
    # not collapse to the same operating state.
    assert (
        abs(
            string_a[
                "global_mpp"
            ][
                "voltage_v"
            ]
            - string_b[
                "global_mpp"
            ][
                "voltage_v"
            ]
        )
        > 1e-6
        or abs(
            string_a[
                "global_mpp"
            ][
                "current_a"
            ]
            - string_b[
                "global_mpp"
            ][
                "current_a"
            ]
        )
        > 1e-6
    )


def test_phase68c_parallel_mppt_uses_common_voltage_and_sums_string_current(
    real_parallel_mppt_results,
):
    combined = (
        real_parallel_mppt_results[
            "combined"
        ]
    )

    curve = combined.curve
    state = combined.state

    assert (
        curve[
            "curve_scope"
        ]
        == "mppt_combined"
    )

    assert (
        curve[
            "source_mppt_instance_id"
        ]
        == MPPT_ID
    )

    # Parallel ordering is normalized.
    assert (
        state[
            "source_string_ids"
        ]
        == sorted(
            [
                STRING_A,
                STRING_B,
            ]
        )
    )

    selected_voltage = float(
        curve[
            "global_mpp"
        ][
            "voltage_v"
        ]
    )

    represented = min(
        state[
            "voltage_samples"
        ],
        key=lambda item: abs(
            float(
                item[
                    "voltage_v"
                ]
            )
            - selected_voltage
        ),
    )

    assert float(
        represented[
            "voltage_v"
        ]
    ) == pytest.approx(
        selected_voltage,
        abs=1e-9,
    )

    contribution_sum = sum(
        float(
            item[
                "current_a"
            ]
        )
        for item
        in represented[
            "string_currents"
        ]
    )

    assert contribution_sum == pytest.approx(
        float(
            represented[
                "total_current_a"
            ]
        ),
        rel=1e-10,
        abs=1e-10,
    )

    assert float(
        represented[
            "total_power_w"
        ]
    ) == pytest.approx(
        selected_voltage
        * contribution_sum,
        rel=1e-10,
        abs=1e-8,
    )


def test_phase68c_shared_mppt_power_is_not_sum_of_independent_string_mpps(
    real_parallel_mppt_results,
):
    string_a = (
        real_parallel_mppt_results[
            "string_a"
        ].curve
    )

    string_b = (
        real_parallel_mppt_results[
            "string_b"
        ].curve
    )

    combined = (
        real_parallel_mppt_results[
            "combined"
        ].curve
    )

    independent_sum = (
        float(
            string_a[
                "global_mpp"
            ][
                "power_w"
            ]
        )
        + float(
            string_b[
                "global_mpp"
            ][
                "power_w"
            ]
        )
    )

    shared_power = float(
        combined[
            "global_mpp"
        ][
            "power_w"
        ]
    )

    # A shared tracker cannot exceed the sum of
    # independently optimized strings under the
    # same represented source curves.
    comparison_tolerance_w = max(
        1e-7,
        1e-9 * max(
            abs(independent_sum),
            1.0,
        ),
    )

    assert (
        shared_power
        <= independent_sum
        + comparison_tolerance_w
    )

    # The fixture intentionally creates mismatched
    # string operating states, so common-voltage
    # operation must carry a real mismatch penalty.
    assert (
        shared_power
        < independent_sum
        - 1e-5
    )


def test_phase68c_explicit_tracker_selects_physical_global_mpp(
    real_parallel_mppt_results,
):
    combined = (
        real_parallel_mppt_results[
            "combined"
        ].curve
    )

    tracker = (
        real_parallel_mppt_results[
            "tracker"
        ].state
    )

    assert (
        tracker[
            "mppt_operating_point_model_id"
        ]
        == IDEAL_GLOBAL_MPPT_MODEL_ID
    )

    assert (
        tracker[
            "selected_operating_point"
        ]
        == combined[
            "global_mpp"
        ]
    )

    assert (
        tracker[
            "ideal_global_mpp"
        ]
        == combined[
            "global_mpp"
        ]
    )

    assert (
        tracker[
            "attribution"
        ][
            "delta_power_w"
        ]
        == pytest.approx(
            0.0,
            abs=1e-12,
        )
    )

    evaluation = tracker[
        "constraint_evaluation"
    ]

    assert (
        evaluation[
            "voltage_within_window"
        ]
        is True
    )

    assert (
        evaluation[
            "operating_current_above_limit"
        ]
        is False
    )

    assert (
        evaluation[
            "selected_point_violates_known_constraints"
        ]
        is False
    )

    assert (
        evaluation[
            "power_limit_evaluated"
        ]
        is False
    )


def test_phase68c_real_parallel_and_tracker_states_are_deterministic_and_valid(
    real_parallel_mppt_results,
):
    data = (
        real_parallel_mppt_results
    )

    assert (
        data[
            "combined"
        ].curve
        == data[
            "repeat_combined"
        ].curve
    )

    assert (
        data[
            "combined"
        ].state
        == data[
            "repeat_combined"
        ].state
    )

    assert (
        data[
            "tracker"
        ].state
        == data[
            "repeat_tracker"
        ].state
    )

    _validate_schema(
        "electrical-iv-curve.schema.json",
        data[
            "combined"
        ].curve,
    )

    _validate_schema(
        "mppt-parallel-iv-state.schema.json",
        data[
            "combined"
        ].state,
    )

    _validate_schema(
        "mppt-tracker-operating-state.schema.json",
        data[
            "tracker"
        ].state,
    )
