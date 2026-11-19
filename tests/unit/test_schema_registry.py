import json
from pathlib import Path
import yaml
from jsonschema import Draft202012Validator
from referencing import Registry, Resource

ROOT = Path(__file__).resolve().parents[2]

SCHEMAS = {
    "module": ROOT / "components/schema/module-definition.schema.json",
    "module_topology": ROOT / "components/schema/module-topology-definition.schema.json",
    "inverter": ROOT / "components/schema/inverter-definition.schema.json",
    "weather": ROOT / "weather/schema/weather-dataset.schema.json",
    "project": ROOT / "schemas/project.schema.json",
    "simulation": ROOT / "schemas/simulation-configuration.schema.json",
    "benchmark": ROOT / "schemas/benchmark-case.schema.json",
    "common": ROOT / "schemas/common.schema.json",
    "simulation_assumption": ROOT / "schemas/simulation-assumption.schema.json",
    "resolved_component_model": ROOT / "schemas/resolved-component-model.schema.json",
    "simulation_model_resolution": ROOT / "schemas/simulation-model-resolution.schema.json",
    "project_revision": ROOT / "schemas/project-revision.schema.json",
    "result_dataset_reference": ROOT / "schemas/result-dataset-reference.schema.json",
    "summary_result": ROOT / "schemas/summary-result.schema.json",
    "reproducibility_manifest": ROOT / "schemas/reproducibility-manifest.schema.json",
    "simulation_run": ROOT / "schemas/simulation-run.schema.json",
    "design_validation_report": ROOT / "schemas/design-validation-report.schema.json",
    "pvsyst_attribution_report": ROOT / "schemas/pvsyst-attribution-report.schema.json",
    "pvsyst_detailed_hourly_attribution_report": ROOT / "schemas/pvsyst-detailed-hourly-attribution-report.schema.json",
    "weather_qc_report": ROOT / "weather/schema/weather-qc-report.schema.json",
    "weather_source_acquisition_manifest": ROOT / "weather/schema/weather-source-acquisition-manifest.schema.json",
    "site_workspace_bootstrap": ROOT / "apps/web/schema/site-workspace-bootstrap.schema.json",
    "project_workspace_bundle": ROOT / "apps/api/schema/project-workspace-bundle.schema.json",
    "phase3_benchmark_suite": ROOT / "schemas/phase3-benchmark-suite.schema.json",
    "local_coordinate_system": ROOT / "geometry/coordinates/local-coordinate-system.schema.json",
    "map_layer_configuration": ROOT / "geometry/coordinates/map-layer-configuration.schema.json",
    "scene_editor_command": ROOT / "apps/web/schema/scene-editor-command.schema.json",
    "pv_field_command": ROOT / "apps/web/schema/pv-field-command.schema.json",
    "pv_field_conflict_report": ROOT / "schemas/pv-field-conflict-report.schema.json",
    "pv_field_layout_impact_report": ROOT / "schemas/pv-field-layout-impact-report.schema.json",
    "manual_module_edit_report": ROOT / "schemas/manual-module-edit-report.schema.json",
    "generated_scene3d": ROOT / "geometry/scene3d/generated-scene3d.schema.json",
    "component_revision_impact": ROOT / "components/schema/component-revision-impact.schema.json",
    "component_binding_manifest": ROOT / "components/schema/component-binding-manifest.schema.json",
    "component_revision_command": ROOT / "apps/web/schema/component-revision-command.schema.json",
    "electrical_topology_command": ROOT / "apps/web/schema/electrical-topology-command.schema.json",
    "electrical_topology_view": ROOT / "apps/web/schema/electrical-topology-view.schema.json",
    "electrical_topology_consistency_report": ROOT / "electrical/schema/electrical-topology-consistency-report.schema.json",
    "string_length_suggestion": ROOT / "electrical/schema/string-length-suggestion.schema.json",
    "engineering_validation_configuration": ROOT / "schemas/engineering-validation-configuration.schema.json",
    "shading_configuration": ROOT / "geometry/shading/shading-configuration.schema.json",
    "compiled_shading_geometry": ROOT / "geometry/shading/compiled-shading-geometry.schema.json",
    "shading_result": ROOT / "geometry/shading/shading-result.schema.json",
    "shading_cache_manifest": ROOT / "geometry/shading/shading-cache-manifest.schema.json",
    "simulation_execution_group_plan": ROOT / "schemas/simulation-execution-group-plan.schema.json",
    "beam_shadow_query_result": ROOT / "geometry/shading/beam-shadow-query-result.schema.json",
    "beam_shadow_diagnostic_artifact": ROOT / "geometry/shading/beam-shadow-diagnostic-artifact.schema.json",
    "sky_visibility_query_result": ROOT / "geometry/shading/sky-visibility-query-result.schema.json",
    "directional_visibility_query_result": ROOT / "geometry/shading/directional-visibility-query-result.schema.json",
    "ground_visibility_query_result": ROOT / "geometry/shading/ground-visibility-query-result.schema.json",
    "electrical_parameterization_evidence": ROOT / "shading/electrical/electrical-parameterization-evidence.schema.json",
    "electrical_shading_configuration": ROOT / "shading/electrical/electrical-shading-configuration.schema.json",
    "electrical_region_map": ROOT / "shading/electrical/electrical-region-map.schema.json",
    "local_electrical_irradiance_state": ROOT / "shading/electrical/local-electrical-irradiance-state.schema.json",
    "electrical_iv_curve": ROOT / "shading/electrical/electrical-iv-curve.schema.json",
    "electrical_shading_result": ROOT / "shading/electrical/electrical-shading-result.schema.json",
}


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))




def schema_registry():
    registry = Registry()
    directories = (
        ROOT / "schemas",
        ROOT / "components/schema",
        ROOT / "weather/schema",
        ROOT / "geometry/scene",
        ROOT / "geometry/coordinates",
        ROOT / "geometry/scene3d",
        ROOT / "geometry/shading",
        ROOT / "shading/electrical",
        ROOT / "electrical/schema",
        ROOT / "apps/web/schema",
        ROOT / "apps/api/schema",
    )
    for directory in directories:
        for path in directory.glob("*.schema.json"):
            schema = load_json(path)
            if "$id" in schema:
                registry = registry.with_resource(
                    schema["$id"], Resource.from_contents(schema)
                )
    return registry


def test_json_schemas_are_valid_draft_2020_12():
    for path in SCHEMAS.values():
        Draft202012Validator.check_schema(load_json(path))


def test_benchmark_ids_are_unique_and_tolerances_exist():
    benchmarks = yaml.safe_load((ROOT / "tests/benchmarks/benchmarks.yaml").read_text(encoding="utf-8"))
    tolerances = yaml.safe_load((ROOT / "tests/benchmarks/tolerances.yaml").read_text(encoding="utf-8"))
    ids = [item["benchmark_id"] for item in benchmarks["benchmarks"]]
    assert len(ids) == len(set(ids))
    valid_tolerances = set(tolerances["tolerance_classes"])
    assert all(item["tolerance_class"] in valid_tolerances for item in benchmarks["benchmarks"])


def test_schema_fixtures_validate():
    fixtures = [
        ("module", ROOT / "tests/fixtures/schema/module.example.json"),
        ("inverter", ROOT / "tests/fixtures/schema/inverter.example.json"),
        ("weather", ROOT / "tests/fixtures/schema/weather-dataset.example.json"),
        ("project", ROOT / "tests/fixtures/schema/project.example.json"),
        ("pv_field_command", ROOT / "tests/fixtures/schema/pv-field-command.example.json"),
        ("component_revision_command", ROOT / "tests/fixtures/schema/component-revision-command.example.json"),
        ("electrical_topology_command", ROOT / "tests/fixtures/schema/electrical-topology-command.example.json"),
        ("engineering_validation_configuration", ROOT / "tests/fixtures/schema/engineering-validation-configuration.example.json"),
        ("weather_source_acquisition_manifest", ROOT / "tests/fixtures/schema/weather-source-acquisition-manifest.example.json"),
        ("site_workspace_bootstrap", ROOT / "tests/fixtures/schema/site-workspace-bootstrap.example.json"),
    ]
    for schema_name, fixture_path in fixtures:
        Draft202012Validator(
            load_json(SCHEMAS[schema_name]), registry=schema_registry()
        ).validate(load_json(fixture_path))
