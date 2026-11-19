from __future__ import annotations

import copy

import pytest

from shading.electrical.substring_reference import (
    PHASE65_ANALYTICAL_REGION_MODEL_ID,
    SubstringReferenceError,
    build_analytical_region_reference_states,
    evaluate_protected_substring_at_current,
    evaluate_series_branch_voltage,
    solve_parallel_branches_at_current,
)


def _topology(
    branches,
    *,
    model_type="constant_forward_drop",
    forward_drop_v=0.5,
):
    region_ids = [
        region_id
        for branch in branches
        for region_id in branch
    ]

    physical_regions = [
        {
            "region_id": region_id,
            "region_type": "grouped_cells",
            "polygon_normalized": [
                [0, 0],
                [1, 0],
                [1, 1],
            ],
            "electrical_substring_id": "s0",
            "equivalent_element_count": 1,
        }
        for region_id in region_ids
    ]

    if model_type == "constant_forward_drop":
        parameters = {
            "forward_voltage_v": forward_drop_v
        }
    elif model_type == "ideal":
        parameters = {}
    else:
        parameters = {
            "fixture_parameter": 1.0
        }

    return {
        "schema_name": "ModuleTopologyDefinition",
        "schema_version": "0.1",
        "contract_version": "0.1",
        "module_topology_id": "phase65-topology",
        "revision_id": "phase65-topology-r1",
        "module_definition_revision_id": (
            "phase65-module-r1"
        ),
        "topology_version": "0.1",
        "orientation_reference": (
            "viewed_from_module_front"
        ),
        "coordinate_convention": (
            "module_front_uv_normalized_width_height"
        ),
        "topology_class": (
            "series_substrings_parallel_branches"
        ),
        "region_resolution": "grouped_cells",
        "physical_regions": physical_regions,
        "electrical_substrings": [
            {
                "substring_id": "s0",
                "series_order": 0,
                "physical_region_ids": region_ids,
                "parallel_branches": [
                    {
                        "branch_id": (
                            f"s0-b{index}"
                        ),
                        "series_region_ids": list(
                            branch
                        ),
                    }
                    for index, branch
                    in enumerate(branches)
                ],
                "bypass_device_id": "d0",
            }
        ],
        "bypass_devices": [
            {
                "bypass_device_id": "d0",
                "device_type": "bypass_diode",
                "protects_substring_ids": [
                    "s0"
                ],
                "forward_voltage_model": {
                    "model_type": model_type,
                    "model_id": (
                        f"phase65."
                        f"{model_type}."
                        "fixture"
                    ),
                    "model_version": "0.1",
                    "model_authority": (
                        "explicit_simulation_assumption"
                    ),
                    "verification_state": (
                        "not_applicable"
                    ),
                    "model_provenance": (
                        "simulation_assumption"
                    ),
                    "validation_record_id": None,
                    "assumption_id": (
                        "phase65-bypass-fixture"
                    ),
                    "assumption_rationale": (
                        "Synthetic Phase-6.5 "
                        "analytical transition fixture."
                    ),
                    "parameters": parameters,
                    "source_ids": [],
                    "model_payload_sha256": (
                        "a" * 64
                    ),
                },
            }
        ],
        "bypass_coverage_complete": True,
        "verification_state": "reviewed",
        "topology_provenance": (
            "manual_verified"
        ),
        "source_ids": [
            "phase65-synthetic-fixture"
        ],
        "notes": (
            "Phase-6.5 analytical test topology."
        ),
        "metadata": {
            "synthetic_reference": True
        },
    }


def _handoff(region_irradiance):
    region_map = {
        "electrical_region_map_id": (
            "phase65-map"
        ),
        "mapping_payload_sha256": (
            "b" * 64
        ),
        "source_module_topology_revision_id": (
            "phase65-topology-r1"
        ),
        "regions": [
            {
                "region_id": (
                    f"mapped-{region_id}"
                ),
                "source_topology_region_id": (
                    region_id
                ),
                "source_electrical_substring_id": (
                    "s0"
                ),
            }
            for region_id
            in region_irradiance
        ],
    }

    local_state = {
        "source_electrical_region_map_id": (
            "phase65-map"
        ),
        "source_electrical_region_map_hash": (
            "b" * 64
        ),
        "regions": [
            {
                "region_id": (
                    f"mapped-{region_id}"
                ),
                "effective_irradiance_w_m2": (
                    irradiance
                ),
            }
            for region_id, irradiance
            in region_irradiance.items()
        ],
    }

    return region_map, local_state


def _states(
    topology,
    region_irradiance,
    *,
    reverse_resistance_ohm_per_element=0.2,
    current_ceiling_a=10.0,
):
    region_map, local_state = (
        _handoff(
            region_irradiance
        )
    )

    return (
        build_analytical_region_reference_states(
            topology,
            region_map,
            local_state,
            reference_irradiance_w_m2=1000.0,
            isc_ref_a=5.0,
            voc_ref_v_per_element=0.6,
            reverse_resistance_ohm_per_element=(
                reverse_resistance_ohm_per_element
            ),
            current_ceiling_a=(
                current_ceiling_a
            ),
        )
    )


def test_phase65_local_irradiance_binds_to_topology_regions():
    topology = _topology([
        ["r0", "r1"]
    ])

    states = _states(
        topology,
        {
            "r0": 1000.0,
            "r1": 500.0,
        },
    )

    assert (
        states["r0"].model_id
        == PHASE65_ANALYTICAL_REGION_MODEL_ID
    )

    assert states["r0"].isc_a == pytest.approx(
        5.0
    )

    assert states["r1"].isc_a == pytest.approx(
        2.5
    )

    assert (
        states["r0"].source_substring_id
        == "s0"
    )


def test_phase65_series_branch_voltage_is_explicit_sum():
    topology = _topology([
        ["r0", "r1"]
    ])

    states = _states(
        topology,
        {
            "r0": 1000.0,
            "r1": 1000.0,
        },
    )

    branch = (
        topology[
            "electrical_substrings"
        ][0][
            "parallel_branches"
        ][0]
    )

    # Each region at half Isc:
    # V = 0.6 * (1 - 2.5/5) = 0.3 V.
    # Two series regions -> 0.6 V.
    voltage = (
        evaluate_series_branch_voltage(
            branch,
            states,
            current_a=2.5,
        )
    )

    assert voltage == pytest.approx(
        0.6
    )


def test_phase65_parallel_branches_share_common_voltage():
    topology = _topology([
        ["r0"],
        ["r1"],
    ])

    states = _states(
        topology,
        {
            "r0": 1000.0,
            "r1": 1000.0,
        },
    )

    branches = (
        topology[
            "electrical_substrings"
        ][0][
            "parallel_branches"
        ]
    )

    solved = (
        solve_parallel_branches_at_current(
            branches,
            states,
            total_current_a=5.0,
        )
    )

    assert (
        solved[
            "common_voltage_v"
        ]
        == pytest.approx(
            0.3,
            abs=1e-8,
        )
    )

    assert [
        item["current_a"]
        for item
        in solved["branch_states"]
    ] == pytest.approx(
        [2.5, 2.5],
        abs=1e-8,
    )


def test_phase65_constant_drop_transition_matches_truth():
    topology = _topology(
        [["r0"]],
        model_type=(
            "constant_forward_drop"
        ),
        forward_drop_v=0.5,
    )

    states = _states(
        topology,
        {"r0": 1000.0},
    )

    # Isc = 5 A
    # reverse R = 0.2 ohm
    # clamp = -0.5 V
    #
    # exact transition:
    #
    # I = 5 + 0.5 / 0.2
    #   = 7.5 A

    before = (
        evaluate_protected_substring_at_current(
            topology,
            "s0",
            states,
            current_a=7.0,
        )
    )

    transition = (
        evaluate_protected_substring_at_current(
            topology,
            "s0",
            states,
            current_a=7.5,
        )
    )

    after = (
        evaluate_protected_substring_at_current(
            topology,
            "s0",
            states,
            current_a=8.0,
        )
    )

    assert (
        before[
            "unbypassed_voltage_v"
        ]
        == pytest.approx(
            -0.4,
            abs=1e-8,
        )
    )

    assert (
        before[
            "bypass_active"
        ]
        is False
    )

    assert (
        transition[
            "transition_margin_v"
        ]
        == pytest.approx(
            0.0,
            abs=1e-10,
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
            "bypass_active"
        ]
        is True
    )

    assert (
        after[
            "pv_current_at_bypass_clamp_a"
        ]
        == pytest.approx(
            7.5,
            abs=1e-8,
        )
    )

    assert (
        after[
            "bypass_current_a"
        ]
        == pytest.approx(
            0.5,
            abs=1e-8,
        )
    )

    assert (
        after[
            "terminal_voltage_v"
        ]
        == pytest.approx(
            -0.5,
            abs=1e-10,
        )
    )


def test_phase65_parallel_transition_sums_branch_currents():
    topology = _topology(
        [
            ["r0"],
            ["r1"],
        ],
        model_type=(
            "constant_forward_drop"
        ),
        forward_drop_v=0.5,
    )

    states = _states(
        topology,
        {
            "r0": 1000.0,
            "r1": 1000.0,
        },
    )

    # Each branch reaches -0.5 V at:
    #
    # 5 + 0.5/0.2 = 7.5 A
    #
    # Two branches therefore transition at 15 A.

    transition = (
        evaluate_protected_substring_at_current(
            topology,
            "s0",
            states,
            current_a=15.0,
        )
    )

    after = (
        evaluate_protected_substring_at_current(
            topology,
            "s0",
            states,
            current_a=16.0,
        )
    )

    assert (
        transition[
            "bypass_active"
        ]
        is False
    )

    assert (
        transition[
            "pv_current_at_bypass_clamp_a"
        ]
        == pytest.approx(
            15.0,
            abs=1e-8,
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
            1.0,
            abs=1e-8,
        )
    )

    assert [
        item["current_a"]
        for item
        in after[
            "terminal_branch_states"
        ]
    ] == pytest.approx(
        [7.5, 7.5],
        abs=1e-8,
    )


def test_phase65_local_shading_moves_bypass_transition():
    topology = _topology(
        [
            ["r0"],
            ["r1"],
        ],
        model_type=(
            "constant_forward_drop"
        ),
        forward_drop_v=0.5,
    )

    states = _states(
        topology,
        {
            "r0": 1000.0,
            "r1": 500.0,
        },
    )

    # Full branch clamp current:
    # 5.0 + 2.5 = 7.5 A
    #
    # Half-irradiance branch:
    # 2.5 + 2.5 = 5.0 A
    #
    # Total transition = 12.5 A.

    transition = (
        evaluate_protected_substring_at_current(
            topology,
            "s0",
            states,
            current_a=12.5,
        )
    )

    after = (
        evaluate_protected_substring_at_current(
            topology,
            "s0",
            states,
            current_a=13.0,
        )
    )

    assert (
        transition[
            "pv_current_at_bypass_clamp_a"
        ]
        == pytest.approx(
            12.5,
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
            "bypass_active"
        ]
        is True
    )

    assert (
        after[
            "bypass_current_a"
        ]
        == pytest.approx(
            0.5,
            abs=1e-8,
        )
    )


def test_phase65_ideal_bypass_clamps_at_zero():
    topology = _topology(
        [["r0"]],
        model_type="ideal",
    )

    states = _states(
        topology,
        {"r0": 1000.0},
    )

    state = (
        evaluate_protected_substring_at_current(
            topology,
            "s0",
            states,
            current_a=6.0,
        )
    )

    assert (
        state[
            "bypass_active"
        ]
        is True
    )

    assert (
        state[
            "terminal_voltage_v"
        ]
        == 0.0
    )

    assert (
        state[
            "pv_current_at_bypass_clamp_a"
        ]
        == pytest.approx(
            5.0,
            abs=1e-8,
        )
    )

    assert (
        state[
            "bypass_current_a"
        ]
        == pytest.approx(
            1.0,
            abs=1e-8,
        )
    )


def test_phase65_parameterized_bypass_fails_closed():
    topology = _topology(
        [["r0"]],
        model_type="parameterized_iv",
    )

    states = _states(
        topology,
        {"r0": 1000.0},
    )

    with pytest.raises(
        SubstringReferenceError,
        match=(
            "parameterized_iv bypass models"
            ".*not implemented"
        ),
    ):
        evaluate_protected_substring_at_current(
            topology,
            "s0",
            states,
            current_a=5.0,
        )


def test_phase65_identity_mixing_fails_closed():
    topology = _topology([
        ["r0"]
    ])

    region_map, local_state = (
        _handoff({
            "r0": 1000.0
        })
    )

    stale = copy.deepcopy(
        local_state
    )

    stale[
        "source_electrical_region_map_hash"
    ] = "c" * 64

    with pytest.raises(
        SubstringReferenceError,
        match="hash mismatch",
    ):
        build_analytical_region_reference_states(
            topology,
            region_map,
            stale,
            reference_irradiance_w_m2=1000.0,
            isc_ref_a=5.0,
            voc_ref_v_per_element=0.6,
            reverse_resistance_ohm_per_element=0.2,
            current_ceiling_a=10.0,
        )


def test_phase65_short_current_domain_fails_closed():
    topology = _topology(
        [["r0"]],
        model_type=(
            "constant_forward_drop"
        ),
        forward_drop_v=0.5,
    )

    states = _states(
        topology,
        {"r0": 1000.0},
        current_ceiling_a=6.0,
    )

    with pytest.raises(
        SubstringReferenceError,
        match=(
            "current ceiling is too low"
        ),
    ):
        evaluate_protected_substring_at_current(
            topology,
            "s0",
            states,
            current_a=6.0,
        )
