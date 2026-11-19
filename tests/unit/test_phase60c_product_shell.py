import json
from pathlib import Path

from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator
from referencing import Registry, Resource

from apps.api.project_store import FileProjectStore
from apps.api.server import create_app
from apps.api.service import ProjectShellService


ROOT = Path(__file__).resolve().parents[2]
MODULE_REV = "mod-rawibumi-ref-650-r1"
INVERTER_REV = "inv-rawibumi-ref-150k-r1"


def _registry():
    registry = Registry()
    for directory in (
        ROOT / "schemas",
        ROOT / "components/schema",
        ROOT / "weather/schema",
        ROOT / "geometry/scene",
        ROOT / "geometry/coordinates",
        ROOT / "geometry/scene3d",
        ROOT / "geometry/shading",
        ROOT / "electrical/schema",
        ROOT / "apps/web/schema",
        ROOT / "apps/api/schema",
    ):
        for path in directory.glob("*.schema.json"):
            schema = json.loads(path.read_text(encoding="utf-8"))
            if "$id" in schema:
                registry = registry.with_resource(
                    schema["$id"], Resource.from_contents(schema)
                )
    return registry


def _validate(path: str, value):
    schema = json.loads((ROOT / path).read_text(encoding="utf-8"))
    Draft202012Validator(schema, registry=_registry()).validate(value)


def _service(tmp_path):
    return ProjectShellService(FileProjectStore(tmp_path / "projects"))


def _build_small_project(service):
    bundle = service.create_project(
        name="Phase 6.0C Browser Test",
        latitude_deg=-6.2,
        longitude_deg=106.8,
        elevation_m=25.0,
        timezone_name="Asia/Jakarta",
        workspace_mode="map_overlay",
    )
    project_id = bundle["project"]["project_id"]

    view = service.add_surface_rectangle(
        project_id,
        name="Main roof",
        origin_x_m=0.0,
        origin_y_m=0.0,
        width_m=20.0,
        height_m=10.0,
        base_elevation_m=8.0,
        surface_type="flat_roof",
        usable_for_pv=True,
    )
    surface_id = view["bundle"]["scene"]["surfaces"][0]["surface_id"]

    before_move_hash = view["identity"]["scene_hash"]
    view = service.move_scene_entity(
        project_id,
        entity_id=surface_id,
        dx_m=1.0,
        dy_m=0.0,
    )
    assert view["identity"]["scene_hash"] != before_move_hash
    assert view["scene_view"]["local_features"][0]["polygon"][0][0] == 1.0

    service.add_box_obstacle(
        project_id,
        name="AHU",
        origin_x_m=9.0,
        origin_y_m=4.0,
        width_m=1.0,
        depth_m=1.0,
        base_elevation_m=8.0,
        height_m=1.2,
    )

    view = service.create_pv_field(
        project_id,
        name="Roof array",
        support_surface_id=surface_id,
        module_definition_revision_id=MODULE_REV,
        orientation="portrait",
        azimuth_deg=0.0,
        tilt_deg=10.0,
        row_pitch_m=2.6,
        perimeter_setback_m=0.3,
        obstacle_setback_m=0.3,
    )
    assert len(view["bundle"]["scene"]["module_instances"]) > 0

    view = service.add_inverter(
        project_id,
        inverter_definition_revision_id=INVERTER_REV,
        name="INV-01",
    )
    inverter_id = view["bundle"]["electrical_design"]["inverter_instances"][0][
        "inverter_instance_id"
    ]

    view = service.create_strings(
        project_id,
        string_length=12,
        allow_shorter_remainder=True,
    )
    strings = view["bundle"]["electrical_design"]["strings"]
    assert 1 <= len(strings) <= 6

    view = service.assign_strings(
        project_id,
        inverter_instance_id=inverter_id,
    )
    assert all(
        item["target_mppt_instance_id"] is not None
        for item in view["bundle"]["electrical_design"]["strings"]
    )
    return project_id, view


def test_phase60c_reference_components_are_valid():
    module = json.loads(
        (ROOT / "components/reference/module-ref-650.json").read_text(
            encoding="utf-8"
        )
    )
    inverter = json.loads(
        (ROOT / "components/reference/inverter-ref-150k.json").read_text(
            encoding="utf-8"
        )
    )
    _validate("components/schema/module-definition.schema.json", module)
    _validate("components/schema/inverter-definition.schema.json", inverter)
    assert module["manufacturer"] == "RawiBumi Reference"
    assert inverter["manufacturer"] == "RawiBumi Reference"


def test_phase60c_project_shell_executes_existing_domain_kernels_and_reopens(tmp_path):
    service = _service(tmp_path)
    project_id, view = _build_small_project(service)
    bundle = view["bundle"]

    _validate("schemas/project.schema.json", bundle["project"])
    _validate("geometry/scene/scene.schema.json", bundle["scene"])
    _validate(
        "electrical/schema/electrical-design.schema.json",
        bundle["electrical_design"],
    )
    _validate(
        "apps/api/schema/project-workspace-bundle.schema.json",
        bundle,
    )

    assert MODULE_REV in bundle["pinned_components"]["modules"]
    assert INVERTER_REV in bundle["pinned_components"]["inverters"]
    assert view["topology_consistency"]["blocking_count"] == 0
    assert len(view["scene_view"]["local_features"]) == len(
        view["scene_view"]["geojson"]["features"]
    )
    assert len(view["scene_view"]["geojson"]["features"]) > 2

    saved = service.save_project(project_id)
    reopened = ProjectShellService(
        FileProjectStore(tmp_path / "projects")
    ).project_view(project_id)
    assert reopened["identity"]["scene_hash"] == saved["scene_hash"]
    assert reopened["identity"]["electrical_hash"] == saved["electrical_hash"]
    assert reopened["bundle"] == service.get_bundle(project_id)


def test_phase60c_map_and_blank_modes_do_not_change_engineering_identity(tmp_path):
    service = _service(tmp_path)
    bundle = service.create_project(
        name="Workspace equivalence",
        latitude_deg=-6.2,
        longitude_deg=106.8,
        elevation_m=20.0,
        timezone_name="Asia/Jakarta",
        workspace_mode="map_overlay",
    )
    project_id = bundle["project"]["project_id"]
    before = service.project_view(project_id)

    service.set_workspace_mode(project_id, "blank_engineering_plane")
    blank = service.project_view(project_id)
    assert (
        blank["bundle"]["site_workspace_bootstrap"]["workspace_context"]["mode"]
        == "blank_engineering_plane"
    )
    assert blank["identity"] == before["identity"]
    assert blank["bundle"]["project"] == before["bundle"]["project"]
    assert blank["bundle"]["scene"] == before["bundle"]["scene"]
    assert (
        blank["bundle"]["electrical_design"]
        == before["bundle"]["electrical_design"]
    )

    service.set_workspace_mode(project_id, "map_overlay")
    mapped = service.project_view(project_id)
    assert mapped["identity"] == before["identity"]


def test_phase60c_local_geometry_projects_from_canonical_lcs(tmp_path):
    service = _service(tmp_path)
    bundle = service.create_project(
        name="Projection test",
        latitude_deg=-6.2,
        longitude_deg=106.8,
        elevation_m=20.0,
        timezone_name="Asia/Jakarta",
    )
    project_id = bundle["project"]["project_id"]
    view = service.add_surface_rectangle(
        project_id,
        name="Roof",
        origin_x_m=0.0,
        origin_y_m=0.0,
        width_m=10.0,
        height_m=5.0,
        base_elevation_m=5.0,
    )
    feature = view["scene_view"]["geojson"]["features"][0]
    ring = feature["geometry"]["coordinates"][0]
    assert feature["properties"]["category"] == "surface"
    assert ring[0] == ring[-1]
    assert abs(ring[0][0] - 106.8) < 1e-6
    assert abs(ring[0][1] - (-6.2)) < 1e-6
    assert ring[1] != ring[0]


def test_phase60c_fastapi_smoke_and_catalog(tmp_path):
    app = create_app(store_root=tmp_path / "api-projects")
    client = TestClient(app)

    health = client.get("/api/health")
    assert health.status_code == 200
    assert health.json() == {"status": "ok", "phase": "6.4"}

    catalog = client.get("/api/catalog")
    assert catalog.status_code == 200
    assert catalog.json()["modules"][0]["revision_id"] == MODULE_REV
    assert catalog.json()["inverters"][0]["revision_id"] == INVERTER_REV

    response = client.post(
        "/api/projects",
        json={
            "name": "API project",
            "latitude_deg": -6.2,
            "longitude_deg": 106.8,
            "elevation_m": 25,
            "timezone": "Asia/Jakarta",
            "workspace_mode": "map_overlay",
        },
    )
    assert response.status_code == 201
    project_id = response.json()["bundle"]["project"]["project_id"]

    listed = client.get("/api/projects")
    assert listed.status_code == 200
    assert listed.json()[0]["project_id"] == project_id

    reopened = client.get(f"/api/projects/{project_id}")
    assert reopened.status_code == 200
    assert reopened.json()["bundle"]["project"]["name"] == "API project"


def test_phase60c_surface_move_fails_closed_after_pv_field_creation(tmp_path):
    service = _service(tmp_path)
    bundle = service.create_project(
        name="Edit dependency guard",
        latitude_deg=-6.2,
        longitude_deg=106.8,
        elevation_m=20.0,
        timezone_name="Asia/Jakarta",
    )
    project_id = bundle["project"]["project_id"]
    view = service.add_surface_rectangle(
        project_id,
        name="Roof",
        origin_x_m=0.0,
        origin_y_m=0.0,
        width_m=12.0,
        height_m=8.0,
        base_elevation_m=5.0,
    )
    surface_id = view["bundle"]["scene"]["surfaces"][0]["surface_id"]
    service.create_pv_field(
        project_id,
        name="Array",
        support_surface_id=surface_id,
        module_definition_revision_id=MODULE_REV,
        row_pitch_m=2.6,
    )

    import pytest
    with pytest.raises(ValueError, match="already used by PV fields"):
        service.move_scene_entity(
            project_id,
            entity_id=surface_id,
            dx_m=1.0,
            dy_m=0.0,
        )


def test_phase60c_rawibumi_project_store_env_precedes_legacy(tmp_path, monkeypatch):
    current = tmp_path / "rawibumi-projects"
    legacy = tmp_path / "opensimpv-projects"
    monkeypatch.setenv("RAWIBUMI_PROJECT_STORE", str(current))
    monkeypatch.setenv("OPENSIMPV_PROJECT_STORE", str(legacy))
    app = create_app()
    assert app.state.project_service.store.root == current


def test_phase60c_legacy_project_store_env_remains_readable(tmp_path, monkeypatch):
    legacy = tmp_path / "opensimpv-projects"
    monkeypatch.delenv("RAWIBUMI_PROJECT_STORE", raising=False)
    monkeypatch.setenv("OPENSIMPV_PROJECT_STORE", str(legacy))
    app = create_app()
    assert app.state.project_service.store.root == legacy
