from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from shading.electrical import (
    IDEAL_GLOBAL_MPPT_MODEL_ID,
    MPPTTrackerOperatingError,
    select_mppt_operating_point,
)


ROOT = Path(
    __file__
).resolve().parents[2]


def _sha(
    text: str,
) -> str:
    return hashlib.sha256(
        text.encode(
            "utf-8"
        )
    ).hexdigest()


def _curve():
    points = [
        {
            "voltage_v": 0.0,
            "current_a": 20.0,
            "power_w": 0.0,
        },
        {
            "voltage_v": 50.0,
            "current_a": 10.0,
            "power_w": 500.0,
        },
        {
            "voltage_v": 100.0,
            "current_a": 0.0,
            "power_w": 0.0,
        },
    ]

    return {
        "schema_name": (
            "ElectricalIVCurve"
        ),
        "schema_version": "0.1",
        "contract_version": "0.1",
        "curve_id": (
            "iv:mppt-combined:test"
        ),
        "curve_scope": (
            "mppt_combined"
        ),
        "representation": (
            "sampled_voltage_grid"
        ),
        "sample_order": (
            "ascending_voltage"
        ),
        "sign_convention": (
            "pv_delivery_current_positive_"
            "power_equals_v_times_i"
        ),
        "source_module_instance_id": None,
        "source_string_id": None,
        "source_mppt_instance_id": (
            "mppt-1"
        ),
        "points": points,
        "isc_a": 20.0,
        "voc_v": 100.0,
        "mpp_semantics": {
            "declaration_authority": (
                "solver_declared"
            ),
            "sample_verification_scope": (
                "represented_samples_only"
            ),
            "voltage_tolerance_v": 1e-9,
            "power_tolerance_w": 1e-7,
            "continuous_curve_guarantee": (
                "solver_guaranteed"
            ),
            "continuous_curve_guarantee_basis": (
                "phase68 test curve"
            ),
        },
        "global_mpp": {
            "voltage_v": 50.0,
            "current_a": 10.0,
            "power_w": 500.0,
        },
        "local_mpp_candidates": [
            {
                "voltage_v": 50.0,
                "current_a": 10.0,
                "power_w": 500.0,
            }
        ],
        "scientific_model_manifest": {
            "model_id": (
                "phase68.test.mppt_combined"
            ),
            "model_version": "0.1",
        },
        "execution_manifest": {
            "solver_id": (
                "phase68.test.mppt_combined"
            ),
            "solver_version": "0.1",
            "voltage_grid_strategy": (
                "explicit_test_points"
            ),
            "point_count": 3,
            "cache_mode": "none",
            "parallelization": "none",
        },
        "scientific_input_sha256": (
            _sha(
                "curve-science"
            )
        ),
        "physical_result_sha256": (
            _sha(
                "curve-physical"
            )
        ),
        "quality_flags": [],
    }


def _template(
    *,
    minimum=20.0,
    maximum=80.0,
    max_current=15.0,
):
    return {
        "min_operating_voltage_v": (
            minimum
        ),
        "max_operating_voltage_v": (
            maximum
        ),
        "max_operating_current_a": (
            max_current
        ),
    }


def _solve(
    curve=None,
    template=None,
    model_id=(
        IDEAL_GLOBAL_MPPT_MODEL_ID
    ),
):
    return (
        select_mppt_operating_point(
            (
                _curve()
                if curve is None
                else curve
            ),
            source_electrical_revision_id=(
                "elec-r1"
            ),
            mppt_operating_point_model_id=(
                model_id
            ),
            mppt_template=(
                _template()
                if template is None
                else template
            ),
        )
    )


def test_phase68b_ideal_global_mpp_selects_physical_global_mpp_exactly():
    result = _solve()

    state = result.state

    assert (
        state[
            "mppt_operating_point_model_id"
        ]
        == IDEAL_GLOBAL_MPPT_MODEL_ID
    )

    assert (
        state[
            "control_assumption"
        ]
        == "ideal_global_mpp"
    )

    assert (
        state[
            "selected_operating_point"
        ]
        == state[
            "ideal_global_mpp"
        ]
    )

    assert state[
        "selected_operating_point"
    ] == {
        "voltage_v": 50.0,
        "current_a": 10.0,
        "power_w": 500.0,
    }

    assert state[
        "attribution"
    ][
        "delta_power_w"
    ] == pytest.approx(
        0.0
    )


def test_phase68b_reports_voltage_window_acceptance_without_clipping():
    state = _solve().state

    evaluation = state[
        "constraint_evaluation"
    ]

    assert (
        evaluation[
            "voltage_below_min"
        ]
        is False
    )

    assert (
        evaluation[
            "voltage_above_max"
        ]
        is False
    )

    assert (
        evaluation[
            "voltage_within_window"
        ]
        is True
    )

    assert (
        evaluation[
            "selected_point_violates_known_constraints"
        ]
        is False
    )

    assert (
        state[
            "selected_operating_point"
        ][
            "voltage_v"
        ]
        == pytest.approx(
            50.0
        )
    )


def test_phase68b_flags_below_minimum_voltage_without_rewriting_selected_point():
    state = _solve(
        template=_template(
            minimum=60.0,
            maximum=90.0,
            max_current=15.0,
        )
    ).state

    evaluation = state[
        "constraint_evaluation"
    ]

    assert (
        evaluation[
            "voltage_below_min"
        ]
        is True
    )

    assert (
        evaluation[
            "voltage_within_window"
        ]
        is False
    )

    assert (
        evaluation[
            "selected_point_violates_known_constraints"
        ]
        is True
    )

    assert (
        state[
            "selected_operating_point"
        ][
            "voltage_v"
        ]
        == pytest.approx(
            50.0
        )
    )


def test_phase68b_flags_above_maximum_voltage_without_rewriting_selected_point():
    state = _solve(
        template=_template(
            minimum=20.0,
            maximum=40.0,
            max_current=15.0,
        )
    ).state

    evaluation = state[
        "constraint_evaluation"
    ]

    assert (
        evaluation[
            "voltage_above_max"
        ]
        is True
    )

    assert (
        evaluation[
            "selected_point_violates_known_constraints"
        ]
        is True
    )

    assert (
        state[
            "selected_operating_point"
        ][
            "voltage_v"
        ]
        == pytest.approx(
            50.0
        )
    )


def test_phase68b_known_current_limit_is_evaluated_explicitly():
    state = _solve(
        template=_template(
            minimum=20.0,
            maximum=80.0,
            max_current=8.0,
        )
    ).state

    evaluation = state[
        "constraint_evaluation"
    ]

    assert (
        evaluation[
            "operating_current_limit_known"
        ]
        is True
    )

    assert (
        evaluation[
            "operating_current_above_limit"
        ]
        is True
    )

    assert (
        evaluation[
            "selected_point_violates_known_constraints"
        ]
        is True
    )


def test_phase68b_unknown_current_limit_remains_unknown_not_unlimited():
    state = _solve(
        template=_template(
            max_current=None
        )
    ).state

    evaluation = state[
        "constraint_evaluation"
    ]

    assert (
        evaluation[
            "operating_current_limit_known"
        ]
        is False
    )

    assert (
        evaluation[
            "operating_current_above_limit"
        ]
        is None
    )

    assert (
        state[
            "constraints"
        ][
            "max_operating_current_a"
        ]
        is None
    )


def test_phase68b_power_limit_is_explicitly_unavailable_not_invented():
    state = _solve().state

    assert (
        state[
            "constraints"
        ][
            "power_limit_contract_status"
        ]
        ==
        "not_available_in_current_"
        "mppt_template_contract"
    )

    assert (
        state[
            "constraint_evaluation"
        ][
            "power_limit_evaluated"
        ]
        is False
    )

    assert (
        state[
            "constraint_evaluation"
        ][
            "power_limit_status"
        ]
        ==
        "not_available_in_current_"
        "mppt_template_contract"
    )


def test_phase68b_is_deterministic_schema_valid_and_does_not_mutate_curve():
    curve = _curve()

    before = deepcopy(
        curve
    )

    first = _solve(
        curve=curve
    )

    second = _solve(
        curve=curve
    )

    assert curve == before

    assert (
        first.state
        == second.state
    )

    schema = json.loads(
        (
            ROOT
            / "shading"
            / "electrical"
            / "mppt-tracker-operating-state.schema.json"
        ).read_text(
            encoding="utf-8"
        )
    )

    Draft202012Validator(
        schema
    ).validate(
        first.state
    )

    with pytest.raises(
        MPPTTrackerOperatingError,
        match="unsupported",
    ):
        _solve(
            model_id=(
                "rawibumi.mppt."
                "perturb_and_observe.v0.1"
            )
        )
