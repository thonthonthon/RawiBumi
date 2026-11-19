"""Phase-5.7 weighted lower-hemisphere receiver-side ground visibility."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import math
from typing import Any, Mapping, Sequence

from .beam import BeamShadowError, _fallback_evidence
from .contract import FACTOR_CONVENTION, sun_vector_from_azimuth_elevation
from .directional import (
    DIRECTIONAL_VISIBILITY_SOLVER_ID,
    DIRECTIONAL_VISIBILITY_SOLVER_VERSION,
    DirectionalVisibilityError,
    calculate_directional_receiver_visibility,
)
from .prepared import (
    PreparedDirectionalError,
    PreparedDirectionalReceiver,
    calculate_prepared_directional_receiver_visibility,
)


GROUND_VISIBILITY_SOLVER_ID = "rawibumi.ground_visibility.weighted_dome"
GROUND_VISIBILITY_SOLVER_VERSION = "0.1"
GROUND_WEIGHTING_METHOD = "patch_solid_angle_times_positive_receiver_cosine"
GROUND_BAND_COORDINATE = "uniform_sin_depression"
_WEIGHT_TOLERANCE = 1e-12


class GroundVisibilityError(ValueError):
    """Raised when weighted ground visibility cannot be evaluated safely."""


@dataclass(frozen=True)
class GroundDomeResolution:
    azimuth_sectors: int
    depression_bands: int

    def __post_init__(self) -> None:
        if (
            isinstance(self.azimuth_sectors, bool)
            or not isinstance(self.azimuth_sectors, int)
            or self.azimuth_sectors < 4
        ):
            raise GroundVisibilityError("azimuth_sectors must be an integer >= 4")
        if (
            isinstance(self.depression_bands, bool)
            or not isinstance(self.depression_bands, int)
            or self.depression_bands < 1
        ):
            raise GroundVisibilityError("depression_bands must be an integer >= 1")

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "GroundDomeResolution":
        required = {"azimuth_sectors", "depression_bands"}
        missing = sorted(required - set(value))
        if missing:
            raise GroundVisibilityError(
                "ground_dome_resolution is missing: " + ", ".join(missing)
            )
        unknown = sorted(set(value) - required)
        if unknown:
            raise GroundVisibilityError(
                "ground_dome_resolution contains unsupported field(s): "
                + ", ".join(unknown)
            )
        return cls(
            azimuth_sectors=value["azimuth_sectors"],
            depression_bands=value["depression_bands"],
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "azimuth_sectors": int(self.azimuth_sectors),
            "depression_bands": int(self.depression_bands),
            "band_coordinate": GROUND_BAND_COORDINATE,
        }


@dataclass(frozen=True)
class GroundPatch:
    patch_id: str
    azimuth_deg: float
    depression_deg: float
    direction_xyz: tuple[float, float, float]
    solid_angle_sr: float


def _dot(a: Sequence[float], b: Sequence[float]) -> float:
    return sum(float(x) * float(y) for x, y in zip(a, b))


def _normal(value: Sequence[float]) -> tuple[float, float, float]:
    if len(value) != 3:
        raise GroundVisibilityError("receiver normal must contain three coordinates")
    vector = tuple(float(item) for item in value)
    if not all(math.isfinite(item) for item in vector):
        raise GroundVisibilityError("receiver normal must be finite")
    norm = math.sqrt(sum(item * item for item in vector))
    if norm <= 0.0:
        raise GroundVisibilityError("receiver normal must have non-zero magnitude")
    return tuple(item / norm for item in vector)  # type: ignore[return-value]


@lru_cache(maxsize=128)
def _ground_patches(
    azimuth_sectors: int,
    depression_bands: int,
) -> tuple[GroundPatch, ...]:
    delta_azimuth = 2.0 * math.pi / azimuth_sectors
    result: list[GroundPatch] = []
    for band in range(depression_bands):
        mu_low = band / depression_bands
        mu_high = (band + 1) / depression_bands
        mu_center = 0.5 * (mu_low + mu_high)
        depression_deg = math.degrees(math.asin(mu_center))
        solid_angle = delta_azimuth * (mu_high - mu_low)
        for sector in range(azimuth_sectors):
            azimuth_deg = (sector + 0.5) * 360.0 / azimuth_sectors
            direction = sun_vector_from_azimuth_elevation(
                azimuth_deg,
                -depression_deg,
            )
            result.append(
                GroundPatch(
                    patch_id=f"ground:b{band:04d}:a{sector:04d}",
                    azimuth_deg=float(azimuth_deg),
                    depression_deg=float(depression_deg),
                    direction_xyz=tuple(float(item) for item in direction),
                    solid_angle_sr=float(solid_angle),
                )
            )
    return tuple(result)


def generate_ground_patches(
    resolution: GroundDomeResolution,
) -> tuple[GroundPatch, ...]:
    return _ground_patches(
        resolution.azimuth_sectors,
        resolution.depression_bands,
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
        raise GroundVisibilityError(
            f"receiver_id must resolve exactly once: {receiver_id!r}"
        )
    receiver = matches[0]
    if receiver.get("enabled") is not True:
        raise GroundVisibilityError(f"receiver is disabled: {receiver_id}")
    return receiver


def _eligible_occluder_count(
    compiled_geometry: Mapping[str, Any],
    receiver: Mapping[str, Any],
    *,
    self_shading_enabled: bool,
) -> int:
    receiver_type = str(receiver.get("source_entity_type") or "")
    receiver_source_id = str(receiver.get("source_entity_id") or "")
    count = 0
    for occluder in compiled_geometry.get("occluders", []):
        if occluder.get("shading_enabled") is not True:
            continue
        source_type = str(occluder.get("source_entity_type") or "")
        source_id = str(occluder.get("source_entity_id") or "")
        if source_type == receiver_type and source_id == receiver_source_id:
            continue
        if source_type == "module_instance" and not self_shading_enabled:
            continue
        count += 1
    return count


def calculate_ground_visibility(
    compiled_geometry: Mapping[str, Any],
    *,
    receiver_id: str,
    self_shading_enabled: bool,
    resolution: GroundDomeResolution,
    prepared_query: PreparedDirectionalReceiver | None = None,
) -> dict[str, Any]:
    """Integrate receiver-side visibility of a uniform lower-hemisphere source."""
    geometry_hash = str(compiled_geometry.get("geometry_payload_sha256") or "")
    if (
        len(geometry_hash) != 64
        or any(character not in "0123456789abcdef" for character in geometry_hash)
    ):
        raise GroundVisibilityError(
            "compiled geometry must provide lowercase geometry_payload_sha256"
        )
    if not isinstance(self_shading_enabled, bool):
        raise GroundVisibilityError("self_shading_enabled must be explicit boolean")

    receiver = _receiver(compiled_geometry, receiver_id)
    if prepared_query is not None:
        if prepared_query.compiled_geometry_hash != geometry_hash:
            raise GroundVisibilityError(
                "prepared query compiled geometry hash mismatch"
            )
        if prepared_query.receiver_id != receiver_id:
            raise GroundVisibilityError("prepared query receiver_id mismatch")
        if prepared_query.self_shading_enabled != self_shading_enabled:
            raise GroundVisibilityError(
                "prepared query self_shading_enabled mismatch"
            )
        normal = prepared_query.normal_xyz
        participant_count = prepared_query.participating_occluder_count
    else:
        normal = _normal(receiver["normal_xyz"])
        participant_count = _eligible_occluder_count(
            compiled_geometry,
            receiver,
            self_shading_enabled=self_shading_enabled,
        )
    patches = generate_ground_patches(resolution)

    fallback_events = []
    front_weight = 0.0
    visible_weight = 0.0
    evaluation_count = 0

    for patch in patches:
        cosine = _dot(normal, patch.direction_xyz)
        if cosine <= _WEIGHT_TOLERANCE:
            continue
        weight = patch.solid_angle_sr * cosine
        front_weight += weight
        if participant_count == 0:
            visibility = 1.0
        else:
            try:
                if prepared_query is not None:
                    directional = calculate_prepared_directional_receiver_visibility(
                        prepared_query,
                        source_direction_xyz=patch.direction_xyz,
                    )
                else:
                    directional = calculate_directional_receiver_visibility(
                        compiled_geometry,
                        receiver_id=receiver_id,
                        source_direction_xyz=patch.direction_xyz,
                        self_shading_enabled=self_shading_enabled,
                    )
            except (BeamShadowError, DirectionalVisibilityError, PreparedDirectionalError) as exc:
                raise GroundVisibilityError(
                    f"ground directional visibility failed at {patch.patch_id}: {exc}"
                ) from exc
            fallback_events.extend(_fallback_evidence(directional, channel="ground").get(
                "shadow_union_precision_fallback_events", []))
            visibility = float(directional["visibility_factor"])
            evaluation_count += 1
        visible_weight += weight * visibility

    has_front_ground_view = front_weight > _WEIGHT_TOLERANCE
    if has_front_ground_view:
        factor = visible_weight / front_weight
        factor = min(1.0, max(0.0, factor))
    else:
        # Neutral factor: conventional front-side ground POA is zero when the
        # receiver has no projected lower-hemisphere view.
        factor = 1.0
        visible_weight = 0.0

    return {
        **_fallback_evidence({"shadow_union_precision_fallback_events": fallback_events}),
        "schema_name": "GroundVisibilityQueryResult",
        "schema_version": "0.1",
        "solver_id": GROUND_VISIBILITY_SOLVER_ID,
        "solver_version": GROUND_VISIBILITY_SOLVER_VERSION,
        "compiled_geometry_hash": geometry_hash,
        "receiver_id": receiver_id,
        "factor_convention": FACTOR_CONVENTION,
        "self_shading_enabled": self_shading_enabled,
        "weighting_method": GROUND_WEIGHTING_METHOD,
        "ground_dome_resolution": resolution.as_dict(),
        "ground_patch_count": len(patches),
        "has_front_ground_view": has_front_ground_view,
        "ground_front_weight_sum_sr": float(front_weight),
        "ground_visible_weight_sum_sr": float(visible_weight),
        "ground_visibility_factor": float(factor),
        "directional_solver_id": DIRECTIONAL_VISIBILITY_SOLVER_ID,
        "directional_solver_version": DIRECTIONAL_VISIBILITY_SOLVER_VERSION,
        "participating_occluder_count": participant_count,
        "evaluation_count": evaluation_count,
    }
