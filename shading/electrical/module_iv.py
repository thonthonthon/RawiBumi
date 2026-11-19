"""Phase-6.6 nonuniform module IV assembly."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import hashlib
import json
import math
from typing import Any, Mapping

from .contract import (
    ElectricalShadingContractError,
    assert_electrical_iv_curve,
    assert_module_topology_definition,
)

from .parameterization import (
    PVSystRegionElectricalState,
    build_pvsyst_region_electrical_states,
)

from .substring_reference import (
    PHASE65_REFERENCE_SOLVER_ID,
    SubstringReferenceError,
    evaluate_protected_substring_at_current,
)


MODULE_NONUNIFORM_IV_SOLVER_ID = (
    "rawibumi.phase66.nonuniform_module_iv.v0.1"
)

MODULE_NONUNIFORM_IV_SOLVER_VERSION = "0.1"


class NonuniformModuleIVError(ValueError):
    """Raised when detailed module IV assembly cannot be solved safely."""


@dataclass(frozen=True)
class NonuniformModuleIVResult:
    curve: dict[str, Any]
    state: dict[str, Any]


def _canonical_sha256(value: Any) -> str:
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")

    return hashlib.sha256(
        encoded
    ).hexdigest()


def _valid_sha_or_hash(
    value: Any,
    fallback: Any,
) -> str:
    text = str(
        value or ""
    )

    if (
        len(text) == 64
        and all(
            ch in "0123456789abcdef"
            for ch in text
        )
    ):
        return text

    return _canonical_sha256(
        fallback
    )


def _ordered_substrings(
    topology: Mapping[str, Any],
) -> list[Mapping[str, Any]]:
    return sorted(
        topology.get(
            "electrical_substrings"
        )
        or [],
        key=lambda item: int(
            item["series_order"]
        ),
    )


def _module_current_ceiling(
    topology: Mapping[str, Any],
    region_states: Mapping[
        str,
        PVSystRegionElectricalState,
    ],
) -> float:
    substring_capacities = []

    for substring in _ordered_substrings(
        topology
    ):
        branch_capacities = []

        for branch in substring[
            "parallel_branches"
        ]:
            region_ids = branch[
                "series_region_ids"
            ]

            branch_capacities.append(
                min(
                    region_states[
                        str(region_id)
                    ].current_ceiling_a
                    for region_id
                    in region_ids
                )
            )

        substring_capacities.append(
            sum(
                branch_capacities
            )
        )

    if not substring_capacities:
        raise NonuniformModuleIVError(
            "module topology contains no substrings"
        )

    return float(
        min(
            substring_capacities
        )
    )


def _module_state_at_current(
    topology: Mapping[str, Any],
    region_states: Mapping[
        str,
        PVSystRegionElectricalState,
    ],
    current_a: float,
    *,
    _reuse=None,
) -> tuple[
    float,
    list[dict[str, Any]],
]:
    substring_states = []
    module_voltage = 0.0

    for substring in _ordered_substrings(
        topology
    ):
        substring_id = str(
            substring[
                "substring_id"
            ]
        )

        try:
            solved = (
                evaluate_protected_substring_at_current(
                    topology,
                    substring_id,
                    region_states,
                    current_a=current_a,
                    _reuse=_reuse,
                )
            )
        except (
            SubstringReferenceError,
            ValueError,
        ) as exc:
            raise NonuniformModuleIVError(
                f"substring {substring_id} "
                f"failed at {current_a} A: {exc}"
            ) from exc

        terminal_voltage = float(
            solved[
                "terminal_voltage_v"
            ]
        )

        module_voltage += (
            terminal_voltage
        )

        substring_states.append(
            {
                "substring_id": (
                    substring_id
                ),
                "series_order": int(
                    substring[
                        "series_order"
                    ]
                ),
                "terminal_voltage_v": (
                    terminal_voltage
                ),
                "unbypassed_voltage_v": (
                    None
                    if solved[
                        "unbypassed_voltage_v"
                    ]
                    is None
                    else float(
                        solved[
                            "unbypassed_voltage_v"
                        ]
                    )
                ),
                "unbypassed_solution_available": bool(
                    solved.get(
                        "unbypassed_solution_available",
                        True,
                    )
                ),
                "bypass_device_id": str(
                    solved[
                        "bypass_device_id"
                    ]
                ),
                "bypass_active": bool(
                    solved[
                        "bypass_active"
                    ]
                ),
                "bypass_current_a": float(
                    solved[
                        "bypass_current_a"
                    ]
                ),
                "transition_margin_v": (
                    None
                    if solved[
                        "transition_margin_v"
                    ]
                    is None
                    else float(
                        solved[
                            "transition_margin_v"
                        ]
                    )
                ),
                "terminal_branch_states": [
                    {
                        "branch_id": str(
                            branch[
                                "branch_id"
                            ]
                        ),
                        "current_a": float(
                            branch[
                                "current_a"
                            ]
                        ),
                        "voltage_v": float(
                            branch[
                                "voltage_v"
                            ]
                        ),
                    }
                    for branch
                    in solved[
                        "terminal_branch_states"
                    ]
                ],
            }
        )

    return (
        float(module_voltage),
        substring_states,
    )


def _solve_module_isc(
    topology: Mapping[str, Any],
    region_states: Mapping[
        str,
        PVSystRegionElectricalState,
    ],
    *,
    current_ceiling_a: float,
    voltage_tolerance_v: float,
    current_tolerance_a: float,
    max_iterations: int,
) -> float:
    v_zero, _ = (
        _module_state_at_current(
            topology,
            region_states,
            0.0,
        )
    )

    if v_zero < -voltage_tolerance_v:
        raise NonuniformModuleIVError(
            "module open-circuit voltage "
            "cannot be negative"
        )

    if abs(v_zero) <= voltage_tolerance_v:
        return 0.0

    v_high, _ = (
        _module_state_at_current(
            topology,
            region_states,
            current_ceiling_a,
        )
    )

    if v_high > voltage_tolerance_v:
        raise NonuniformModuleIVError(
            "explicit region current domains are "
            "too short to reach module Isc"
        )

    lo = 0.0
    hi = float(
        current_ceiling_a
    )

    for _ in range(
        max_iterations
    ):
        mid = 0.5 * (
            lo + hi
        )

        voltage, _ = (
            _module_state_at_current(
                topology,
                region_states,
                mid,
            )
        )

        if (
            abs(voltage)
            <= voltage_tolerance_v
            or (
                hi - lo
                <= current_tolerance_a
            )
        ):
            return float(mid)

        if voltage > 0:
            lo = mid
        else:
            hi = mid

    return float(
        0.5 * (
            lo + hi
        )
    )


def _local_mpp_candidates(
    points: list[dict[str, float]],
    global_index: int,
) -> list[dict[str, float]]:
    candidates = []

    for index in range(
        1,
        len(points) - 1,
    ):
        previous_power = (
            points[
                index - 1
            ][
                "power_w"
            ]
        )
        power = (
            points[
                index
            ][
                "power_w"
            ]
        )
        next_power = (
            points[
                index + 1
            ][
                "power_w"
            ]
        )

        if (
            power >= previous_power
            and power >= next_power
            and (
                power > previous_power
                or power > next_power
            )
        ):
            candidates.append(
                {
                    "voltage_v": float(
                        points[
                            index
                        ][
                            "voltage_v"
                        ]
                    ),
                    "current_a": float(
                        points[
                            index
                        ][
                            "current_a"
                        ]
                    ),
                    "power_w": float(
                        power
                    ),
                }
            )

    global_point = {
        "voltage_v": float(
            points[
                global_index
            ][
                "voltage_v"
            ]
        ),
        "current_a": float(
            points[
                global_index
            ][
                "current_a"
            ]
        ),
        "power_w": float(
            points[
                global_index
            ][
                "power_w"
            ]
        ),
    }

    if not any(
        abs(
            candidate[
                "voltage_v"
            ]
            - global_point[
                "voltage_v"
            ]
        ) <= 1e-12
        and abs(
            candidate[
                "power_w"
            ]
            - global_point[
                "power_w"
            ]
        ) <= 1e-12
        for candidate
        in candidates
    ):
        candidates.append(
            global_point
        )

    candidates.sort(
        key=lambda item: (
            item[
                "voltage_v"
            ],
            item[
                "current_a"
            ],
        )
    )

    return candidates


def assemble_nonuniform_module_iv(
    topology_definition: Mapping[str, Any],
    electrical_region_map: Mapping[str, Any],
    local_irradiance_state: Mapping[str, Any],
    parameterization_definition: Mapping[str, Any],
    parameterization_evidence: Mapping[str, Any],
    *,
    sample_count: int = 401,
    region_solver: str = "lambertw",
    voltage_tolerance_v: float = 1e-9,
    current_tolerance_a: float = 1e-9,
    max_iterations: int = 200,
    authorization_witness=None,
) -> NonuniformModuleIVResult:
    """Assemble complete module IV from explicit regional physics."""

    from engine.simulation.detailed_inputs import SnapshotWitnessError
    from shading.electrical.contract import NumericalAssumptionInputError

    try:
        assert_module_topology_definition(
            topology_definition
        )
    except ElectricalShadingContractError as exc:
        raise NonuniformModuleIVError(
            str(exc)
        ) from exc

    if (
        isinstance(sample_count, bool)
        or not isinstance(
            sample_count,
            int,
        )
        or sample_count < 25
    ):
        raise NonuniformModuleIVError(
            "sample_count must be an integer >= 25"
        )

    if voltage_tolerance_v <= 0:
        raise NonuniformModuleIVError(
            "voltage_tolerance_v must be positive"
        )

    if current_tolerance_a <= 0:
        raise NonuniformModuleIVError(
            "current_tolerance_a must be positive"
        )

    if max_iterations < 1:
        raise NonuniformModuleIVError(
            "max_iterations must be >= 1"
        )

    try:
        region_states = (
            build_pvsyst_region_electrical_states(
                topology_definition,
                electrical_region_map,
                local_irradiance_state,
                parameterization_definition,
                parameterization_evidence,
                solver=region_solver,
                authorization_witness=authorization_witness,
            )
        )
    except (NumericalAssumptionInputError, SnapshotWitnessError):
        raise
    except ValueError as exc:
        raise NonuniformModuleIVError(
            str(exc)
        ) from exc

    current_ceiling = (
        _module_current_ceiling(
            topology_definition,
            region_states,
        )
    )

    isc = _solve_module_isc(
        topology_definition,
        region_states,
        current_ceiling_a=(
            current_ceiling
        ),
        voltage_tolerance_v=(
            voltage_tolerance_v
        ),
        current_tolerance_a=(
            current_tolerance_a
        ),
        max_iterations=max_iterations,
    )

    voc, _ = (
        _module_state_at_current(
            topology_definition,
            region_states,
            0.0,
        )
    )

    if voc < -voltage_tolerance_v:
        raise NonuniformModuleIVError(
            "module Voc is negative"
        )

    if (
        voc <= voltage_tolerance_v
        and isc <= current_tolerance_a
    ):
        raise NonuniformModuleIVError(
            "zero-generation module IV requires "
            "a dedicated dark-state representation"
        )

    current_samples = []

    for index in range(
        sample_count
    ):
        fraction = (
            index
            / (
                sample_count - 1
            )
        )

        current = (
            isc * fraction
        )

        voltage, substrings = (
            _module_state_at_current(
                topology_definition,
                region_states,
                current,
            )
        )

        if index == sample_count - 1:
            voltage = 0.0

        elif (
            voltage < 0
            and abs(voltage)
            <= 10
            * voltage_tolerance_v
        ):
            voltage = 0.0

        if (
            voltage
            < -10
            * voltage_tolerance_v
        ):
            raise NonuniformModuleIVError(
                "sampled current below Isc "
                "produced negative module voltage"
            )

        voltage = max(
            0.0,
            float(voltage),
        )

        current_samples.append(
            {
                "current_a": float(
                    current
                ),
                "module_voltage_v": (
                    voltage
                ),
                "module_power_w": float(
                    voltage
                    * current
                ),
                "substrings": substrings,
            }
        )

    points = [
        {
            "voltage_v": float(
                item[
                    "module_voltage_v"
                ]
            ),
            "current_a": float(
                item[
                    "current_a"
                ]
            ),
            "power_w": float(
                item[
                    "module_power_w"
                ]
            ),
        }
        for item
        in reversed(
            current_samples
        )
    ]

    points.sort(
        key=lambda item: (
            item[
                "voltage_v"
            ],
            -item[
                "current_a"
            ],
        )
    )

    global_index = max(
        range(
            len(points)
        ),
        key=lambda index: (
            points[
                index
            ][
                "power_w"
            ]
        ),
    )

    global_mpp = {
        "voltage_v": float(
            points[
                global_index
            ][
                "voltage_v"
            ]
        ),
        "current_a": float(
            points[
                global_index
            ][
                "current_a"
            ]
        ),
        "power_w": float(
            points[
                global_index
            ][
                "power_w"
            ]
        ),
    }

    local_candidates = (
        _local_mpp_candidates(
            points,
            global_index,
        )
    )

    local_state_hash = (
        _valid_sha_or_hash(
            local_irradiance_state.get(
                "state_payload_sha256"
            ),
            local_irradiance_state,
        )
    )

    map_hash = str(
        electrical_region_map[
            "mapping_payload_sha256"
        ]
    )

    parameter_hash = str(
        parameterization_definition[
            "parameterization_payload_sha256"
        ]
    )

    bypass_model_ids = sorted({
        str(
            device[
                "forward_voltage_model"
            ][
                "model_id"
            ]
        )
        for device
        in topology_definition.get(
            "bypass_devices"
        )
        or []
        if isinstance(
            device.get(
                "forward_voltage_model"
            ),
            Mapping,
        )
    })

    scientific_input = {
        "source_module_instance_id": str(
            electrical_region_map[
                "source_module_instance_id"
            ]
        ),
        "source_module_topology_revision_id": str(
            topology_definition[
                "revision_id"
            ]
        ),
        "source_electrical_region_map_hash": (
            map_hash
        ),
        "source_local_irradiance_state_hash": (
            local_state_hash
        ),
        "parameterization_id": str(
            parameterization_definition[
                "parameterization_id"
            ]
        ),
        "parameterization_payload_sha256": (
            parameter_hash
        ),
        "parameterization_evidence_id": str(
            parameterization_evidence[
                "evidence_id"
            ]
        ),
        "region_model_id": str(
            parameterization_definition[
                "model_id"
            ]
        ),
        "region_model_version": str(
            parameterization_definition[
                "model_version"
            ]
        ),
        "bypass_model_ids": (
            bypass_model_ids
        ),
        "thermal_state_scope": (
            "single_module_temperature"
        ),
        "module_temperature_c": (
            local_irradiance_state[
                "module_temperature_c"
            ]
        ),
    }

    scientific_input_sha = (
        _canonical_sha256(
            scientific_input
        )
    )

    physical_payload = {
        "isc_a": float(
            isc
        ),
        "voc_v": float(
            voc
        ),
        "points": points,
        "global_mpp": (
            global_mpp
        ),
        "local_mpp_candidates": (
            local_candidates
        ),
    }

    physical_hash = (
        _canonical_sha256(
            physical_payload
        )
    )

    execution_payload = {
        "solver_id": (
            MODULE_NONUNIFORM_IV_SOLVER_ID
        ),
        "solver_version": (
            MODULE_NONUNIFORM_IV_SOLVER_VERSION
        ),
        "substring_solver_id": (
            PHASE65_REFERENCE_SOLVER_ID
        ),
        "region_solver": (
            region_solver
        ),
        "sample_count": (
            sample_count
        ),
        "voltage_tolerance_v": (
            voltage_tolerance_v
        ),
        "current_tolerance_a": (
            current_tolerance_a
        ),
        "max_iterations": (
            max_iterations
        ),
    }

    execution_hash = (
        _canonical_sha256(
            execution_payload
        )
    )

    curve_id = (
        "iv:module:"
        + physical_hash[:20]
    )

    curve = {
        "schema_name": (
            "ElectricalIVCurve"
        ),
        "schema_version": "0.1",
        "contract_version": "0.1",
        "curve_id": curve_id,
        "curve_scope": "module",
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
        "source_module_instance_id": str(
            electrical_region_map[
                "source_module_instance_id"
            ]
        ),
        "points": points,
        "isc_a": float(
            isc
        ),
        "voc_v": float(
            voc
        ),
        "mpp_semantics": {
            "declaration_authority": (
                "solver_declared"
            ),
            "sample_verification_scope": (
                "represented_samples_only"
            ),
            "voltage_tolerance_v": float(
                max(
                    voltage_tolerance_v,
                    1e-8,
                )
            ),
            "power_tolerance_w": 1e-8,
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
        "local_mpp_candidates": (
            local_candidates
        ),
        "scientific_model_manifest": {
            "model_id": (
                MODULE_NONUNIFORM_IV_SOLVER_ID
            ),
            "model_version": (
                MODULE_NONUNIFORM_IV_SOLVER_VERSION
            ),
            "parameterization_id": str(
                parameterization_definition[
                    "parameterization_id"
                ]
            ),
            "topology_revision_id": str(
                topology_definition[
                    "revision_id"
                ]
            ),
            "bypass_model_ids": (
                bypass_model_ids
            ),
            "region_model_id": str(
                parameterization_definition[
                    "model_id"
                ]
            ),
            "region_model_version": str(
                parameterization_definition[
                    "model_version"
                ]
            ),
            "notes": (
                "Explicit regional PVsyst SDM "
                "plus explicit limited reverse "
                "model; no module-SDM splitting."
            ),
        },
        "execution_manifest": {
            "solver_id": (
                MODULE_NONUNIFORM_IV_SOLVER_ID
            ),
            "solver_version": (
                MODULE_NONUNIFORM_IV_SOLVER_VERSION
            ),
            "voltage_grid_strategy": (
                "current_domain_sampling_"
                "then_ascending_voltage_projection"
            ),
            "point_count": (
                len(points)
            ),
            "cache_mode": "none",
            "parallelization": "none",
            "substring_solver_id": (
                PHASE65_REFERENCE_SOLVER_ID
            ),
            "region_solver": (
                region_solver
            ),
        },
        "scientific_input_sha256": (
            scientific_input_sha
        ),
        "physical_result_sha256": (
            physical_hash
        ),
        "execution_payload_sha256": (
            execution_hash
        ),
        "quality_flags": [
            "sampled_mpp_only",
            "explicit_region_parameterization",
            "limited_linear_reverse_bias_model"
        ],
    }

    try:
        assert_electrical_iv_curve(
            curve
        )
    except ElectricalShadingContractError as exc:
        raise NonuniformModuleIVError(
            "assembled ElectricalIVCurve "
            f"violates canonical contract: {exc}"
        ) from exc

    state_payload = {
        "source_module_instance_id": str(
            electrical_region_map[
                "source_module_instance_id"
            ]
        ),
        "source_module_topology_revision_id": str(
            topology_definition[
                "revision_id"
            ]
        ),
        "source_electrical_region_map_id": str(
            electrical_region_map[
                "electrical_region_map_id"
            ]
        ),
        "source_electrical_region_map_hash": (
            map_hash
        ),
        "source_local_irradiance_state_id": str(
            local_irradiance_state[
                "state_id"
            ]
        ),
        "source_local_irradiance_state_hash": (
            local_state_hash
        ),
        "parameterization_id": str(
            parameterization_definition[
                "parameterization_id"
            ]
        ),
        "parameterization_payload_sha256": (
            parameter_hash
        ),
        "module_curve_id": (
            curve_id
        ),
        "isc_a": float(
            isc
        ),
        "voc_v": float(
            voc
        ),
        "current_samples": (
            current_samples
        ),
        "scientific_input_sha256": (
            scientific_input_sha
        ),
    }

    state_hash = (
        _canonical_sha256(
            state_payload
        )
    )

    state = {
        "schema_name": (
            "ModuleNonuniformIVState"
        ),
        "schema_version": "0.1",
        "contract_version": "0.1",
        "state_id": (
            "module-nonuniform-iv:"
            + state_hash[:20]
        ),
        **deepcopy(
            state_payload
        ),
        "state_payload_sha256": (
            state_hash
        ),
    }

    return NonuniformModuleIVResult(
        curve=curve,
        state=state,
    )
