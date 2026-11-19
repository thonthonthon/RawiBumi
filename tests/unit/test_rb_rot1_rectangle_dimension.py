"""RB-ROT1: exact dimensions preserve a rectangle along its own axes."""

import math

from fastapi.testclient import TestClient
import pytest

from apps.api.server import create_app
from geometry.scene.geometry2d import rotate_points_clockwise, set_edge_length


RECTANGLE = rotate_points_clockwise([(0, 0), (10, 0), (10, 6), (0, 6)], (5, 3), 30)
# Shared hard-coded oracle with apps/web/tests/unit/rot1-rectangle-dimension.test.ts.
EXPECTED = [
    (-0.8301270189221936, 2.901923788646684),
    (9.562177826491071, -3.098076211353316),
    (12.562177826491071, 2.098076211353316),
    (2.1698729810778064, 8.098076211353316),
]
TRAPEZOID = [(0, 0), (10, 0), (8, 6), (0, 6)]
PENTAGON = [(0, 0), (10, 0), (10, 3), (8, 6), (0, 6)]


def assert_points(actual, expected):
    assert len(actual) == len(expected)
    for point, target in zip(actual, expected):
        assert point == pytest.approx(target, rel=0, abs=1e-9)


def assert_rectangle(ring, lengths):
    edges = [(ring[(i + 1) % 4][0] - p[0], ring[(i + 1) % 4][1] - p[1])
             for i, p in enumerate(ring)]
    sizes = [math.hypot(*edge) for edge in edges]
    assert sizes == pytest.approx(lengths, rel=0, abs=1e-9)
    for i, (x, y) in enumerate(edges):
        nx, ny = edges[(i + 1) % 4]
        assert abs((x * nx + y * ny) / (sizes[i] * sizes[(i + 1) % 4])) <= 1e-9


def test_rotated_rectangle_has_shared_expected_coordinates():
    result = set_edge_length(RECTANGLE, 0, 12, preserve="rectangle")
    assert_points(result, EXPECTED)
    assert_rectangle(result, [12, 6, 12, 6])
    assert result[0] == RECTANGLE[0]
    assert result[3] == RECTANGLE[3]


@pytest.mark.parametrize("edge", range(4))
@pytest.mark.parametrize("length", [4, 12])
@pytest.mark.parametrize("clockwise", [False, True])
def test_each_edge_preserves_start_side_and_adjacent_edge_vectors(edge, length, clockwise):
    ring = list(reversed(RECTANGLE)) if clockwise else RECTANGLE
    original = list(ring)
    result = set_edge_length(ring, edge, length, preserve="rectangle")
    lengths = [math.dist(ring[i], ring[(i + 1) % 4]) for i in range(4)]
    lengths[edge] = lengths[(edge + 2) % 4] = length
    assert_rectangle(result, lengths)
    assert result[edge] == ring[edge]
    assert result[(edge - 1) % 4] == ring[(edge - 1) % 4]
    for i in ((edge + 1) % 4, (edge + 3) % 4):
        assert_points([(result[(i + 1) % 4][0] - result[i][0],
                        result[(i + 1) % 4][1] - result[i][1])],
                      [(ring[(i + 1) % 4][0] - ring[i][0],
                        ring[(i + 1) % 4][1] - ring[i][1])])
    assert ring == original


@pytest.mark.parametrize("ring,closed", [
    (TRAPEZOID, True), (PENTAGON, True), (RECTANGLE, False),
    ([(0, 0), (0, 0), (10, 6), (0, 6)], True),
])
def test_rectangle_mode_rejects_other_geometry(ring, closed):
    with pytest.raises(ValueError, match="^preserve rectangle needs a rectangle$"):
        set_edge_length(ring, 0, 12, preserve="rectangle", closed=closed)


@pytest.mark.parametrize("skew,accepted", [(0.5e-9, True), (2e-9, False)])
def test_rectangle_uses_unit_dot_product_tolerance(skew, accepted):
    ring = [(0, 0), (10, 0), (10 + 6 * skew, 6), (6 * skew, 6)]
    if accepted:
        set_edge_length(ring, 0, 12, preserve="rectangle")
    else:
        with pytest.raises(ValueError, match="preserve rectangle needs a rectangle"):
            set_edge_length(ring, 0, 12, preserve="rectangle")


def test_start_and_default_keep_the_previous_single_vertex_edit():
    expected = [RECTANGLE[0], EXPECTED[1], RECTANGLE[2], RECTANGLE[3]]
    assert_points(set_edge_length(RECTANGLE, 0, 12, preserve="start"), expected)
    assert_points(set_edge_length(RECTANGLE, 0, 12), expected)
    with pytest.raises(ValueError, match="preserve must be start, end, midpoint, or rectangle"):
        set_edge_length(RECTANGLE, 0, 12, preserve="unknown")


@pytest.mark.parametrize("kind,ring,status", [
    ("flat_roof", RECTANGLE, 200), ("exclusion_area", RECTANGLE, 200),
    ("obstacle", RECTANGLE, 200), ("flat_roof", TRAPEZOID, 422),
    ("flat_roof", PENTAGON, 422),
])
def test_api_rectangle_dimension_is_validated_and_persisted(tmp_path, kind, ring, status):
    app = create_app(store_root=tmp_path / "projects")
    service = app.state.project_service
    bundle = service.create_project(name="RB-ROT1", latitude_deg=-6.2, longitude_deg=106.8,
                                    timezone_name="Asia/Jakarta", workspace_mode="blank_engineering_plane")
    pid = bundle["project"]["project_id"]
    url = f"/api/projects/{pid}/scene/commands"
    with TestClient(app) as client:
        if kind == "obstacle":
            view = service.add_polygon_obstacle(pid, vertices=ring, height_m=2)
            entity_id = view["bundle"]["scene"]["obstacles"][-1]["obstacle_id"]
        else:
            response = client.post(url, json={"command": {
                "schema_name": "SceneEditorCommand", "schema_version": "0.1", "command_id": "rot1-draw",
                "command_type": "draw_polygon", "target_entity_ids": [],
                "parameters": {"name": "Rectangle", "surface_type": kind, "vertices": ring},
            }})
            assert response.status_code == 200, response.text
            entity_id = response.json()["bundle"]["scene"]["surfaces"][-1]["surface_id"]
        path = service.store.path_for(pid)
        before = path.read_bytes()
        response = client.post(url, json={"command": {
            "schema_name": "SceneEditorCommand", "schema_version": "0.1", "command_id": "rot1-dimension",
            "command_type": "edit_exact_dimension", "target_entity_ids": [entity_id],
            "parameters": {"edge_index": 0, "length_m": 12, "preserve": "rectangle"},
        }})
        assert response.status_code == status, response.text
        if status == 422:
            assert response.json()["detail"] == "preserve rectangle needs a rectangle"
            assert path.read_bytes() == before
        else:
            features = response.json()["scene_view"]["local_features"]
            polygon = next(f["polygon"] for f in features if f["id"] == entity_id)
            assert_points(polygon, EXPECTED)
            assert_rectangle(polygon, [12, 6, 12, 6])
            assert service.get_bundle(pid)["scene"] == response.json()["bundle"]["scene"]
