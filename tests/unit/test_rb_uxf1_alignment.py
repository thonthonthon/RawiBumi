"""UXF1 (U2-6): nine-point fill alignment. Along the rows: row_alignment; across: depth_alignment (start = back/high
side at min field y, end = front/low side). An anchor never places fewer modules than the fill without it."""
import math

import pytest

from geometry.pvfield import PVFieldPackingSession
from geometry.scene import canonical_scene_json
from tests.unit.test_phase43_pvfield_packing import MODULE, _field, _modules, _roof_scene
from tests.unit.test_rb_fix_s2_honest_preflight import Project

ROW_Y = math.cos(math.radians(10.0))  # half the plan depth of a 2 m module at 10° tilt


def _session(scene, *, azimuth=0.0, **alignment):
    session = PVFieldPackingSession(scene, {MODULE["revision_id"]: MODULE})
    session.create_field(
        pv_field_id="field-1", name="Field 1", support_surface_id="roof",
        module_definition_revision_id=MODULE["revision_id"], orientation="portrait", azimuth_deg=azimuth,
        tilt_deg=10.0, module_gap_x_m=0.0, module_gap_y_m=0.0, row_pitch_m=2.0, mounting_height_m=0.2, **alignment)
    session.fill_area("field-1")
    return session


def _extent(scene):
    xs = [m["transform"]["position_x_m"] for m in _modules(scene)]
    ys = [m["transform"]["position_y_m"] for m in _modules(scene)]
    return min(xs), min(ys), len(xs)


@pytest.mark.parametrize("row", ["start", "center", "end"])
@pytest.mark.parametrize("depth", ["start", "center", "end"])
def test_each_of_the_nine_anchors_moves_the_layout_as_named_with_the_same_count(row, depth):
    # 10.5 m x 9 m roof: 0.5 m spare along the rows, 9 - 2*ROW_Y - 3*2 m spare across them.
    min_x, min_y, count = _extent(_session(_roof_scene(width=10.5, height=9.0), row_alignment=row, depth_alignment=depth).scene)
    spare_depth = 9.0 - 2 * ROW_Y - 6.0
    assert count == 40
    assert min_x == pytest.approx(0.5 + {"start": 0.0, "center": 0.25, "end": 0.5}[row])
    assert min_y == pytest.approx(ROW_Y + {"start": 0.0, "center": spare_depth / 2, "end": spare_depth}[depth])


def test_no_anchor_is_byte_identical_to_the_fill_before_uxf1():
    plain = _session(_roof_scene(width=10.5, height=9.0))
    assert "depth_alignment" not in _field(plain.scene)["packing_parameters"]
    explicit_default = _session(_roof_scene(width=10.5, height=9.0), row_alignment="start")
    assert canonical_scene_json(plain.scene) == canonical_scene_json(explicit_default.scene)


@pytest.mark.parametrize("azimuth", [0.0, 2.5, 7.0, 33.0])
@pytest.mark.parametrize("height", [7.3, 8.1, 9.7])
def test_an_anchor_never_places_fewer_modules_than_the_automatic_fill(azimuth, height):
    automatic = _extent(_session(_roof_scene(width=11.2, height=height), azimuth=azimuth).scene)[2]
    for depth in ("start", "center", "end"):
        anchored = _extent(_session(_roof_scene(width=11.2, height=height), azimuth=azimuth,
                                    depth_alignment=depth).scene)[2]
        assert anchored == automatic, (azimuth, height, depth)


def test_refill_changes_only_the_alignment_and_other_edits_keep_the_stored_parameters():
    session = _session(_roof_scene(width=10.5, height=9.0))
    before = dict(_field(session.scene)["packing_parameters"])
    session.update_field("field-1", tilt_deg=12.0)
    assert _field(session.scene)["packing_parameters"] == before  # an unrelated edit rewrites nothing
    session.update_field("field-1", depth_alignment="end", row_alignment="center")
    params = _field(session.scene)["packing_parameters"]
    assert params["depth_alignment"] == "end" and params["row_alignment"] == "center"
    with pytest.raises(ValueError, match="alignment"):
        session.update_field("field-1", depth_alignment="middle")


def test_the_api_creates_and_updates_a_field_with_both_alignments(tmp_path):
    project = Project(tmp_path, 20, weather=False, strings=False)
    field = project.bundle()["scene"]["pv_fields"][0]
    url = f"{project.url}/pv-fields/{field['pv_field_id']}"
    response = project.client.patch(url, json={"depth_alignment": "center", "row_alignment": "end"})
    assert response.status_code == 200, response.text
    stored = project.bundle()["scene"]["pv_fields"][0]["packing_parameters"]
    assert stored["depth_alignment"] == "center" and stored["row_alignment"] == "end"
    assert len(project.bundle()["scene"]["module_instances"]) == 20
    assert project.client.patch(url, json={"depth_alignment": "middle"}).status_code == 422
