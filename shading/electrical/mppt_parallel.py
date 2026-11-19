"""Phase-6.8A physical parallel-string I-V aggregation.

This module is deliberately separate from the legacy electrical.mppt
shortcut.

Scientific boundary
-------------------
The source object is a Phase-6 ElectricalIVCurve representing PV delivery
current on a non-negative voltage grid.

Between represented source points this solver uses explicit piecewise-linear
I(V) interpolation.

For V above a source string's represented Voc, that source contributes zero
delivery current. This does NOT claim blocking-diode behavior and does NOT
model inter-string reverse/backfeed current. Reverse-current interaction is
outside the current Phase-6 electrical model and is never fabricated.

At every represented MPPT voltage:

    I_mppt(V) = sum(I_string_k(V))

Power is:

    P_mppt(V) = V * I_mppt(V)

The physical combined curve is independent of tracker/control selection.
"""

from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass
import hashlib
import json
import math
from typing import Any, Mapping

from .contract import (
    ElectricalShadingContractError,
    assert_electrical_iv_curve,
)


PARALLEL_STRING_IV_SOLVER_ID = (
    "rawibumi.phase68."
    "parallel_string_iv.v0.1"
)

PARALLEL_STRING_IV_SOLVER_VERSION = "0.1"

PARALLEL_RULE = (
    "common_voltage_sum_delivery_currents"
)

SOURCE_CURVE_INTERPOLATION = (
    "piecewise_linear_current_"
    "on_represented_voltage_grid"
)

REVERSE_INTERSTRING_CURRENT_POLICY = (
    "not_modeled_pv_delivery_branch_only_"
    "zero_contribution_above_source_voc"
)

VOLTAGE_GRID_STRATEGY = (
    "union_source_voltage_knots_plus_"
    "exact_interval_power_vertices"
)


class ParallelStringIVError(ValueError):
    """Raised when parallel string I-V cannot be assembled safely."""


@dataclass(frozen=True)
class ParallelStringIVResult:
    curve: dict[str, Any]
    state: dict[str, Any]


@dataclass(frozen=True)
class _NormalizedStringCurve:
    string_id: str
    curve_id: str
    scientific_input_sha256: str
    physical_result_sha256: str
    isc_a: float
    voc_v: float
    voltages_v: tuple[float, ...]
    currents_a: tuple[float, ...]


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
        raise ParallelStringIVError(
            f"{label} must be finite"
        ) from exc

    if not math.isfinite(
        number
    ):
        raise ParallelStringIVError(
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
            char not in (
                "0123456789abcdef"
            )
            for char
            in text
        )
    ):
        raise ParallelStringIVError(
            f"{label} must be "
            "a lowercase SHA-256"
        )

    return text


def _normalize_mppt_instance(
    mppt_instance: Mapping[str, Any],
) -> tuple[
    str,
    str,
    int,
    tuple[str, ...],
]:
    mppt_id = str(
        mppt_instance.get(
            "mppt_instance_id"
        )
        or ""
    )

    if not mppt_id:
        raise ParallelStringIVError(
            "MPPTInstance.mppt_instance_id "
            "must be non-empty"
        )

    inverter_id = str(
        mppt_instance.get(
            "inverter_instance_id"
        )
        or ""
    )

    if not inverter_id:
        raise ParallelStringIVError(
            "MPPTInstance.inverter_instance_id "
            "must be non-empty"
        )

    raw_index = mppt_instance.get(
        "index"
    )

    if (
        isinstance(
            raw_index,
            bool,
        )
        or not isinstance(
            raw_index,
            int,
        )
        or raw_index < 0
    ):
        raise ParallelStringIVError(
            "MPPTInstance.index must be "
            "an integer >= 0"
        )

    if (
        mppt_instance.get(
            "enabled"
        )
        is not True
    ):
        raise ParallelStringIVError(
            "Phase-6.8 parallel solver "
            "requires an enabled MPPTInstance"
        )

    raw_ids = (
        mppt_instance.get(
            "connected_string_ids"
        )
        or []
    )

    if not isinstance(
        raw_ids,
        (list, tuple),
    ):
        raise ParallelStringIVError(
            "MPPTInstance.connected_string_ids "
            "must be an array"
        )

    ids = tuple(
        str(value)
        for value
        in raw_ids
    )

    if (
        not ids
        or any(
            not value
            for value
            in ids
        )
    ):
        raise ParallelStringIVError(
            "MPPTInstance.connected_string_ids "
            "must contain non-empty IDs"
        )

    if len(ids) != len(
        set(ids)
    ):
        raise ParallelStringIVError(
            "MPPTInstance.connected_string_ids "
            "must be unique"
        )

    # Parallel electrical order has no physical
    # meaning. Normalize for scientific identity.
    normalized_ids = tuple(
        sorted(
            ids
        )
    )

    return (
        mppt_id,
        inverter_id,
        raw_index,
        normalized_ids,
    )


def _normalize_string_curve(
    string_id: str,
    curve: Mapping[str, Any],
    *,
    voltage_tolerance_v: float,
    current_tolerance_a: float,
) -> _NormalizedStringCurve:
    try:
        assert_electrical_iv_curve(
            curve
        )
    except ElectricalShadingContractError as exc:
        raise ParallelStringIVError(
            f"string {string_id} "
            f"ElectricalIVCurve invalid: {exc}"
        ) from exc

    if (
        curve.get(
            "curve_scope"
        )
        != "string"
    ):
        raise ParallelStringIVError(
            f"string {string_id} requires "
            "curve_scope='string'"
        )

    source_string_id = str(
        curve.get(
            "source_string_id"
        )
        or ""
    )

    if (
        source_string_id
        != string_id
    ):
        raise ParallelStringIVError(
            f"string curve identity mismatch: "
            f"expected {string_id}, "
            f"got {source_string_id!r}"
        )

    curve_id = str(
        curve.get(
            "curve_id"
        )
        or ""
    )

    if not curve_id:
        raise ParallelStringIVError(
            f"string {string_id} "
            "curve_id must be non-empty"
        )

    scientific_sha = _sha256(
        curve.get(
            "scientific_input_sha256"
        ),
        label=(
            f"{string_id}."
            "scientific_input_sha256"
        ),
    )

    physical_sha = _sha256(
        curve.get(
            "physical_result_sha256"
        ),
        label=(
            f"{string_id}."
            "physical_result_sha256"
        ),
    )

    isc = _finite(
        curve.get(
            "isc_a"
        ),
        label=(
            f"{string_id}.isc_a"
        ),
    )

    voc = _finite(
        curve.get(
            "voc_v"
        ),
        label=(
            f"{string_id}.voc_v"
        ),
    )

    if isc < 0:
        raise ParallelStringIVError(
            f"string {string_id} "
            "Isc cannot be negative"
        )

    if voc <= 0:
        raise ParallelStringIVError(
            f"string {string_id} "
            "Voc must be positive"
        )

    raw_points = curve.get(
        "points"
    )

    if (
        not isinstance(
            raw_points,
            list,
        )
        or len(
            raw_points
        ) < 2
    ):
        raise ParallelStringIVError(
            f"string {string_id} "
            "requires at least two points"
        )

    voltages = []
    currents = []

    previous_voltage = None
    previous_current = None

    for index, point in enumerate(
        raw_points
    ):
        if not isinstance(
            point,
            Mapping,
        ):
            raise ParallelStringIVError(
                f"string {string_id} "
                f"point {index} "
                "must be an object"
            )

        voltage = _finite(
            point.get(
                "voltage_v"
            ),
            label=(
                f"{string_id}."
                f"points[{index}].voltage_v"
            ),
        )

        current = _finite(
            point.get(
                "current_a"
            ),
            label=(
                f"{string_id}."
                f"points[{index}].current_a"
            ),
        )

        if (
            voltage
            < -voltage_tolerance_v
        ):
            raise ParallelStringIVError(
                f"string {string_id} "
                "contains negative terminal voltage; "
                "Phase-6.8A MPPT bus uses the "
                "non-negative voltage delivery branch"
            )

        if (
            current
            < -current_tolerance_a
        ):
            raise ParallelStringIVError(
                f"string {string_id} "
                "contains negative delivery current; "
                "inter-string reverse current is "
                "not modeled in Phase 6.8A"
            )

        if (
            previous_voltage
            is not None
            and voltage
            <= previous_voltage
        ):
            raise ParallelStringIVError(
                f"string {string_id} "
                "voltage grid must be "
                "strictly increasing"
            )

        if (
            previous_current
            is not None
            and current
            > (
                previous_current
                + current_tolerance_a
            )
        ):
            raise ParallelStringIVError(
                f"string {string_id} "
                "delivery current must be "
                "non-increasing with voltage"
            )

        if (
            abs(
                voltage
            )
            <= voltage_tolerance_v
        ):
            voltage = 0.0

        if (
            abs(
                current
            )
            <= current_tolerance_a
        ):
            current = 0.0

        voltages.append(
            float(
                voltage
            )
        )

        currents.append(
            float(
                current
            )
        )

        previous_voltage = (
            voltage
        )

        previous_current = (
            current
        )

    if (
        abs(
            voltages[0]
        )
        > voltage_tolerance_v
    ):
        raise ParallelStringIVError(
            f"string {string_id} "
            "represented delivery curve "
            "must begin at V=0"
        )

    if (
        abs(
            currents[0]
            - isc
        )
        > max(
            current_tolerance_a,
            1e-9
            * max(
                abs(
                    isc
                ),
                1.0,
            ),
        )
    ):
        raise ParallelStringIVError(
            f"string {string_id} "
            "first represented current "
            "must equal Isc"
        )

    if (
        abs(
            voltages[-1]
            - voc
        )
        > max(
            voltage_tolerance_v,
            1e-9
            * max(
                abs(
                    voc
                ),
                1.0,
            ),
        )
    ):
        raise ParallelStringIVError(
            f"string {string_id} "
            "last represented voltage "
            "must equal Voc"
        )

    if (
        abs(
            currents[-1]
        )
        > current_tolerance_a
    ):
        raise ParallelStringIVError(
            f"string {string_id} "
            "represented current at Voc "
            "must be zero"
        )

    return _NormalizedStringCurve(
        string_id=(
            string_id
        ),
        curve_id=(
            curve_id
        ),
        scientific_input_sha256=(
            scientific_sha
        ),
        physical_result_sha256=(
            physical_sha
        ),
        isc_a=float(
            isc
        ),
        voc_v=float(
            voc
        ),
        voltages_v=tuple(
            voltages
        ),
        currents_a=tuple(
            currents
        ),
    )


def _current_at_voltage(
    source: _NormalizedStringCurve,
    voltage_v: float,
    *,
    voltage_tolerance_v: float,
) -> float:
    voltage = _finite(
        voltage_v,
        label="common voltage_v",
    )

    if (
        voltage
        < -voltage_tolerance_v
    ):
        raise ParallelStringIVError(
            "common MPPT voltage "
            "cannot be negative"
        )

    if (
        voltage
        >= (
            source.voc_v
            - voltage_tolerance_v
        )
    ):
        # Explicit Phase-6 delivery-branch policy:
        #
        # no negative/backfeed string current is
        # fabricated above represented Voc.
        return 0.0

    if (
        voltage
        <= voltage_tolerance_v
    ):
        return float(
            source.isc_a
        )

    voltages = (
        source.voltages_v
    )

    index = (
        bisect_right(
            voltages,
            voltage,
        )
        - 1
    )

    if index < 0:
        return float(
            source.isc_a
        )

    if (
        index
        >= len(
            voltages
        )
        - 1
    ):
        return 0.0

    v0 = float(
        voltages[
            index
        ]
    )

    v1 = float(
        voltages[
            index + 1
        ]
    )

    i0 = float(
        source.currents_a[
            index
        ]
    )

    i1 = float(
        source.currents_a[
            index + 1
        ]
    )

    fraction = (
        (
            voltage
            - v0
        )
        / (
            v1
            - v0
        )
    )

    current = (
        i0
        + fraction
        * (
            i1
            - i0
        )
    )

    if (
        current < 0
        and abs(
            current
        )
        <= 1e-10
    ):
        current = 0.0

    if current < 0:
        raise ParallelStringIVError(
            f"piecewise interpolation for "
            f"{source.string_id} produced "
            "negative delivery current"
        )

    return float(
        current
    )


def _combined_state_at_voltage(
    ordered_sources: tuple[
        _NormalizedStringCurve,
        ...
    ],
    voltage_v: float,
    *,
    voltage_tolerance_v: float,
) -> tuple[
    float,
    list[dict[str, Any]],
]:
    voltage = _finite(
        voltage_v,
        label="voltage_v",
    )

    total_current = 0.0
    contributions = []

    for source in ordered_sources:
        current = (
            _current_at_voltage(
                source,
                voltage,
                voltage_tolerance_v=(
                    voltage_tolerance_v
                ),
            )
        )

        power = float(
            voltage
            * current
        )

        total_current += (
            current
        )

        contributions.append(
            {
                "string_id": (
                    source.string_id
                ),
                "current_a": float(
                    current
                ),
                "power_w": (
                    power
                ),
            }
        )

    return (
        float(
            total_current
        ),
        contributions,
    )


def _interval_vertex(
    v0: float,
    v1: float,
    i0: float,
    i1: float,
    *,
    voltage_tolerance_v: float,
) -> float | None:
    width = (
        v1 - v0
    )

    if (
        width
        <= voltage_tolerance_v
    ):
        return None

    slope = (
        (
            i1
            - i0
        )
        / width
    )

    if slope >= 0:
        return None

    intercept = (
        i0
        - slope
        * v0
    )

    vertex = (
        -intercept
        / (
            2.0
            * slope
        )
    )

    if (
        vertex
        <= (
            v0
            + voltage_tolerance_v
        )
        or vertex
        >= (
            v1
            - voltage_tolerance_v
        )
    ):
        return None

    return float(
        vertex
    )


def _local_mpp_candidates(
    points: list[
        dict[str, float]
    ],
    global_index: int,
    *,
    power_tolerance_w: float,
) -> list[
    dict[str, float]
]:
    candidates = []

    for index in range(
        1,
        len(
            points
        )
        - 1,
    ):
        previous_power = float(
            points[
                index - 1
            ][
                "power_w"
            ]
        )

        power = float(
            points[
                index
            ][
                "power_w"
            ]
        )

        next_power = float(
            points[
                index + 1
            ][
                "power_w"
            ]
        )

        if (
            power
            >= (
                previous_power
                - power_tolerance_w
            )
            and power
            >= (
                next_power
                - power_tolerance_w
            )
            and (
                power
                > (
                    previous_power
                    + power_tolerance_w
                )
                or power
                > (
                    next_power
                    + power_tolerance_w
                )
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
                    "power_w": (
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
            item[
                "voltage_v"
            ]
            - global_point[
                "voltage_v"
            ]
        )
        <= 1e-12
        and abs(
            item[
                "power_w"
            ]
            - global_point[
                "power_w"
            ]
        )
        <= power_tolerance_w
        for item
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


def assemble_parallel_mppt_iv(
    mppt_instance: Mapping[str, Any],
    string_curves: Mapping[
        str,
        Mapping[str, Any],
    ],
    *,
    source_electrical_revision_id: str,
    voltage_tolerance_v: float = 1e-9,
    current_tolerance_a: float = 1e-9,
    power_tolerance_w: float = 1e-7,
) -> ParallelStringIVResult:
    """Assemble the physical common-voltage curve of one MPPT.

    This function performs NO tracker/control selection.

    The returned ElectricalIVCurve describes the represented physical
    parallel source under the explicit Phase-6 non-negative PV delivery
    current boundary.
    """

    electrical_revision_id = str(
        source_electrical_revision_id
        or ""
    )

    if not electrical_revision_id:
        raise ParallelStringIVError(
            "source_electrical_revision_id "
            "must be non-empty"
        )

    for value, label in (
        (
            voltage_tolerance_v,
            "voltage_tolerance_v",
        ),
        (
            current_tolerance_a,
            "current_tolerance_a",
        ),
        (
            power_tolerance_w,
            "power_tolerance_w",
        ),
    ):
        numeric = _finite(
            value,
            label=label,
        )

        if numeric < 0:
            raise ParallelStringIVError(
                f"{label} cannot be negative"
            )

    (
        mppt_id,
        inverter_id,
        mppt_index,
        source_string_ids,
    ) = _normalize_mppt_instance(
        mppt_instance
    )

    actual_curve_ids = {
        str(value)
        for value
        in string_curves
    }

    expected_curve_ids = set(
        source_string_ids
    )

    if (
        actual_curve_ids
        != expected_curve_ids
    ):
        missing = sorted(
            expected_curve_ids
            - actual_curve_ids
        )

        extra = sorted(
            actual_curve_ids
            - expected_curve_ids
        )

        raise ParallelStringIVError(
            "string curve coverage must "
            "exactly match MPPT connected strings; "
            f"missing={missing}, extra={extra}"
        )

    ordered_sources = tuple(
        _normalize_string_curve(
            string_id,
            string_curves[
                string_id
            ],
            voltage_tolerance_v=(
                voltage_tolerance_v
            ),
            current_tolerance_a=(
                current_tolerance_a
            ),
        )
        for string_id
        in source_string_ids
    )

    source_metadata = [
        {
            "string_id": (
                source.string_id
            ),
            "curve_id": (
                source.curve_id
            ),
            "scientific_input_sha256": (
                source.scientific_input_sha256
            ),
            "physical_result_sha256": (
                source.physical_result_sha256
            ),
            "isc_a": float(
                source.isc_a
            ),
            "voc_v": float(
                source.voc_v
            ),
        }
        for source
        in ordered_sources
    ]

    # Every original source knot is retained.
    #
    # Therefore each interval between successive
    # common knots has a linear total I(V).
    base_knots = {
        0.0,
    }

    for source in ordered_sources:
        base_knots.update(
            float(value)
            for value
            in source.voltages_v
        )

        base_knots.add(
            float(
                source.voc_v
            )
        )

    combined_voc = max(
        float(
            source.voc_v
        )
        for source
        in ordered_sources
    )

    base_knots.add(
        combined_voc
    )

    base_grid = sorted(
        base_knots
    )

    # Exact maximum of P(V)=V*(a+bV) may
    # occur inside each interval. Add those
    # quadratic vertices explicitly.
    vertices = []

    for index in range(
        len(
            base_grid
        )
        - 1
    ):
        v0 = float(
            base_grid[
                index
            ]
        )

        v1 = float(
            base_grid[
                index + 1
            ]
        )

        i0, _ = (
            _combined_state_at_voltage(
                ordered_sources,
                v0,
                voltage_tolerance_v=(
                    voltage_tolerance_v
                ),
            )
        )

        i1, _ = (
            _combined_state_at_voltage(
                ordered_sources,
                v1,
                voltage_tolerance_v=(
                    voltage_tolerance_v
                ),
            )
        )

        vertex = _interval_vertex(
            v0,
            v1,
            i0,
            i1,
            voltage_tolerance_v=(
                voltage_tolerance_v
            ),
        )

        if vertex is not None:
            vertices.append(
                vertex
            )

    voltage_grid = sorted(
        set(
            base_grid
            + vertices
        )
    )

    voltage_samples = []
    curve_points = []

    previous_voltage = None
    previous_total_current = None

    for voltage in voltage_grid:
        total_current, contributions = (
            _combined_state_at_voltage(
                ordered_sources,
                voltage,
                voltage_tolerance_v=(
                    voltage_tolerance_v
                ),
            )
        )

        if (
            previous_voltage
            is not None
            and voltage
            <= previous_voltage
        ):
            raise ParallelStringIVError(
                "combined voltage grid "
                "must be strictly increasing"
            )

        if (
            previous_total_current
            is not None
            and total_current
            > (
                previous_total_current
                + current_tolerance_a
            )
        ):
            raise ParallelStringIVError(
                "combined parallel delivery "
                "current must be non-increasing "
                "with voltage"
            )

        if (
            abs(
                total_current
            )
            <= current_tolerance_a
        ):
            total_current = 0.0

        power = float(
            voltage
            * total_current
        )

        voltage_samples.append(
            {
                "voltage_v": float(
                    voltage
                ),
                "total_current_a": float(
                    total_current
                ),
                "total_power_w": (
                    power
                ),
                "string_currents": (
                    contributions
                ),
            }
        )

        curve_points.append(
            {
                "voltage_v": float(
                    voltage
                ),
                "current_a": float(
                    total_current
                ),
                "power_w": (
                    power
                ),
            }
        )

        previous_voltage = (
            voltage
        )

        previous_total_current = (
            total_current
        )

    if (
        curve_points[0][
            "voltage_v"
        ]
        != 0.0
    ):
        raise ParallelStringIVError(
            "combined curve must begin at V=0"
        )

    combined_isc = float(
        curve_points[0][
            "current_a"
        ]
    )

    if (
        abs(
            curve_points[-1][
                "voltage_v"
            ]
            - combined_voc
        )
        > voltage_tolerance_v
    ):
        raise ParallelStringIVError(
            "combined curve must end at "
            "maximum represented string Voc"
        )

    if (
        abs(
            curve_points[-1][
                "current_a"
            ]
        )
        > current_tolerance_a
    ):
        raise ParallelStringIVError(
            "combined current at combined Voc "
            "must be zero under the explicit "
            "Phase-6 delivery-current policy"
        )

    global_index = max(
        range(
            len(
                curve_points
            )
        ),
        key=lambda index: (
            curve_points[
                index
            ][
                "power_w"
            ]
        ),
    )

    global_mpp = {
        "voltage_v": float(
            curve_points[
                global_index
            ][
                "voltage_v"
            ]
        ),
        "current_a": float(
            curve_points[
                global_index
            ][
                "current_a"
            ]
        ),
        "power_w": float(
            curve_points[
                global_index
            ][
                "power_w"
            ]
        ),
    }

    local_candidates = (
        _local_mpp_candidates(
            curve_points,
            global_index,
            power_tolerance_w=(
                power_tolerance_w
            ),
        )
    )

    normalized_mppt_topology = {
        "source_electrical_revision_id": (
            electrical_revision_id
        ),
        "mppt_instance_id": (
            mppt_id
        ),
        "inverter_instance_id": (
            inverter_id
        ),
        "mppt_index": (
            mppt_index
        ),
        "connected_string_ids": (
            list(
                source_string_ids
            )
        ),
        "enabled": True,
    }

    scientific_input = {
        "solver_id": (
            PARALLEL_STRING_IV_SOLVER_ID
        ),
        "solver_version": (
            PARALLEL_STRING_IV_SOLVER_VERSION
        ),
        "normalized_mppt_topology": (
            normalized_mppt_topology
        ),
        "source_string_curves": (
            source_metadata
        ),
        "parallel_rule": (
            PARALLEL_RULE
        ),
        "source_curve_interpolation": (
            SOURCE_CURVE_INTERPOLATION
        ),
        "reverse_interstring_current_policy": (
            REVERSE_INTERSTRING_CURRENT_POLICY
        ),
    }

    scientific_input_sha = (
        _canonical_sha256(
            scientific_input
        )
    )

    physical_payload = {
        "source_mppt_instance_id": (
            mppt_id
        ),
        "points": (
            curve_points
        ),
        "isc_a": (
            combined_isc
        ),
        "voc_v": float(
            combined_voc
        ),
        "global_mpp": (
            global_mpp
        ),
        "local_mpp_candidates": (
            local_candidates
        ),
    }

    physical_result_sha = (
        _canonical_sha256(
            physical_payload
        )
    )

    curve_id = (
        "iv:mppt-combined:"
        f"{mppt_id}:"
        f"{physical_result_sha[:16]}"
    )

    execution_payload_sha = (
        _canonical_sha256(
            {
                "scientific_input_sha256": (
                    scientific_input_sha
                ),
                "physical_result_sha256": (
                    physical_result_sha
                ),
                "solver_id": (
                    PARALLEL_STRING_IV_SOLVER_ID
                ),
                "solver_version": (
                    PARALLEL_STRING_IV_SOLVER_VERSION
                ),
                "voltage_grid_strategy": (
                    VOLTAGE_GRID_STRATEGY
                ),
                "point_count": len(
                    curve_points
                ),
            }
        )
    )

    curve = {
        "schema_name": (
            "ElectricalIVCurve"
        ),
        "schema_version": "0.1",
        "contract_version": "0.1",
        "curve_id": (
            curve_id
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
            mppt_id
        ),
        "points": (
            curve_points
        ),
        "isc_a": (
            combined_isc
        ),
        "voc_v": float(
            combined_voc
        ),
        "mpp_semantics": {
            "declaration_authority": (
                "solver_declared"
            ),
            "sample_verification_scope": (
                "represented_samples_only"
            ),
            "voltage_tolerance_v": float(
                voltage_tolerance_v
            ),
            "power_tolerance_w": float(
                power_tolerance_w
            ),
            "continuous_curve_guarantee": (
                "solver_guaranteed"
            ),
            "continuous_curve_guarantee_basis": (
                "exact interval quadratic "
                "maximization of the explicit "
                "piecewise-linear source-current "
                "interpolation model"
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
                PARALLEL_STRING_IV_SOLVER_ID
            ),
            "model_version": (
                PARALLEL_STRING_IV_SOLVER_VERSION
            ),
            "parameterization_id": None,
            "topology_revision_id": (
                electrical_revision_id
            ),
            "bypass_model_ids": [],
            "notes": (
                "Physical common-voltage "
                "parallel aggregation only. "
                "Tracker/controller selection "
                "is not performed. "
                "Reverse inter-string current "
                "is outside the Phase-6A "
                "delivery-current model."
            ),
        },
        "execution_manifest": {
            "solver_id": (
                PARALLEL_STRING_IV_SOLVER_ID
            ),
            "solver_version": (
                PARALLEL_STRING_IV_SOLVER_VERSION
            ),
            "voltage_grid_strategy": (
                VOLTAGE_GRID_STRATEGY
            ),
            "point_count": len(
                curve_points
            ),
            "cache_mode": "none",
            "parallelization": "none",
        },
        "scientific_input_sha256": (
            scientific_input_sha
        ),
        "physical_result_sha256": (
            physical_result_sha
        ),
        "execution_payload_sha256": (
            execution_payload_sha
        ),
        "quality_flags": [
            (
                "source_string_curves_"
                "piecewise_linear_interpolated"
            ),
            (
                "reverse_interstring_backfeed_"
                "not_modeled"
            ),
            (
                "tracker_operating_point_"
                "not_selected"
            ),
        ],
    }

    try:
        assert_electrical_iv_curve(
            curve
        )
    except ElectricalShadingContractError as exc:
        raise ParallelStringIVError(
            "assembled MPPT-combined "
            f"ElectricalIVCurve invalid: {exc}"
        ) from exc

    state_payload = {
        "source_electrical_revision_id": (
            electrical_revision_id
        ),
        "source_mppt_instance_id": (
            mppt_id
        ),
        "source_inverter_instance_id": (
            inverter_id
        ),
        "source_mppt_index": (
            mppt_index
        ),
        "source_string_ids": (
            list(
                source_string_ids
            )
        ),
        "source_string_curves": (
            source_metadata
        ),
        "combined_curve_id": (
            curve_id
        ),
        "parallel_rule": (
            PARALLEL_RULE
        ),
        "source_curve_interpolation": (
            SOURCE_CURVE_INTERPOLATION
        ),
        "reverse_interstring_current_policy": (
            REVERSE_INTERSTRING_CURRENT_POLICY
        ),
        "voltage_grid_strategy": (
            VOLTAGE_GRID_STRATEGY
        ),
        "voltage_samples": (
            voltage_samples
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
            "MPPTParallelIVState"
        ),
        "schema_version": "0.1",
        "contract_version": "0.1",
        "state_id": (
            "mppt-parallel:"
            f"{mppt_id}:"
            f"{state_hash[:16]}"
        ),
        **state_payload,
        "state_payload_sha256": (
            state_hash
        ),
    }

    return ParallelStringIVResult(
        curve=curve,
        state=state,
    )
