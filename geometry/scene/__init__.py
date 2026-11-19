"""Canonical scene and constrained 2-D editor APIs."""

from .editor import SceneEditorSession
from .geometry2d import (
    Point2D,
    bounding_box,
    polygon_centroid,
    segment_azimuth_deg,
    segment_length,
    validate_polygon,
)
from .serialization import canonical_scene_hash, canonical_scene_json
from .snapping import SNAP_KINDS, SnapEngine, SnapResult
from .surface_plane import (
    SURFACE_PLANE_MODEL_VERSION,
    SurfacePlane,
    azimuth_direction,
    module_center_z,
    row_direction,
    synchronize_scene_module_center_z,
)

__all__ = [
    "Point2D",
    "SNAP_KINDS",
    "SceneEditorSession",
    "SnapEngine",
    "SnapResult",
    "SURFACE_PLANE_MODEL_VERSION",
    "SurfacePlane",
    "azimuth_direction",
    "bounding_box",
    "canonical_scene_hash",
    "canonical_scene_json",
    "module_center_z",
    "polygon_centroid",
    "segment_azimuth_deg",
    "row_direction",
    "segment_length",
    "synchronize_scene_module_center_z",
    "validate_polygon",
]
