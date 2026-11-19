from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from shading.electrical import (
    ParallelStringIVError,
    assemble_parallel_mppt_iv,
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


def _curve(
    string_id: str,
    samples,
    *,
    salt: str,
):
    points = [
        {
            "voltage_v": float(
                voltage
            ),
            "current_a": float(
                current
            ),
            "power_w": float(
                voltage
                * current
            ),
        }
        for voltage, current
        in samples
    ]

    max_index = max(
        range(
            len(
                points
            )
        ),
        key=lambda index: (
            points[
                index
            ][
                "power_w"
            ]
        ),
    )

    global_mpp = copy.deepcopy(
        points[
            max_index
        ]
    )

    return {
        "schema_name": (
            "ElectricalIVCurve"
        ),
        "schema_version": "0.1",
        "contract_version": "0.1",
        "curve_id": (
            f"curve:{string_id}:{salt}"
        ),
        "curve_scope": "string",
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
        "source_string_id": (
            string_id
        ),
        "source_mppt_instance_id": None,
        "points": points,
        "isc_a": float(
            points[0][
                "current_a"
            ]
        ),
        "voc_v": float(
            points[-1][
                "voltage_v"
            ]
        ),
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
                "none"
            ),
            "continuous_curve_guarantee_basis": (
                None
            ),
        },
        "global_mpp": (
            global_mpp
        ),
        "local_mpp_candidates": [
            copy.deepcopy(
                global_mpp
            )
        ],
        "scientific_model_manifest": {
            "model_id": (
                "phase68.test.string_curve"
            ),
            "model_version": "0.1",
        },
        "execution_manifest": {
            "solver_id": (
                "phase68.test.string_curve"
            ),
            "solver_version": "0.1",
            "voltage_grid_strategy": (
                "explicit_test_points"
            ),
            "point_count": len(
                points
            ),
            "cache_mode": "none",
            "parallelization": "none",
        },
        "scientific_input_sha256": (
            _sha(
                "scientific:"
                + string_id
                + ":"
                + salt
            )
        ),
        "physical_result_sha256": (
            _sha(
                "physical:"
                + string_id
                + ":"
                + salt
            )
        ),
        "quality_flags": [],
    }


def _mppt(
    string_ids,
):
    return {
        "mppt_instance_id": (
            "mppt-1"
        ),
        "inverter_instance_id": (
            "inv-1"
        ),
        "index": 1,
        "connected_string_ids": list(
            string_ids
        ),
        "enabled": True,
    }


def _validate(
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


def test_phase68a_identical_strings_sum_current_and_power():
    a = _curve(
        "S01",
        [
            (0.0, 10.0),
            (50.0, 5.0),
            (100.0, 0.0),
        ],
        salt="a",
    )

    b = _curve(
        "S02",
        [
            (0.0, 10.0),
            (50.0, 5.0),
            (100.0, 0.0),
        ],
        salt="b",
    )

    result = (
        assemble_parallel_mppt_iv(
            _mppt(
                [
                    "S01",
                    "S02",
                ]
            ),
            {
                "S01": a,
                "S02": b,
            },
            source_electrical_revision_id=(
                "elec-r1"
            ),
        )
    )

    curve = result.curve

    assert (
        curve[
            "curve_scope"
        ]
        == "mppt_combined"
    )

    assert curve[
        "isc_a"
    ] == pytest.approx(
        20.0
    )

    assert curve[
        "voc_v"
    ] == pytest.approx(
        100.0
    )

    assert curve[
        "global_mpp"
    ][
        "voltage_v"
    ] == pytest.approx(
        50.0
    )

    assert curve[
        "global_mpp"
    ][
        "current_a"
    ] == pytest.approx(
        10.0
    )

    assert curve[
        "global_mpp"
    ][
        "power_w"
    ] == pytest.approx(
        500.0
    )


def test_phase68a_mismatched_voc_uses_explicit_nonnegative_delivery_policy():
    a = _curve(
        "S01",
        [
            (0.0, 10.0),
            (50.0, 5.0),
            # Redundant point exactly on the existing
            # 50 -> 100 V linear segment:
            #
            # I(90 V) = 1 A.
            #
            # It exposes an explicit represented
            # voltage above S02 Voc=80 V without
            # changing S01's piecewise-linear IV law.
            (90.0, 1.0),
            (100.0, 0.0),
        ],
        salt="a",
    )

    b = _curve(
        "S02",
        [
            (0.0, 6.0),
            (40.0, 3.0),
            (80.0, 0.0),
        ],
        salt="b",
    )

    result = (
        assemble_parallel_mppt_iv(
            _mppt(
                [
                    "S01",
                    "S02",
                ]
            ),
            {
                "S01": a,
                "S02": b,
            },
            source_electrical_revision_id=(
                "elec-r1"
            ),
        )
    )

    curve = result.curve
    state = result.state

    assert curve[
        "isc_a"
    ] == pytest.approx(
        16.0
    )

    # Under the explicit Phase-6 delivery-current
    # boundary the lower-Voc string contributes
    # zero current above its represented Voc.
    assert curve[
        "voc_v"
    ] == pytest.approx(
        100.0
    )

    sample_90 = next(
        sample
        for sample
        in state[
            "voltage_samples"
        ]
        if sample[
            "voltage_v"
        ]
        == pytest.approx(
            90.0
        )
    )

    contributions = {
        item[
            "string_id"
        ]:
        item[
            "current_a"
        ]
        for item
        in sample_90[
            "string_currents"
        ]
    }

    assert contributions[
        "S01"
    ] == pytest.approx(
        1.0
    )

    assert contributions[
        "S02"
    ] == pytest.approx(
        0.0
    )

    assert (
        state[
            "reverse_interstring_current_policy"
        ]
        ==
        "not_modeled_pv_delivery_branch_only_"
        "zero_contribution_above_source_voc"
    )

    assert (
        "reverse_interstring_backfeed_not_modeled"
        in curve[
            "quality_flags"
        ]
    )


def test_phase68a_detects_multiple_local_mpp_candidates():
    a = _curve(
        "S01",
        [
            (0.0, 10.0),
            (20.0, 9.0),
            (21.0, 4.0),
            (50.0, 3.0),
            (51.0, 1.0),
            (80.0, 0.0),
        ],
        salt="multi",
    )

    result = (
        assemble_parallel_mppt_iv(
            _mppt(
                [
                    "S01",
                ]
            ),
            {
                "S01": a,
            },
            source_electrical_revision_id=(
                "elec-r1"
            ),
        )
    )

    voltages = [
        item[
            "voltage_v"
        ]
        for item
        in result.curve[
            "local_mpp_candidates"
        ]
    ]

    assert any(
        value
        == pytest.approx(
            20.0
        )
        for value
        in voltages
    )

    assert any(
        value
        == pytest.approx(
            50.0
        )
        for value
        in voltages
    )


def test_phase68a_parallel_input_order_does_not_change_identity():
    a = _curve(
        "S01",
        [
            (0.0, 10.0),
            (50.0, 5.0),
            (100.0, 0.0),
        ],
        salt="a",
    )

    b = _curve(
        "S02",
        [
            (0.0, 6.0),
            (40.0, 3.0),
            (80.0, 0.0),
        ],
        salt="b",
    )

    first = (
        assemble_parallel_mppt_iv(
            _mppt(
                [
                    "S01",
                    "S02",
                ]
            ),
            {
                "S01": a,
                "S02": b,
            },
            source_electrical_revision_id=(
                "elec-r1"
            ),
        )
    )

    second = (
        assemble_parallel_mppt_iv(
            _mppt(
                [
                    "S02",
                    "S01",
                ]
            ),
            {
                "S02": b,
                "S01": a,
            },
            source_electrical_revision_id=(
                "elec-r1"
            ),
        )
    )

    assert (
        first.curve
        == second.curve
    )

    assert (
        first.state
        == second.state
    )


def test_phase68a_repeat_execution_is_deterministic():
    a = _curve(
        "S01",
        [
            (0.0, 11.0),
            (45.0, 6.0),
            (92.0, 0.0),
        ],
        salt="a",
    )

    b = _curve(
        "S02",
        [
            (0.0, 8.0),
            (39.0, 4.0),
            (84.0, 0.0),
        ],
        salt="b",
    )

    kwargs = {
        "mppt_instance": (
            _mppt(
                [
                    "S01",
                    "S02",
                ]
            )
        ),
        "string_curves": {
            "S01": a,
            "S02": b,
        },
        "source_electrical_revision_id": (
            "elec-r1"
        ),
    }

    first = (
        assemble_parallel_mppt_iv(
            **kwargs
        )
    )

    second = (
        assemble_parallel_mppt_iv(
            **kwargs
        )
    )

    assert (
        first.curve
        == second.curve
    )

    assert (
        first.state
        == second.state
    )


def test_phase68a_requires_exact_connected_string_coverage():
    a = _curve(
        "S01",
        [
            (0.0, 10.0),
            (50.0, 5.0),
            (100.0, 0.0),
        ],
        salt="a",
    )

    with pytest.raises(
        ParallelStringIVError,
        match="exactly match",
    ):
        assemble_parallel_mppt_iv(
            _mppt(
                [
                    "S01",
                    "S02",
                ]
            ),
            {
                "S01": a,
            },
            source_electrical_revision_id=(
                "elec-r1"
            ),
        )


def test_phase68a_rejects_non_string_curve():
    a = _curve(
        "S01",
        [
            (0.0, 10.0),
            (50.0, 5.0),
            (100.0, 0.0),
        ],
        salt="a",
    )

    a[
        "curve_scope"
    ] = "module"

    with pytest.raises(
        ParallelStringIVError,
        match="curve_scope='string'",
    ):
        assemble_parallel_mppt_iv(
            _mppt(
                [
                    "S01",
                ]
            ),
            {
                "S01": a,
            },
            source_electrical_revision_id=(
                "elec-r1"
            ),
        )


def test_phase68a_rejects_negative_delivery_current():
    a = _curve(
        "S01",
        [
            (0.0, 10.0),
            (50.0, -1.0),
            (100.0, 0.0),
        ],
        salt="negative",
    )

    with pytest.raises(
        ParallelStringIVError,
        match="negative delivery current",
    ):
        assemble_parallel_mppt_iv(
            _mppt(
                [
                    "S01",
                ]
            ),
            {
                "S01": a,
            },
            source_electrical_revision_id=(
                "elec-r1"
            ),
        )


def test_phase68a_rejects_nonmonotone_delivery_current():
    a = _curve(
        "S01",
        [
            (0.0, 10.0),
            (30.0, 5.0),
            (40.0, 6.0),
            (100.0, 0.0),
        ],
        salt="rising-current",
    )

    with pytest.raises(
        ParallelStringIVError,
        match="non-increasing",
    ):
        assemble_parallel_mppt_iv(
            _mppt(
                [
                    "S01",
                ]
            ),
            {
                "S01": a,
            },
            source_electrical_revision_id=(
                "elec-r1"
            ),
        )


def test_phase68a_state_and_curve_validate_against_schemas():
    a = _curve(
        "S01",
        [
            (0.0, 10.0),
            (50.0, 5.0),
            (100.0, 0.0),
        ],
        salt="a",
    )

    b = _curve(
        "S02",
        [
            (0.0, 6.0),
            (40.0, 3.0),
            (80.0, 0.0),
        ],
        salt="b",
    )

    result = (
        assemble_parallel_mppt_iv(
            _mppt(
                [
                    "S01",
                    "S02",
                ]
            ),
            {
                "S01": a,
                "S02": b,
            },
            source_electrical_revision_id=(
                "elec-r1"
            ),
        )
    )

    _validate(
        "electrical-iv-curve.schema.json",
        result.curve,
    )

    _validate(
        "mppt-parallel-iv-state.schema.json",
        result.state,
    )

    assert (
        result.curve[
            "mpp_semantics"
        ][
            "continuous_curve_guarantee"
        ]
        == "solver_guaranteed"
    )
