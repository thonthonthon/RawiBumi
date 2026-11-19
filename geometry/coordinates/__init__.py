"""Site, map, and local engineering coordinate foundation."""

from .core import (
    GeographicPoint,
    LocalCoordinateSystem,
    LocalPoint,
    MapPoint,
    WorldPixelPoint,
    WEB_MERCATOR_MAX_LATITUDE_DEG,
    geographic_to_web_mercator,
    geographic_to_world_pixel,
    web_mercator_ground_resolution_m_per_pixel,
    web_mercator_scale_factor,
    web_mercator_to_geographic,
    world_pixel_to_geographic,
)
from .map_layers import MapLayer, MapLayerConfiguration, MapProvider
from .measurement import (
    SegmentMeasurement,
    measure_geographic_segment,
    measure_local_segment,
    measure_world_pixel_segment,
)
from .orthophoto import (
    AffineTransform2D,
    OrthophotoCalibration,
    OrthophotoControlPoint,
    fit_affine_control_points,
    measure_orthophoto_segment,
)

__all__ = [
    "AffineTransform2D",
    "GeographicPoint",
    "LocalCoordinateSystem",
    "LocalPoint",
    "MapPoint",
    "MapLayer",
    "MapLayerConfiguration",
    "MapProvider",
    "OrthophotoCalibration",
    "OrthophotoControlPoint",
    "SegmentMeasurement",
    "WEB_MERCATOR_MAX_LATITUDE_DEG",
    "WorldPixelPoint",
    "fit_affine_control_points",
    "geographic_to_web_mercator",
    "geographic_to_world_pixel",
    "measure_geographic_segment",
    "measure_local_segment",
    "measure_orthophoto_segment",
    "measure_world_pixel_segment",
    "web_mercator_ground_resolution_m_per_pixel",
    "web_mercator_scale_factor",
    "web_mercator_to_geographic",
    "world_pixel_to_geographic",
]
