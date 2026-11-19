"""Phase-5.6 deterministic weighted sky-dome visibility.

The reference solver integrates directional geometric receiver visibility over a
discrete global upper hemisphere. Every patch is weighted by exact patch solid
angle and the positive receiver cosine response. Directional visibility itself
reuses the analytically validated Phase-5.3 polygon-projection kernel.

The same machinery evaluates a separate low-elevation horizon band. Circumsolar
visibility is intentionally not calculated here because it is sun-state
dependent and is supplied by the Phase-5.5 direct-beam path.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import math
from typing import Any, Mapping, Sequence

from .beam import (
    _fallback_evidence,
    BEAM_SOLVER_ID,
    BEAM_SOLVER_VERSION,
    BeamShadowError,
    calculate_direct_beam_shadow,
)
from .contract import FACTOR_CONVENTION, sun_vector_from_azimuth_elevation
from .prepared import (
    PreparedDirectionalError,
    PreparedDirectionalReceiver,
    calculate_prepared_direct_beam_shadow,
)


SKY_VISIBILITY_SOLVER_ID = "rawibumi.sky_visibility.weighted_dome"
SKY_VISIBILITY_SOLVER_VERSION = "0.1"
SKY_WEIGHTING_METHOD = "patch_solid_angle_times_positive_receiver_cosine"
SKY_BAND_COORDINATE = "uniform_sin_elevation"
_FACTOR_TOLERANCE = 1e-12
_COSINE_TOLERANCE = 1e-12


class SkyVisibilityError(ValueError):
    """Raised when weighted sky visibility cannot be evaluated defensibly."""


@dataclass(frozen=True)
class SkyDomeResolution:
    """Explicit Phase-5.6 sky and horizon discretization."""

    azimuth_sectors: int
    elevation_bands: int
    horizon_azimuth_sectors: int
    horizon_elevation_bands: int
    horizon_band_elevation_deg: float

    def __post_init__(self) -> None:
        for value, name, minimum in (
            (self.azimuth_sectors, "azimuth_sectors", 4),
            (self.elevation_bands, "elevation_bands", 1),
            (self.horizon_azimuth_sectors, "horizon_azimuth_sectors", 4),
            (self.horizon_elevation_bands, "horizon_elevation_bands", 1),
        ):
            if isinstance(value, bool) or not isinstance(value, int):
                raise SkyVisibilityError(f"{name} must be an integer")
            if value < minimum:
                raise SkyVisibilityError(f"{name} must be >= {minimum}")

        horizon = float(self.horizon_band_elevation_deg)
        if not math.isfinite(horizon) or not 0.0 < horizon <= 45.0:
            raise SkyVisibilityError(
                "horizon_band_elevation_deg must be finite and within (0, 45]"
            )

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "SkyDomeResolution":
        required = (
            "azimuth_sectors",
            "elevation_bands",
            "horizon_azimuth_sectors",
            "horizon_elevation_bands",
            "horizon_band_elevation_deg",
        )
        missing = [field for field in required if field not in value]
        if missing:
            raise SkyVisibilityError(
                "sky_dome_resolution is missing: " + ", ".join(missing)
            )
        unknown = sorted(set(value) - set(required))
        if unknown:
            raise SkyVisibilityError(
                "sky_dome_resolution contains unsupported field(s): "
                + ", ".join(unknown)
            )
        return cls(
            azimuth_sectors=value["azimuth_sectors"],
            elevation_bands=value["elevation_bands"],
            horizon_azimuth_sectors=value["horizon_azimuth_sectors"],
            horizon_elevation_bands=value["horizon_elevation_bands"],
            horizon_band_elevation_deg=float(
                value["horizon_band_elevation_deg"]
            ),
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "azimuth_sectors": int(self.azimuth_sectors),
            "elevation_bands": int(self.elevation_bands),
            "horizon_azimuth_sectors": int(self.horizon_azimuth_sectors),
            "horizon_elevation_bands": int(self.horizon_elevation_bands),
            "horizon_band_elevation_deg": float(
                self.horizon_band_elevation_deg
            ),
            "band_coordinate": SKY_BAND_COORDINATE,
        }


@dataclass(frozen=True)
class SkyPatch:
    patch_id: str
    azimuth_deg: float
    elevation_deg: float
    direction_xyz: tuple[float, float, float]
    solid_angle_sr: float


def _dot(a: Sequence[float], b: Sequence[float]) -> float:
    return float(a[0]) * float(b[0]) + float(a[1]) * float(b[1]) + float(a[2]) * float(b[2])


def _normal(value: Sequence[float]) -> tuple[float, float, float]:
    if len(value) != 3:
        raise SkyVisibilityError("receiver normal must contain three coordinates")
    vector = tuple(float(item) for item in value)
    if not all(math.isfinite(item) for item in vector):
        raise SkyVisibilityError("receiver normal must be finite")
    norm = math.sqrt(sum(item * item for item in vector))
    if norm <= 0.0:
        raise SkyVisibilityError("receiver normal must have non-zero magnitude")
    return tuple(item / norm for item in vector)  # type: ignore[return-value]


@lru_cache(maxsize=128)
def _patches(
    azimuth_sectors: int,
    elevation_bands: int,
    maximum_elevation_deg: float,
    prefix: str,
) -> tuple[SkyPatch, ...]:
    """Generate equal-solid-angle bands using mu = sin(elevation)."""
    if azimuth_sectors < 4 or elevation_bands < 1:
        raise SkyVisibilityError("invalid sky-patch resolution")
    maximum = float(maximum_elevation_deg)
    if not 0.0 < maximum <= 90.0:
        raise SkyVisibilityError("maximum_elevation_deg must be within (0, 90]")

    mu_max = math.sin(math.radians(maximum))
    delta_azimuth_rad = 2.0 * math.pi / azimuth_sectors
    result: list[SkyPatch] = []

    for band in range(elevation_bands):
        mu_low = mu_max * band / elevation_bands
        mu_high = mu_max * (band + 1) / elevation_bands
        mu_center = 0.5 * (mu_low + mu_high)
        elevation_deg = math.degrees(math.asin(mu_center))
        solid_angle = delta_azimuth_rad * (mu_high - mu_low)

        for sector in range(azimuth_sectors):
            azimuth_deg = (sector + 0.5) * 360.0 / azimuth_sectors
            direction = sun_vector_from_azimuth_elevation(
                azimuth_deg,
                elevation_deg,
            )
            result.append(
                SkyPatch(
                    patch_id=f"{prefix}:b{band:04d}:a{sector:04d}",
                    azimuth_deg=float(azimuth_deg),
                    elevation_deg=float(elevation_deg),
                    direction_xyz=tuple(float(item) for item in direction),
                    solid_angle_sr=float(solid_angle),
                )
            )
    return tuple(result)


def generate_sky_patches(
    resolution: SkyDomeResolution,
) -> tuple[SkyPatch, ...]:
    """Return the deterministic full global-upper-hemisphere dome."""
    return _patches(
        resolution.azimuth_sectors,
        resolution.elevation_bands,
        90.0,
        "sky",
    )


def generate_horizon_patches(
    resolution: SkyDomeResolution,
) -> tuple[SkyPatch, ...]:
    """Return a deterministic low-elevation directional horizon band."""
    return _patches(
        resolution.horizon_azimuth_sectors,
        resolution.horizon_elevation_bands,
        float(resolution.horizon_band_elevation_deg),
        "horizon",
    )


def _receiver(
    compiled_geometry: Mapping[str, Any],
    receiver_id: str,
) -> Mapping[str, Any]:
    matches = [
        item
        for item in compiled_geometry.get("receivers", [])
        if str(item.get("receiver_id")) == receiver_id
    ]
    if len(matches) != 1:
        raise SkyVisibilityError(
            f"receiver_id must resolve exactly once: {receiver_id!r}"
        )
    receiver = matches[0]
    if receiver.get("enabled") is not True:
        raise SkyVisibilityError(f"receiver is disabled: {receiver_id}")
    return receiver


def _receiver_query_geometry(
    compiled_geometry: Mapping[str, Any],
    receiver: Mapping[str, Any],
    *,
    self_shading_enabled: bool,
) -> tuple[dict[str, Any], int]:
    """Remove occluders that the Phase-5.3 kernel would ignore anyway."""
    receiver_type = str(receiver.get("source_entity_type") or "")
    receiver_source_id = str(receiver.get("source_entity_id") or "")
    eligible: list[Mapping[str, Any]] = []

    for occluder in compiled_geometry.get("occluders", []):
        if occluder.get("shading_enabled") is not True:
            continue
        source_type = str(occluder.get("source_entity_type") or "")
        source_id = str(occluder.get("source_entity_id") or "")
        if source_type == receiver_type and source_id == receiver_source_id:
            continue
        if source_type == "module_instance" and not self_shading_enabled:
            continue
        eligible.append(occluder)

    query_geometry = dict(compiled_geometry)
    query_geometry["occluders"] = sorted(
        eligible,
        key=lambda item: str(item.get("occluder_id", "")),
    )
    return query_geometry, len(eligible)


def _bounded_factor(numerator: float, denominator: float, *, name: str) -> float:
    if not math.isfinite(numerator) or not math.isfinite(denominator):
        raise SkyVisibilityError(f"{name} weights must be finite")
    if denominator <= 0.0:
        raise SkyVisibilityError(f"{name} front-facing weight must be positive")
    factor = numerator / denominator
    if factor < -_FACTOR_TOLERANCE or factor > 1.0 + _FACTOR_TOLERANCE:
        raise SkyVisibilityError(f"{name} visibility escaped [0, 1]")
    return min(1.0, max(0.0, factor))


def _integrate_patch_set(
    compiled_geometry: Mapping[str, Any],
    *,
    receiver_id: str,
    receiver_normal: Sequence[float],
    patches: Sequence[SkyPatch],
    self_shading_enabled: bool,
    has_occluders: bool,
    prepared_query: PreparedDirectionalReceiver | None = None,
    fallback_events: list | None = None,
    channel: str = "sky",
) -> tuple[float, float, int]:
    front_weight = 0.0
    visible_weight = 0.0
    evaluation_count = 0

    for patch in patches:
        cosine = _dot(receiver_normal, patch.direction_xyz)
        if cosine <= _COSINE_TOLERANCE:
            continue
        weight = float(patch.solid_angle_sr) * cosine
        front_weight += weight

        if has_occluders:
            try:
                if prepared_query is not None:
                    beam = calculate_prepared_direct_beam_shadow(
                        prepared_query,
                        sun_vector_xyz=patch.direction_xyz,
                    )
                else:
                    beam = calculate_direct_beam_shadow(
                        compiled_geometry,
                        receiver_id=receiver_id,
                        sun_vector_xyz=patch.direction_xyz,
                        self_shading_enabled=self_shading_enabled,
                    )
            except (BeamShadowError, PreparedDirectionalError) as exc:
                raise SkyVisibilityError(
                    f"directional visibility failed at {patch.patch_id}: {exc}"
                ) from exc
            if fallback_events is not None:
                fallback_events.extend(_fallback_evidence(beam, channel=channel).get(
                    "shadow_union_precision_fallback_events", []))
            visibility = float(beam["beam_visibility_factor"])
            evaluation_count += 1
        else:
            visibility = 1.0

        visible_weight += weight * visibility

    return front_weight, visible_weight, evaluation_count


def calculate_sky_visibility(
    compiled_geometry: Mapping[str, Any],
    *,
    receiver_id: str,
    self_shading_enabled: bool,
    resolution: SkyDomeResolution,
    prepared_query: PreparedDirectionalReceiver | None = None,
) -> dict[str, Any]:
    """Calculate weighted isotropic-sky and horizon-band visibility."""
    if not isinstance(self_shading_enabled, bool):
        raise SkyVisibilityError("self_shading_enabled must be explicit boolean")

    geometry_hash = str(compiled_geometry.get("geometry_payload_sha256") or "")
    if (
        len(geometry_hash) != 64
        or any(character not in "0123456789abcdef" for character in geometry_hash)
    ):
        raise SkyVisibilityError(
            "compiled geometry must provide lowercase geometry_payload_sha256"
        )

    receiver = _receiver(compiled_geometry, receiver_id)
    if prepared_query is not None:
        if prepared_query.compiled_geometry_hash != geometry_hash:
            raise SkyVisibilityError(
                "prepared query compiled geometry hash mismatch"
            )
        if prepared_query.receiver_id != receiver_id:
            raise SkyVisibilityError("prepared query receiver_id mismatch")
        if prepared_query.self_shading_enabled != self_shading_enabled:
            raise SkyVisibilityError(
                "prepared query self_shading_enabled mismatch"
            )
        normal = prepared_query.normal_xyz
        query_geometry = compiled_geometry
        participant_count = prepared_query.participating_occluder_count
    else:
        normal = _normal(receiver["normal_xyz"])
        query_geometry, participant_count = _receiver_query_geometry(
            compiled_geometry,
            receiver,
            self_shading_enabled=self_shading_enabled,
        )
    has_occluders = participant_count > 0

    sky_patches = generate_sky_patches(resolution)
    horizon_patches = generate_horizon_patches(resolution)

    fallback_events = []
    sky_front, sky_visible, sky_evaluations = _integrate_patch_set(
        query_geometry,
        receiver_id=receiver_id,
        receiver_normal=normal,
        patches=sky_patches,
        fallback_events=fallback_events, channel="sky",
        self_shading_enabled=self_shading_enabled,
        has_occluders=has_occluders,
        prepared_query=prepared_query,
    )
    horizon_front, horizon_visible, horizon_evaluations = _integrate_patch_set(
        query_geometry,
        receiver_id=receiver_id,
        receiver_normal=normal,
        patches=horizon_patches,
        fallback_events=fallback_events, channel="horizon",
        self_shading_enabled=self_shading_enabled,
        has_occluders=has_occluders,
        prepared_query=prepared_query,
    )

    return {
        **_fallback_evidence({"shadow_union_precision_fallback_events": fallback_events}),
        "schema_name": "SkyVisibilityQueryResult",
        "schema_version": "0.1",
        "solver_id": SKY_VISIBILITY_SOLVER_ID,
        "solver_version": SKY_VISIBILITY_SOLVER_VERSION,
        "compiled_geometry_hash": geometry_hash,
        "receiver_id": receiver_id,
        "factor_convention": FACTOR_CONVENTION,
        "self_shading_enabled": self_shading_enabled,
        "weighting_method": SKY_WEIGHTING_METHOD,
        "sky_dome_resolution": resolution.as_dict(),
        "sky_patch_count": len(sky_patches),
        "horizon_patch_count": len(horizon_patches),
        "sky_front_weight_sum_sr": float(sky_front),
        "sky_visible_weight_sum_sr": float(sky_visible),
        "horizon_front_weight_sum_sr": float(horizon_front),
        "horizon_visible_weight_sum_sr": float(horizon_visible),
        "sky_visibility_factor": _bounded_factor(
            sky_visible,
            sky_front,
            name="sky",
        ),
        "horizon_visibility_factor": _bounded_factor(
            horizon_visible,
            horizon_front,
            name="horizon",
        ),
        "beam_solver_id": BEAM_SOLVER_ID,
        "beam_solver_version": BEAM_SOLVER_VERSION,
        "participating_occluder_count": participant_count,
        "evaluation_count": sky_evaluations + horizon_evaluations,
    }
