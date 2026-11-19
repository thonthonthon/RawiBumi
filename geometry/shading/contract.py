"""Machine-enforced Phase-5.0 geometry-aware shading conventions.

This module deliberately contains no production shading solver. It freezes the
coordinate, sun-vector, factor, and configuration semantics that later Phase-5
geometry kernels must consume.
"""

from __future__ import annotations

import math
from typing import Any, Mapping


CONTRACT_VERSION = "0.1"
COORDINATE_BASIS = "scene_local_east_north_up_m"
SUN_VECTOR_CONVENTION = "receiver_to_sun"
FACTOR_CONVENTION = "visibility_one_clear_zero_blocked"
ELECTRICAL_SHADING_SCOPE = "not_modeled"

CURRENT_PRODUCT_NAMESPACE_PREFIX = "rawibumi."
LEGACY_PRODUCT_NAMESPACE_PREFIXES = ("opensimpv.",)


def normalize_product_namespace_identifier(value: Any) -> Any:
    """Map legacy product-scoped identifiers to the current RawiBumi namespace.

    Persisted pre-rename configurations remain readable. New runtime manifests and
    generated artifacts use the current namespace constants. Non-product values
    such as ``none`` are returned unchanged.
    """
    if not isinstance(value, str):
        return value
    for prefix in LEGACY_PRODUCT_NAMESPACE_PREFIXES:
        if value.startswith(prefix):
            return CURRENT_PRODUCT_NAMESPACE_PREFIX + value[len(prefix):]
    return value

_RECEIVER_GRANULARITIES = {"module", "pv_field", "surface", "mixed"}
_CACHE_MODES = {"none", "exact", "angular_bins"}
_ALLOWED_PHASE5_ELECTRICAL_METHODS = {None, "none", "not_modeled"}


class ShadingContractError(ValueError):
    """Raised when a geometry-aware configuration violates Phase-5.0."""


def sun_vector_from_azimuth_elevation(
    azimuth_deg: float,
    elevation_deg: float,
) -> tuple[float, float, float]:
    """Return the normalized local-ENU vector from receiver toward the sun.

    Canonical local axes are:

        X = East
        Y = North
        Z = Up

    Solar azimuth is clockwise from true/local north:

        0 deg   = North
        90 deg  = East
        180 deg = South
        270 deg = West

    Elevation is positive above the local horizon. The function defines vector
    convention only; later beam solvers decide whether a below-horizon sun
    contributes irradiance.
    """
    azimuth = float(azimuth_deg)
    elevation = float(elevation_deg)
    if not math.isfinite(azimuth) or not math.isfinite(elevation):
        raise ShadingContractError("solar azimuth/elevation must be finite")
    if elevation < -90.0 or elevation > 90.0:
        raise ShadingContractError("solar elevation must be within [-90, 90] deg")

    azimuth_rad = math.radians(azimuth % 360.0)
    elevation_rad = math.radians(elevation)
    horizontal = math.cos(elevation_rad)
    vector = (
        horizontal * math.sin(azimuth_rad),
        horizontal * math.cos(azimuth_rad),
        math.sin(elevation_rad),
    )
    norm = math.sqrt(sum(value * value for value in vector))
    if norm <= 0.0 or not math.isfinite(norm):
        raise ShadingContractError("sun vector normalization failed")
    return tuple(value / norm for value in vector)


def validate_visibility_factor(value: float) -> float:
    """Validate and return a canonical visibility factor in [0, 1]."""
    factor = float(value)
    if not math.isfinite(factor):
        raise ShadingContractError("visibility factor must be finite")
    if factor < 0.0 or factor > 1.0:
        raise ShadingContractError("visibility factor must be within [0, 1]")
    return factor


def shaded_fraction_from_visibility(visibility_factor: float) -> float:
    """Return shaded fraction using the frozen Phase-5 factor convention."""
    return 1.0 - validate_visibility_factor(visibility_factor)


def assert_geometry_aware_shading_configuration(
    configuration: Mapping[str, Any],
) -> None:
    """Fail closed when an active Phase-5 geometry configuration is ambiguous.

    The general SimulationConfiguration schema remains backward-compatible with
    Phase-4 objects. Any geometry-aware Phase-5 worker must call this stricter
    validator before physics execution.
    """
    required_exact = {
        "geometry_contract_version": CONTRACT_VERSION,
        "coordinate_basis": COORDINATE_BASIS,
        "sun_vector_convention": SUN_VECTOR_CONVENTION,
        "factor_convention": FACTOR_CONVENTION,
    }
    for field, expected in required_exact.items():
        actual = configuration.get(field)
        if actual != expected:
            raise ShadingContractError(
                f"{field} must be {expected!r} for Phase-5 geometry-aware execution"
            )

    receiver_granularity = configuration.get("receiver_granularity")
    if receiver_granularity not in _RECEIVER_GRANULARITIES:
        raise ShadingContractError(
            "receiver_granularity must be one of "
            + ", ".join(sorted(_RECEIVER_GRANULARITIES))
        )

    if not isinstance(configuration.get("self_shading_enabled"), bool):
        raise ShadingContractError("self_shading_enabled must be explicit boolean")

    if "sun_position_resolution_seconds" not in configuration:
        raise ShadingContractError(
            "sun_position_resolution_seconds must be explicit; null means use "
            "the canonical simulation solar-evaluation timestamps without "
            "additional temporal coarsening"
        )
    resolution = configuration.get("sun_position_resolution_seconds")
    if resolution is not None:
        if isinstance(resolution, bool) or not isinstance(resolution, int) or resolution < 1:
            raise ShadingContractError(
                "sun_position_resolution_seconds must be null or a positive integer"
            )

    electrical_method = configuration.get("electrical_shading_method")
    if electrical_method not in _ALLOWED_PHASE5_ELECTRICAL_METHODS:
        raise ShadingContractError(
            "Phase 5 geometry-aware execution does not model electrical shading; "
            "electrical_shading_method must be null, 'none', or 'not_modeled'"
        )
    if configuration.get("electrical_shading_configuration") is not None:
        raise ShadingContractError(
            "Phase 5 geometry-aware execution does not consume the Phase-6 "
            "electrical_shading_configuration contract"
        )

    cache_policy = configuration.get("cache_policy")
    if not isinstance(cache_policy, Mapping):
        raise ShadingContractError("cache_policy must be explicit")
    mode = cache_policy.get("mode")
    if mode not in _CACHE_MODES:
        raise ShadingContractError(
            "cache_policy.mode must be one of " + ", ".join(sorted(_CACHE_MODES))
        )

    if mode == "angular_bins":
        for field in ("sun_azimuth_bin_deg", "sun_altitude_bin_deg"):
            value = cache_policy.get(field)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ShadingContractError(
                    f"{field} must be numeric for angular_bins cache mode"
                )
            if not math.isfinite(float(value)) or float(value) <= 0.0:
                raise ShadingContractError(
                    f"{field} must be finite and greater than zero"
                )
        if float(cache_policy["sun_azimuth_bin_deg"]) > 360.0:
            raise ShadingContractError("sun_azimuth_bin_deg must be <= 360")
        if float(cache_policy["sun_altitude_bin_deg"]) > 180.0:
            raise ShadingContractError("sun_altitude_bin_deg must be <= 180")

def assert_shading_result_storage_consistency(
    result: Mapping[str, Any],
) -> None:
    """Enforce storage-mode invariants that JSON Schema cannot compare numerically."""
    mode = result.get("storage_mode")
    record_count = result.get("record_count")
    if isinstance(record_count, bool) or not isinstance(record_count, int) or record_count < 0:
        raise ShadingContractError("record_count must be a non-negative integer")

    inline_present = "inline_records" in result
    dataset_reference = result.get("dataset_reference")

    if mode == "inline":
        if not inline_present:
            raise ShadingContractError(
                "inline ShadingResult requires inline_records"
            )
        records = result.get("inline_records")
        if not isinstance(records, list):
            raise ShadingContractError("inline_records must be an array")
        if len(records) != record_count:
            raise ShadingContractError(
                "inline ShadingResult record_count must equal len(inline_records)"
            )
        if dataset_reference is not None:
            raise ShadingContractError(
                "inline ShadingResult must not carry a dataset_reference"
            )
        return

    if mode == "dataset_reference":
        if inline_present:
            raise ShadingContractError(
                "dataset_reference ShadingResult must not carry inline_records"
            )
        if not isinstance(dataset_reference, Mapping):
            raise ShadingContractError(
                "dataset_reference ShadingResult requires a dataset reference"
            )
        referenced_rows = dataset_reference.get("row_count")
        if referenced_rows != record_count:
            raise ShadingContractError(
                "dataset_reference ShadingResult record_count must equal "
                "dataset_reference.row_count"
            )
        return

    raise ShadingContractError(
        "storage_mode must be 'inline' or 'dataset_reference'"
    )

