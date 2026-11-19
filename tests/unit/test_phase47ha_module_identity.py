import json
from copy import deepcopy
from pathlib import Path

from jsonschema import Draft202012Validator

from geometry.pvfield import (
    MODULE_IDENTITY_VERSION,
    PVFieldPackingSession,
    placement_fingerprint,
)
from geometry.scene import SceneEditorSession


ROOT = Path(__file__).resolve().parents[2]

MODULE = {
    "schema_name": "ModuleDefinition",
    "schema_version": "0.1",
    "module_definition_id": "mod-47ha",
    "revision_id": "mod-47ha-r1",
    "manufacturer": "OpenSIMPV Test",
    "model": "IDENTITY-1x2",
    "verification_state": "auto_validated",
    "mechanical": {
        "width_m": 1.0,
        "height_m": 2.0,
        "thickness_m": 0.03,
        "mass_kg": 20.0,
    },
    "stc": {
        "pmp_w": 400.0,
        "voc_v": 40.0,
        "isc_a": 12.0,
        "vmp_v": 33.0,
        "imp_a": 11.5,
        "reference_irradiance_w_m2": 1000.0,
        "reference_cell_temperature_c": 25.0,
    },
    "capability_flags": {
        "layout_ready": True,
        "basic_yield_ready": True,
        "detailed_sdm_ready": False,
        "bifacial_ready": False,
        "detailed_shading_ready": False,
    },
}


def _load(path: str):
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


def _roof_scene():
    editor = SceneEditorSession(
        _load("tests/fixtures/phase42/simple-survey-base.scene.json")
    )
    editor.draw_rectangle(
        surface_id="roof",
        scene_object_id="obj-roof",
        name="Identity roof",
        surface_type="flat_roof",
        origin_x_m=0.0,
        origin_y_m=0.0,
        width_m=10.0,
        height_m=8.0,
        base_elevation_m=8.0,
        usable_for_pv=True,
        geometry_source="field_measurement",
    )
    return editor.scene


def _session(scene=None, *, electrical_design=None):
    session = PVFieldPackingSession(
        scene or _roof_scene(),
        {MODULE["revision_id"]: MODULE},
        electrical_design=electrical_design,
    )
    if not session.scene.get("pv_fields"):
        session.create_field(
            pv_field_id="field-1",
            name="Field 1",
            support_surface_id="roof",
            module_definition_revision_id=MODULE["revision_id"],
            orientation="portrait",
            azimuth_deg=0.0,
            tilt_deg=10.0,
            module_gap_x_m=0.0,
            module_gap_y_m=0.0,
            row_pitch_m=2.0,
            mounting_height_m=0.2,
            requested_row_count=1,
            requested_modules_per_row=5,
        )
    return session


def _field(scene):
    return next(
        item for item in scene["pv_fields"]
        if item["pv_field_id"] == "field-1"
    )


def _modules(scene):
    return sorted(
        [
            item for item in scene["module_instances"]
            if item["pv_field_id"] == "field-1"
        ],
        key=lambda item: (item["row_index"], item["column_index"]),
    )


def _electrical(module_ids):
    return {
        "schema_name": "ElectricalDesignRevision",
        "schema_version": "0.1",
        "electrical_revision_id": "elec-47ha-r1",
        "project_id": "proj-47ha",
        "project_revision_id": "proj-47ha-r1",
        "revision_number": 1,
        "supersedes_revision_id": None,
        "status": "draft",
        "inverter_instances": [],
        "mppt_instances": [],
        "strings": [
            {
                "string_id": "S01",
                "project_revision_id": "proj-47ha-r1",
                "name": "String 1",
                "module_instance_ids": list(module_ids),
                "target_mppt_instance_id": None,
                "enabled": False,
                "polarity": "normal",
            }
        ],
        "connections": [],
        "pcc_definition": {"pcc_id": "pcc-1"},
    }


def test_fresh_generated_ids_are_deterministic_and_placement_derived():
    first = _session()
    first.fill_area("field-1")
    second = _session()
    second.fill_area("field-1")

    first_modules = _modules(first.scene)
    second_modules = _modules(second.scene)
    first_ids = [item["module_instance_id"] for item in first_modules]

    assert first_ids == [
        item["module_instance_id"] for item in second_modules
    ]
    assert all(value.startswith("field-1-m-") for value in first_ids)
    assert len(first_ids) == len(set(first_ids))
    assert all(
        item["metadata"]["module_identity_version"]
        == MODULE_IDENTITY_VERSION
        for item in first_modules
    )
    assert all(
        item["metadata"]["placement_fingerprint"]
        == placement_fingerprint(_field(first.scene), item)
        for item in first_modules
    )


def test_unchanged_rebuild_preserves_existing_legacy_ids():
    session = _session()
    session.fill_area("field-1")
    legacy = session.scene
    field = _field(legacy)

    replacements = {}
    for module in _modules(legacy):
        old_id = module["module_instance_id"]
        new_id = (
            f"field-1-r{module['row_index']:04d}"
            f"-c{module['column_index']:04d}"
        )
        replacements[old_id] = new_id
        module["module_instance_id"] = new_id

    field["generated_module_instance_ids"] = [
        replacements[value]
        for value in field["generated_module_instance_ids"]
    ]
    for row in field["row_layouts"]:
        row["module_instance_ids"] = [
            replacements[value] for value in row["module_instance_ids"]
        ]

    expected = [item["module_instance_id"] for item in _modules(legacy)]
    migrated = _session(legacy)
    result = migrated.rebuild_field("field-1")

    assert [item["module_instance_id"] for item in _modules(migrated.scene)] == expected
    assert result["layout_impact"]["retained_module_ids"] == sorted(expected)
    assert result["layout_impact"]["moved_modules"] == []
    assert result["layout_impact"]["invalidated_module_ids"] == []
    assert result["layout_impact"]["topology_status"] == "unchanged"


def test_changed_repack_invalidates_changed_placements_and_reports_strings():
    initial = _session()
    initial.fill_area("field-1")
    before = initial.scene
    old_ids = [item["module_instance_id"] for item in _modules(before)]
    electrical = _electrical(old_ids)
    electrical_before = deepcopy(electrical)

    session = _session(before, electrical_design=electrical)
    result = session.equalize_spacing("field-1", axis="horizontal")
    impact = result["layout_impact"]
    after_ids = [item["module_instance_id"] for item in _modules(session.scene)]

    assert after_ids[0] == old_ids[0]
    assert after_ids[1:] != old_ids[1:]
    assert len(impact["retained_module_ids"]) == 1
    assert len(impact["moved_modules"]) == 4
    assert set(impact["invalidated_module_ids"]) == set(old_ids[1:])
    assert impact["topology_status"] == "review_required"
    assert impact["electrical_design_mutated"] is False
    assert session.electrical_design == electrical_before
    assert impact["affected_strings"] == [
        {
            "string_id": "S01",
            "referenced_invalidated_module_ids": sorted(old_ids[1:]),
            "unresolved_module_instance_ids": sorted(old_ids[1:]),
            "membership_status": "stale_reference",
        }
    ]


def test_layout_impact_report_is_deterministic_and_schema_valid():
    initial = _session()
    initial.fill_area("field-1")
    before = initial.scene
    electrical = _electrical(
        [item["module_instance_id"] for item in _modules(before)]
    )

    first = _session(before, electrical_design=electrical)
    first_report = first.equalize_spacing(
        "field-1", axis="horizontal"
    )["layout_impact"]

    second = _session(before, electrical_design=electrical)
    second_report = second.equalize_spacing(
        "field-1", axis="horizontal"
    )["layout_impact"]

    assert first_report == second_report
    assert len(first_report["impact_hash"]) == 64

    schema = _load("schemas/pv-field-layout-impact-report.schema.json")
    Draft202012Validator(schema).validate(first_report)
