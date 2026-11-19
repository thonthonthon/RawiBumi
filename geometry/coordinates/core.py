"""Reversible WGS84 to local engineering and web-map transforms.

Canonical engineering geometry uses a local tangent-plane frame derived from WGS84.
Web Mercator exists only for map context and is never used as the engineering geometry
authority.

Rotation convention:
rotation_from_true_north_deg is positive clockwise. At zero rotation X = East,
Y = North, Z = Up. At +30 degrees the local +Y axis has true azimuth
30 degrees and the local +X axis has true azimuth 120 degrees.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any, Mapping


WGS84_SEMI_MAJOR_AXIS_M = 6_378_137.0
WGS84_INVERSE_FLATTENING = 298.257223563
WGS84_FLATTENING = 1.0 / WGS84_INVERSE_FLATTENING
WGS84_SEMI_MINOR_AXIS_M = WGS84_SEMI_MAJOR_AXIS_M * (1.0 - WGS84_FLATTENING)
WGS84_ECCENTRICITY_SQUARED = WGS84_FLATTENING * (2.0 - WGS84_FLATTENING)
WGS84_SECOND_ECCENTRICITY_SQUARED = (
    WGS84_SEMI_MAJOR_AXIS_M**2 - WGS84_SEMI_MINOR_AXIS_M**2
) / WGS84_SEMI_MINOR_AXIS_M**2

WEB_MERCATOR_MAX_LATITUDE_DEG = 85.0511287798066


def _require_finite(name: str, value: float) -> float:
    resolved = float(value)
    if not math.isfinite(resolved):
        raise ValueError(f"{name} must be finite")
    return resolved


def _validate_latitude(latitude_deg: float, *, allow_poles: bool = True) -> float:
    latitude = _require_finite("latitude_deg", latitude_deg)
    lower_ok = latitude >= -90.0 if allow_poles else latitude > -90.0
    upper_ok = latitude <= 90.0 if allow_poles else latitude < 90.0
    if not (lower_ok and upper_ok):
        bound = "[-90, 90]" if allow_poles else "(-90, 90)"
        raise ValueError(f"latitude_deg must be inside {bound}")
    return latitude


def _validate_longitude(longitude_deg: float) -> float:
    longitude = _require_finite("longitude_deg", longitude_deg)
    if longitude < -180.0 or longitude > 180.0:
        raise ValueError("longitude_deg must be inside [-180, 180]")
    return longitude


def _normalize_longitude(longitude_deg: float) -> float:
    value = (longitude_deg + 180.0) % 360.0 - 180.0
    if value == -180.0 and longitude_deg > 0.0:
        return 180.0
    return value


@dataclass(frozen=True)
class GeographicPoint:
    """WGS84 geographic coordinate.

    elevation_m is ellipsoidal height for the reversible 3-D transform. If omitted
    while converting into a local frame, the coordinate-system origin elevation is used.
    """

    latitude_deg: float
    longitude_deg: float
    elevation_m: float | None = None

    def __post_init__(self) -> None:
        _validate_latitude(self.latitude_deg)
        _validate_longitude(self.longitude_deg)
        if self.elevation_m is not None:
            _require_finite("elevation_m", self.elevation_m)


@dataclass(frozen=True)
class LocalPoint:
    """Local engineering point in metres."""

    x_m: float
    y_m: float
    z_m: float = 0.0

    def __post_init__(self) -> None:
        _require_finite("x_m", self.x_m)
        _require_finite("y_m", self.y_m)
        _require_finite("z_m", self.z_m)


@dataclass(frozen=True)
class MapPoint:
    """EPSG:3857 / Web-Mercator coordinate used only as map context."""

    x_m: float
    y_m: float


@dataclass(frozen=True)
class WorldPixelPoint:
    """Floating-point world pixel coordinate at one web-map zoom."""

    x_px: float
    y_px: float
    zoom: float
    tile_size_px: int = 512


def _geodetic_to_ecef(
    latitude_deg: float,
    longitude_deg: float,
    elevation_m: float,
) -> tuple[float, float, float]:
    latitude = math.radians(_validate_latitude(latitude_deg))
    longitude = math.radians(_validate_longitude(longitude_deg))
    elevation = _require_finite("elevation_m", elevation_m)

    sin_lat = math.sin(latitude)
    cos_lat = math.cos(latitude)
    sin_lon = math.sin(longitude)
    cos_lon = math.cos(longitude)

    prime_vertical_radius = WGS84_SEMI_MAJOR_AXIS_M / math.sqrt(
        1.0 - WGS84_ECCENTRICITY_SQUARED * sin_lat**2
    )
    x = (prime_vertical_radius + elevation) * cos_lat * cos_lon
    y = (prime_vertical_radius + elevation) * cos_lat * sin_lon
    z = (
        prime_vertical_radius * (1.0 - WGS84_ECCENTRICITY_SQUARED)
        + elevation
    ) * sin_lat
    return x, y, z


def _ecef_to_geodetic(x_m: float, y_m: float, z_m: float) -> GeographicPoint:
    x = _require_finite("ecef_x_m", x_m)
    y = _require_finite("ecef_y_m", y_m)
    z = _require_finite("ecef_z_m", z_m)

    horizontal = math.hypot(x, y)
    longitude = math.atan2(y, x)

    if horizontal < 1e-12:
        latitude = math.copysign(math.pi / 2.0, z)
        elevation = abs(z) - WGS84_SEMI_MINOR_AXIS_M
        return GeographicPoint(
            math.degrees(latitude),
            _normalize_longitude(math.degrees(longitude)),
            elevation,
        )

    theta = math.atan2(
        z * WGS84_SEMI_MAJOR_AXIS_M,
        horizontal * WGS84_SEMI_MINOR_AXIS_M,
    )
    sin_theta = math.sin(theta)
    cos_theta = math.cos(theta)

    latitude = math.atan2(
        z
        + WGS84_SECOND_ECCENTRICITY_SQUARED
        * WGS84_SEMI_MINOR_AXIS_M
        * sin_theta**3,
        horizontal
        - WGS84_ECCENTRICITY_SQUARED
        * WGS84_SEMI_MAJOR_AXIS_M
        * cos_theta**3,
    )
    sin_lat = math.sin(latitude)
    prime_vertical_radius = WGS84_SEMI_MAJOR_AXIS_M / math.sqrt(
        1.0 - WGS84_ECCENTRICITY_SQUARED * sin_lat**2
    )
    elevation = horizontal / math.cos(latitude) - prime_vertical_radius

    return GeographicPoint(
        math.degrees(latitude),
        _normalize_longitude(math.degrees(longitude)),
        elevation,
    )


@dataclass(frozen=True)
class LocalCoordinateSystem:
    """WGS84-anchored local tangent plane for canonical engineering geometry."""

    coordinate_system_id: str
    site_id: str
    origin_latitude_deg: float
    origin_longitude_deg: float
    origin_elevation_m: float
    rotation_from_true_north_deg: float = 0.0

    def __post_init__(self) -> None:
        if not self.coordinate_system_id:
            raise ValueError("coordinate_system_id must not be empty")
        if not self.site_id:
            raise ValueError("site_id must not be empty")
        _validate_latitude(self.origin_latitude_deg, allow_poles=False)
        _validate_longitude(self.origin_longitude_deg)
        _require_finite("origin_elevation_m", self.origin_elevation_m)
        rotation = _require_finite(
            "rotation_from_true_north_deg", self.rotation_from_true_north_deg
        )
        if rotation < -180.0 or rotation >= 180.0:
            raise ValueError(
                "rotation_from_true_north_deg must be inside [-180, 180)"
            )

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "LocalCoordinateSystem":
        """Build from the canonical Project.site.local_coordinate_system object."""
        return cls(
            coordinate_system_id=str(value["coordinate_system_id"]),
            site_id=str(value["site_id"]),
            origin_latitude_deg=float(value["origin_latitude_deg"]),
            origin_longitude_deg=float(value["origin_longitude_deg"]),
            origin_elevation_m=float(value["origin_elevation_m"]),
            rotation_from_true_north_deg=float(
                value.get("rotation_from_true_north_deg", 0.0)
            ),
        )

    def to_mapping(self) -> dict[str, Any]:
        return {
            "schema_name": "LocalCoordinateSystem",
            "schema_version": "0.1",
            "coordinate_system_id": self.coordinate_system_id,
            "site_id": self.site_id,
            "origin_latitude_deg": self.origin_latitude_deg,
            "origin_longitude_deg": self.origin_longitude_deg,
            "origin_elevation_m": self.origin_elevation_m,
            "geographic_crs": "EPSG:4326",
            "local_frame": "rotated_enu",
            "x_axis_definition": "East",
            "y_axis_definition": "North",
            "z_axis_definition": "Up",
            "rotation_from_true_north_deg": self.rotation_from_true_north_deg,
            "rotation_convention": "positive_clockwise_local_y_from_true_north",
            "map_projection": {
                "crs": "EPSG:3857",
                "role": "context_only",
            },
        }

    @property
    def _origin_ecef(self) -> tuple[float, float, float]:
        return _geodetic_to_ecef(
            self.origin_latitude_deg,
            self.origin_longitude_deg,
            self.origin_elevation_m,
        )

    def enu_vector_to_local(
        self,
        east_m: float,
        north_m: float,
        up_m: float = 0.0,
    ) -> LocalPoint:
        """Rotate an ENU vector into the engineering XY frame."""
        east = _require_finite("east_m", east_m)
        north = _require_finite("north_m", north_m)
        up = _require_finite("up_m", up_m)
        angle = math.radians(self.rotation_from_true_north_deg)
        x = east * math.cos(angle) - north * math.sin(angle)
        y = east * math.sin(angle) + north * math.cos(angle)
        return LocalPoint(x, y, up)

    def local_vector_to_enu(
        self,
        x_m: float,
        y_m: float,
        z_m: float = 0.0,
    ) -> tuple[float, float, float]:
        """Rotate an engineering-frame vector into East/North/Up."""
        x = _require_finite("x_m", x_m)
        y = _require_finite("y_m", y_m)
        z = _require_finite("z_m", z_m)
        angle = math.radians(self.rotation_from_true_north_deg)
        east = x * math.cos(angle) + y * math.sin(angle)
        north = -x * math.sin(angle) + y * math.cos(angle)
        return east, north, z

    def geographic_to_local(self, point: GeographicPoint) -> LocalPoint:
        """Convert WGS84 latitude/longitude to local engineering metres."""
        elevation = (
            self.origin_elevation_m
            if point.elevation_m is None
            else float(point.elevation_m)
        )
        x, y, z = _geodetic_to_ecef(
            point.latitude_deg,
            point.longitude_deg,
            elevation,
        )
        origin_x, origin_y, origin_z = self._origin_ecef
        dx = x - origin_x
        dy = y - origin_y
        dz = z - origin_z

        latitude = math.radians(self.origin_latitude_deg)
        longitude = math.radians(self.origin_longitude_deg)
        sin_lat = math.sin(latitude)
        cos_lat = math.cos(latitude)
        sin_lon = math.sin(longitude)
        cos_lon = math.cos(longitude)

        east = -sin_lon * dx + cos_lon * dy
        north = (
            -sin_lat * cos_lon * dx
            - sin_lat * sin_lon * dy
            + cos_lat * dz
        )
        up = (
            cos_lat * cos_lon * dx
            + cos_lat * sin_lon * dy
            + sin_lat * dz
        )
        return self.enu_vector_to_local(east, north, up)

    def local_to_geographic(self, point: LocalPoint) -> GeographicPoint:
        """Convert canonical local engineering metres back to WGS84."""
        east, north, up = self.local_vector_to_enu(
            point.x_m,
            point.y_m,
            point.z_m,
        )

        latitude = math.radians(self.origin_latitude_deg)
        longitude = math.radians(self.origin_longitude_deg)
        sin_lat = math.sin(latitude)
        cos_lat = math.cos(latitude)
        sin_lon = math.sin(longitude)
        cos_lon = math.cos(longitude)

        dx = (
            -sin_lon * east
            - sin_lat * cos_lon * north
            + cos_lat * cos_lon * up
        )
        dy = (
            cos_lon * east
            - sin_lat * sin_lon * north
            + cos_lat * sin_lon * up
        )
        dz = cos_lat * north + sin_lat * up

        origin_x, origin_y, origin_z = self._origin_ecef
        return _ecef_to_geodetic(
            origin_x + dx,
            origin_y + dy,
            origin_z + dz,
        )


def geographic_to_web_mercator(point: GeographicPoint) -> MapPoint:
    """Project WGS84 into EPSG:3857 for map display.

    The returned pseudo-Mercator metres are not engineering distances.
    """
    latitude = _validate_latitude(point.latitude_deg)
    if abs(latitude) > WEB_MERCATOR_MAX_LATITUDE_DEG:
        raise ValueError(
            "Web Mercator is limited to approximately +/-85.05112878 degrees"
        )
    longitude = _validate_longitude(point.longitude_deg)
    lon_rad = math.radians(longitude)
    lat_rad = math.radians(latitude)
    x = WGS84_SEMI_MAJOR_AXIS_M * lon_rad
    y = WGS84_SEMI_MAJOR_AXIS_M * math.log(
        math.tan(math.pi / 4.0 + lat_rad / 2.0)
    )
    return MapPoint(x, y)


def web_mercator_to_geographic(point: MapPoint) -> GeographicPoint:
    """Inverse EPSG:3857 map-context projection."""
    x = _require_finite("map_x_m", point.x_m)
    y = _require_finite("map_y_m", point.y_m)
    longitude = math.degrees(x / WGS84_SEMI_MAJOR_AXIS_M)
    latitude = math.degrees(
        2.0 * math.atan(math.exp(y / WGS84_SEMI_MAJOR_AXIS_M))
        - math.pi / 2.0
    )
    return GeographicPoint(latitude, _normalize_longitude(longitude), None)


def web_mercator_scale_factor(latitude_deg: float) -> float:
    """Spherical EPSG:3857 scale factor relative to local ground distance."""
    latitude = _validate_latitude(latitude_deg)
    if abs(latitude) >= 90.0:
        raise ValueError("scale factor is undefined at the poles")
    return 1.0 / math.cos(math.radians(latitude))


def web_mercator_ground_resolution_m_per_pixel(
    latitude_deg: float,
    zoom: float,
    *,
    tile_size_px: int = 512,
) -> float:
    """Approximate ground metres represented by one web-map pixel."""
    latitude = _validate_latitude(latitude_deg)
    zoom_value = _require_finite("zoom", zoom)
    if zoom_value < 0.0:
        raise ValueError("zoom must be non-negative")
    if tile_size_px <= 0:
        raise ValueError("tile_size_px must be positive")
    world_size = float(tile_size_px) * 2.0**zoom_value
    projected_m_per_px = (
        2.0 * math.pi * WGS84_SEMI_MAJOR_AXIS_M / world_size
    )
    return projected_m_per_px / web_mercator_scale_factor(latitude)


def geographic_to_world_pixel(
    point: GeographicPoint,
    zoom: float,
    *,
    tile_size_px: int = 512,
) -> WorldPixelPoint:
    """Convert WGS84 into floating-point slippy-map world pixels."""
    zoom_value = _require_finite("zoom", zoom)
    if zoom_value < 0.0:
        raise ValueError("zoom must be non-negative")
    if tile_size_px <= 0:
        raise ValueError("tile_size_px must be positive")
    mercator = geographic_to_web_mercator(point)
    circumference = 2.0 * math.pi * WGS84_SEMI_MAJOR_AXIS_M
    world_size = float(tile_size_px) * 2.0**zoom_value
    x_px = (mercator.x_m / circumference + 0.5) * world_size
    y_px = (0.5 - mercator.y_m / circumference) * world_size
    return WorldPixelPoint(x_px, y_px, zoom_value, tile_size_px)


def world_pixel_to_geographic(point: WorldPixelPoint) -> GeographicPoint:
    """Inverse floating-point slippy-map world-pixel transform."""
    zoom = _require_finite("zoom", point.zoom)
    if zoom < 0.0:
        raise ValueError("zoom must be non-negative")
    if point.tile_size_px <= 0:
        raise ValueError("tile_size_px must be positive")
    circumference = 2.0 * math.pi * WGS84_SEMI_MAJOR_AXIS_M
    world_size = float(point.tile_size_px) * 2.0**zoom
    x_m = (point.x_px / world_size - 0.5) * circumference
    y_m = (0.5 - point.y_px / world_size) * circumference
    return web_mercator_to_geographic(MapPoint(x_m, y_m))
