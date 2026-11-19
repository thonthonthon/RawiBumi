"""Phase-6.8B explicit MPPT tracker operating-point selection."""

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
)


IDEAL_GLOBAL_MPPT_MODEL_ID = (
    "rawibumi.mppt.ideal_global_mpp.v0.1"
)

IDEAL_GLOBAL_MPPT_MODEL_VERSION = "0.1"

MPPT_CONSTRAINT_ENFORCEMENT_POLICY = (
    "flag_only_no_clipping_phase68"
)

MPPT_POWER_LIMIT_STATUS = (
    "not_available_in_current_mppt_template_contract"
)


class MPPTTrackerOperatingError(ValueError):
    """Raised when MPPT operating-point selection cannot be resolved safely."""


@dataclass(frozen=True)
class MPPTTrackerOperatingResult:
    state: dict[str, Any]


def _canonical_sha256(
    value: Any,
) -> str:
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode(
        "utf-8"
    )

    return hashlib.sha256(
        encoded
    ).hexdigest()


def _finite(
    value: Any,
    *,
    label: str,
) -> float:
    try:
        number = float(
            value
        )
    except (
        TypeError,
        ValueError,
    ) as exc:
        raise MPPTTrackerOperatingError(
            f"{label} must be finite"
        ) from exc

    if not math.isfinite(
        number
    ):
        raise MPPTTrackerOperatingError(
            f"{label} must be finite"
        )

    return number


def _sha256(
    value: Any,
    *,
    label: str,
) -> str:
    text = str(
        value or ""
    )

    if (
        len(text) != 64
        or any(
            character
            not in "0123456789abcdef"
            for character in text
        )
    ):
        raise MPPTTrackerOperatingError(
            f"{label} must be a lowercase SHA-256"
        )

    return text


def _point(
    value: Mapping[str, Any],
    *,
    label: str,
) -> dict[str, float]:
    if not isinstance(
        value,
        Mapping,
    ):
        raise MPPTTrackerOperatingError(
            f"{label} must be an object"
        )

    voltage = _finite(
        value.get(
            "voltage_v"
        ),
        label=(
            f"{label}.voltage_v"
        ),
    )

    current = _finite(
        value.get(
            "current_a"
        ),
        label=(
            f"{label}.current_a"
        ),
    )

    power = _finite(
        value.get(
            "power_w"
        ),
        label=(
            f"{label}.power_w"
        ),
    )

    if (
        voltage < 0
        or current < 0
        or power < 0
    ):
        raise MPPTTrackerOperatingError(
            f"{label} must use non-negative "
            "PV delivery values"
        )

    expected_power = (
        voltage * current
    )

    tolerance = max(
        1e-9,
        1e-9
        * max(
            abs(
                expected_power
            ),
            abs(
                power
            ),
            1.0,
        ),
    )

    if (
        abs(
            power
            - expected_power
        )
        > tolerance
    ):
        raise MPPTTrackerOperatingError(
            f"{label}.power_w must equal "
            "voltage_v * current_a"
        )

    return {
        "voltage_v": float(
            voltage
        ),
        "current_a": float(
            current
        ),
        "power_w": float(
            power
        ),
    }


def _constraints(
    mppt_template: Mapping[str, Any],
) -> dict[str, Any]:
    if not isinstance(
        mppt_template,
        Mapping,
    ):
        raise MPPTTrackerOperatingError(
            "mppt_template must be an object"
        )

    minimum = _finite(
        mppt_template.get(
            "min_operating_voltage_v"
        ),
        label=(
            "mppt_template."
            "min_operating_voltage_v"
        ),
    )

    maximum = _finite(
        mppt_template.get(
            "max_operating_voltage_v"
        ),
        label=(
            "mppt_template."
            "max_operating_voltage_v"
        ),
    )

    if minimum < 0:
        raise MPPTTrackerOperatingError(
            "min_operating_voltage_v "
            "cannot be negative"
        )

    if maximum <= 0:
        raise MPPTTrackerOperatingError(
            "max_operating_voltage_v "
            "must be positive"
        )

    if maximum < minimum:
        raise MPPTTrackerOperatingError(
            "max_operating_voltage_v "
            "must be >= min_operating_voltage_v"
        )

    raw_current = (
        mppt_template.get(
            "max_operating_current_a"
        )
    )

    if raw_current is None:
        max_current = None

    else:
        max_current = _finite(
            raw_current,
            label=(
                "mppt_template."
                "max_operating_current_a"
            ),
        )

        if max_current <= 0:
            raise MPPTTrackerOperatingError(
                "max_operating_current_a "
                "must be positive when known"
            )

    return {
        "min_operating_voltage_v": (
            float(
                minimum
            )
        ),
        "max_operating_voltage_v": (
            float(
                maximum
            )
        ),
        "max_operating_current_a": (
            None
            if max_current is None
            else float(
                max_current
            )
        ),
        "power_limit_contract_status": (
            MPPT_POWER_LIMIT_STATUS
        ),
    }


def select_mppt_operating_point(
    combined_curve: Mapping[str, Any],
    *,
    source_electrical_revision_id: str,
    mppt_operating_point_model_id: str,
    mppt_template: Mapping[str, Any],
) -> MPPTTrackerOperatingResult:
    """Select one explicit tracker operating point.

    Phase 6.8B supports only the explicit ideal-global-MPP model.

    The source physical MPPT-combined curve is never modified.

    MPPT voltage/current constraints are evaluated as flags only in Phase 6.8.
    Clipping/blocking/inverter conversion remains a later integration concern.

    No per-MPPT operating-power limit is invented because the current
    canonical MPPT template contract does not provide one.
    """

    try:
        assert_electrical_iv_curve(
            combined_curve
        )
    except ElectricalShadingContractError as exc:
        raise MPPTTrackerOperatingError(
            f"combined ElectricalIVCurve invalid: {exc}"
        ) from exc

    if (
        combined_curve.get(
            "curve_scope"
        )
        != "mppt_combined"
    ):
        raise MPPTTrackerOperatingError(
            "tracker input requires "
            "curve_scope='mppt_combined'"
        )

    model_id = str(
        mppt_operating_point_model_id
        or ""
    )

    if (
        model_id
        != IDEAL_GLOBAL_MPPT_MODEL_ID
    ):
        raise MPPTTrackerOperatingError(
            "unsupported "
            "mppt_operating_point_model_id: "
            f"{model_id!r}"
        )

    electrical_revision_id = str(
        source_electrical_revision_id
        or ""
    )

    if not electrical_revision_id:
        raise MPPTTrackerOperatingError(
            "source_electrical_revision_id "
            "must be non-empty"
        )

    mppt_id = str(
        combined_curve.get(
            "source_mppt_instance_id"
        )
        or ""
    )

    if not mppt_id:
        raise MPPTTrackerOperatingError(
            "combined curve must identify "
            "source_mppt_instance_id"
        )

    curve_id = str(
        combined_curve.get(
            "curve_id"
        )
        or ""
    )

    if not curve_id:
        raise MPPTTrackerOperatingError(
            "combined curve curve_id "
            "must be non-empty"
        )

    physical_sha = _sha256(
        combined_curve.get(
            "physical_result_sha256"
        ),
        label=(
            "combined_curve."
            "physical_result_sha256"
        ),
    )

    scientific_sha = _sha256(
        combined_curve.get(
            "scientific_input_sha256"
        ),
        label=(
            "combined_curve."
            "scientific_input_sha256"
        ),
    )

    limits = _constraints(
        mppt_template
    )

    ideal = _point(
        combined_curve.get(
            "global_mpp"
        ),
        label=(
            "combined_curve.global_mpp"
        ),
    )

    # The first explicit tracker model is ideal:
    # selected operating point == physical global MPP.
    selected = deepcopy(
        ideal
    )

    voltage = float(
        selected[
            "voltage_v"
        ]
    )

    current = float(
        selected[
            "current_a"
        ]
    )

    below_min = (
        voltage
        < limits[
            "min_operating_voltage_v"
        ]
    )

    above_max = (
        voltage
        > limits[
            "max_operating_voltage_v"
        ]
    )

    within_window = (
        not below_min
        and not above_max
    )

    current_limit = (
        limits[
            "max_operating_current_a"
        ]
    )

    current_limit_known = (
        current_limit
        is not None
    )

    if current_limit_known:
        current_above_limit = (
            current
            > float(
                current_limit
            )
        )
    else:
        current_above_limit = None

    violates_known = (
        below_min
        or above_max
        or (
            current_above_limit
            is True
        )
    )

    constraint_evaluation = {
        "voltage_below_min": bool(
            below_min
        ),
        "voltage_above_max": bool(
            above_max
        ),
        "voltage_within_window": bool(
            within_window
        ),
        "operating_current_limit_known": bool(
            current_limit_known
        ),
        "operating_current_above_limit": (
            current_above_limit
        ),
        "power_limit_evaluated": False,
        "power_limit_status": (
            MPPT_POWER_LIMIT_STATUS
        ),
        "selected_point_violates_known_constraints": bool(
            violates_known
        ),
        "enforcement_policy": (
            MPPT_CONSTRAINT_ENFORCEMENT_POLICY
        ),
    }

    attribution = {
        "status": "modeled",
        "counterfactual_basis": (
            "ideal_global_mpp_to_"
            "selected_tracker_operating_point"
        ),
        # For the explicit ideal-global-MPP model,
        # the tracker contribution itself is zero.
        "delta_power_w": float(
            selected[
                "power_w"
            ]
            - ideal[
                "power_w"
            ]
        ),
    }

    scientific_input = {
        "source_electrical_revision_id": (
            electrical_revision_id
        ),
        "source_mppt_instance_id": (
            mppt_id
        ),
        "source_combined_curve_id": (
            curve_id
        ),
        "source_combined_curve_scientific_input_sha256": (
            scientific_sha
        ),
        "source_combined_curve_physical_result_sha256": (
            physical_sha
        ),
        "mppt_operating_point_model_id": (
            model_id
        ),
        "control_assumption": (
            "ideal_global_mpp"
        ),
        "constraints": (
            limits
        ),
        "constraint_enforcement_policy": (
            MPPT_CONSTRAINT_ENFORCEMENT_POLICY
        ),
    }

    tracker_scientific_sha = (
        _canonical_sha256(
            scientific_input
        )
    )

    state_payload = {
        "source_electrical_revision_id": (
            electrical_revision_id
        ),
        "source_mppt_instance_id": (
            mppt_id
        ),
        "source_combined_curve_id": (
            curve_id
        ),
        "source_combined_curve_physical_result_sha256": (
            physical_sha
        ),
        "mppt_operating_point_model_id": (
            model_id
        ),
        "control_assumption": (
            "ideal_global_mpp"
        ),
        "ideal_global_mpp": (
            ideal
        ),
        "selected_operating_point": (
            selected
        ),
        "constraints": (
            limits
        ),
        "constraint_evaluation": (
            constraint_evaluation
        ),
        "attribution": (
            attribution
        ),
        "scientific_input_sha256": (
            tracker_scientific_sha
        ),
    }

    state_hash = (
        _canonical_sha256(
            state_payload
        )
    )

    state = {
        "schema_name": (
            "MPPTTrackerOperatingState"
        ),
        "schema_version": "0.1",
        "contract_version": "0.1",
        "state_id": (
            "mppt-tracker:"
            f"{mppt_id}:"
            f"{state_hash[:16]}"
        ),
        **state_payload,
        "state_payload_sha256": (
            state_hash
        ),
    }

    return MPPTTrackerOperatingResult(
        state=state
    )
