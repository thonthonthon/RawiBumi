from __future__ import annotations

import copy
import json
from pathlib import Path

import pvlib
import pytest
from jsonschema import Draft202012Validator

from shading.electrical import (
    ElectricalParameterizationError,
    assemble_nonuniform_module_iv,
    assert_electrical_parameterization_definition,
    build_pvsyst_region_electrical_states,
    finalize_parameterization_payload,
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


def _parameter_set():
    # Explicit synthetic REGION model.
    #
    # It is intentionally authored independently
    # for this fixture. It is NOT derived by
    # dividing a whole-module parameter set.
    return {
        "alpha_sc_a_per_c": 0.002,
        "gamma_ref": 1.10,
        "mu_gamma": 0.0,
        "photocurrent_ref_a": 8.0,
        "saturation_current_ref_a": 1.0e-10,
        "r_shunt_ref_ohm": 500.0,
        "r_shunt_0_ohm": 2000.0,
        "r_series_ohm": 0.05,
        "cells_in_series": 24,
        "r_shunt_exp": 5.5,
        "energy_bandgap_ref_ev": 1.121,
        "reference_irradiance_w_m2": 1000.0,
        "reference_cell_temperature_c": 25.0,
    }


def _parameterization(topology=None):
    topology = (
        topology
        if topology is not None
        else _topology()
    )

    definition = {
        "schema_name": (
            "ElectricalParameterizationDefinition"
        ),
        "schema_version": "0.1",
        "contract_version": "0.1",
        "parameterization_id": (
            "phase66-synthetic-region-param"
        ),
        "revision_id": (
            "phase66-synthetic-region-param-r1"
        ),
        "parameterization_scope": (
            "region_substring"
        ),
        "module_definition_revision_id": (
            topology[
                "module_definition_revision_id"
            ]
        ),
        "module_topology_revision_id": (
            topology["revision_id"]
        ),
        "model_id": (
            "rawibumi.region."
            "pvsyst_singlediode_linear_reverse.v0.1"
        ),
        "model_version": "0.1",
        "region_parameterizations": [
            {
                "region_id": (
                    region["region_id"]
                ),
                "model_type": (
                    "pvsyst_singlediode_linear_reverse"
                ),
                "parameter_set": (
                    _parameter_set()
                ),
                "reverse_bias": {
                    "model_type": (
                        "linear_resistance_from_isc"
                    ),
                    "resistance_ohm": 0.20,
                    "minimum_supported_voltage_v": (
                        -1.5
                    ),
                },
                "current_domain_max_a": 12.0,
                "metadata": {
                    "synthetic_fixture": True
                },
            }
            for region
            in topology[
                "physical_regions"
            ]
        ],
        "source_ids": [
            "phase66-synthetic-region-source"
        ],
        "parameterization_payload_sha256": (
            "0" * 64
        ),
        "notes": (
            "Synthetic Phase-6.6 executable "
            "region-parameterization fixture."
        ),
        "metadata": {
            "synthetic_reference": True
        },
    }

    return (
        finalize_parameterization_payload(
            definition
        )
    )


def _evidence(
    parameterization,
):
    return {
        "schema_name": (
            "ElectricalParameterizationEvidence"
        ),
        "schema_version": "0.1",
        "contract_version": "0.1",
        "evidence_id": (
            "phase66-region-evidence"
        ),
        "parameterization_scope": (
            "region_substring"
        ),
        "parameterization_id": (
            parameterization[
                "parameterization_id"
            ]
        ),
        "module_definition_revision_id": (
            parameterization[
                "module_definition_revision_id"
            ]
        ),
        "module_topology_revision_id": (
            parameterization[
                "module_topology_revision_id"
            ]
        ),
        "model_id": (
            parameterization[
                "model_id"
            ]
        ),
        "model_version": (
            parameterization[
                "model_version"
            ]
        ),
        "validation_record_id": (
            "phase66-synthetic-validation"
        ),
        "validation_status": "passed",
        "verification_state": (
            "auto_validated"
        ),
        "parameterization_provenance": (
            "derived_validated"
        ),
        "source_ids": [
            "phase66-synthetic-region-source"
        ],
        "parameterization_payload_sha256": (
            parameterization[
                "parameterization_payload_sha256"
            ]
        ),
        "notes": (
            "Synthetic executable parameterization "
            "test evidence."
        ),
        "metadata": {},
    }


def _handoff(
    topology,
    *,
    irradiance_overrides=None,
):
    irradiance_overrides = (
        irradiance_overrides
        or {}
    )

    region_map = {
        "electrical_region_map_id": (
            "phase66-map"
        ),
        "mapping_payload_sha256": (
            "b" * 64
        ),
        "source_scene_revision_id": (
            "phase66-scene-r1"
        ),
        "source_module_instance_id": (
            "phase66-module-instance"
        ),
        "source_module_definition_revision_id": (
            topology[
                "module_definition_revision_id"
            ]
        ),
        "source_module_topology_revision_id": (
            topology["revision_id"]
        ),
        "source_receiver_id": (
            "receiver:module:phase66-module-instance"
        ),
        "mapped_region_area_m2": 6.0,
        "mapped_region_area_fraction": 1.0,
        "regions": [
            {
                "region_id": (
                    "mapped-"
                    + region["region_id"]
                ),
                "source_topology_region_id": (
                    region["region_id"]
                ),
                "source_electrical_substring_id": (
                    region[
                        "electrical_substring_id"
                    ]
                ),
                "area_m2": 1.0,
            }
            for region
            in topology[
                "physical_regions"
            ]
        ],
    }

    local_state = {
        "schema_name": (
            "LocalElectricalIrradianceState"
        ),
        "schema_version": "0.1",
        "contract_version": "0.1",
        "state_id": "phase66-local-state",
        "state_payload_sha256": "c" * 64,
        "source_electrical_region_map_id": (
            "phase66-map"
        ),
        "source_electrical_region_map_hash": (
            "b" * 64
        ),
        "source_scene_revision_id": (
            "phase66-scene-r1"
        ),
        "source_module_instance_id": (
            "phase66-module-instance"
        ),
        "source_module_definition_revision_id": (
            topology[
                "module_definition_revision_id"
            ]
        ),
        "source_shading_result_id": (
            "phase66-shading"
        ),
        "source_shading_physical_result_hash": (
            "d" * 64
        ),
        "interval_start": (
            "2026-10-01T04:00:00Z"
        ),
        "evaluation_time": (
            "2026-10-01T04:30:00Z"
        ),
        "irradiance_mapping_order": (
            "unshaded_poa_by_channel_then_"
            "geometry_visibility_then_optical_treatment"
        ),
        "thermal_state_scope": (
            "single_module_temperature"
        ),
        "module_temperature_c": 25.0,
        "optical_model_manifest": {
            "model_id": "phase66-unity",
            "model_version": "0.1"
        },
        "quality_flags": [],
        "regions": [
            {
                "region_id": (
                    "mapped-"
                    + region["region_id"]
                ),
                "effective_irradiance_w_m2": (
                    irradiance_overrides.get(
                        region["region_id"],
                        1000.0,
                    )
                ),
            }
            for region
            in topology[
                "physical_regions"
            ]
        ],
    }

    return (
        region_map,
        local_state,
    )


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


def test_phase66_parameterization_payload_is_explicit_and_hashed():
    topology = _topology()

    parameterization = (
        _parameterization(
            topology
        )
    )

    assert_electrical_parameterization_definition(
        parameterization,
        topology,
    )

    _validate_schema(
        "electrical-parameterization-definition.schema.json",
        parameterization,
    )

    assert (
        len(
            parameterization[
                "parameterization_payload_sha256"
            ]
        )
        == 64
    )


def test_phase66_parameterization_tampering_fails_closed():
    topology = _topology()

    parameterization = (
        _parameterization(
            topology
        )
    )

    parameterization[
        "region_parameterizations"
    ][0][
        "parameter_set"
    ][
        "photocurrent_ref_a"
    ] = 9.0

    with pytest.raises(
        ElectricalParameterizationError,
        match="payload hash mismatch",
    ):
        assert_electrical_parameterization_definition(
            parameterization,
            topology,
        )


def test_phase66_evidence_must_bind_exact_payload():
    topology = _topology()

    parameterization = (
        _parameterization(
            topology
        )
    )

    evidence = _evidence(
        parameterization
    )

    evidence[
        "parameterization_payload_sha256"
    ] = "f" * 64

    region_map, local = (
        _handoff(
            topology
        )
    )

    with pytest.raises(
        ElectricalParameterizationError,
        match="does not match payload",
    ):
        build_pvsyst_region_electrical_states(
            topology,
            region_map,
            local,
            parameterization,
            evidence,
        )


def test_phase66_uniform_module_matches_topological_scaling():
    topology = _topology()

    parameterization = (
        _parameterization(
            topology
        )
    )

    evidence = _evidence(
        parameterization
    )

    region_map, local = (
        _handoff(
            topology
        )
    )

    states = (
        build_pvsyst_region_electrical_states(
            topology,
            region_map,
            local,
            parameterization,
            evidence,
        )
    )

    one_region = states[
        "s0-r0"
    ]

    solved_region = (
        pvlib.pvsystem.singlediode(
            *one_region.diode_parameters,
            method="lambertw",
        )
    )

    result = (
        assemble_nonuniform_module_iv(
            topology,
            region_map,
            local,
            parameterization,
            evidence,
            sample_count=401,
        )
    )

    curve = result.curve

    # Three identical protected substrings
    # in series:
    #   module Voc = 3 × region Voc
    #
    # Two identical branches in parallel:
    #   module Isc = 2 × region Isc
    assert (
        curve["voc_v"]
        == pytest.approx(
            3.0
            * one_region.voc_v,
            rel=1e-8,
        )
    )

    assert (
        curve["isc_a"]
        == pytest.approx(
            2.0
            * one_region.isc_a,
            rel=1e-7,
        )
    )

    # 3-series × 2-parallel = 6 identical
    # region powers in the uniform case.
    expected_pmp = (
        6.0
        * float(
            solved_region[
                "p_mp"
            ]
        )
    )

    assert (
        curve[
            "global_mpp"
        ][
            "power_w"
        ]
        == pytest.approx(
            expected_pmp,
            rel=0.01,
        )
    )

    _validate_schema(
        "electrical-iv-curve.schema.json",
        curve,
    )

    _validate_schema(
        "module-nonuniform-iv-state.schema.json",
        result.state,
    )


def test_phase66_nonuniform_region_activates_explicit_bypass():
    topology = _topology()

    parameterization = (
        _parameterization(
            topology
        )
    )

    evidence = _evidence(
        parameterization
    )

    region_map, local = (
        _handoff(
            topology,
            irradiance_overrides={
                "s1-r1": 0.0,
            },
        )
    )

    result = (
        assemble_nonuniform_module_iv(
            topology,
            region_map,
            local,
            parameterization,
            evidence,
            sample_count=401,
        )
    )

    bypass_samples = []

    for sample in result.state[
        "current_samples"
    ]:
        states = {
            item[
                "substring_id"
            ]: item
            for item
            in sample[
                "substrings"
            ]
        }

        if states[
            "s1"
        ][
            "bypass_active"
        ]:
            bypass_samples.append(
                states
            )

    assert bypass_samples

    # Shaded middle substring bypasses while
    # at least one unshaded series substring
    # is still generating positive voltage.
    assert any(
        states[
            "s0"
        ][
            "terminal_voltage_v"
        ] > 0
        and states[
            "s2"
        ][
            "terminal_voltage_v"
        ] > 0
        for states
        in bypass_samples
    )


def test_phase66_nonuniform_irradiance_changes_physical_curve():
    topology = _topology()

    parameterization = (
        _parameterization(
            topology
        )
    )

    evidence = _evidence(
        parameterization
    )

    uniform_map, uniform_local = (
        _handoff(
            topology
        )
    )

    shaded_map, shaded_local = (
        _handoff(
            topology,
            irradiance_overrides={
                "s1-r1": 300.0,
            },
        )
    )

    uniform = (
        assemble_nonuniform_module_iv(
            topology,
            uniform_map,
            uniform_local,
            parameterization,
            evidence,
            sample_count=301,
        )
    )

    shaded = (
        assemble_nonuniform_module_iv(
            topology,
            shaded_map,
            shaded_local,
            parameterization,
            evidence,
            sample_count=301,
        )
    )

    assert (
        uniform.curve[
            "physical_result_sha256"
        ]
        != shaded.curve[
            "physical_result_sha256"
        ]
    )

    assert (
        shaded.curve[
            "global_mpp"
        ][
            "power_w"
        ]
        < uniform.curve[
            "global_mpp"
        ][
            "power_w"
        ]
    )


def test_phase66_exact_series_order_is_deterministic():
    topology = _topology()

    reordered = copy.deepcopy(
        topology
    )

    reordered[
        "electrical_substrings"
    ] = list(
        reversed(
            reordered[
                "electrical_substrings"
            ]
        )
    )

    parameterization = (
        _parameterization(
            topology
        )
    )

    evidence = _evidence(
        parameterization
    )

    region_map, local = (
        _handoff(
            topology,
            irradiance_overrides={
                "s1-r1": 500.0,
            },
        )
    )

    first = (
        assemble_nonuniform_module_iv(
            topology,
            region_map,
            local,
            parameterization,
            evidence,
            sample_count=201,
        )
    )

    second = (
        assemble_nonuniform_module_iv(
            reordered,
            region_map,
            local,
            parameterization,
            evidence,
            sample_count=201,
        )
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

    for sample in first.state[
        "current_samples"
    ]:
        assert [
            item[
                "series_order"
            ]
            for item
            in sample[
                "substrings"
            ]
        ] == [0, 1, 2]


def test_phase66_repeat_execution_has_identical_identity():
    topology = _topology()

    parameterization = (
        _parameterization(
            topology
        )
    )

    evidence = _evidence(
        parameterization
    )

    region_map, local = (
        _handoff(
            topology,
            irradiance_overrides={
                "s0-r0": 800.0,
                "s1-r1": 350.0,
            },
        )
    )

    first = (
        assemble_nonuniform_module_iv(
            topology,
            region_map,
            local,
            parameterization,
            evidence,
            sample_count=251,
        )
    )

    second = (
        assemble_nonuniform_module_iv(
            topology,
            region_map,
            local,
            parameterization,
            evidence,
            sample_count=251,
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


def test_phase66_effective_current_ceiling_intersects_current_and_voltage_domains():
    topology = _topology()

    parameterization = (
        _parameterization(
            topology
        )
    )

    evidence = _evidence(
        parameterization
    )

    region_map, local = (
        _handoff(
            topology,
            irradiance_overrides={
                "s1-r1": 0.0,
            },
        )
    )

    states = (
        build_pvsyst_region_electrical_states(
            topology,
            region_map,
            local,
            parameterization,
            evidence,
        )
    )

    dark = states[
        "s1-r1"
    ]

    # Fixture:
    # current_domain_max = 12 A
    # Rreverse = 0.20 ohm
    # Vmin = -1.5 V
    # Isc(dark) = 0 A
    #
    # Imax from reverse-voltage support:
    # 0 + 1.5 / 0.20 = 7.5 A
    #
    # effective domain:
    # min(12, 7.5) = 7.5 A
    assert (
        dark.current_ceiling_a
        == pytest.approx(
            7.5,
            abs=1e-10,
        )
    )

    assert (
        dark.voltage_at_current(
            7.5
        )
        == pytest.approx(
            -1.5,
            abs=1e-10,
        )
    )

    with pytest.raises(
        ElectricalParameterizationError,
        match="exceeds explicit parameterization domain",
    ):
        dark.voltage_at_current(
            7.5001
        )

