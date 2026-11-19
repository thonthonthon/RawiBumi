"""Canonical packing inputs/results for Phase 4.3+."""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any, Mapping


PACKING_COMMAND_VERSION = "opensimpv-packing-0.2"
PACKING_GEOMETRY_BASIS = "horizontal_plan_projection"


@dataclass(frozen=True)
class ModuleFootprint:
    module_definition_revision_id: str
    physical_width_m: float
    physical_height_m: float
    orientation: str
    # Legacy names retained for compatibility: these are oriented physical
    # module-plane dimensions, not the horizontal packing projection.
    packed_width_m: float
    packed_height_m: float
    tilt_deg: float
    plan_projection_width_m: float
    plan_projection_height_m: float

    @classmethod
    def from_definition(
        cls,
        module_definition: Mapping[str, Any],
        orientation: str,
        tilt_deg: float = 0.0,
    ) -> "ModuleFootprint":
        if orientation not in {"portrait", "landscape"}:
            raise ValueError("orientation must be portrait or landscape")
        mechanical = module_definition.get("mechanical") or {}
        width = float(mechanical.get("width_m", 0.0))
        height = float(mechanical.get("height_m", 0.0))
        if not math.isfinite(width) or not math.isfinite(height):
            raise ValueError("module dimensions must be finite")
        if width <= 0.0 or height <= 0.0:
            raise ValueError(
                "module definition requires positive mechanical dimensions"
            )
        tilt = float(tilt_deg)
        if not math.isfinite(tilt) or tilt < 0.0 or tilt >= 90.0:
            raise ValueError(
                "plan-projection packing requires 0 <= tilt_deg < 90"
            )
        revision_id = str(module_definition.get("revision_id") or "")
        if not revision_id:
            raise ValueError("module definition requires revision_id")
        capabilities = module_definition.get("capability_flags") or {}
        if capabilities and capabilities.get("layout_ready") is False:
            raise ValueError("module definition is not layout_ready")

        plane_width, plane_height = (
            (width, height)
            if orientation == "portrait"
            else (height, width)
        )
        plan_width = plane_width
        plan_height = plane_height * math.cos(math.radians(tilt))
        if plan_height <= 0.0:
            raise ValueError("module plan projection must have positive area")
        return cls(
            module_definition_revision_id=revision_id,
            physical_width_m=width,
            physical_height_m=height,
            orientation=orientation,
            packed_width_m=plane_width,
            packed_height_m=plane_height,
            tilt_deg=tilt,
            plan_projection_width_m=plan_width,
            plan_projection_height_m=plan_height,
        )

    @classmethod
    def from_mapping(
        cls,
        stored: Mapping[str, Any],
        *,
        fallback_tilt_deg: float,
    ) -> "ModuleFootprint":
        tilt = float(stored.get("tilt_deg", fallback_tilt_deg))
        plane_width = float(stored["packed_width_m"])
        plane_height = float(stored["packed_height_m"])
        basis = str(stored.get("packing_basis") or "support_surface_2d")
        if basis == PACKING_GEOMETRY_BASIS:
            plan_width = float(
                stored.get("plan_projection_width_m", plane_width)
            )
            plan_height = float(
                stored.get(
                    "plan_projection_height_m",
                    plane_height * math.cos(math.radians(tilt)),
                )
            )
        elif basis == "support_surface_2d":
            # Legacy Phase-4.3 values used physical oriented dimensions in XY.
            # Reconstruct the v0.2 horizontal projection from the preserved
            # physical plane dimensions and current field tilt.
            plan_width = plane_width
            plan_height = plane_height * math.cos(math.radians(tilt))
        else:
            raise ValueError(f"unsupported module packing_basis: {basis}")
        if min(plane_width, plane_height, plan_width, plan_height) <= 0.0:
            raise ValueError("module footprint dimensions must be positive")
        return cls(
            module_definition_revision_id=str(stored["source_revision_id"]),
            physical_width_m=float(stored["physical_width_m"]),
            physical_height_m=float(stored["physical_height_m"]),
            orientation=str(stored["orientation"]),
            packed_width_m=plane_width,
            packed_height_m=plane_height,
            tilt_deg=tilt,
            plan_projection_width_m=plan_width,
            plan_projection_height_m=plan_height,
        )

    def to_mapping(self) -> dict[str, Any]:
        return {
            "source_revision_id": self.module_definition_revision_id,
            "physical_width_m": self.physical_width_m,
            "physical_height_m": self.physical_height_m,
            "orientation": self.orientation,
            "packed_width_m": self.packed_width_m,
            "packed_height_m": self.packed_height_m,
            "tilt_deg": self.tilt_deg,
            "plan_projection_width_m": self.plan_projection_width_m,
            "plan_projection_height_m": self.plan_projection_height_m,
            "packing_basis": PACKING_GEOMETRY_BASIS,
        }


@dataclass(frozen=True)
class PackingConflict:
    code: str
    module_instance_id: str | None
    related_entity_id: str | None
    message: str

    def to_mapping(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "module_instance_id": self.module_instance_id,
            "related_entity_id": self.related_entity_id,
            "message": self.message,
        }


@dataclass(frozen=True)
class PackingResult:
    pv_field: dict[str, Any]
    module_instances: tuple[dict[str, Any], ...]
    rejected_candidate_count: int
    packing_input_hash: str

    @property
    def module_count(self) -> int:
        return len(self.module_instances)
