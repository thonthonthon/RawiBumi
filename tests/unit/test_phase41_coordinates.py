import json
import math
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from referencing import Registry, Resource

from geometry.coordinates import (
    GeographicPoint,
    LocalCoordinateSystem,
    LocalPoint,
    MapLayerConfiguration,
    OrthophotoControlPoint,
    fit_affine_control_points,
    geographic_to_web_mercator,
    geographic_to_world_pixel,
    measure_geographic_segment,
    measure_local_segment,
    measure_orthophoto_segment,
    measure_world_pixel_segment,
    web_mercator_ground_resolution_m_per_pixel,
    web_mercator_to_geographic,
)


ROOT = Path(__file__).resolve().parents[2]


def _coordinate_system(*, rotation_deg=0.0, longitude_deg=106.8):
    return LocalCoordinateSystem(
        coordinate_system_id="enu-phase41",
        site_id="site-phase41",
        origin_latitude_deg=-6.0,
        origin_longitude_deg=longitude_deg,
        origin_elevation_m=100.0,
        rotation_from_true_north_deg=rotation_deg,
    )


def _schema_registry():
    registry = Registry()
    directories = (
        ROOT / "schemas",
        ROOT / "components/schema",
        ROOT / "weather/schema",
        ROOT / "geometry/scene",
        ROOT / "geometry/coordinates",
        ROOT / "electrical/schema",
    )
    for directory in directories:
        for path in directory.glob("*.schema.json"):
            schema = json.loads(path.read_text(encoding="utf-8"))
            if "$id" in schema:
                registry = registry.with_resource(
                    schema["$id"], Resource.from_contents(schema)
                )
    return registry


def test_phase41_project_and_scene_fixtures_validate_coordinate_map_contracts():
    project = json.loads(
        (ROOT / "tests/fixtures/schema/project.example.json").read_text(
            encoding="utf-8"
        )
    )
    scene = json.loads(
        (ROOT / "tests/fixtures/schema/scene.example.json").read_text(
            encoding="utf-8"
        )
    )
    project_schema = json.loads(
        (ROOT / "schemas/project.schema.json").read_text(encoding="utf-8")
    )
    scene_schema = json.loads(
        (ROOT / "geometry/scene/scene.schema.json").read_text(
            encoding="utf-8"
        )
    )
    registry = _schema_registry()

    Draft202012Validator(project_schema, registry=registry).validate(project)
    Draft202012Validator(scene_schema, registry=registry).validate(scene)

    coordinate = project["site"]["local_coordinate_system"]
    assert scene["coordinate_system_id"] == coordinate["coordinate_system_id"]
    assert project["site"]["north_reference"] == "geodetic_true_north"
    assert coordinate["geographic_crs"] == "EPSG:4326"
    assert coordinate["map_projection"] == {
        "crs": "EPSG:3857",
        "role": "context_only",
    }

    maps = scene["map_layer_configuration"]
    assert maps["engineering_geometry_authority"] == "local_metric"
    assert maps["map_measurement_role"] == "context_only"
    ortho = next(
        item for item in maps["layers"] if item["layer_type"] == "orthophoto"
    )
    assert ortho["imported_asset_id"] == "asset-ortho-ref-001"
    assert len(ortho["orthophoto_georeference"]["control_points"]) >= 3



def test_provider_abstraction_preserves_required_attribution_and_refs():
    scene = json.loads(
        (ROOT / "tests/fixtures/schema/scene.example.json").read_text(
            encoding="utf-8"
        )
    )
    config = MapLayerConfiguration.from_mapping(
        scene["map_layer_configuration"]
    )
    assert config.engineering_geometry_authority == "local_metric"
    assert config.map_measurement_role == "context_only"
    assert config.required_attributions() == ()

    external = {
        "schema_name": "MapLayerConfiguration",
        "schema_version": "0.1",
        "map_configuration_id": "map-attribution",
        "engineering_geometry_authority": "local_metric",
        "map_measurement_role": "context_only",
        "providers": [
            {
                "provider_id": "provider-public",
                "provider_kind": "xyz_raster",
                "name": "Public raster provider",
                "tile_url_template": "https://tiles.example.invalid/{z}/{x}/{y}.png",
                "style_url": None,
                "credential_reference": None,
                "attribution_required": True,
                "attribution": "Synthetic map attribution",
                "license_note": "Fixture only.",
            }
        ],
        "layers": [
            {
                "layer_id": "base",
                "layer_type": "base_map",
                "provider_id": "provider-public",
                "source_record_id": "source-map-provider",
                "imported_asset_id": None,
                "orthophoto_georeference": None,
                "notes": None,
            }
        ],
    }
    parsed = MapLayerConfiguration.from_mapping(external)
    assert parsed.required_attributions() == ("Synthetic map attribution",)


def test_provider_abstraction_rejects_missing_required_attribution():
    invalid = {
        "map_configuration_id": "map-invalid",
        "engineering_geometry_authority": "local_metric",
        "map_measurement_role": "context_only",
        "providers": [
            {
                "provider_id": "provider-public",
                "provider_kind": "xyz_raster",
                "name": "Public raster provider",
                "attribution_required": True,
                "attribution": None,
            }
        ],
        "layers": [],
    }
    with pytest.raises(ValueError, match="requires attribution"):
        MapLayerConfiguration.from_mapping(invalid)

def test_coordinate_mapping_serializes_to_canonical_schema():
    coordinate = _coordinate_system(rotation_deg=12.0)
    mapping = coordinate.to_mapping()
    schema = json.loads(
        (
            ROOT
            / "geometry/coordinates/local-coordinate-system.schema.json"
        ).read_text(encoding="utf-8")
    )
    Draft202012Validator(schema).validate(mapping)
    recovered = LocalCoordinateSystem.from_mapping(mapping)
    assert recovered == coordinate


def test_origin_is_zero_and_geo_local_geo_round_trip_is_sub_millimetre():
    coordinate = _coordinate_system(rotation_deg=17.5)
    origin = GeographicPoint(-6.0, 106.8, 100.0)

    local_origin = coordinate.geographic_to_local(origin)
    assert local_origin.x_m == pytest.approx(0.0, abs=2e-9)
    assert local_origin.y_m == pytest.approx(0.0, abs=2e-9)
    assert local_origin.z_m == pytest.approx(0.0, abs=2e-9)

    for local in (
        LocalPoint(0.001, 0.002, 0.003),
        LocalPoint(12.5, 7.25, 8.0),
        LocalPoint(5_000.0, 3_000.0, 50.0),
        LocalPoint(-12_000.0, 8_000.0, -10.0),
    ):
        geographic = coordinate.local_to_geographic(local)
        recovered = coordinate.geographic_to_local(geographic)
        assert recovered.x_m == pytest.approx(local.x_m, abs=1e-6)
        assert recovered.y_m == pytest.approx(local.y_m, abs=1e-6)
        assert recovered.z_m == pytest.approx(local.z_m, abs=1e-6)


def test_map_zoom_does_not_change_ten_metre_engineering_dimension():
    coordinate = _coordinate_system()
    start_geo = coordinate.local_to_geographic(LocalPoint(0.0, 0.0, 0.0))
    end_geo = coordinate.local_to_geographic(LocalPoint(10.0, 0.0, 0.0))

    direct = measure_geographic_segment(start_geo, end_geo, coordinate)
    assert direct.horizontal_distance_m == pytest.approx(10.0, abs=1e-6)

    measured = []
    pixel_separations = []
    for zoom in (8.0, 20.0):
        start_px = geographic_to_world_pixel(start_geo, zoom)
        end_px = geographic_to_world_pixel(end_geo, zoom)
        pixel_separations.append(
            math.hypot(
                end_px.x_px - start_px.x_px,
                end_px.y_px - start_px.y_px,
            )
        )
        measured.append(
            measure_world_pixel_segment(start_px, end_px, coordinate)
            .horizontal_distance_m
        )

    assert measured[0] == pytest.approx(10.0, abs=2e-5)
    assert measured[1] == pytest.approx(10.0, abs=2e-5)
    assert pixel_separations[1] > pixel_separations[0] * 1000.0


def test_true_north_and_rotated_local_axis_convention():
    coordinate = _coordinate_system(rotation_deg=30.0)

    local_y = measure_local_segment(
        LocalPoint(0.0, 0.0),
        LocalPoint(0.0, 10.0),
        coordinate,
    )
    assert local_y.local_azimuth_deg == pytest.approx(0.0, abs=1e-12)
    assert local_y.true_azimuth_deg == pytest.approx(30.0, abs=1e-12)

    local_x = measure_local_segment(
        LocalPoint(0.0, 0.0),
        LocalPoint(10.0, 0.0),
        coordinate,
    )
    assert local_x.local_azimuth_deg == pytest.approx(90.0, abs=1e-12)
    assert local_x.true_azimuth_deg == pytest.approx(120.0, abs=1e-12)

    true_north_local = coordinate.enu_vector_to_local(0.0, 25.0)
    true_north = measure_local_segment(
        LocalPoint(0.0, 0.0),
        true_north_local,
        coordinate,
    )
    assert true_north.horizontal_distance_m == pytest.approx(25.0, abs=1e-12)
    assert true_north.true_azimuth_deg == pytest.approx(0.0, abs=1e-12)


def test_small_rooftop_dimensions_survive_geographic_round_trip():
    coordinate = _coordinate_system()
    corners = [
        LocalPoint(0.0, 0.0),
        LocalPoint(12.5, 0.0),
        LocalPoint(12.5, 7.25),
        LocalPoint(0.0, 7.25),
    ]
    recovered = [
        coordinate.geographic_to_local(coordinate.local_to_geographic(point))
        for point in corners
    ]

    length = measure_local_segment(recovered[0], recovered[1], coordinate)
    width = measure_local_segment(recovered[1], recovered[2], coordinate)
    assert length.horizontal_distance_m == pytest.approx(12.5, abs=1e-6)
    assert width.horizontal_distance_m == pytest.approx(7.25, abs=1e-6)


def test_large_ground_site_round_trip_remains_precise():
    coordinate = _coordinate_system(rotation_deg=-12.0)
    target = LocalPoint(15_000.0, -8_000.0, 120.0)
    geographic = coordinate.local_to_geographic(target)
    recovered = coordinate.geographic_to_local(geographic)

    assert recovered.x_m == pytest.approx(target.x_m, abs=2e-6)
    assert recovered.y_m == pytest.approx(target.y_m, abs=2e-6)
    assert recovered.z_m == pytest.approx(target.z_m, abs=2e-6)


def test_local_frame_is_continuous_across_utm_like_zone_boundary():
    # Longitude 6 degrees E is a UTM zone boundary. The canonical local frame
    # is tangent-plane ENU and therefore has no zone discontinuity.
    coordinate = LocalCoordinateSystem(
        coordinate_system_id="enu-zone-boundary",
        site_id="site-zone-boundary",
        origin_latitude_deg=0.0,
        origin_longitude_deg=5.99995,
        origin_elevation_m=0.0,
    )
    west = coordinate.geographic_to_local(
        GeographicPoint(0.0, 5.99995, 0.0)
    )
    east = coordinate.geographic_to_local(
        GeographicPoint(0.0, 6.00005, 0.0)
    )
    measurement = measure_local_segment(west, east, coordinate)

    assert 11.0 < measurement.horizontal_distance_m < 11.2
    recovered = coordinate.local_to_geographic(east)
    assert recovered.longitude_deg == pytest.approx(6.00005, abs=1e-11)


def test_web_mercator_is_reversible_context_and_scale_halves_each_zoom():
    point = GeographicPoint(-6.0, 106.8)
    mercator = geographic_to_web_mercator(point)
    recovered = web_mercator_to_geographic(mercator)

    assert recovered.latitude_deg == pytest.approx(point.latitude_deg, abs=1e-12)
    assert recovered.longitude_deg == pytest.approx(
        point.longitude_deg, abs=1e-12
    )

    resolution_18 = web_mercator_ground_resolution_m_per_pixel(-6.0, 18)
    resolution_19 = web_mercator_ground_resolution_m_per_pixel(-6.0, 19)
    assert resolution_19 == pytest.approx(resolution_18 / 2.0, rel=1e-12)


def test_uploaded_orthophoto_affine_reference_measures_in_local_metres():
    control_points = [
        OrthophotoControlPoint(0.0, 0.0, 0.0, 100.0),
        OrthophotoControlPoint(1000.0, 0.0, 100.0, 100.0),
        OrthophotoControlPoint(0.0, 1000.0, 0.0, 0.0),
        OrthophotoControlPoint(1000.0, 1000.0, 100.0, 0.0),
    ]
    calibration = fit_affine_control_points(control_points)

    assert calibration.control_point_count == 4
    assert calibration.rms_error_m == pytest.approx(0.0, abs=1e-10)

    measurement = measure_orthophoto_segment(
        (100.0, 500.0),
        (200.0, 500.0),
        calibration,
        _coordinate_system(),
    )
    assert measurement.horizontal_distance_m == pytest.approx(10.0, abs=1e-10)
    assert measurement.true_azimuth_deg == pytest.approx(90.0, abs=1e-10)

    local = calibration.transform.pixel_to_local(250.0, 750.0)
    pixel = calibration.transform.local_to_pixel(local.x_m, local.y_m)
    assert pixel[0] == pytest.approx(250.0, abs=1e-10)
    assert pixel[1] == pytest.approx(750.0, abs=1e-10)


def test_degenerate_orthophoto_control_points_fail_closed():
    with pytest.raises(ValueError, match="degenerate"):
        fit_affine_control_points(
            [
                OrthophotoControlPoint(0.0, 0.0, 0.0, 0.0),
                OrthophotoControlPoint(1.0, 1.0, 1.0, 1.0),
                OrthophotoControlPoint(2.0, 2.0, 2.0, 2.0),
            ]
        )


def test_invalid_coordinate_rotation_and_web_mercator_poles_fail_closed():
    with pytest.raises(ValueError, match="rotation_from_true_north_deg"):
        _coordinate_system(rotation_deg=180.0)

    with pytest.raises(ValueError, match="Web Mercator"):
        geographic_to_web_mercator(GeographicPoint(89.0, 0.0))
