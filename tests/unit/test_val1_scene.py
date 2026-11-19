from copy import deepcopy
import numpy as np
import pytest
from shapely.geometry import Polygon
from validation.pvsyst_benchmark.source import read_objects, SourceError
from validation.pvsyst_benchmark.project import extract_project
from validation.pvsyst_benchmark.scene import (
    read_scene,
    reconstruction_counts,
    scene_equivalence,
    resolve_anchor_hypotheses,
    prism_request,
)
from tests.fixtures.val1.synthetic import scene_bytes, project_sources


def test_synthetic_scene_counts_orientation_bom_native_request_and_topology():
    s = read_scene(read_objects(scene_bytes()))
    vc, prj = project_sources()
    gate = reconstruction_counts(
        s, extract_project(read_objects(vc), read_objects(prj), label="P2")
    )
    assert gate["counts_match"] and gate["orientations_match"]
    assert s.meshes[0].topology() == "vertical_prism"
    request = prism_request(s.meshes[0], label="P2")
    assert (
        request["json"]["height_m"] == 1 and request["json"]["base_elevation_m"] == -1
    )
    assert (
        request["json"]["on_module_conflict"] == "reject"
        and request["json"]["dry_run"] is True
    )
    assert (
        read_scene(read_objects(scene_bytes(raised=True))).meshes[0].topology()
        == "multi_level_mesh"
    )
    assert (
        read_scene(read_objects(scene_bytes(open_mesh=True))).meshes[0].topology()
        == "open_or_nonmanifold_mesh"
    )
    with pytest.raises(SourceError):
        prism_request(
            read_scene(read_objects(scene_bytes(raised=True))).meshes[0], label="P2"
        )


def test_world_equivalence_is_geometry_not_metadata_or_raw_face_layout():
    a = read_scene(read_objects(scene_bytes()))
    other = scene_bytes().replace(b"ModSpacingX=0", b"ModSpacingX=0.02")
    # Embedded snapshots may lack the newly saved module metadata.
    other = other.replace(b"    NModInWidth=2\n", b"").replace(
        b"    NModInHeight=1\n", b""
    )
    b = read_scene(read_objects(other), require_layout=False)
    assert scene_equivalence(a, b)["world_equivalent_all_anchors"]
    c = deepcopy(b)
    c.meshes[0].vertices[:, 0] += 1
    assert not scene_equivalence(a, c)["world_equivalent_all_anchors"]


def test_discrete_origin_unique_ambiguous_and_inconsistent():
    table = read_scene(read_objects(scene_bytes())).tables[0]
    support = (Polygon([(0, 0), (2, 0), (2, -1), (0, -1)]), np.array([0.0, 0.0, 0.0]))
    r = resolve_anchor_hypotheses(
        [table], [support], dimensions={table.object_id: (1, 1)}
    )
    assert r["status"] == "resolved" and r["accepted_anchor"] == [0, 0]
    broad = (Polygon([(-10, -10), (10, -10), (10, 10), (-10, 10)]), np.zeros(3))
    assert resolve_anchor_hypotheses([table], [broad])["status"] == "ambiguous"
    assert resolve_anchor_hypotheses([table], [])["status"] == "inconsistent"
    assert (
        resolve_anchor_hypotheses(
            [table], [support], dimensions={table.object_id: (9, 9)}
        )["status"]
        == "inconsistent"
    )


@pytest.mark.parametrize(
    "mutate",
    [
        lambda b: b.replace(b"FOCalcul=foLinear", b"FOCalcul=foElectrical"),
        lambda b: b.replace(b"NElements=6", b"NElements=7"),
        lambda b: b.replace(b"Faces=-1,0,1", b"Faces=-1,99,1"),
        lambda b: b.replace(b"TypeOrigine=1", b"TypeOrigine=nan"),
        lambda b: b.replace(b"NOrientTables=2", b"NOrientTables=3"),
    ],
)
def test_scientific_scene_errors_fail_closed(mutate):
    with pytest.raises(SourceError):
        read_scene(read_objects(mutate(scene_bytes())))


def test_unknown_key_register_and_orientation_mismatch():
    s = read_scene(read_objects(scene_bytes(extra="FutureGeometry=2")))
    assert any(f.code == "scene_key_unknown" and f.blocking for f in s.unsupported)
    vc, prj = project_sources()
    p = extract_project(read_objects(vc), read_objects(prj), label="P2")
    p.subarrays[0]["module_count"] += 1
    assert not reconstruction_counts(s, p)["counts_match"]


def test_continuation_marker_is_structural_and_missing_continuation_refused():
    original = scene_bytes().decode("utf-8-sig")
    changed = original.replace("    Faces=", "    Faces=contd\n    Faces_contd=")
    group = "  PVObject_Group=pvShdObjectGroup\n    Objects=contd\n    Objects_contd=1,2,3,\n  End of PVObject pvShdObjectGroup\n"
    changed = changed.replace(
        "End of PVObject pvShading", group + "End of PVObject pvShading"
    )
    s = read_scene(read_objects(changed.encode()))
    assert s.groups == [["1", "2", "3"]] and s.meshes[0].topology() == "vertical_prism"
    with pytest.raises(SourceError, match="continuation"):
        read_scene(
            read_objects(changed.replace("    Objects_contd=1,2,3,\n", "").encode())
        )


def test_continuation_suffixes_on_each_segment_are_not_object_ids():
    group = "  PVObject_Group=pvShdObjectGroup\n    Objects=1,contd\n    Objects_contd=2,contd\n    Objects_contd=3,\n  End of PVObject pvShdObjectGroup\n"
    text = (
        scene_bytes()
        .decode("utf-8-sig")
        .replace("End of PVObject pvShading", group + "End of PVObject pvShading")
    )
    assert read_scene(read_objects(text.encode())).groups == [["1", "2", "3"]]


def test_missing_embedded_yaw_is_unresolved_not_an_invented_zero():
    a = read_scene(read_objects(scene_bytes()))
    text = scene_bytes().decode("utf-8-sig").replace("    DAzimut=0\n", "")
    # Only omit generic-object yaw, not the PV table's mandatory azimuth.
    head, tail = (
        scene_bytes().decode("utf-8-sig").split("  PVObject_Object=pvShdGenObject", 1)
    )
    b = read_scene(
        read_objects(
            (
                head
                + "  PVObject_Object=pvShdGenObject"
                + tail.replace("    DAzimut=0\n", "", 1)
            ).encode()
        ),
        require_layout=False,
    )
    assert any(f.code == "mesh_transform_unresolved" for f in b.unsupported)
    assert scene_equivalence(a, b)["status"] == "unavailable"


@pytest.mark.parametrize(
    "change",
    [
        lambda b: b.replace(b"ModSpacingX=0", b"UnknownGap=0"),
        lambda b: b.replace(b"ModuleOrient=moPortrait", b"ModuleOrient=unknown"),
    ],
)
def test_saved_layout_never_inherits_missing_spacing_or_orientation(change):
    with pytest.raises(SourceError):
        read_scene(read_objects(change(scene_bytes())))
