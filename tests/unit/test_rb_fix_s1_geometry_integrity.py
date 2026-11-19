"""S1 acceptance cases, using persisted projects and no provider network calls."""

from copy import deepcopy
import json
import math
from pathlib import Path
from time import perf_counter

from fastapi.testclient import TestClient
import pytest
from shapely.geometry import box

from apps.api.server import create_app
from apps.api.execution_readiness import scene_layout_readiness_findings
from geometry.pvfield import PVFieldPackingSession
from geometry.pvfield.packing import validate_field_layout
from geometry.pvfield.scene_layout import validate_scene_layout
from components.design_integration import module_nameplate_w  # D14: the DC nameplate basis


ROOT = Path(__file__).resolve().parents[2]
MODULE = "mod-rawibumi-uat-550-r1"
INVERTER = "inv-rawibumi-uat-150k-r1"


class Project:
    def __init__(self, tmp_path, *, width=8.0, height=8.5, setback=0.3, tilt=10.0):
        self.app = create_app(store_root=tmp_path / "projects")
        self.service = self.app.state.project_service
        self.study = self.app.state.study_service
        self.client = TestClient(self.app)
        bundle = self.service.create_project(
            name="S1 geometry", latitude_deg=-6.2, longitude_deg=106.8,
            elevation_m=25.0, timezone_name="Asia/Jakarta",
        )
        self.pid = bundle["project"]["project_id"]
        self.url = f"/api/projects/{self.pid}"
        self.path = self.service.store.path_for(self.pid)
        view = self.service.add_surface_rectangle(
            self.pid, name="Roof", origin_x_m=0, origin_y_m=0, width_m=width,
            height_m=height, base_elevation_m=6.1, surface_type="flat_roof", usable_for_pv=True,
        )
        self.surface_id = view["bundle"]["scene"]["surfaces"][0]["surface_id"]
        self.fill = {
            "support_surface_id": self.surface_id,
            "module_definition_revision_id": MODULE, "tilt_deg": tilt,
            "obstacle_setback_m": setback,
        }
        response = self.client.post(self.url + "/pv-fields", json=self.fill)
        assert response.status_code == 200, response.text
        self.field_id = self.bundle()["scene"]["pv_fields"][0]["pv_field_id"]

    def bundle(self):
        return self.service.get_bundle(self.pid)

    def modules(self):
        return sorted(self.bundle()["scene"]["module_instances"],
                      key=lambda m: (m["row_index"], m["column_index"]))

    def layout(self, scene=None):
        bundle = self.bundle()
        return validate_scene_layout(scene or bundle["scene"], bundle["pinned_components"]["modules"])

    def obstacle(self, **options):
        modules = self.modules()[:3]
        x = [m["transform"]["position_x_m"] for m in modules]
        y = modules[0]["transform"]["position_y_m"]
        return {
            "name": "Across three", "origin_x_m": min(x) - 0.1,
            "origin_y_m": y - 0.1, "width_m": max(x) - min(x) + 0.2,
            "depth_m": 0.2, "base_elevation_m": 6.1, "height_m": 1.0, **options,
        }

    def executable(self):
        self.service.add_inverter(self.pid, inverter_definition_revision_id=INVERTER, name="INV")
        self.service.create_strings(self.pid, string_length=6)
        iid = self.bundle()["electrical_design"]["inverter_instances"][0]["inverter_instance_id"]
        self.service.assign_strings(self.pid, inverter_instance_id=iid)
        self.study.acquire_weather(
            self.pid, source_id="open_meteo_archive_era5", start_date="2025-01-01", end_date="2025-01-01",
            raw_response=(ROOT / "tests/fixtures/weather/open_meteo_era5_phase60d_uat_padded_s10.json").read_bytes(),
        )
        assert self.study.execution_readiness(self.pid)["ready"]

    def duplicate(self):
        """Write a pre-S1 duplicate directly, bypassing the new create gate."""
        bundle = self.bundle()
        field = deepcopy(bundle["scene"]["pv_fields"][0])
        field["pv_field_id"] = "legacy-duplicate-field"
        bundle["scene"]["pv_fields"].append(field)
        for original in list(bundle["scene"]["module_instances"]):
            module = deepcopy(original)
            module["module_instance_id"] += "-duplicate"
            module["pv_field_id"] = field["pv_field_id"]
            bundle["scene"]["module_instances"].append(module)
        self.service.store.save(bundle)


@pytest.fixture
def project(tmp_path):
    return Project(tmp_path)


def _independent_removal(bundle, obstacle):
    """Independent S1 oracle: construct axis-aligned fixtures without S1 helpers."""
    fields = {f["pv_field_id"]: f for f in bundle["scene"]["pv_fields"]}
    definitions = bundle["pinned_components"]["modules"]
    obstacle_polygon = box(
        obstacle["origin_x_m"], obstacle["origin_y_m"],
        obstacle["origin_x_m"] + obstacle["width_m"],
        obstacle["origin_y_m"] + obstacle["depth_m"],
    )
    candidates = []
    affected = set()
    for m in bundle["scene"]["module_instances"]:
        if not m.get("enabled", True):
            continue
        field = fields[m["pv_field_id"]]
        definition = definitions[m["module_definition_revision_id"]]
        width, up = definition["mechanical"]["width_m"], definition["mechanical"]["height_m"]
        if field["orientation"] == "landscape":
            width, up = up, width
        tilt = math.radians(field["tilt_deg"])
        half_y = up * math.cos(tilt) / 2
        dz = up * math.sin(tilt) / 2
        x, y, z = (m["transform"][f"position_{axis}_m"] for axis in "xyz")
        assert m["transform"]["rotation_z_deg"] == 0
        polygon = box(x - width / 2, y - half_y, x + width / 2, y + half_y)
        if obstacle["base_elevation_m"] > z + dz or (
            obstacle["base_elevation_m"] + obstacle["height_m"] < z - dz
        ):
            continue
        overlap = polygon.intersection(obstacle_polygon).area > 1e-6
        setback = field["setback_configuration"]["obstacle_setback_m"]
        if overlap:
            affected.add(m["pv_field_id"])
        if overlap or polygon.distance(obstacle_polygon) < setback - 1e-9:
            candidates.append((m["module_instance_id"], m["pv_field_id"]))
    return {mid for mid, fid in candidates if fid in affected}


def test_01_duplicate_fill_rejected_without_revision_or_byte_change(project):
    before = project.path.read_bytes()
    assert len(project.modules()) == 18
    revision = project.bundle()["project"]["project_revision"]
    response = project.client.post(project.url + "/pv-fields", json=project.fill)
    assert response.status_code == 422
    assert project.field_id in response.json()["detail"]["message"]
    assert "update that field instead" in response.json()["detail"]["message"]
    assert response.json()["detail"]["conflicts"]
    assert project.path.read_bytes() == before
    assert project.bundle()["project"]["project_revision"] == revision


def test_02_two_halves_of_thirty_metre_roof_allow_touching(tmp_path):
    project = Project(tmp_path, width=15, height=8.5)
    bundle = project.bundle()
    # Author a partial-field fixture: the API has no region-update route until
    # S4. Right-align the first half exactly at x=15, then fill the other half
    # through the API on the same surface id.
    width = bundle["pinned_components"]["modules"][MODULE]["mechanical"]["width_m"]
    right = max(m["transform"]["position_x_m"] + width / 2 for m in project.modules())
    for m in bundle["scene"]["module_instances"]:
        m["transform"]["position_x_m"] += 15 - right
    surface = bundle["scene"]["surfaces"][0]
    surface["boundary_2d"]["vertices"] = [[15, 0], [30, 0], [30, 8.5], [15, 8.5]]
    project.service.store.save(bundle)
    response = project.client.post(project.url + "/pv-fields", json={
        **project.fill, "perimeter_setback_m": 0,
    })
    assert response.status_code == 200, response.text
    bundle = project.bundle()
    bundle["scene"]["surfaces"][0]["boundary_2d"]["vertices"] = [[0, 0], [30, 0], [30, 8.5], [0, 8.5]]
    project.service.store.save(bundle)
    assert len(bundle["scene"]["pv_fields"]) == 2
    assert project.layout() == {"status": "ok", "conflicts": []}
    first = [m for m in bundle["scene"]["module_instances"] if m["pv_field_id"] == project.field_id]
    second = [m for m in bundle["scene"]["module_instances"] if m["pv_field_id"] != project.field_id]
    assert max(m["transform"]["position_x_m"] + width / 2 for m in first) == pytest.approx(15)
    assert min(m["transform"]["position_x_m"] - width / 2 for m in second) == pytest.approx(15)


def test_03_rotated_fill_uses_polygons(project):
    before = project.path.read_bytes()
    response = project.client.post(project.url + "/pv-fields", json={**project.fill, "azimuth_deg": 40})
    assert response.status_code == 422, response.text
    assert response.json()["detail"]["conflicts"][0]["code"] == "module_module_overlap"
    assert project.path.read_bytes() == before
    # Two long parallel rectangles can share a bbox without sharing any area.
    scene = project.bundle()["scene"]
    a, b = deepcopy(scene["module_instances"][:2])
    a["transform"].update(position_x_m=0, position_y_m=0, rotation_z_deg=40)
    angle = math.radians(40)
    b["transform"].update(position_x_m=1.2 * math.cos(angle),
                          position_y_m=-1.2 * math.sin(angle), rotation_z_deg=40)
    scene["module_instances"] = [a, b]
    assert project.layout(scene)["status"] == "ok"


def test_04_obstacle_default_rejects_with_module_field_and_string_ids(project):
    project.executable()
    before = project.path.read_bytes()
    response = project.client.post(project.url + "/obstacles/box", json=project.obstacle())
    assert response.status_code == 422
    detail = response.json()["detail"]
    assert len([c for c in detail["conflicts"] if c["code"] == "module_obstacle_overlap"]) == 3
    assert project.field_id in detail["message"]
    assert project.modules()[0]["module_instance_id"] in detail["message"]
    assert detail["options"]["remove_modules"]["string_ids"]
    assert all(s in detail["message"] for s in detail["options"]["remove_modules"]["string_ids"])
    assert project.path.read_bytes() == before


def test_05_dry_run_all_options_returns_exact_pinned_power_without_saving(project):
    project.executable()
    before = project.path.read_bytes()
    for option in ("reject", "remove_modules", "refill_field"):
        response = project.client.post(project.url + "/obstacles/box", json=project.obstacle(
            dry_run=True, on_module_conflict=option,
        ))
        assert response.status_code == 200, response.text
        preview = response.json()
        assert preview["dry_run"] is True
        remove = preview["options"]["remove_modules"]
        assert remove["module_count"] == 3
        assert set(remove["module_instance_ids"]) == {m["module_instance_id"] for m in project.modules()[:3]}
        assert remove["stc_power_w"] == pytest.approx(
            3 * module_nameplate_w(project.bundle()["pinned_components"]["modules"][MODULE])
        )
        assert remove["requires_discard_dependent_strings"] is True
        assert preview["options"]["refill_field"]["available"] is True
        assert project.path.read_bytes() == before
    # Even a conflict-free preview does not commit.
    response = project.client.post(project.url + "/obstacles/box", json=project.obstacle(
        origin_x_m=50, dry_run=True,
    ))
    assert response.status_code == 200 and not response.json()["conflicts"]
    assert project.path.read_bytes() == before


def test_06_remove_modules_matches_independent_s1_rules(project):
    before = project.bundle()
    # Extend toward the fourth module, leaving a 0.1 m setback-only gap.
    obstacle = project.obstacle(on_module_conflict="remove_modules")
    fourth = project.modules()[3]["transform"]["position_x_m"]
    half_width = before["pinned_components"]["modules"][MODULE]["mechanical"]["width_m"] / 2
    obstacle["width_m"] = fourth - half_width - 0.1 - obstacle["origin_x_m"]
    expected = _independent_removal(before, obstacle)
    assert len(expected) == 4  # three overlaps, plus the fourth's setback
    response = project.client.post(project.url + "/obstacles/box", json=obstacle)
    assert response.status_code == 200, response.text
    after = project.bundle()
    survivors = {m["module_instance_id"]: m for m in after["scene"]["module_instances"]}
    originals = {m["module_instance_id"]: m for m in before["scene"]["module_instances"]}
    assert originals.keys() - survivors.keys() == expected
    assert survivors == {mid: m for mid, m in originals.items() if mid not in expected}
    field = after["scene"]["pv_fields"][0]
    assert field["layout_status"] == "manual" and field["packing_input_hash"] is None
    assert not any(c["code"] == "packing_inputs_changed" for c in validate_field_layout(
        after["scene"], project.field_id
    )["conflicts"])
    assert project.layout()["status"] == "ok"
    reopened = create_app(store_root=project.service.store.root).state.project_service.get_bundle(project.pid)
    assert reopened == after


def test_07_string_discard_requires_flag_and_commits_both_revisions_once(project, monkeypatch):
    project.executable()
    before = project.bundle()
    before_bytes = project.path.read_bytes()
    obstacle = project.obstacle(on_module_conflict="remove_modules")
    response = project.client.post(project.url + "/obstacles/box", json=obstacle)
    assert response.status_code == 422
    affected = response.json()["detail"]["options"]["remove_modules"]["string_ids"]
    assert len(affected) == 1
    assert project.path.read_bytes() == before_bytes
    saved = []
    save = project.service.store.save

    def capture(bundle):
        saved.append(deepcopy(bundle))
        return save(bundle)

    monkeypatch.setattr(project.service.store, "save", capture)
    # A failed final save leaves the persisted scene and electrical design intact.
    def fail_save(bundle):
        raise OSError("injected save failure")

    with monkeypatch.context() as context:
        context.setattr(project.service.store, "save", fail_save)
        with pytest.raises(OSError, match="injected save failure"):
            project.service.add_box_obstacle(project.pid, **obstacle, discard_dependent_strings=True)
        assert project.path.read_bytes() == before_bytes
    response = project.client.post(project.url + "/obstacles/box", json={
        **obstacle, "discard_dependent_strings": True,
    })
    assert response.status_code == 200, response.text
    after = project.bundle()
    assert len(saved) == 1
    assert after["scene"]["revision_number"] == before["scene"]["revision_number"] + 1
    assert after["electrical_design"]["revision_number"] == before["electrical_design"]["revision_number"] + 1
    assert after["project"]["project_revision"]["revision_number"] == before["project"]["project_revision"]["revision_number"] + 1
    assert after["electrical_design"]["strings"] == [
        s for s in before["electrical_design"]["strings"] if s["string_id"] not in affected
    ]
    assert not any(set(affected).intersection(m["connected_string_ids"])
                   for m in after["electrical_design"]["mppt_instances"])
    project_revision = after["project"]["project_revision"]
    assert project_revision["scene_revision_id"] == after["scene"]["revision_id"]
    assert project_revision["electrical_revision_id"] == after["electrical_design"]["electrical_revision_id"]


def test_08_refill_is_reserved_for_s4(project):
    before = project.path.read_bytes()
    response = project.client.post(project.url + "/obstacles/box", json=project.obstacle(on_module_conflict="refill_field"))
    assert response.status_code == 200
    assert project.layout()["status"] == "ok"
    assert project.path.read_bytes() != before
    bad = project.client.post(project.url + "/obstacles/box", json=project.obstacle(on_module_conflict="invalid"))
    assert bad.status_code == 422
    # Unrelated errors retain their string detail contract.
    unknown = project.client.post(project.url + "/scene/move", json={"entity_id": "missing", "dx_m": 1, "dy_m": 0})
    assert unknown.status_code == 422 and isinstance(unknown.json()["detail"], str)


def test_09_move_obstacle_has_same_preview_reject_and_removal_policy(project):
    obstacle = project.obstacle(origin_x_m=50)
    assert project.client.post(project.url + "/obstacles/box", json=obstacle).status_code == 200
    oid = project.bundle()["scene"]["obstacles"][0]["obstacle_id"]
    original = project.obstacle()
    move = {"entity_id": oid, "dx_m": original["origin_x_m"] - 50, "dy_m": 0}
    before = project.path.read_bytes()
    assert project.client.post(project.url + "/scene/move", json=move).status_code == 422
    assert project.path.read_bytes() == before
    preview = project.client.post(project.url + "/scene/move", json={**move, "dry_run": True})
    assert preview.status_code == 200
    assert preview.json()["options"]["remove_modules"]["module_count"] == 3
    assert project.path.read_bytes() == before
    response = project.client.post(project.url + "/scene/move", json={**move, "on_module_conflict": "remove_modules"})
    assert response.status_code == 200, response.text
    assert len(project.modules()) == 15


def test_10_ground_obstacle_below_elevated_modules_is_accepted(project):
    modules = deepcopy(project.modules())
    response = project.client.post(project.url + "/obstacles/box", json=project.obstacle(
        base_elevation_m=0, height_m=2, on_module_conflict="remove_modules",
    ))
    assert response.status_code == 200, response.text
    assert project.modules() == modules
    assert all(m["transform"]["position_z_m"] == pytest.approx(6.3) for m in modules)
    assert project.layout()["status"] == "ok"
    # Zero-height planes conflict only inside the closed module vertical range.
    for base, expected in ((6.3, 422), (5.0, 200)):
        response = project.client.post(project.url + "/obstacles/box", json=project.obstacle(
            base_elevation_m=base, height_m=0,
        ))
        assert response.status_code == expected, response.text
    # The height interval uses definition height in portrait and width in
    # landscape, including exact zero-height contact at either end of the range.
    scene = project.bundle()["scene"]
    scene["module_instances"] = [deepcopy(modules[0])]
    transform = scene["module_instances"][0]["transform"]
    x, y, z = (transform[f"position_{axis}_m"] for axis in "xyz")
    mechanical = project.bundle()["pinned_components"]["modules"][MODULE]["mechanical"]
    for orientation, up in (("portrait", mechanical["height_m"]), ("landscape", mechanical["width_m"])):
        scene["pv_fields"][0].update(orientation=orientation, tilt_deg=60)
        dz = up * math.sin(math.radians(60)) / 2
        for base, conflict in ((z - dz, True), (z + dz, True), (z + dz + 1e-6, False)):
            scene["obstacles"] = [{
                "obstacle_id": "height-boundary", "footprint": {"vertices": [
                    [x - 0.05, y - 0.05], [x + 0.05, y - 0.05],
                    [x + 0.05, y + 0.05], [x - 0.05, y + 0.05],
                ]}, "base_elevation_m": base, "height_m": 0,
            }]
            assert (project.layout(scene)["status"] == "conflict") is conflict


def test_11_setback_only_is_nonblocking_and_height_aware(project):
    project.executable()
    first = project.modules()[0]["transform"]
    obstacle = project.obstacle(
        origin_x_m=0.1, origin_y_m=first["position_y_m"] - 0.1,
        width_m=0.1, depth_m=0.2,
    )
    before_ids = {m["module_instance_id"] for m in project.modules()}
    response = project.client.post(project.url + "/obstacles/box", json=obstacle)
    assert response.status_code == 200, response.text
    readiness = project.study.execution_readiness(project.pid)
    warnings = [f for f in readiness["findings"] if f["rule_id"] == "SCENE_MODULE_OBSTACLE_SETBACK"]
    assert readiness["ready"] is True
    assert len(warnings) == 1 and warnings[0]["severity"] == "warning"
    assert {m["module_instance_id"] for m in project.modules()} == before_ids
    scene = project.bundle()["scene"]
    scene["obstacles"][0].update(base_elevation_m=0, height_m=2)
    assert project.layout(scene)["status"] == "ok"


def test_12_legacy_overlapping_bundle_loads_but_cannot_simulate(project):
    project.executable()
    project.duplicate()
    before = project.path.read_bytes()
    assert project.client.get(project.url).status_code == 200
    ready = project.client.get(project.url + "/execution-readiness").json()
    assert ready["ready"] is False
    assert any(f["rule_id"] == "SCENE_MODULE_OVERLAP" for f in ready["findings"])
    response = project.client.post(project.url + "/simulate", json={})
    assert response.status_code == 422
    assert "simulation execution preflight failed" in response.json()["detail"]
    assert project.path.read_bytes() == before
    assert project.client.get(project.url + "/runs").json() == []
    # Already-persisted module/obstacle overlaps are gated by the same checker.
    bundle = project.bundle()
    bundle["scene"]["pv_fields"] = bundle["scene"]["pv_fields"][:1]
    bundle["scene"]["module_instances"] = [m for m in bundle["scene"]["module_instances"]
                                            if m["pv_field_id"] == project.field_id]
    from geometry.scene import SceneEditorSession
    editor = SceneEditorSession(bundle["scene"])
    editor.draw_box_obstacle(obstacle_id="old-obstacle", scene_object_id="obj-old-obstacle",
                             **project.obstacle())
    bundle["scene"] = editor.scene
    project.service.store.save(bundle)
    ready = project.study.execution_readiness(project.pid)
    assert not ready["ready"]
    assert any(f["rule_id"] == "SCENE_MODULE_OBSTACLE_OVERLAP" for f in ready["findings"])
    assert project.client.post(project.url + "/simulate", json={}).status_code == 422


def test_13_remove_all_modules_keeps_field_with_empty_warning(project):
    response = project.client.post(project.url + "/obstacles/box", json=project.obstacle(
        origin_x_m=0, origin_y_m=0, width_m=8, depth_m=8.5, on_module_conflict="remove_modules",
    ))
    assert response.status_code == 200, response.text
    assert not project.modules()
    assert project.bundle()["scene"]["pv_fields"][0]["pv_field_id"] == project.field_id
    ready = project.study.execution_readiness(project.pid)
    assert any(f["rule_id"] == "PV_FIELD_EMPTY" and f["severity"] == "warning" for f in ready["findings"])


def test_14_remove_modules_is_one_undo_step_and_failures_are_atomic(project):
    bundle = project.bundle()
    session = PVFieldPackingSession(bundle["scene"], bundle["pinned_components"]["modules"])
    before = session.scene
    ids = [m["module_instance_id"] for m in project.modules()[:3]]
    for bad in ([], [ids[0], "unknown"]):
        with pytest.raises(ValueError):
            session.remove_modules(bad)
        assert session.scene == before and session.undo_depth == 0
    result = session.remove_modules(ids)
    assert result == {"removed_module_instance_ids": sorted(ids), "pv_field_ids": [project.field_id]}
    after = session.scene
    assert len(after["module_instances"]) == 15 and session.undo_depth == 1
    assert session.undo() and session.scene == before
    assert not session.undo()
    assert session.redo() and session.scene == after


def test_15_ten_thousand_modules_spatial_index_budget(project, record_property):
    scene = project.bundle()["scene"]
    template = scene["module_instances"][0]
    scene["module_instances"] = []
    for index in range(10_000):
        module = {**template, "module_instance_id": f"perf-{index:05d}", "transform": {
            **template["transform"], "position_x_m": (index % 100) * 2,
            "position_y_m": (index // 100) * 3,
        }}
        scene["module_instances"].append(module)
    definitions = project.bundle()["pinned_components"]["modules"]
    start = perf_counter()
    report = validate_scene_layout(scene, definitions)
    elapsed = perf_counter() - start
    record_property("scene_layout_10000_modules_seconds", elapsed)
    # Target is <2 s on the development machine. The 5 s assertion allows
    # scheduling noise on shared CI; the measured result is retained in JUnit.
    assert elapsed < 5.0, f"10,000 modules: {elapsed:.3f}s (dev target <2s)"
    assert report == {"status": "ok", "conflicts": []}


def test_16_determinism_purity_disabled_modules_and_bounded_findings(project):
    project.duplicate()
    scene = project.bundle()["scene"]
    before = deepcopy(scene)
    first = project.layout(scene)
    scene["module_instances"].reverse()
    scene["pv_fields"].reverse()
    second = project.layout(scene)
    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)
    scene["module_instances"].reverse()
    scene["pv_fields"].reverse()
    assert scene == before
    for m in scene["module_instances"]:
        if m["pv_field_id"] != project.field_id:
            m["enabled"] = False
    assert project.layout(scene)["status"] == "ok"
    # Many coincident placements produce bounded readiness diagnostics.
    bundle = project.bundle()
    original = bundle["scene"]["module_instances"][0]
    bundle["scene"]["module_instances"] = [
        {**deepcopy(original), "module_instance_id": f"duplicate-{i}"} for i in range(12)
    ]
    project.service.store.save(bundle)
    findings = [f for f in project.study.execution_readiness(project.pid)["findings"]
                if f["rule_id"] == "SCENE_MODULE_OVERLAP"]
    assert len(findings) == 51
    summary = next(f for f in findings if "omitted_pair_count" in f["context"])
    assert summary["context"] == {"total_pair_count": 66, "omitted_pair_count": 16}
    # Pin the area tolerance independently of contact/setback behavior.
    scene = deepcopy(before)
    scene["pv_fields"][0].update(tilt_deg=0, orientation="portrait")
    scene["pv_fields"][0]["setback_configuration"]["obstacle_setback_m"] = 0
    module = next(m for m in scene["module_instances"] if m["pv_field_id"] == project.field_id)
    scene["module_instances"] = [module]
    module["transform"].update(position_x_m=0, position_y_m=0, rotation_z_deg=0)
    width = project.bundle()["pinned_components"]["modules"][MODULE]["mechanical"]["width_m"]
    for area, conflict in ((0.9e-6, False), (1.1e-6, True)):
        left = width / 2 - area
        scene["obstacles"] = [{
            "obstacle_id": "area-tolerance", "base_elevation_m": 6.1, "height_m": 1,
            "footprint": {"vertices": [[left, -0.5], [left + 0.2, -0.5],
                                       [left + 0.2, 0.5], [left, 0.5]]},
        }]
        assert (project.layout(scene)["status"] == "conflict") is conflict


def test_17_s1_keeps_touching_and_vertically_separated_modules_despite_packer(tmp_path):
    project = Project(tmp_path, setback=0, tilt=0)
    bundle = project.bundle()
    m = project.modules()[0]
    mechanical = bundle["pinned_components"]["modules"][MODULE]["mechanical"]
    right = m["transform"]["position_x_m"] + mechanical["width_m"] / 2
    before_ids = {m["module_instance_id"] for m in project.modules()}
    response = project.client.post(project.url + "/obstacles/box", json=project.obstacle(
        origin_x_m=right, width_m=0.01, on_module_conflict="remove_modules",
    ))
    assert response.status_code == 200, response.text
    assert {m["module_instance_id"] for m in project.modules()} == before_ids
    assert project.layout()["status"] == "ok"
    assert any(c["code"] == "module_obstacle_overlap" for c in validate_field_layout(
        project.bundle()["scene"], project.field_id
    )["conflicts"])
    response = project.client.post(project.url + "/obstacles/box", json=project.obstacle(
        base_elevation_m=0, height_m=2, on_module_conflict="remove_modules",
    ))
    assert response.status_code == 200, response.text
    assert {m["module_instance_id"] for m in project.modules()} == before_ids
    assert project.layout()["status"] == "ok"
    obstacle_id = project.bundle()["scene"]["obstacles"][-1]["obstacle_id"]
    assert any(c["code"] == "module_obstacle_overlap" and c["related_entity_id"] == obstacle_id
               for c in validate_field_layout(project.bundle()["scene"], project.field_id)["conflicts"])
    # S1 readiness never imports the packer's plan-only obstacle diagnoses.
    findings = project.study.execution_readiness(project.pid)["findings"]
    assert not any(f["rule_id"].startswith("SCENE_") and f["rule_id"] != "SCENE_PV_FIELD_LAYOUT_STALE"
                   for f in findings)
    stale = [f for f in findings if f["rule_id"] == "SCENE_PV_FIELD_LAYOUT_STALE"]
    assert len(stale) == 1
    assert stale[0]["entity_id"] == project.field_id and stale[0]["severity"] == "warning"


def test_18_detailed_findings_preserved_and_geometry_never_bypassed(project, tmp_path, monkeypatch):
    project.executable()
    requests = [{"requested_fidelity": "level_2_bypass_substring", "fallback_policy": policy}
                for policy in ("fail_closed", "explicit_lower_fidelity")]
    project.duplicate()
    for request in requests:
        # Compare the detailed logic on the SAME conflicting scene with S1
        # findings disabled: extra modules can independently change its existing
        # electrical coverage diagnosis, which must also be retained verbatim.
        with monkeypatch.context() as context:
            context.setattr("apps.api.execution_readiness.scene_layout_readiness_findings", lambda bundle: [])
            before_findings = project.study.execution_readiness(project.pid, request)["findings"]
        ready = project.client.get(project.url + "/execution-readiness", params=request).json()
        geometry = [f for f in ready["findings"] if f["rule_id"].startswith("SCENE_")]
        assert ready["ready"] is False and ready["execution_class"] == "blocked_detailed_inputs"
        assert geometry and all(f["rule_id"] == "SCENE_MODULE_OVERLAP" for f in geometry)
        assert [f for f in ready["findings"] if f["rule_id"] != "MODULES_NOT_SIMULATED"] == [
            f for f in before_findings if f["rule_id"] != "MODULES_NOT_SIMULATED"
        ] + geometry
        assert ready["findings"][-1]["rule_id"] == "MODULES_NOT_SIMULATED"
        assert before_findings[-1]["rule_id"] == "MODULES_NOT_SIMULATED"
        assert ready["findings"][-1] == before_findings[-1]
        assert project.client.post(project.url + "/simulate", json={
            "electrical_shading_configuration": request,
        }).status_code == 422
    # Pin an existing successful detailed fixture's exact findings. Also cover
    # missing weather, electrical-validation failure, and the detailed success
    # path; these paths must append S1 findings without changing the originals.
    from tests.unit.test_phase69b_browser_launch import setup_project, REQUEST
    app, pid, bundle = setup_project(tmp_path / "detailed")
    service, study = app.state.project_service, app.state.study_service
    request = REQUEST["electrical_shading_configuration"]
    no_conflict = study.execution_readiness(pid, request)
    assert no_conflict["ready"] is True and no_conflict["findings"] == []
    base_bundle = deepcopy(bundle)
    for path in ("success", "weather_missing", "validation_blocked", "fallback"):
        bundle = deepcopy(base_bundle)
        path_request = dict(request)
        if path == "weather_missing":
            bundle["weather_selection"] = None
        with monkeypatch.context() as context:
            if path == "success":
                context.setattr("apps.api.study._resolve", lambda *a, **k: None)
            if path == "validation_blocked":
                context.setattr("apps.api.study.validate_engineering_design", lambda *a, **k: {
                    "blocking_simulation": True,
                    "findings": [{"rule_id": "EXISTING_ELECTRICAL_RULE", "severity": "blocking_error", "message": "unchanged"}],
                })
            if path == "fallback":
                from engine.simulation.detailed_inputs import DetailedInputError

                def unavailable(*args, **kwargs):
                    raise DetailedInputError("existing unsupported detailed input")

                context.setattr("apps.api.study._resolve", unavailable)
                path_request["fallback_policy"] = "explicit_lower_fidelity"
            service.store.save(bundle)
            original_result = study.execution_readiness(pid, path_request)
            warning_bundle = deepcopy(bundle)
            empty_field = deepcopy(bundle["scene"]["pv_fields"][0])
            empty_field["pv_field_id"] = "empty-warning-field"
            warning_bundle["scene"]["pv_fields"].append(empty_field)
            service.save_bundle(warning_bundle)
            warned = study.execution_readiness(pid, path_request)
            assert warned["ready"] == original_result["ready"]
            assert warned["execution_class"] == original_result["execution_class"]
            assert warned["findings"][:-1] == original_result["findings"]
            assert warned["findings"][-1]["rule_id"] == "PV_FIELD_EMPTY"
            assert warned["findings"][-1]["severity"] == "warning"
            duplicate = deepcopy(bundle["scene"]["module_instances"][0])
            duplicate["module_instance_id"] += "-old-duplicate"
            bundle["scene"]["module_instances"].append(duplicate)
            service.store.save(bundle)
            result = study.execution_readiness(pid, path_request)
            assert result["findings"][:len(original_result["findings"])] == original_result["findings"]
            assert result["findings"][len(original_result["findings"]):][0]["rule_id"] == "SCENE_MODULE_OVERLAP"
            assert not result["ready"] and result["execution_class"] == "blocked_detailed_inputs"


@pytest.mark.parametrize("damage,reason,baseline_rule", [
    ("missing_field", "pv_field_missing", "EXECUTION_PLAN_EXECUTION_GROUP_FIELD_UNRESOLVED"),
    ("missing_definitions", "definition_missing", "EXECUTION_MODULE_REVISION_NOT_PINNED"),
])
def test_19_damaged_bundle_readiness_reports_and_simulation_blocks(
    project, monkeypatch, damage, reason, baseline_rule,
):
    project.executable()
    bundle = project.bundle()
    if damage == "missing_field":
        bundle["scene"]["pv_fields"] = []
    else:
        bundle["pinned_components"]["modules"] = {}
    project.service.store.save(bundle)
    before_bytes = project.path.read_bytes()
    # Preserve the existing baseline findings verbatim on the same damaged
    # input, independently of the additional S1 findings.
    with monkeypatch.context() as context:
        context.setattr("apps.api.execution_readiness.scene_layout_readiness_findings", lambda bundle: [])
        baseline = project.study.execution_readiness(project.pid)
    assert not baseline["ready"]
    assert any(f["rule_id"] == baseline_rule for f in baseline["findings"])
    scene_before = deepcopy(bundle["scene"])
    report = validate_scene_layout(bundle["scene"], bundle["pinned_components"]["modules"])
    unresolved = [c for c in report["conflicts"] if c["code"] == "module_unresolved"]
    assert len(unresolved) == 18 and all(c["reason"] == reason for c in unresolved)
    assert bundle["scene"] == scene_before
    response = project.client.get(project.url + "/execution-readiness")
    assert response.status_code == 200, response.text
    readiness = response.json()
    assert not readiness["ready"]
    additions = [f for f in readiness["findings"] if f["rule_id"] == "SCENE_LAYOUT_UNRESOLVED"]
    assert len(additions) == 18 and all(f["severity"] == "blocking_error" for f in additions)
    assert [f for f in readiness["findings"] if f not in additions] == baseline["findings"]
    response = project.client.post(project.url + "/simulate", json={})
    assert response.status_code == 422
    assert "simulation execution preflight failed" in response.json()["detail"]
    for policy in ("fail_closed", "explicit_lower_fidelity"):
        request = {"requested_fidelity": "level_2_bypass_substring", "fallback_policy": policy}
        response = project.client.get(project.url + "/execution-readiness", params=request)
        assert response.status_code == 200, response.text
        detailed = response.json()
        assert not detailed["ready"] and detailed["execution_class"] == "blocked_detailed_inputs"
        assert [f for f in detailed["findings"] if f["rule_id"] == "SCENE_LAYOUT_UNRESOLVED"] == additions
        response = project.client.post(project.url + "/simulate", json={"electrical_shading_configuration": request})
        assert response.status_code == 422
        assert "simulation execution preflight failed" in response.json()["detail"]
    assert project.path.read_bytes() == before_bytes
    assert project.client.get(project.url + "/runs").json() == []


@pytest.mark.parametrize("damage", [
    "missing_field", "missing_definition", "not_layout_ready", "invalid_definition",
    "invalid_transform", "obstacle_footprint", "obstacle_base", "obstacle_height",
])
def test_20_unresolved_entities_do_not_hide_resolvable_conflicts(project, damage):
    bundle = project.bundle()
    scene = bundle["scene"]
    definitions = bundle["pinned_components"]["modules"]
    a = deepcopy(scene["module_instances"][0])
    b = deepcopy(a)
    b["module_instance_id"] = "z-valid-duplicate"
    scene["module_instances"] = [a, b]
    x, y, z = (a["transform"][f"position_{axis}_m"] for axis in "xyz")
    valid_obstacle = {
        "obstacle_id": "z-valid-obstacle", "base_elevation_m": z, "height_m": 1,
        "footprint": {"vertices": [[x - 0.1, y - 0.1], [x + 0.1, y - 0.1],
                                   [x + 0.1, y + 0.1], [x - 0.1, y + 0.1]]},
    }
    scene["obstacles"] = [valid_obstacle]
    if damage.startswith("obstacle_"):
        bad = deepcopy(valid_obstacle)
        bad["obstacle_id"] = "a-bad-obstacle"
        bad.pop({"obstacle_footprint": "footprint", "obstacle_base": "base_elevation_m",
                 "obstacle_height": "height_m"}[damage])
        scene["obstacles"].append(bad)
        expected_code, entity_id = "obstacle_unresolved", bad["obstacle_id"]
    else:
        bad = deepcopy(a)
        bad["module_instance_id"] = "a-bad-module"
        scene["module_instances"].append(bad)
        expected_code, entity_id = "module_unresolved", bad["module_instance_id"]
        if damage == "missing_field":
            bad["pv_field_id"] = "missing-field"
        elif damage == "invalid_transform":
            bad["transform"].pop("position_z_m")
        else:
            revision_id = "unresolvable-module-revision"
            bad["module_definition_revision_id"] = revision_id
            if damage != "missing_definition":
                definition = deepcopy(definitions[MODULE])
                definition["revision_id"] = revision_id
                if damage == "not_layout_ready":
                    definition["capability_flags"]["layout_ready"] = False
                else:
                    definition["mechanical"]["width_m"] = 0
                definitions[revision_id] = definition
    before = deepcopy(bundle)
    report = validate_scene_layout(scene, definitions)
    assert bundle == before
    assert report == validate_scene_layout(scene, definitions)
    unresolved = [c for c in report["conflicts"] if c["code"] == expected_code]
    assert len(unresolved) == 1
    codes = {c["code"] for c in report["conflicts"]}
    assert {"module_module_overlap", "module_obstacle_overlap"} <= codes
    assert any({c["module_instance_id"], c["other_id"]} == {a["module_instance_id"], b["module_instance_id"]}
               for c in report["conflicts"] if c["code"] == "module_module_overlap")
    findings = [f for f in scene_layout_readiness_findings(bundle) if f["rule_id"] == "SCENE_LAYOUT_UNRESOLVED"]
    assert len(findings) == 1 and findings[0]["entity_id"] == entity_id
    assert findings[0]["context"] == unresolved[0]
    assert findings[0]["severity"] == "blocking_error"
    if damage == "not_layout_ready":
        assert unresolved[0]["reason"] == "definition_not_layout_ready"
        scene["module_instances"] = [a, b, *[
            {**deepcopy(bad), "module_instance_id": f"unresolved-{i:02d}"} for i in range(51)
        ]]
        bounded = [f for f in scene_layout_readiness_findings(bundle) if f["rule_id"] == "SCENE_LAYOUT_UNRESOLVED"]
        assert len(bounded) == 51
        summary = next(f for f in bounded if f["entity_id"] is None)
        assert summary["context"] == {"total_entity_count": 51, "omitted_entity_count": 1}
