import json
from pathlib import Path

from jsonschema import Draft202012Validator
from referencing import Registry, Resource

ROOT = Path(__file__).resolve().parents[2]

def _registry():
    registry = Registry()
    for directory in (ROOT / "schemas", ROOT / "components/schema", ROOT / "geometry/scene", ROOT / "geometry/coordinates", ROOT / "geometry/scene3d", ROOT / "electrical/schema", ROOT / "apps/web/schema", ROOT / "apps/api/schema", ROOT / "shading/electrical"):
        if not directory.exists():
            continue
        for path in directory.glob("*.schema.json"):
            schema = json.loads(path.read_text(encoding="utf-8"))
            if "$id" in schema:
                registry = registry.with_resource(schema["$id"], Resource.from_contents(schema))
    return registry

def test_phase62_workspace_schema_accepts_optional_electrical_shading_state_definitions():
    schema = json.loads((ROOT / "apps/api/schema/project-workspace-bundle.schema.json").read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    assert "pinned_electrical_shading_assets" in schema["properties"]
    assert "electrical_shading_selections" in schema["properties"]
    assert "pinned_electrical_shading_assets" not in schema["required"]
    assert "electrical_shading_selections" not in schema["required"]

def test_phase62_workspace_selection_schema_rejects_unknown_selection_fields():
    schema = json.loads((ROOT / "apps/api/schema/project-workspace-bundle.schema.json").read_text(encoding="utf-8"))
    selection = {
        "state_version":"0.1", "module_definition_revision_id":"mod-r1",
        "module_topology_revision_id":None, "region_parameterization_evidence_id":None,
        "cell_parameterization_evidence_id":None, "requested_fidelity":"level_0_geometric_only",
        "resolved_fidelity":"level_0_geometric_only", "fallback_policy":"fail_closed",
        "fallback_applied":False, "fallback_reason":None, "selection_payload_sha256":"a"*64,
        "capability_snapshot":{"available_fidelity_levels":["level_0_geometric_only"],"maximum_fidelity_level":"level_0_geometric_only","bypass_assumption_ids":[],"findings":[]},
        "unexpected":True,
    }
    selection_schema = {"$defs": schema["$defs"], **schema["$defs"]["electrical_shading_selection"]}
    validator = Draft202012Validator(selection_schema, registry=_registry())
    assert list(validator.iter_errors(selection))
