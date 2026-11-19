"""Phase-6.5 slow analytical substring / bypass reference kernel.

This module is intentionally a reference implementation, not the production
nonuniform module-IV solver.

It consumes:
- explicit Phase-6 ModuleTopologyDefinition;
- ElectricalRegionMap identity;
- Phase-6.3 LocalElectricalIrradianceState.

The region IV law used here is deliberately synthetic and piecewise-linear so
that bypass transitions have closed-form analytical fixtures.

It MUST NOT be used to infer region/cell parameters from a whole-module SDM.
Phase 6.6 is responsible for physically parameterized nonuniform module IV.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from math import isfinite
from typing import Any, Mapping, Sequence

from .contract import (
    ElectricalShadingContractError,
    assert_bypass_model_contract,
    assert_module_topology_definition,
)


PHASE65_REFERENCE_SOLVER_ID = (
    "rawibumi.phase65.substring_bypass_reference.v0.1"
)

PHASE65_ANALYTICAL_REGION_MODEL_ID = (
    "rawibumi.phase65.analytical_piecewise_linear_region_iv.v0.1"
)


class SubstringReferenceError(ValueError):
    """Raised when a Phase-6.5 reference problem is ambiguous or unsupported."""


def _finite(value: Any, *, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise SubstringReferenceError(f"{label} must be numeric")
    number = float(value)
    if not isfinite(number):
        raise SubstringReferenceError(f"{label} must be finite")
    return number


def _positive(value: Any, *, label: str) -> float:
    number = _finite(value, label=label)
    if number <= 0.0:
        raise SubstringReferenceError(f"{label} must be positive")
    return number


@dataclass(frozen=True)
class AnalyticalRegionReferenceState:
    """Synthetic IV state used only by the Phase-6.5 analytical reference path."""

    region_id: str
    source_local_region_id: str
    source_substring_id: str
    equivalent_element_count: int

    effective_irradiance_w_m2: float
    reference_irradiance_w_m2: float

    isc_a: float
    voc_v: float
    reverse_resistance_ohm: float
    current_ceiling_a: float

    model_id: str = PHASE65_ANALYTICAL_REGION_MODEL_ID

    def voltage_at_current(self, current_a: float) -> float:
        current = _finite(current_a, label="region current_a")

        if current < 0.0:
            raise SubstringReferenceError(
                "Phase-6.5 reference region current must be non-negative"
            )

        if current > self.current_ceiling_a + 1e-12:
            raise SubstringReferenceError(
                f"region {self.region_id} current {current} A exceeds "
                f"reference ceiling {self.current_ceiling_a} A"
            )

        if self.isc_a <= 0.0:
            return -self.reverse_resistance_ohm * current

        if current <= self.isc_a:
            return self.voc_v * (1.0 - current / self.isc_a)

        return -self.reverse_resistance_ohm * (
            current - self.isc_a
        )

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)

    def current_at_voltage(
        self,
        voltage_v: float,
    ) -> float:
        """Exact inverse of the analytical fixture V(I) law."""

        voltage = _finite(
            voltage_v,
            label="region voltage_v",
        )

        if voltage >= self.voc_v:
            return 0.0

        if voltage >= 0.0:
            if (
                self.isc_a <= 0.0
                or self.voc_v <= 0.0
            ):
                return 0.0

            current = (
                self.isc_a
                * (
                    1.0
                    - voltage
                    / self.voc_v
                )
            )

        else:
            current = (
                self.isc_a
                + (
                    -voltage
                    / self.reverse_resistance_ohm
                )
            )

        if (
            current
            > self.current_ceiling_a
            + 1e-10
        ):
            raise SubstringReferenceError(
                f"region {self.region_id} "
                f"voltage {voltage} V requires "
                f"{current} A above reference "
                f"ceiling {self.current_ceiling_a} A"
            )

        return float(
            max(
                0.0,
                current,
            )
        )


def _topology_region_map(
    topology_definition: Mapping[str, Any],
) -> dict[str, Mapping[str, Any]]:
    return {
        str(region["region_id"]): region
        for region in topology_definition.get("physical_regions") or []
    }


def build_analytical_region_reference_states(
    topology_definition: Mapping[str, Any],
    electrical_region_map: Mapping[str, Any],
    local_irradiance_state: Mapping[str, Any],
    *,
    reference_irradiance_w_m2: float,
    isc_ref_a: float,
    voc_ref_v_per_element: float,
    reverse_resistance_ohm_per_element: float,
    current_ceiling_a: float,
    active_irradiance_threshold_w_m2: float = 1e-9,
) -> dict[str, AnalyticalRegionReferenceState]:
    """Bind local irradiance to explicit topology regions.

    Analytical fixture law:

        Isc = Isc_ref * G_eff / G_ref

    Positive-irradiance Voc is fixed per explicitly declared equivalent
    series element. Above Isc, voltage enters a linear reverse region:

        V = -R_reverse * (I - Isc)

    This model exists ONLY for analytical Phase-6.5 transition tests.
    """

    try:
        assert_module_topology_definition(topology_definition)
    except ElectricalShadingContractError as exc:
        raise SubstringReferenceError(str(exc)) from exc

    reference_irradiance = _positive(
        reference_irradiance_w_m2,
        label="reference_irradiance_w_m2",
    )
    isc_reference = _positive(
        isc_ref_a,
        label="isc_ref_a",
    )
    voc_per_element = _positive(
        voc_ref_v_per_element,
        label="voc_ref_v_per_element",
    )
    reverse_r_per_element = _positive(
        reverse_resistance_ohm_per_element,
        label="reverse_resistance_ohm_per_element",
    )
    current_ceiling = _positive(
        current_ceiling_a,
        label="current_ceiling_a",
    )

    threshold = _finite(
        active_irradiance_threshold_w_m2,
        label="active_irradiance_threshold_w_m2",
    )
    if threshold < 0.0:
        raise SubstringReferenceError(
            "active_irradiance_threshold_w_m2 must be non-negative"
        )

    map_id = str(
        electrical_region_map.get("electrical_region_map_id") or ""
    )
    map_hash = str(
        electrical_region_map.get("mapping_payload_sha256") or ""
    )

    if not map_id or not map_hash:
        raise SubstringReferenceError(
            "electrical region map requires explicit id and mapping hash"
        )

    if (
        str(
            local_irradiance_state.get(
                "source_electrical_region_map_id"
            )
            or ""
        )
        != map_id
    ):
        raise SubstringReferenceError(
            "local irradiance state is bound to a different "
            "electrical region map"
        )

    if (
        str(
            local_irradiance_state.get(
                "source_electrical_region_map_hash"
            )
            or ""
        )
        != map_hash
    ):
        raise SubstringReferenceError(
            "local irradiance state electrical-region-map hash mismatch"
        )

    topology_revision = str(
        topology_definition.get("revision_id") or ""
    )
    mapped_topology_revision = str(
        electrical_region_map.get(
            "source_module_topology_revision_id"
        )
        or ""
    )

    if mapped_topology_revision != topology_revision:
        raise SubstringReferenceError(
            "electrical region map is bound to a different "
            "topology revision"
        )

    topology_regions = _topology_region_map(
        topology_definition
    )

    mapped_regions = list(
        electrical_region_map.get("regions") or []
    )
    local_regions = list(
        local_irradiance_state.get("regions") or []
    )

    map_by_region_id: dict[str, Mapping[str, Any]] = {}
    source_ids_seen: set[str] = set()

    for region in mapped_regions:
        map_region_id = str(
            region.get("region_id") or ""
        )
        source_region_id = str(
            region.get("source_topology_region_id") or ""
        )

        if not map_region_id or not source_region_id:
            raise SubstringReferenceError(
                "electrical region map requires region_id and "
                "source_topology_region_id"
            )

        if map_region_id in map_by_region_id:
            raise SubstringReferenceError(
                f"duplicate electrical region-map region_id: "
                f"{map_region_id}"
            )

        if source_region_id in source_ids_seen:
            raise SubstringReferenceError(
                f"duplicate source topology region mapping: "
                f"{source_region_id}"
            )

        map_by_region_id[map_region_id] = region
        source_ids_seen.add(source_region_id)

    if source_ids_seen != set(topology_regions):
        raise SubstringReferenceError(
            "electrical region map must cover the exact topology "
            "physical-region set"
        )

    local_by_region_id: dict[str, Mapping[str, Any]] = {}

    for region in local_regions:
        region_id = str(
            region.get("region_id") or ""
        )

        if not region_id:
            raise SubstringReferenceError(
                "local irradiance region_id is required"
            )

        if region_id in local_by_region_id:
            raise SubstringReferenceError(
                f"duplicate local irradiance region_id: "
                f"{region_id}"
            )

        local_by_region_id[region_id] = region

    if set(local_by_region_id) != set(map_by_region_id):
        raise SubstringReferenceError(
            "local irradiance regions must exactly match the "
            "electrical region map"
        )

    out: dict[
        str,
        AnalyticalRegionReferenceState,
    ] = {}

    for map_region_id in sorted(map_by_region_id):
        mapped = map_by_region_id[map_region_id]
        local = local_by_region_id[map_region_id]

        source_region_id = str(
            mapped["source_topology_region_id"]
        )
        topology_region = topology_regions[
            source_region_id
        ]

        source_substring_id = str(
            topology_region["electrical_substring_id"]
        )

        mapped_substring_id = mapped.get(
            "source_electrical_substring_id"
        )

        if (
            mapped_substring_id is not None
            and str(mapped_substring_id)
            != source_substring_id
        ):
            raise SubstringReferenceError(
                f"region {source_region_id} substring identity mismatch"
            )

        effective = _finite(
            local.get("effective_irradiance_w_m2"),
            label=(
                f"region {source_region_id} "
                "effective_irradiance_w_m2"
            ),
        )

        if effective < 0.0:
            raise SubstringReferenceError(
                f"region {source_region_id} effective irradiance "
                "must be non-negative"
            )

        count = topology_region.get(
            "equivalent_element_count"
        )

        if (
            isinstance(count, bool)
            or not isinstance(count, int)
            or count < 1
        ):
            raise SubstringReferenceError(
                f"region {source_region_id} "
                "equivalent_element_count must be >= 1"
            )

        irradiance_ratio = (
            effective / reference_irradiance
        )

        isc = (
            isc_reference
            * irradiance_ratio
        )

        voc = (
            voc_per_element * count
            if effective > threshold
            else 0.0
        )

        reverse_r = (
            reverse_r_per_element
            * count
        )

        if current_ceiling + 1e-12 < isc:
            raise SubstringReferenceError(
                f"region {source_region_id} current ceiling "
                "is below analytical Isc"
            )

        out[source_region_id] = (
            AnalyticalRegionReferenceState(
                region_id=source_region_id,
                source_local_region_id=map_region_id,
                source_substring_id=source_substring_id,
                equivalent_element_count=count,
                effective_irradiance_w_m2=effective,
                reference_irradiance_w_m2=(
                    reference_irradiance
                ),
                isc_a=isc,
                voc_v=voc,
                reverse_resistance_ohm=reverse_r,
                current_ceiling_a=current_ceiling,
            )
        )

    return out


def evaluate_series_branch_voltage(
    branch: Mapping[str, Any],
    region_states: Mapping[
        str,
        AnalyticalRegionReferenceState,
    ],
    *,
    current_a: float,
) -> float:
    """Sum region voltages in explicit branch series order."""

    current = _finite(
        current_a,
        label="branch current_a",
    )

    if current < 0.0:
        raise SubstringReferenceError(
            "branch current must be non-negative"
        )

    region_ids = list(
        branch.get("series_region_ids") or []
    )

    if not region_ids:
        raise SubstringReferenceError(
            "branch requires explicit series_region_ids"
        )

    voltage = 0.0

    for region_id in region_ids:
        state = region_states.get(
            str(region_id)
        )

        if state is None:
            raise SubstringReferenceError(
                f"missing reference state for region "
                f"{region_id}"
            )

        voltage += state.voltage_at_current(
            current
        )

    return float(voltage)


def _branch_current_ceiling(
    branch: Mapping[str, Any],
    region_states: Mapping[
        str,
        AnalyticalRegionReferenceState,
    ],
) -> float:
    ceilings = []

    for region_id in (
        branch.get("series_region_ids") or []
    ):
        state = region_states.get(
            str(region_id)
        )

        if state is None:
            raise SubstringReferenceError(
                f"missing reference state for region "
                f"{region_id}"
            )

        ceilings.append(
            state.current_ceiling_a
        )

    if not ceilings:
        raise SubstringReferenceError(
            "branch requires at least one region"
        )

    return float(min(ceilings))


@dataclass(frozen=True, eq=False, repr=False)
class _BranchEndpoints:
    """Successful invariant values only; never a scientific payload."""

    ceiling: float | None = None
    open_voltage: float | None = None
    end_voltage: float | None = None


class _BranchBinding:
    __slots__ = ("branch", "region_ids", "states", "values", "currents")

    def __init__(self, branch, region_states):
        self.branch = branch
        self.region_ids = tuple(branch.get("series_region_ids") or ())
        self.states = tuple(region_states.get(str(r)) for r in self.region_ids)
        self.values = _BranchEndpoints()
        self.currents = {}


class _BranchEndpointHolder:
    """Model-owned, fixed-size runtime storage; unknown bindings stay uncached.

    Strong branch/state references prevent object-ID reuse. No quantities are
    evaluated during registration, and no new slots are admitted afterward.
    """

    __slots__ = ("_region_states", "_slots")

    def __init__(self, branches, region_states):
        self._region_states = region_states
        self._slots = {id(b): _BranchBinding(b, region_states) for b in branches}

    def bind(self, branch, region_states):
        if region_states is not self._region_states:
            return None
        slot = self._slots.get(id(branch))
        if slot is None or slot.branch is not branch:
            return None
        if tuple(branch.get("series_region_ids") or ()) != slot.region_ids:
            return None
        if any(region_states.get(str(r)) is not state for r, state in zip(slot.region_ids, slot.states)):
            return None
        return slot


def _branch_ceiling_with_reuse(branch, region_states, slot=None, *, evaluator=None):
    if slot is not None and slot.values.ceiling is not None:
        return slot.values.ceiling
    value = (evaluator or _branch_current_ceiling)(branch, region_states)
    if slot is not None:
        slot.values = replace(slot.values, ceiling=value)
    return value


def _branch_open_with_reuse(branch, region_states, slot=None):
    if slot is not None and slot.values.open_voltage is not None:
        return slot.values.open_voltage
    value = evaluate_series_branch_voltage(branch, region_states, current_a=0.0)
    if slot is not None:
        slot.values = replace(slot.values, open_voltage=value)
    return value


def _branch_end_with_reuse(branch, region_states, ceiling, slot=None, *, evaluator=None):
    if slot is not None and slot.values.end_voltage is not None:
        return slot.values.end_voltage
    value = (evaluator or evaluate_series_branch_voltage)(branch, region_states, current_a=ceiling)
    if slot is not None:
        slot.values = replace(slot.values, end_voltage=value)
    return value


_BRANCH_CURRENT_MEMO_LIMIT = 256


def _branch_current_at_voltage(
    branch, region_states, *, voltage_v, voltage_tolerance_v,
    current_tolerance_a, max_iterations, _reuse=None,
):
    """Reuse successful exact I(V) evaluations within an immutable model.

    Admit the first bounded set of points, retaining shared bisection prefixes.
    No rounding, eviction-dependent arithmetic, or exception caching occurs.
    """
    target = _finite(voltage_v, label="branch target voltage_v")
    slot = _reuse.bind(branch, region_states) if _reuse is not None else None
    if slot is not None:
        # Only the two known frozen, pure region laws qualify. Custom mutable
        # region implementations retain the original evaluation behavior.
        from .parameterization import PVSystRegionElectricalState
        if not all(type(state) in (AnalyticalRegionReferenceState,
                                   PVSystRegionElectricalState) for state in slot.states):
            slot = None
    key = (target.hex(), voltage_tolerance_v, current_tolerance_a, max_iterations)
    if slot is not None and key in slot.currents:
        return slot.currents[key]
    value = _branch_current_at_voltage_uncached(
        branch, region_states, voltage_v=target,
        voltage_tolerance_v=voltage_tolerance_v,
        current_tolerance_a=current_tolerance_a, max_iterations=max_iterations,
        _reuse=_reuse,
    )
    if slot is not None and len(slot.currents) < _BRANCH_CURRENT_MEMO_LIMIT:
        slot.currents[key] = value
    return value


def _branch_current_at_voltage_uncached(
    branch: Mapping[str, Any],
    region_states: Mapping[
        str,
        AnalyticalRegionReferenceState,
    ],
    *,
    voltage_v: float,
    voltage_tolerance_v: float,
    current_tolerance_a: float,
    max_iterations: int,
    _reuse: _BranchEndpointHolder | None = None,
) -> float:
    target = _finite(
        voltage_v,
        label="branch target voltage_v",
    )

    slot = _reuse.bind(branch, region_states) if _reuse is not None else None
    ceiling = _branch_ceiling_with_reuse(branch, region_states, slot)
    v_open = _branch_open_with_reuse(branch, region_states, slot)
    v_end = _branch_end_with_reuse(branch, region_states, ceiling, slot)

    if target >= v_open - voltage_tolerance_v:
        return 0.0

    if target < v_end - voltage_tolerance_v:
        raise SubstringReferenceError(
            "reference current ceiling is too low "
            "to reach requested branch voltage"
        )

    if abs(
        target - v_end
    ) <= voltage_tolerance_v:
        return float(
            ceiling
        )

    region_ids = [
        str(region_id)
        for region_id
        in (
            branch.get(
                "series_region_ids"
            )
            or []
        )
    ]

    # Exact fast path.
    #
    # A one-region branch requires no numerical
    # inversion: the region model itself owns
    # I(V). This is mathematically equivalent to
    # the old bisection, not an approximation.
    if len(region_ids) == 1:
        state = region_states.get(
            region_ids[0]
        )

        if state is None:
            raise SubstringReferenceError(
                "missing region state for "
                f"{region_ids[0]}"
            )

        inverse = getattr(
            state,
            "current_at_voltage",
            None,
        )

        if callable(inverse):
            current = float(
                inverse(
                    target
                )
            )

            if (
                current
                < -current_tolerance_a
                or current
                > ceiling
                + current_tolerance_a
            ):
                raise SubstringReferenceError(
                    "single-region inverse "
                    "returned current outside "
                    "supported branch domain"
                )

            return float(
                min(
                    ceiling,
                    max(
                        0.0,
                        current,
                    ),
                )
            )

    # Generic transparent reference path for an
    # arbitrary series group.
    lo = 0.0
    hi = ceiling

    for _ in range(
        max_iterations
    ):
        mid = 0.5 * (
            lo + hi
        )

        value = (
            evaluate_series_branch_voltage(
                branch,
                region_states,
                current_a=mid,
            )
        )

        if (
            abs(
                value - target
            )
            <= voltage_tolerance_v
        ):
            return float(
                mid
            )

        if value > target:
            lo = mid
        else:
            hi = mid

        if (
            hi - lo
            <= current_tolerance_a
        ):
            break

    return float(
        0.5
        * (
            lo + hi
        )
    )



def solve_parallel_branches_at_current(
    branches: Sequence[Mapping[str, Any]],
    region_states: Mapping[
        str,
        AnalyticalRegionReferenceState,
    ],
    *,
    total_current_a: float,
    voltage_tolerance_v: float = 1e-10,
    current_tolerance_a: float = 1e-10,
    max_iterations: int = 200,
    _reuse: _BranchEndpointHolder | None = None,
) -> dict[str, Any]:
    """Solve branch current split at one common voltage."""

    total_current = _finite(
        total_current_a,
        label="total_current_a",
    )

    if total_current < 0.0:
        raise SubstringReferenceError(
            "total_current_a must be non-negative"
        )

    if not branches:
        raise SubstringReferenceError(
            "parallel branch group cannot be empty"
        )

    if (
        voltage_tolerance_v <= 0.0
        or current_tolerance_a <= 0.0
    ):
        raise SubstringReferenceError(
            "solver tolerances must be positive"
        )

    if max_iterations < 1:
        raise SubstringReferenceError(
            "max_iterations must be at least 1"
        )

    branch_data = []

    for branch in branches:
        slot = _reuse.bind(branch, region_states) if _reuse is not None else None
        ceiling = _branch_ceiling_with_reuse(branch, region_states, slot)
        v_open = _branch_open_with_reuse(branch, region_states, slot)
        v_end = _branch_end_with_reuse(branch, region_states, ceiling, slot)

        if v_end > v_open + voltage_tolerance_v:
            raise SubstringReferenceError(
                "reference branch IV must be "
                "non-increasing with current"
            )

        branch_data.append(
            (
                branch,
                ceiling,
                v_open,
                v_end,
            )
        )

    high_v = max(
        item[2] for item in branch_data
    )

    # Highest end-voltage is the first branch to hit
    # its current-domain ceiling. Therefore this is
    # the lowest common voltage supported by every
    # supplied branch curve.
    low_v = max(
        item[3] for item in branch_data
    )

    def currents_at(
        voltage: float,
    ) -> list[float]:
        return [
            _branch_current_at_voltage(
                branch,
                region_states,
                voltage_v=voltage,
                voltage_tolerance_v=(
                    voltage_tolerance_v
                ),
                current_tolerance_a=(
                    current_tolerance_a
                ),
                max_iterations=max_iterations,
                _reuse=_reuse,
            )
            for branch, _, _, _ in branch_data
        ]

    if total_current <= current_tolerance_a:
        branch_currents = [
            0.0 for _ in branch_data
        ]
        common_v = high_v

    else:
        low_currents = currents_at(
            low_v
        )

        supported_current = sum(
            low_currents
        )

        if (
            total_current
            > supported_current
            + current_tolerance_a
        ):
            raise SubstringReferenceError(
                "reference current ceiling is too low "
                "for requested parallel current"
            )

        lo = low_v
        hi = high_v

        for _ in range(max_iterations):
            mid = 0.5 * (lo + hi)

            mid_currents = currents_at(
                mid
            )

            summed = sum(
                mid_currents
            )

            if (
                abs(
                    summed
                    - total_current
                )
                <= current_tolerance_a
                or hi - lo
                <= voltage_tolerance_v
            ):
                lo = hi = mid
                break

            if summed > total_current:
                lo = mid
            else:
                hi = mid

        common_v = 0.5 * (
            lo + hi
        )

        branch_currents = currents_at(
            common_v
        )

    states = []

    for (
        branch,
        _,
        _,
        _,
    ), current in zip(
        branch_data,
        branch_currents,
    ):
        voltage = evaluate_series_branch_voltage(
            branch,
            region_states,
            current_a=current,
        )

        states.append(
            {
                "branch_id": str(
                    branch.get(
                        "branch_id"
                    )
                    or ""
                ),
                "current_a": float(
                    current
                ),
                "voltage_v": float(
                    voltage
                ),
                "series_region_ids": [
                    str(value)
                    for value
                    in (
                        branch.get(
                            "series_region_ids"
                        )
                        or []
                    )
                ],
            }
        )

    return {
        "common_voltage_v": float(
            common_v
        ),
        "total_current_a": float(
            sum(
                item["current_a"]
                for item in states
            )
        ),
        "branch_states": states,
        "current_residual_a": float(
            sum(
                item["current_a"]
                for item in states
            )
            - total_current
        ),
    }


def _resolve_bypass_device(
    topology_definition: Mapping[str, Any],
    substring: Mapping[str, Any],
) -> Mapping[str, Any]:

    substring_id = str(
        substring["substring_id"]
    )

    devices = [
        device
        for device
        in (
            topology_definition.get(
                "bypass_devices"
            )
            or []
        )
        if isinstance(
            device,
            Mapping,
        )
    ]

    by_id = {
        str(
            device.get(
                "bypass_device_id"
            )
        ): device
        for device in devices
        if device.get(
            "bypass_device_id"
        )
    }

    declared_id = substring.get(
        "bypass_device_id"
    )

    if declared_id is not None:
        device = by_id.get(
            str(declared_id)
        )

        if device is None:
            raise SubstringReferenceError(
                f"substring {substring_id} "
                "bypass device is missing"
            )

        return device

    candidates = [
        device
        for device in devices
        if substring_id
        in set(
            device.get(
                "protects_substring_ids"
            )
            or []
        )
    ]

    if len(candidates) != 1:
        raise SubstringReferenceError(
            f"substring {substring_id} must "
            "resolve exactly one bypass device"
        )

    return candidates[0]


def _bypass_clamp_voltage(
    device: Mapping[str, Any],
) -> tuple[
    float,
    Mapping[str, Any],
]:

    model = device.get(
        "forward_voltage_model"
    )

    if not isinstance(
        model,
        Mapping,
    ):
        raise SubstringReferenceError(
            f"bypass device "
            f"{device.get('bypass_device_id')} "
            "has no executable model"
        )

    try:
        assert_bypass_model_contract(
            model,
            device_id=str(
                device.get(
                    "bypass_device_id"
                )
                or "unknown"
            ),
        )
    except ElectricalShadingContractError as exc:
        raise SubstringReferenceError(
            str(exc)
        ) from exc

    model_type = str(
        model.get("model_type")
    )

    if model_type == "ideal":
        return 0.0, model

    if (
        model_type
        == "constant_forward_drop"
    ):
        drop = _finite(
            (
                model.get("parameters")
                or {}
            ).get(
                "forward_voltage_v"
            ),
            label=(
                "bypass "
                "forward_voltage_v"
            ),
        )

        return -drop, model

    raise SubstringReferenceError(
        "parameterized_iv bypass models are "
        "structurally valid but are not implemented "
        "by the Phase-6.5 reference kernel"
    )


def _branch_states_at_voltage(
    branches: Sequence[
        Mapping[str, Any]
    ],
    region_states: Mapping[
        str,
        AnalyticalRegionReferenceState,
    ],
    *,
    voltage_v: float,
    voltage_tolerance_v: float,
    current_tolerance_a: float,
    max_iterations: int,
    _reuse: _BranchEndpointHolder | None = None,
) -> list[dict[str, Any]]:

    out = []

    for branch in branches:
        current = _branch_current_at_voltage(
            branch,
            region_states,
            voltage_v=voltage_v,
            voltage_tolerance_v=(
                voltage_tolerance_v
            ),
            current_tolerance_a=(
                current_tolerance_a
            ),
            max_iterations=(
                max_iterations
            ),
            _reuse=_reuse,
        )

        out.append(
            {
                "branch_id": str(
                    branch.get(
                        "branch_id"
                    )
                    or ""
                ),
                "current_a": float(
                    current
                ),
                "voltage_v": float(
                    evaluate_series_branch_voltage(
                        branch,
                        region_states,
                        current_a=current,
                    )
                ),
                "series_region_ids": [
                    str(value)
                    for value
                    in (
                        branch.get(
                            "series_region_ids"
                        )
                        or []
                    )
                ],
            }
        )

    return out


def evaluate_protected_substring_at_current(
    topology_definition: Mapping[str, Any],
    substring_id: str,
    region_states: Mapping[
        str,
        AnalyticalRegionReferenceState,
    ],
    *,
    current_a: float,
    voltage_tolerance_v: float = 1e-10,
    current_tolerance_a: float = 1e-10,
    max_iterations: int = 200,
    _reuse: _BranchEndpointHolder | None = None,
) -> dict[str, Any]:
    """Evaluate one protected substring at a requested terminal current.

    Bypass activation is determined from the physically useful threshold:

        requested current
        >
        PV-network current available at the bypass clamp voltage

    This is equivalent to comparing the hypothetical unbypassed voltage
    against the bypass clamp when the unbypassed solution exists.

    Critically, once the requested current exceeds the clamp-transition
    current, the actual protected substring remains evaluable even when the
    hypothetical no-bypass operating point would lie outside the explicitly
    supported reverse-bias domain.

    The hypothetical unbypassed state is retained when it can be solved and
    otherwise reported as unavailable rather than extrapolated silently.
    """

    try:
        assert_module_topology_definition(
            topology_definition
        )
    except ElectricalShadingContractError as exc:
        raise SubstringReferenceError(
            str(exc)
        ) from exc

    current = _finite(
        current_a,
        label="substring current_a",
    )

    if current < 0.0:
        raise SubstringReferenceError(
            "substring current must be non-negative"
        )

    matches = [
        substring
        for substring
        in (
            topology_definition.get(
                "electrical_substrings"
            )
            or []
        )
        if str(
            substring.get(
                "substring_id"
            )
            or ""
        )
        == str(
            substring_id
        )
    ]

    if len(matches) != 1:
        raise SubstringReferenceError(
            f"substring_id {substring_id!r} "
            "must resolve exactly once"
        )

    substring = matches[0]

    required_regions = {
        str(value)
        for value
        in substring[
            "physical_region_ids"
        ]
    }

    if not required_regions.issubset(
        region_states
    ):
        missing = sorted(
            required_regions
            - set(region_states)
        )

        raise SubstringReferenceError(
            "reference region states "
            "missing substring regions: "
            f"{missing}"
        )

    branches = list(
        substring[
            "parallel_branches"
        ]
    )

    device = _resolve_bypass_device(
        topology_definition,
        substring,
    )

    clamp_voltage, model = (
        _bypass_clamp_voltage(
            device
        )
    )

    # Solve the PV network exactly at the bypass
    # clamp. This is the authoritative transition
    # current and must itself lie inside every
    # region's supported domain.
    clamp_branch_states = (
        _branch_states_at_voltage(
            branches,
            region_states,
            voltage_v=(
                clamp_voltage
            ),
            voltage_tolerance_v=(
                voltage_tolerance_v
            ),
            current_tolerance_a=(
                current_tolerance_a
            ),
            max_iterations=(
                max_iterations
            ),
            _reuse=_reuse,
        )
    )

    pv_current_at_clamp = float(
        sum(
            item["current_a"]
            for item
            in clamp_branch_states
        )
    )

    # Current-domain transition comparison is
    # retained as a fallback for cases where the
    # hypothetical unbypassed state lies outside
    # the validated region domain.
    #
    # Parallel branch inversion can contribute one
    # current tolerance per branch, so use an
    # accumulated numerical tolerance here.
    transition_current_tolerance = (
        current_tolerance_a
        * max(
            1,
            2 * len(branches),
        )
    )

    bypass_active_from_current = (
        current
        > pv_current_at_clamp
        + transition_current_tolerance
    )

    # The unbypassed state remains valuable
    # diagnostic information, but after bypass
    # activation it is counterfactual. It must
    # therefore never force extrapolation outside
    # the validated region domain.
    unbypassed = None

    try:
        unbypassed = (
            solve_parallel_branches_at_current(
                branches,
                region_states,
                total_current_a=current,
                voltage_tolerance_v=(
                    voltage_tolerance_v
                ),
                current_tolerance_a=(
                    current_tolerance_a
                ),
                max_iterations=(
                    max_iterations
                ),
                _reuse=_reuse,
            )
        )
    except ValueError:
        if not bypass_active_from_current:
            raise

    if unbypassed is None:
        unbypassed_voltage = None
        unbypassed_branch_states = []
        transition_margin = None
        unbypassed_solution_available = False

        bypass_active = (
            bypass_active_from_current
        )

    else:
        unbypassed_voltage = float(
            unbypassed[
                "common_voltage_v"
            ]
        )

        unbypassed_branch_states = list(
            unbypassed[
                "branch_states"
            ]
        )

        transition_margin = float(
            unbypassed_voltage
            - clamp_voltage
        )

        unbypassed_solution_available = True

        # When the hypothetical no-bypass solution
        # is executable, voltage is the more direct
        # physical transition criterion:
        #
        #   V_unbypassed > V_clamp  -> diode off
        #   V_unbypassed = V_clamp  -> transition
        #   V_unbypassed < V_clamp  -> diode on
        #
        # Equality within solver tolerance remains
        # the transition point and is reported with
        # bypass_active=False.
        bypass_active = (
            transition_margin
            < -voltage_tolerance_v
        )

    if bypass_active:
        terminal_voltage = float(
            clamp_voltage
        )

        bypass_current = max(
            0.0,
            current
            - pv_current_at_clamp,
        )

        terminal_branch_states = (
            clamp_branch_states
        )

    else:
        if unbypassed is None:
            raise SubstringReferenceError(
                "non-bypassed substring requires "
                "an executable unbypassed state"
            )

        if (
            unbypassed_voltage
            < clamp_voltage
            - voltage_tolerance_v
        ):
            raise SubstringReferenceError(
                "bypass transition classification "
                "is internally inconsistent"
            )

        terminal_voltage = float(
            unbypassed_voltage
        )

        bypass_current = 0.0

        terminal_branch_states = (
            unbypassed_branch_states
        )

    return {
        "schema_name": (
            "Phase65ProtectedSubstringReferenceState"
        ),
        "schema_version": "0.2",
        "solver_id": (
            PHASE65_REFERENCE_SOLVER_ID
        ),
        "region_model_id": (
            PHASE65_ANALYTICAL_REGION_MODEL_ID
        ),
        "substring_id": str(
            substring[
                "substring_id"
            ]
        ),
        "series_order": int(
            substring[
                "series_order"
            ]
        ),
        "evaluation_current_a": float(
            current
        ),
        "unbypassed_solution_available": bool(
            unbypassed_solution_available
        ),
        "unbypassed_voltage_v": (
            unbypassed_voltage
        ),
        "bypass_device_id": str(
            device[
                "bypass_device_id"
            ]
        ),
        "bypass_model_id": str(
            model[
                "model_id"
            ]
        ),
        "bypass_clamp_voltage_v": float(
            clamp_voltage
        ),
        "pv_current_at_bypass_clamp_a": (
            pv_current_at_clamp
        ),
        "transition_margin_v": (
            transition_margin
        ),
        "bypass_active": bool(
            bypass_active
        ),
        "bypass_current_a": float(
            bypass_current
        ),
        "terminal_voltage_v": float(
            terminal_voltage
        ),
        "unbypassed_branch_states": (
            unbypassed_branch_states
        ),
        "bypass_clamp_branch_states": (
            clamp_branch_states
        ),
        "terminal_branch_states": (
            terminal_branch_states
        ),
        "limitations": [
            (
                "region_model_authority_depends_"
                "on_supplied_region_state"
            ),
            (
                "nonnegative_branch_current_only"
            ),
            (
                "parameterized_bypass_iv_"
                "not_supported"
            ),
            (
                "counterfactual_unbypassed_state_"
                "may_be_unavailable_outside_"
                "validated_region_domain"
            ),
            (
                "no_string_or_mppt_assembly"
            ),
        ],
    }
