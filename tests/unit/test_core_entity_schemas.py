import json
from pathlib import Path

from jsonschema import Draft202012Validator
from referencing import Registry, Resource


ROOT = Path(__file__).resolve().parents[2]

CASES = [
    ("geometry/scene/scene.schema.json", "tests/fixtures/schema/scene.example.json"),
    ("electrical/schema/electrical-design.schema.json", "tests/fixtures/schema/electrical-design.example.json"),
    ("schemas/source-record.schema.json", "tests/fixtures/schema/source-record.example.json"),
    ("schemas/imported-asset.schema.json", "tests/fixtures/schema/imported-asset.example.json"),
    ("schemas/import-record.schema.json", "tests/fixtures/schema/import-record.example.json"),
    ("schemas/validation-finding.schema.json", "tests/fixtures/schema/validation-finding.example.json"),
    ("schemas/design-suggestion.schema.json", "tests/fixtures/schema/design-suggestion.example.json"),
]


def load_json(relative_path: str):
    return json.loads((ROOT / relative_path).read_text(encoding="utf-8"))




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
            schema = load_json(str(path.relative_to(ROOT)))
            if "$id" in schema:
                registry = registry.with_resource(
                    schema["$id"], Resource.from_contents(schema)
                )
    return registry


def test_core_entity_schemas_are_valid_draft_2020_12():
    for schema_path, _ in CASES:
        Draft202012Validator.check_schema(load_json(schema_path))


def test_core_entity_fixtures_validate():
    for schema_path, fixture_path in CASES:
        Draft202012Validator(
            load_json(schema_path), registry=_schema_registry()
        ).validate(load_json(fixture_path))
