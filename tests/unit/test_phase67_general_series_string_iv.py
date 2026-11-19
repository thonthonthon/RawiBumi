from __future__ import annotations

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from shading.electrical import (
    GeneralSeriesStringIVError,
    SeriesModuleOperatingModel,
    assemble_general_series_string_iv,
)


ROOT = Path(
    __file__
).resolve().parents[2]


def _string(
    module_ids,
    *,
    string_id="S67",
):
    return {
        "string_id": string_id,
        "project_revision_id": (
            "project-phase67-r1"
        ),
        "name": string_id,
        "module_instance_ids": list(
            module_ids
        ),
        "target_mppt_instance_id": (
            "mppt-phase67-1"
        ),
        "enabled": True,
        "polarity": "normal",
        "cable_definition_id": None,
        "notes": None,
        "topology_source": "phase67-test",
    }


def _linear_model(
    module_id,
    *,
    voc_v,
    resistance_v_per_a,
    current_ceiling_a=30.0,
    identity_char="a",
):
    def evaluate(
        current_a,
    ):
        voltage = (
            voc_v
            - resistance_v_per_a
            * current_a
        )

        return {
            "terminal_voltage_v": (
                voltage
            ),
            "protected_substrings": [],
        }

    return SeriesModuleOperatingModel(
        module_instance_id=(
            module_id
        ),
        current_domain_ceiling_a=(
            current_ceiling_a
        ),
        scientific_input_sha256=(
            identity_char
            * 64
        ),
        model_id=(
            "phase67.synthetic.linear_vi"
        ),
        model_version="0.1",
        voltage_at_current=(
            evaluate
        ),
    )


def _schema(
    filename,
):
    return json.loads(
        (
            ROOT
            / "shading"
            / "electrical"
            / filename
        ).read_text(
            encoding="utf-8"
        )
    )


def test_phase67_identical_modules_follow_exact_series_rules():
    modules = {
        "M1": _linear_model(
            "M1",
            voc_v=40.0,
            resistance_v_per_a=2.0,
            identity_char="a",
        ),
        "M2": _linear_model(
            "M2",
            voc_v=40.0,
            resistance_v_per_a=2.0,
            identity_char="b",
        ),
    }

    result = (
        assemble_general_series_string_iv(
            _string(
                ["M1", "M2"]
            ),
            modules,
            sample_count=101,
        )
    )

    curve = result.curve

    # Each module:
    #
    # V = 40 - 2I
    #
    # String:
    #
    # V = 80 - 4I
    #
    # Isc = 20 A
    # MPP: I = 10 A
    #      V = 40 V
    #      P = 400 W
    assert curve[
        "voc_v"
    ] == pytest.approx(
        80.0,
        abs=1e-8,
    )

    assert curve[
        "isc_a"
    ] == pytest.approx(
        20.0,
        abs=1e-7,
    )

    assert curve[
        "global_mpp"
    ][
        "current_a"
    ] == pytest.approx(
        10.0,
        abs=1e-7,
    )

    assert curve[
        "global_mpp"
    ][
        "voltage_v"
    ] == pytest.approx(
        40.0,
        abs=1e-7,
    )

    assert curve[
        "global_mpp"
    ][
        "power_w"
    ] == pytest.approx(
        400.0,
        abs=1e-6,
    )

    assert curve[
        "curve_scope"
    ] == "string"

    assert curve[
        "source_string_id"
    ] == "S67"

    Draft202012Validator(
        _schema(
            "electrical-iv-curve.schema.json"
        )
    ).validate(
        curve
    )

    Draft202012Validator(
        _schema(
            "string-series-iv-state.schema.json"
        )
    ).validate(
        result.state
    )


def test_phase67_weak_module_can_run_negative_beyond_its_standalone_isc():
    modules = {
        "strong": _linear_model(
            "strong",
            voc_v=40.0,
            resistance_v_per_a=2.0,
            identity_char="c",
        ),
        "weak": _linear_model(
            "weak",
            voc_v=20.0,
            resistance_v_per_a=5.0,
            identity_char="d",
        ),
    }

    result = (
        assemble_general_series_string_iv(
            _string(
                [
                    "strong",
                    "weak",
                ]
            ),
            modules,
            sample_count=101,
        )
    )

    # Weak module standalone Isc:
    #
    # 20 - 5I = 0
    # I = 4 A
    #
    # Full string:
    #
    # V = 60 - 7I
    # Isc = 60/7 = 8.5714 A
    #
    # Therefore a correct general series solver
    # must operate the weak module beyond its
    # standalone Isc.
    assert result.curve[
        "isc_a"
    ] == pytest.approx(
        60.0 / 7.0,
        rel=1e-8,
    )

    assert (
        result.curve[
            "isc_a"
        ]
        > 4.0
    )

    negative_weak_states = []

    for sample in result.state[
        "current_samples"
    ]:
        by_id = {
            item[
                "module_instance_id"
            ]:
            item
            for item
            in sample[
                "modules"
            ]
        }

        if (
            by_id[
                "weak"
            ][
                "terminal_voltage_v"
            ]
            < 0.0
            and sample[
                "string_voltage_v"
            ]
            > 0.0
        ):
            negative_weak_states.append(
                sample
            )

    assert negative_weak_states

    # Analytical string MPP:
    #
    # P = I(60 - 7I)
    #
    # dP/dI = 60 - 14I = 0
    #
    # I = 30/7
    assert result.curve[
        "global_mpp"
    ][
        "current_a"
    ] == pytest.approx(
        30.0 / 7.0,
        rel=1e-7,
    )

    # At that current, the weak module is already
    # reverse-driven:
    #
    # Vweak = 20 - 5*(30/7)
    #       = -10/7 V
    assert result.curve[
        "global_mpp"
    ][
        "power_w"
    ] == pytest.approx(
        900.0 / 7.0,
        rel=1e-7,
    )


def test_phase67_preserves_canonical_module_order_in_explanatory_state():
    models = {
        "M1": _linear_model(
            "M1",
            voc_v=30.0,
            resistance_v_per_a=1.0,
            identity_char="1",
        ),
        "M2": _linear_model(
            "M2",
            voc_v=30.0,
            resistance_v_per_a=1.0,
            identity_char="2",
        ),
        "M3": _linear_model(
            "M3",
            voc_v=30.0,
            resistance_v_per_a=1.0,
            identity_char="3",
        ),
    }

    order = [
        "M3",
        "M1",
        "M2",
    ]

    result = (
        assemble_general_series_string_iv(
            _string(
                order
            ),
            models,
            sample_count=51,
        )
    )

    assert result.state[
        "source_module_instance_ids"
    ] == order

    assert [
        item[
            "module_instance_id"
        ]
        for item
        in result.state[
            "module_sources"
        ]
    ] == order

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
        ] == order

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
            2,
        ]


def test_phase67_reordering_changes_scientific_identity_not_physical_result():
    models = {
        "A": _linear_model(
            "A",
            voc_v=40.0,
            resistance_v_per_a=2.0,
            identity_char="4",
        ),
        "B": _linear_model(
            "B",
            voc_v=25.0,
            resistance_v_per_a=3.0,
            identity_char="5",
        ),
    }

    first = (
        assemble_general_series_string_iv(
            _string(
                ["A", "B"]
            ),
            models,
            sample_count=61,
        )
    )

    second = (
        assemble_general_series_string_iv(
            _string(
                ["B", "A"]
            ),
            models,
            sample_count=61,
        )
    )

    # Pure series voltage summation is
    # commutative physically.
    assert (
        first.curve[
            "physical_result_sha256"
        ]
        == second.curve[
            "physical_result_sha256"
        ]
    )

    # But canonical engineer-defined module order
    # is part of scientific provenance.
    assert (
        first.curve[
            "scientific_input_sha256"
        ]
        != second.curve[
            "scientific_input_sha256"
        ]
    )

    assert (
        first.state[
            "state_payload_sha256"
        ]
        != second.state[
            "state_payload_sha256"
        ]
    )


def test_phase67_module_model_coverage_fails_closed():
    circuit = _string(
        ["M1", "M2"]
    )

    only_one = {
        "M1": _linear_model(
            "M1",
            voc_v=40.0,
            resistance_v_per_a=2.0,
            identity_char="6",
        )
    }

    with pytest.raises(
        GeneralSeriesStringIVError,
        match="coverage",
    ):
        assemble_general_series_string_iv(
            circuit,
            only_one,
        )

    extra = {
        "M1": _linear_model(
            "M1",
            voc_v=40.0,
            resistance_v_per_a=2.0,
            identity_char="6",
        ),
        "M2": _linear_model(
            "M2",
            voc_v=40.0,
            resistance_v_per_a=2.0,
            identity_char="7",
        ),
        "M3": _linear_model(
            "M3",
            voc_v=40.0,
            resistance_v_per_a=2.0,
            identity_char="8",
        ),
    }

    with pytest.raises(
        GeneralSeriesStringIVError,
        match="coverage",
    ):
        assemble_general_series_string_iv(
            circuit,
            extra,
        )


@pytest.mark.parametrize(
    "polarity",
    [
        "reversed",
        "unknown",
    ],
)
def test_phase67_non_normal_polarity_fails_closed(
    polarity,
):
    circuit = _string(
        ["M1"]
    )

    circuit[
        "polarity"
    ] = polarity

    with pytest.raises(
        GeneralSeriesStringIVError,
        match="polarity='normal'",
    ):
        assemble_general_series_string_iv(
            circuit,
            {
                "M1": _linear_model(
                    "M1",
                    voc_v=40.0,
                    resistance_v_per_a=2.0,
                    identity_char="9",
                )
            },
        )


def test_phase67_unsupported_current_domain_fails_closed():
    models = {
        "M1": _linear_model(
            "M1",
            voc_v=40.0,
            resistance_v_per_a=1.0,
            current_ceiling_a=10.0,
            identity_char="a",
        ),
        "M2": _linear_model(
            "M2",
            voc_v=40.0,
            resistance_v_per_a=1.0,
            current_ceiling_a=10.0,
            identity_char="b",
        ),
    }

    # Vstring = 80 - 2I.
    # At the declared 10 A ceiling V=60 V,
    # so the supported source domains cannot
    # reach string Isc.
    with pytest.raises(
        GeneralSeriesStringIVError,
        match="too short to reach string Isc",
    ):
        assemble_general_series_string_iv(
            _string(
                ["M1", "M2"]
            ),
            models,
        )


def test_phase67_repeat_execution_is_deterministic():
    models = {
        "M1": _linear_model(
            "M1",
            voc_v=42.0,
            resistance_v_per_a=2.5,
            identity_char="c",
        ),
        "M2": _linear_model(
            "M2",
            voc_v=38.0,
            resistance_v_per_a=1.5,
            identity_char="d",
        ),
    }

    circuit = _string(
        ["M1", "M2"]
    )

    first = (
        assemble_general_series_string_iv(
            circuit,
            models,
            sample_count=81,
        )
    )

    second = (
        assemble_general_series_string_iv(
            circuit,
            models,
            sample_count=81,
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
