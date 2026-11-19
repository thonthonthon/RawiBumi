import json
from pathlib import Path

from jsonschema import Draft202012Validator
from referencing import Registry, Resource


ROOT = Path(__file__).resolve().parents[2]


def _load(path: str):
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


def _canonical_registry():
    registry = Registry()
    for path in (ROOT / "schemas").glob("*.schema.json"):
        schema = _load(str(path.relative_to(ROOT)))
        if "$id" in schema:
            registry = registry.with_resource(
                schema["$id"], Resource.from_contents(schema)
            )
    return registry


def test_phase40_new_contract_schemas_are_valid():
    paths = [
        "schemas/design-validation-report.schema.json",
        "apps/web/schema/design-workspace-state.schema.json",
    ]
    for path in paths:
        Draft202012Validator.check_schema(_load(path))


def test_design_validation_report_fixture_pins_exact_design_revisions():
    schema = _load("schemas/design-validation-report.schema.json")
    fixture = _load("tests/fixtures/schema/design-validation-report.example.json")
    Draft202012Validator(
        schema, registry=_canonical_registry()
    ).validate(fixture)

    project = _load("tests/fixtures/schema/project.example.json")["project_revision"]
    assert fixture["project_revision_id"] == project["project_revision_id"]
    assert fixture["scene_revision_id"] == project["scene_revision_id"]
    assert fixture["electrical_revision_id"] == project["electrical_revision_id"]
    assert fixture["blocking_simulation"] is False
    assert fixture["finding_counts"]["blocking_error"] == 0


def test_workspace_state_is_valid_but_not_a_simulation_input():
    schema = _load("apps/web/schema/design-workspace-state.schema.json")
    fixture = _load("tests/fixtures/schema/design-workspace-state.example.json")
    Draft202012Validator(schema).validate(fixture)

    forbidden = [
        "surfaces",
        "obstacles",
        "pv_fields",
        "module_instances",
        "strings",
        "mppt_instances",
        "inverter_instances",
        "simulation_timestep_seconds",
        "weather_dataset_revision_id",
    ]
    serialized = json.dumps(schema)
    for field in forbidden:
        assert f'"{field}"' not in serialized

    for canonical_path in [
        "schemas/project-revision.schema.json",
        "schemas/simulation-configuration.schema.json",
        "schemas/simulation-run.schema.json",
    ]:
        assert "DesignWorkspaceState" not in json.dumps(_load(canonical_path))
        assert "workspace_state" not in json.dumps(_load(canonical_path))


def test_existing_scene_and_electrical_serializations_are_phase40_revision_roles():
    project = _load("tests/fixtures/schema/project.example.json")["project_revision"]
    scene = _load("tests/fixtures/schema/scene.example.json")
    electrical = _load("tests/fixtures/schema/electrical-design.example.json")

    assert scene["schema_name"] == "Scene"
    assert scene["revision_id"] == project["scene_revision_id"]
    assert electrical["schema_name"] == "ElectricalDesignRevision"
    assert electrical["electrical_revision_id"] == project["electrical_revision_id"]


def test_design_suggestion_freezes_actual_vs_suggested_semantics():
    schema = _load("schemas/design-suggestion.schema.json")
    fixture = _load("tests/fixtures/schema/design-suggestion.example.json")
    Draft202012Validator(schema).validate(fixture)

    assert fixture["actual_value"] == 1.2
    assert fixture["suggested_value"] == 1.05
    assert fixture["actual_source"] == "user_input"
    assert fixture["suggestion_source"] == "heuristic"
    assert fixture["override_state"] == "user_overridden"
    assert "current_value" not in fixture


def test_simulation_run_uses_scene_revision_id_consistently():
    schema = _load("schemas/simulation-run.schema.json")
    required = set(schema["required"])
    properties = schema["properties"]

    assert "scene_revision_id" in required
    assert "scene_revision_id" in properties
    assert "geometry_revision_id" not in required
    assert "geometry_revision_id" not in properties
