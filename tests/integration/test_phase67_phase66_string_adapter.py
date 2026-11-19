from __future__ import annotations

import copy
import json
from pathlib import Path
import runpy

import pytest
from jsonschema import Draft202012Validator

from shading.electrical import (
    assemble_general_series_string_iv,
    assemble_nonuniform_module_iv,
    build_phase66_series_module_operating_model,
)


ROOT = Path(
    __file__
).resolve().parents[2]


# Reuse the already validated Phase-6.6 controlled fixtures
# without making production code depend on test code.
_PHASE66 = runpy.run_path(
    str(
        ROOT
        / "tests"
        / "unit"
        / "test_phase66_nonuniform_module_iv.py"
    )
)

for _name in (
    "_topology",
    "_parameterization",
    "_evidence",
    "_handoff",
):
    if _name not in _PHASE66:
        raise RuntimeError(
            "Frozen Phase-6.6 fixture helper "
            f"missing: {_name}"
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

_handoff = _PHASE66[
    "_handoff"
]


def _module_handoff(
    topology,
    module_id,
    *,
    irradiance_overrides=None,
    map_hex="1",
    local_hex="2",
):
    region_map, local = (
        _handoff(
            topology,
            irradiance_overrides=(
                irradiance_overrides
                or {}
            ),
        )
    )

    region_map = copy.deepcopy(
        region_map
    )

    local = copy.deepcopy(
        local
    )

    map_id = (
        "phase67-map:"
        + module_id
    )

    map_hash = (
        map_hex * 64
    )

    local_id = (
        "phase67-local:"
        + module_id
    )

    local_hash = (
        local_hex * 64
    )

    region_map[
        "source_module_instance_id"
    ] = module_id

    region_map[
        "electrical_region_map_id"
    ] = map_id

    region_map[
        "mapping_payload_sha256"
    ] = map_hash

    local[
        "source_module_instance_id"
    ] = module_id

    local[
        "source_electrical_region_map_id"
    ] = map_id

    local[
        "source_electrical_region_map_hash"
    ] = map_hash

    local[
        "state_id"
    ] = local_id

    local[
        "state_payload_sha256"
    ] = local_hash

    return (
        region_map,
        local,
    )


def _string_circuit(
    module_ids,
):
    return {
        "string_id": (
            "S67-PHASE66"
        ),
        "project_revision_id": (
            "project-phase67-r1"
        ),
        "name": (
            "Phase-6.7 Phase-6.6 adapter string"
        ),
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
        "topology_source": (
            "phase67-test"
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
def phase67b_results():
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

    # Strong module: completely clear.
    (
        strong_map,
        strong_local,
    ) = _module_handoff(
        topology,
        "module-strong",
        irradiance_overrides={},
        map_hex="1",
        local_hex="2",
    )

    # Weak module: one region in protected
    # substring s1 is completely dark.
    (
        weak_map,
        weak_local,
    ) = _module_handoff(
        topology,
        "module-weak",
        irradiance_overrides={
            "s1-r1": 0.0,
        },
        map_hex="3",
        local_hex="4",
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

    # Standalone weak-module Isc is intentionally
    # computed through the frozen Phase-6.6 API.
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
        _string_circuit(
            [
                "module-weak",
                "module-strong",
            ]
        )
    )

    string_result = (
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
        "strong_model": (
            strong_model
        ),
        "weak_model": (
            weak_model
        ),
        "weak_standalone": (
            weak_standalone
        ),
        "string_result": (
            string_result
        ),
        "repeat": (
            repeat
        ),
    }


def test_phase67b_phase66_adapter_preserves_negative_module_voltage(
    phase67b_results,
):
    data = phase67b_results

    weak_isc = float(
        data[
            "weak_standalone"
        ].curve[
            "isc_a"
        ]
    )

    string_isc = float(
        data[
            "string_result"
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

    weak_state = (
        data[
            "weak_model"
        ].voltage_at_current(
            probe_current
        )
    )

    strong_state = (
        data[
            "strong_model"
        ].voltage_at_current(
            probe_current
        )
    )

    weak_voltage = float(
        weak_state[
            "terminal_voltage_v"
        ]
    )

    strong_voltage = float(
        strong_state[
            "terminal_voltage_v"
        ]
    )

    assert weak_voltage < 0.0

    assert (
        strong_voltage
        + weak_voltage
        > 0.0
    )

    assert any(
        item[
            "bypass_active"
        ]
        for item
        in weak_state[
            "protected_substrings"
        ]
    )


def test_phase67b_string_curve_and_state_are_canonical(
    phase67b_results,
):
    result = phase67b_results[
        "string_result"
    ]

    assert (
        result.curve[
            "curve_scope"
        ]
        == "string"
    )

    assert (
        result.curve[
            "source_string_id"
        ]
        == "S67-PHASE66"
    )

    assert (
        result.state[
            "source_module_instance_ids"
        ]
        == [
            "module-weak",
            "module-strong",
        ]
    )

    assert [
        source[
            "module_instance_id"
        ]
        for source
        in result.state[
            "module_sources"
        ]
    ] == [
        "module-weak",
        "module-strong",
    ]

    assert (
        result.curve[
            "global_mpp"
        ][
            "power_w"
        ]
        > 0.0
    )

    _validate_schema(
        "electrical-iv-curve.schema.json",
        result.curve,
    )

    _validate_schema(
        "string-series-iv-state.schema.json",
        result.state,
    )


def test_phase67b_phase66_adapter_is_deterministic(
    phase67b_results,
):
    first = phase67b_results[
        "string_result"
    ]

    second = phase67b_results[
        "repeat"
    ]

    assert (
        first.curve
        == second.curve
    )

    assert (
        first.state
        == second.state
    )

    assert (
        first.curve[
            "physical_result_sha256"
        ]
        == second.curve[
            "physical_result_sha256"
        ]
    )

    assert (
        first.state[
            "state_payload_sha256"
        ]
        == second.state[
            "state_payload_sha256"
        ]
    )


def test_phase67b_adapter_identity_changes_with_module_physics(
    phase67b_results,
):
    strong = phase67b_results[
        "strong_model"
    ]

    weak = phase67b_results[
        "weak_model"
    ]

    assert (
        strong.scientific_input_sha256
        != weak.scientific_input_sha256
    )

    assert (
        strong.module_instance_id
        == "module-strong"
    )

    assert (
        weak.module_instance_id
        == "module-weak"
    )
