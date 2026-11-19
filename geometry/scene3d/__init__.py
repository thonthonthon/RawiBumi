"""Phase-4.4 deterministic 3-D verification APIs."""

from .generator import generate_scene3d, generation_input_hash
from .height import (
    HEIGHT_MODEL_VERSION,
    Point3D,
    SurfacePlane,
    azimuth_direction,
    bounds3d,
    distance3d,
    module_axes,
    module_corners,
    row_direction,
)
from .serialization import canonical_scene3d_hash, canonical_scene3d_json

__all__ = [
    "HEIGHT_MODEL_VERSION",
    "Point3D",
    "SurfacePlane",
    "azimuth_direction",
    "bounds3d",
    "canonical_scene3d_hash",
    "canonical_scene3d_json",
    "distance3d",
    "generate_scene3d",
    "generation_input_hash",
    "module_axes",
    "module_corners",
    "row_direction",
]
