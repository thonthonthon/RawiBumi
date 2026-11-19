from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from geometry.shading import (
    GroundDomeResolution,
    SkyDomeResolution,
)

from shading.electrical import (
    assemble_nonuniform_module_iv,
    build_local_electrical_irradiance_state,
    derive_electrical_region_map,
    evaluate_electrical_region_visibility,
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


def _base_compiled_geometry():
    return {
        "source_scene_revision_id": (
            "phase66-integration-scene-r1"
        ),
        "geometry_payload_sha256": (
            "6" * 64
        ),
        "receivers": [
            {
                "receiver_id": (
                    "receiver:module:"
                    "phase66-integration"
                ),
                "source_entity_type": (
                    "module_instance"
                ),
                "source_entity_id": (
                    "phase66-module-instance"
                ),
                "receiver_type": (
                    "module_plane"
                ),

                # Same deterministic module plane
                # convention already proven by
                # the Phase-6.5 integration gate.
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
                    "phase66-field"
                ),
                "support_surface_id": (
                    "phase66-surface"
                ),
                "module_instance_id": (
                    "phase66-module-instance"
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
    """Occlude exactly the mapped target polygon."""

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
            "occluder:phase66:"
            + mapped_region[
                "source_topology_region_id"
            ]
        ),
        "source_entity_type": (
            "obstacle"
        ),
        "source_entity_id": (
            "phase66-target-obstacle"
        ),
        "geometry_type": (
            "polygon_faces"
        ),
        "faces": [
            {
                "face_id": (
                    "phase66-target-obstacle:"
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
            "phase66_fixture": True,
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
                "phase66-module-instance"
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
                    "phase66.integration.unity"
                ),
                "model_version": "0.1",
                "notes": (
                    "Phase-6.6 real handoff "
                    "integration fixture."
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


def _parameter_set():
    # Explicit synthetic REGION parameters.
    #
    # Deliberately authored independently.
    # These are NOT obtained by dividing or
    # otherwise scaling a whole-module SDM.
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


def _parameterization(
    topology,
):
    definition = {
        "schema_name": (
            "ElectricalParameterizationDefinition"
        ),
        "schema_version": "0.1",
        "contract_version": "0.1",
        "parameterization_id": (
            "phase66-integration-region-param"
        ),
        "revision_id": (
            "phase66-integration-region-param-r1"
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
            topology[
                "revision_id"
            ]
        ),
        "model_id": (
            "rawibumi.region."
            "pvsyst_singlediode_linear_reverse.v0.1"
        ),
        "model_version": "0.1",
        "region_parameterizations": [
            {
                "region_id": (
                    region[
                        "region_id"
                    ]
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
            "phase66-integration-region-source"
        ],
        "parameterization_payload_sha256": (
            "0" * 64
        ),
        "notes": (
            "Synthetic executable regional "
            "parameterization used only for "
            "Phase-6.6 integration validation."
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
            "phase66-integration-evidence"
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
            "phase66-integration-validation"
        ),
        "validation_status": "passed",
        "verification_state": (
            "auto_validated"
        ),
        "parameterization_provenance": (
            "derived_validated"
        ),
        "source_ids": [
            "phase66-integration-region-source"
        ],
        "parameterization_payload_sha256": (
            parameterization[
                "parameterization_payload_sha256"
            ]
        ),
        "notes": (
            "Synthetic Phase-6.6 integration "
            "parameterization evidence."
        ),
        "metadata": {},
    }


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
            local_region[
                "region_id"
            ]
        ]:
        local_region[
            "effective_irradiance_w_m2"
        ]
        for local_region
        in local_state[
            "regions"
        ]
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
def integration_results():
    topology = _topology()

    parameterization = (
        _parameterization(
            topology
        )
    )

    evidence = _evidence(
        parameterization
    )

    # --------------------------------------------------------
    # Clear real Phase-6.3 handoff
    # --------------------------------------------------------

    clear_geometry = (
        _base_compiled_geometry()
    )

    (
        clear_map,
        clear_visibility,
        clear_local,
    ) = _local_state(
        clear_geometry,
        topology,
    )

    clear_result = (
        assemble_nonuniform_module_iv(
            topology,
            clear_map,
            clear_local,
            parameterization,
            evidence,

            # Integration coverage does not require
            # the 201/301/401-point unit-test grids.
            sample_count=81,
        )
    )

    # --------------------------------------------------------
    # Shaded real Phase-6.3 handoff
    # --------------------------------------------------------

    base_map = (
        derive_electrical_region_map(
            clear_geometry,
            topology,
            module_instance_id=(
                "phase66-module-instance"
            ),
        )
    )

    target = _target_region(
        base_map,
        "s1-r1",
    )

    shaded_geometry = copy.deepcopy(
        clear_geometry
    )

    shaded_geometry[
        "geometry_payload_sha256"
    ] = "7" * 64

    shaded_geometry[
        "occluders"
    ] = [
        _occluder_from_mapped_region(
            target
        )
    ]

    (
        shaded_map,
        shaded_visibility,
        shaded_local,
    ) = _local_state(
        shaded_geometry,
        topology,
    )

    shaded_result = (
        assemble_nonuniform_module_iv(
            topology,
            shaded_map,
            shaded_local,
            parameterization,
            evidence,
            sample_count=81,
        )
    )

    # One repeat proves deterministic identity.
    shaded_repeat = (
        assemble_nonuniform_module_iv(
            topology,
            shaded_map,
            shaded_local,
            parameterization,
            evidence,
            sample_count=81,
        )
    )

    return {
        "topology": topology,
        "parameterization": (
            parameterization
        ),
        "evidence": evidence,

        "clear_map": clear_map,
        "clear_visibility": (
            clear_visibility
        ),
        "clear_local": clear_local,
        "clear_result": clear_result,

        "shaded_map": shaded_map,
        "shaded_visibility": (
            shaded_visibility
        ),
        "shaded_local": shaded_local,
        "shaded_result": shaded_result,
        "shaded_repeat": shaded_repeat,
    }


def test_phase66_real_clear_geometry_reaches_complete_module_iv(
    integration_results,
):
    data = integration_results

    effective = (
        _effective_by_source_region(
            data[
                "clear_map"
            ],
            data[
                "clear_local"
            ],
        )
    )

    assert set(
        effective
    ) == {
        region[
            "region_id"
        ]
        for region
        in data[
            "topology"
        ][
            "physical_regions"
        ]
    }

    assert all(
        irradiance
        == pytest.approx(
            1000.0,
            abs=1e-9,
        )
        for irradiance
        in effective.values()
    )

    curve = data[
        "clear_result"
    ].curve

    state = data[
        "clear_result"
    ].state

    assert curve[
        "curve_scope"
    ] == "module"

    assert curve[
        "source_module_instance_id"
    ] == "phase66-module-instance"

    assert curve[
        "voc_v"
    ] > 0.0

    assert curve[
        "isc_a"
    ] > 0.0

    assert curve[
        "global_mpp"
    ][
        "power_w"
    ] > 0.0

    # Uniform clear fixture should not require
    # any substring bypass within the represented
    # positive-power module-IV domain.
    assert not any(
        substring[
            "bypass_active"
        ]
        for sample
        in state[
            "current_samples"
        ]
        for substring
        in sample[
            "substrings"
        ]
    )

    assert all(
        [
            substring[
                "series_order"
            ]
            for substring
            in sample[
                "substrings"
            ]
        ]
        == [0, 1, 2]
        for sample
        in state[
            "current_samples"
        ]
    )

    _validate_schema(
        "electrical-iv-curve.schema.json",
        curve,
    )

    _validate_schema(
        "module-nonuniform-iv-state.schema.json",
        state,
    )


def test_phase66_real_shading_changes_module_iv_and_activates_bypass(
    integration_results,
):
    data = integration_results

    effective = (
        _effective_by_source_region(
            data[
                "shaded_map"
            ],
            data[
                "shaded_local"
            ],
        )
    )

    # Geometry authority decides where s1-r1 is.
    # The test never reproduces the UV transform.
    assert effective[
        "s1-r1"
    ] == pytest.approx(
        0.0,
        abs=1e-9,
    )

    assert effective[
        "s1-r0"
    ] == pytest.approx(
        1000.0,
        abs=1e-9,
    )

    clear_curve = (
        data[
            "clear_result"
        ].curve
    )

    shaded_curve = (
        data[
            "shaded_result"
        ].curve
    )

    assert (
        clear_curve[
            "physical_result_sha256"
        ]
        != shaded_curve[
            "physical_result_sha256"
        ]
    )

    assert (
        clear_curve[
            "scientific_input_sha256"
        ]
        != shaded_curve[
            "scientific_input_sha256"
        ]
    )

    assert (
        shaded_curve[
            "global_mpp"
        ][
            "power_w"
        ]
        < clear_curve[
            "global_mpp"
        ][
            "power_w"
        ]
    )

    bypass_states = []

    for sample in data[
        "shaded_result"
    ].state[
        "current_samples"
    ]:
        by_id = {
            substring[
                "substring_id"
            ]:
            substring
            for substring
            in sample[
                "substrings"
            ]
        }

        if by_id[
            "s1"
        ][
            "bypass_active"
        ]:
            bypass_states.append(
                by_id
            )

    assert bypass_states

    # At least one operating state must show the
    # shaded protected substring bypassed while
    # the two unaffected series substrings still
    # contribute positive terminal voltage.
    assert any(
        state[
            "s0"
        ][
            "terminal_voltage_v"
        ] > 0.0
        and state[
            "s2"
        ][
            "terminal_voltage_v"
        ] > 0.0
        for state
        in bypass_states
    )

    _validate_schema(
        "electrical-iv-curve.schema.json",
        shaded_curve,
    )

    _validate_schema(
        "module-nonuniform-iv-state.schema.json",
        data[
            "shaded_result"
        ].state,
    )


def test_phase66_real_geometry_to_module_iv_is_deterministic(
    integration_results,
):
    first = integration_results[
        "shaded_result"
    ]

    second = integration_results[
        "shaded_repeat"
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
