"""Phase-6.7 adapter from validated Phase-6.6 module physics to series V(I)."""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from typing import Any, Mapping

from .module_iv import (
    MODULE_NONUNIFORM_IV_SOLVER_ID,
    MODULE_NONUNIFORM_IV_SOLVER_VERSION,
    NonuniformModuleIVError,
    _module_current_ceiling,
    _module_state_at_current,
)
from .parameterization import (
    build_pvsyst_region_electrical_states,
)
from .string_iv import (
    SeriesModuleOperatingModel,
)
from .substring_reference import _BranchEndpointHolder


PHASE66_SERIES_MODULE_ADAPTER_ID = (
    "rawibumi.phase67."
    "phase66_series_module_adapter.v0.1"
)

PHASE66_SERIES_MODULE_ADAPTER_VERSION = "0.1"


class Phase66SeriesModuleAdapterError(ValueError):
    """Raised when Phase-6.6 module physics cannot be adapted safely."""


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
            character in "0123456789abcdef"
            for character in text
        )
    ):
        return text

    return _canonical_sha256(
        fallback
    )


def build_phase66_series_module_operating_model(
    topology_definition: Mapping[str, Any],
    electrical_region_map: Mapping[str, Any],
    local_irradiance_state: Mapping[str, Any],
    parameterization_definition: Mapping[str, Any],
    parameterization_evidence: Mapping[str, Any],
    *,
    region_solver: str = "lambertw",
    authorization_witness=None,
    lifecycle_sink=None,
) -> SeriesModuleOperatingModel:
    """Expose validated Phase-6.6 protected-module physics as V(I).

    The standalone Phase-6.6 ElectricalIVCurve ends at its own module Isc
    and represents that endpoint as zero terminal voltage.

    A module inside a mismatched series string may instead operate beyond
    that standalone Isc. Therefore this adapter evaluates the underlying
    Phase-6.6 protected-substring physics directly and preserves negative
    module terminal voltage.

    No execution beyond the validated regional current domains is allowed.
    """

    if lifecycle_sink is not None:
        from .branch_memo_lifecycle import validate_lifecycle_sink
        validate_lifecycle_sink(lifecycle_sink)

    topology = deepcopy(
        topology_definition
    )

    region_map = deepcopy(
        electrical_region_map
    )

    local_state = deepcopy(
        local_irradiance_state
    )

    parameterization = deepcopy(
        parameterization_definition
    )

    evidence = deepcopy(
        parameterization_evidence
    )

    from engine.simulation.detailed_inputs import SnapshotWitnessError
    from shading.electrical.contract import NumericalAssumptionInputError

    try:
        region_states = (
            build_pvsyst_region_electrical_states(
                topology,
                region_map,
                local_state,
                parameterization,
                evidence,
                solver=region_solver,
                authorization_witness=authorization_witness,
            )
        )
    except (NumericalAssumptionInputError, SnapshotWitnessError):
        raise
    except ValueError as exc:
        raise Phase66SeriesModuleAdapterError(
            str(exc)
        ) from exc

    if lifecycle_sink is not None:
        return _build_series_model_from_checked_states(
            topology, region_map, local_state, parameterization, evidence,
            region_states, region_solver=region_solver, lifecycle_sink=lifecycle_sink,
        )

    return _build_series_model_from_checked_states(
        topology, region_map, local_state, parameterization, evidence,
        region_states, region_solver=region_solver,
    )


def _build_series_model_from_checked_states(
    topology, region_map, local_state, parameterization, evidence, region_states,
    *, region_solver="lambertw", lifecycle_sink=None,
) -> SeriesModuleOperatingModel:
    """Shared production V(I) assembly, with no execution authorization result."""
    if lifecycle_sink is not None:
        from .branch_memo_lifecycle import validate_lifecycle_sink
        validate_lifecycle_sink(lifecycle_sink)

    module_instance_id = str(
        region_map.get(
            "source_module_instance_id"
        )
        or ""
    )

    if not module_instance_id:
        raise Phase66SeriesModuleAdapterError(
            "electrical region map must identify "
            "source_module_instance_id"
        )

    try:
        current_ceiling = float(
            _module_current_ceiling(
                topology,
                region_states,
            )
        )
    except (
        NonuniformModuleIVError,
        ValueError,
        TypeError,
    ) as exc:
        raise Phase66SeriesModuleAdapterError(
            "unable to resolve supported "
            f"module current domain: {exc}"
        ) from exc

    if current_ceiling <= 0:
        raise Phase66SeriesModuleAdapterError(
            "supported module current domain "
            "must be positive"
        )

    map_hash = _valid_sha_or_hash(
        region_map.get(
            "mapping_payload_sha256"
        ),
        region_map,
    )

    local_hash = _valid_sha_or_hash(
        local_state.get(
            "state_payload_sha256"
        ),
        local_state,
    )

    parameter_hash = _valid_sha_or_hash(
        parameterization.get(
            "parameterization_payload_sha256"
        ),
        parameterization,
    )

    topology_hash = _canonical_sha256(
        topology
    )

    evidence_hash = _canonical_sha256(
        evidence
    )

    scientific_input = {
        "adapter_id": (
            PHASE66_SERIES_MODULE_ADAPTER_ID
        ),
        "adapter_version": (
            PHASE66_SERIES_MODULE_ADAPTER_VERSION
        ),
        "source_phase66_module_solver_id": (
            MODULE_NONUNIFORM_IV_SOLVER_ID
        ),
        "source_phase66_module_solver_version": (
            MODULE_NONUNIFORM_IV_SOLVER_VERSION
        ),
        "source_module_instance_id": (
            module_instance_id
        ),
        "source_module_topology_revision_id": str(
            topology.get(
                "revision_id"
            )
            or ""
        ),
        "source_module_topology_sha256": (
            topology_hash
        ),
        "source_electrical_region_map_sha256": (
            map_hash
        ),
        "source_local_irradiance_state_sha256": (
            local_hash
        ),
        "parameterization_id": str(
            parameterization.get(
                "parameterization_id"
            )
            or ""
        ),
        "parameterization_payload_sha256": (
            parameter_hash
        ),
        "parameterization_evidence_sha256": (
            evidence_hash
        ),
        "region_model_id": str(
            parameterization.get(
                "model_id"
            )
            or ""
        ),
        "region_model_version": str(
            parameterization.get(
                "model_version"
            )
            or ""
        ),
        "region_solver": (
            region_solver
        ),
        "current_domain_ceiling_a": (
            current_ceiling
        ),
        "series_operation_semantics": (
            "raw_phase66_module_voltage_at_common_series_current_"
            "negative_module_voltage_preserved"
        ),
    }

    scientific_input_sha = (
        _canonical_sha256(
            scientific_input
        )
    )

    branch_reuse = _BranchEndpointHolder(
        [branch for substring in topology["electrical_substrings"] for branch in substring["parallel_branches"]],
        region_states,
    )
    if lifecycle_sink is not None:
        lifecycle_token = lifecycle_sink.holder_created(
            factory_role="normal", slot_count=len(branch_reuse._slots),
        )

    def voltage_at_current(
        current_a: float,
    ) -> Mapping[str, Any]:
        try:
            (
                terminal_voltage,
                substring_states,
            ) = _module_state_at_current(
                topology,
                region_states,
                float(
                    current_a
                ),
                _reuse=branch_reuse,
            )
        except (
            NonuniformModuleIVError,
            ValueError,
        ) as exc:
            raise Phase66SeriesModuleAdapterError(
                f"module {module_instance_id} "
                f"failed at {current_a} A: {exc}"
            ) from exc

        return {
            "terminal_voltage_v": float(
                terminal_voltage
            ),
            "protected_substrings": [
                {
                    "substring_id": str(
                        substring[
                            "substring_id"
                        ]
                    ),
                    "terminal_voltage_v": float(
                        substring[
                            "terminal_voltage_v"
                        ]
                    ),
                    "bypass_active": bool(
                        substring[
                            "bypass_active"
                        ]
                    ),
                    "bypass_current_a": float(
                        substring[
                            "bypass_current_a"
                        ]
                    ),
                }
                for substring
                in substring_states
            ],
        }

    model = SeriesModuleOperatingModel(
        module_instance_id=(
            module_instance_id
        ),
        current_domain_ceiling_a=(
            current_ceiling
        ),
        scientific_input_sha256=(
            scientific_input_sha
        ),
        model_id=(
            PHASE66_SERIES_MODULE_ADAPTER_ID
        ),
        model_version=(
            PHASE66_SERIES_MODULE_ADAPTER_VERSION
        ),
        voltage_at_current=(
            voltage_at_current
        ),
    )
    if lifecycle_sink is not None:
        lifecycle_sink.owner_returned(*lifecycle_token)
    return model
