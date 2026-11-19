import json
from copy import deepcopy
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from referencing import Registry, Resource

from electrical.topology import (
    ElectricalTopologyEditorSession,
    new_electrical_design,
)
from geometry.pvfield import PVFieldPackingSession
from geometry.scene import SceneEditorSession, canonical_scene_hash
from validation.engineering import validate_engineering_design


ROOT = Path(__file__).resolve().parents[2]


def _load(path: str):
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


def _registry():
    registry = Registry()
    for directory in (
        ROOT / "schemas",
        ROOT / "components/schema",
        ROOT / "weather/schema",
        ROOT / "geometry/scene",
        ROOT / "geometry/coordinates",
        ROOT / "geometry/scene3d",
        ROOT / "electrical/schema",
        ROOT / "apps/web/schema",
    ):
        for path in directory.glob("*.schema.json"):
            schema = json.loads(path.read_text(encoding="utf-8"))
            if "$id" in schema:
                registry = registry.with_resource(
                    schema["$id"], Resource.from_contents(schema)
                )
    return registry


def _module(
    revision_id="mod-val-r1",
    *,
    include_coefficients=True,
    basic_yield_ready=True,
):
    value = {
        "schema_name": "ModuleDefinition",
        "schema_version": "0.1",
        "module_definition_id": "mod-val",
        "revision_id": revision_id,
        "manufacturer": "OpenSIMPV Test",
        "model": "VAL-400",
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
        "limits": {
            "max_system_voltage_v": 1000.0,
            "max_series_fuse_a": 25.0,
            "operating_temperature_min_c": -40.0,
            "operating_temperature_max_c": 85.0,
        },
        "electrical_models": [
            {
                "model_type": "pvwatts",
                "model_version": "test-v1",
                "parameter_set": {},
                "verification_state": "auto_validated",
            }
        ],
        "capability_flags": {
            "layout_ready": True,
            "basic_yield_ready": basic_yield_ready,
            "detailed_sdm_ready": False,
            "bifacial_ready": False,
            "detailed_shading_ready": False,
            "independent_iv_validated": False,
        },
    }
    if include_coefficients:
        value["temperature_coefficients"] = {
            "alpha_isc_per_c": 0.005,
            "beta_voc_per_c": -0.12,
            "gamma_pmp_per_c": -1.5,
            "coefficient_basis": "absolute",
        }
    return value


MODULE = _module()


def _inverter(
    revision_id="inv-val-r1",
    *,
    max_dc_voltage=600.0,
    mppt_min=100.0,
    mppt_max=250.0,
    mppt_operating_current=20.0,
    mppt_isc=25.0,
    total_dc_current=40.0,
    total_dc_isc=50.0,
    nominal_ac_power=3000.0,
    basic_design_ready=True,
    mppt_design_ready=True,
):
    return {
        "schema_name": "InverterDefinition",
        "schema_version": "0.1",
        "inverter_definition_id": "inv-val",
        "revision_id": revision_id,
        "manufacturer": "OpenSIMPV Test",
        "model": "VAL-3K",
        "inverter_type": "string",
        "phase_configuration": "single_phase",
        "verification_state": "auto_validated",
        "dc_limits": {
            "max_dc_voltage_v": max_dc_voltage,
            "nominal_dc_voltage_v": 150.0,
            "max_dc_power_w": 5000.0,
            "max_dc_current_a": total_dc_current,
            "max_dc_short_circuit_current_a": total_dc_isc,
        },
        "ac_limits": {
            "nominal_ac_power_w": nominal_ac_power,
            "max_ac_power_w": nominal_ac_power * 1.1,
            "nominal_ac_voltage_v": 230.0,
            "nominal_frequency_hz": 50.0,
        },
        "mppt_template": {
            "count": 2,
            "min_operating_voltage_v": mppt_min,
            "max_operating_voltage_v": mppt_max,
            "nominal_voltage_v": 150.0,
            "max_operating_current_a": mppt_operating_current,
            "max_short_circuit_current_a": mppt_isc,
            "input_count_per_mppt": 2,
            "total_input_count": 4,
            "independent_inputs": True,
        },
        "efficiency_model": {
            "model_type": "constant",
            "curves": [],
            "reference_metrics": {
                "max_efficiency_fraction": 0.98,
                "european_efficiency_fraction": 0.97,
                "cec_efficiency_fraction": None,
            },
        },
        "array_sizing_limits": {
            "max_pv_array_power_w": 5000.0,
            "max_pv_current_a": total_dc_current,
        },
        "capability_flags": {
            "basic_design_ready": basic_design_ready,
            "mppt_design_ready": mppt_design_ready,
            "basic_yield_ready": True,
            "detailed_efficiency_ready": False,
            "derating_ready": False,
            "mppt_voltage_ready": True,
            "mppt_current_limit_ready": True,
            "array_sizing_ready": True,
        },
    }


INVERTER = _inverter()


def _scene(module=MODULE):
    editor = SceneEditorSession(
        _load("tests/fixtures/phase42/simple-survey-base.scene.json")
    )
    editor.draw_rectangle(
        surface_id="roof",
        scene_object_id="obj-roof",
        name="Validation roof",
        surface_type="flat_roof",
        origin_x_m=0.0,
        origin_y_m=0.0,
        width_m=4.0,
        height_m=4.0,
        base_elevation_m=8.0,
        usable_for_pv=True,
        geometry_source="field_measurement",
    )
    packing = PVFieldPackingSession(
        editor.scene, {module["revision_id"]: module}
    )
    packing.create_field(
        pv_field_id="field-1",
        name="Field 1",
        support_surface_id="roof",
        module_definition_revision_id=module["revision_id"],
        orientation="portrait",
        azimuth_deg=180.0,
        tilt_deg=10.0,
        module_gap_x_m=0.0,
        module_gap_y_m=0.0,
        row_pitch_m=2.0,
        mounting_height_m=0.2,
        requested_row_count=2,
        requested_modules_per_row=4,
    )
    packing.fill_area("field-1")
    assert len(packing.scene["module_instances"]) == 8
    return packing.scene


def _module_ids(scene):
    return [
        item["module_instance_id"]
        for item in sorted(
            scene["module_instances"],
            key=lambda item: (
                item["row_index"],
                item["column_index"],
            ),
        )
    ]


def _electrical(
    scene,
    *,
    inverter=INVERTER,
    string_lengths=(4, 4),
    same_mppt=False,
):
    design = new_electrical_design(
        project_id="proj-val",
        electrical_revision_id="elec-val-r1",
        pcc_id="pcc-1",
        project_revision_id="proj-val-r1",
    )
    session = ElectricalTopologyEditorSession(
        scene,
        design,
        project_revision_id="proj-val-r1",
        module_definitions={MODULE["revision_id"]: MODULE},
        inverter_definitions={inverter["revision_id"]: inverter},
    )
    inv = session.add_inverter(
        inverter_instance_id="inv-1",
        inverter_definition_revision_id=inverter["revision_id"],
        name="INV-1",
    )
    ids = _module_ids(scene)
    cursor = 0
    for index, length in enumerate(string_lengths, start=1):
        session.create_string(
            string_id=f"S{index:02d}",
            module_instance_ids=ids[cursor : cursor + length],
        )
        cursor += length
    if same_mppt:
        session.assign_strings_to_mppt(
            [f"S{index:02d}" for index in range(1, len(string_lengths) + 1)],
            mppt_instance_id=inv["mppt_instance_ids"][0],
        )
    else:
        for index in range(1, len(string_lengths) + 1):
            session.assign_strings_to_mppt(
                [f"S{index:02d}"],
                mppt_instance_id=inv[
                    "mppt_instance_ids"
                ][(index - 1) % 2],
            )
    return session.electrical_design


def _config(**overrides):
    value = {
        "schema_name": "EngineeringValidationConfiguration",
        "schema_version": "0.1",
        "minimum_cell_temperature_c": -10.0,
        "maximum_cell_temperature_c": 70.0,
        "design_irradiance_w_m2": 1000.0,
        "orientation_tolerance_deg": 0.1,
        "dc_ac_ratio_warning_min": None,
        "dc_ac_ratio_warning_max": None,
        "temperature_model_policy": "detailed_then_linear_fallback",
    }
    value.update(overrides)
    return value


def _validate(scene, electrical, components, **config_overrides):
    return validate_engineering_design(
        scene,
        electrical,
        project_revision_id="proj-val-r1",
        component_revisions=components,
        configuration=_config(**config_overrides),
        design_validation_report_id="validation-r1",
        generated_at="2026-09-24T00:00:00Z",
    )


def _codes(report):
    return {item["rule_id"] for item in report["findings"]}


def _by_code(report, code):
    return [
        item for item in report["findings"]
        if item["rule_id"] == code
    ]


def test_valid_design_uses_explicit_linear_fallback_and_remains_simulatable():
    scene = _scene()
    electrical = _electrical(scene)
    before_scene = canonical_scene_hash(scene)
    before_electrical = deepcopy(electrical)

    report = _validate(
        scene,
        electrical,
        {
            MODULE["revision_id"]: MODULE,
            INVERTER["revision_id"]: INVERTER,
        },
    )

    assert canonical_scene_hash(scene) == before_scene
    assert electrical == before_electrical
    assert report["blocking_simulation"] is False
    assert report["status"] == "valid_with_findings"
    assert "MODULE_TEMPERATURE_MODEL_DOWNGRADED" in _codes(report)
    assert "INVERTER_DC_AC_RATIO" in _codes(report)
    assert report["metadata"]["classification_counts"]["INVALID"] == 0
    assert report["metadata"]["design_mutated"] is False


def test_cold_voc_above_inverter_absolute_limit_is_invalid():
    inverter = _inverter(
        revision_id="inv-low-vmax",
        max_dc_voltage=150.0,
    )
    scene = _scene()
    electrical = _electrical(scene, inverter=inverter)

    report = _validate(
        scene,
        electrical,
        {
            MODULE["revision_id"]: MODULE,
            inverter["revision_id"]: inverter,
        },
    )

    findings = _by_code(
        report, "STRING_VOC_EXCEEDS_INVERTER_MAX_DC"
    )
    assert len(findings) == 2
    assert all(item["classification"] == "INVALID" for item in findings)
    assert report["blocking_simulation"] is True
    assert report["status"] == "invalid"


def test_vmpp_temperature_endpoints_are_checked_against_mppt_window():
    hot_limit = _inverter(
        revision_id="inv-hot-window",
        mppt_min=120.0,
        mppt_max=250.0,
    )
    scene = _scene()
    electrical = _electrical(scene, inverter=hot_limit)
    report = _validate(
        scene,
        electrical,
        {
            MODULE["revision_id"]: MODULE,
            hot_limit["revision_id"]: hot_limit,
        },
    )
    assert (
        "STRING_VMPP_MAX_TEMP_OUTSIDE_MPPT_WINDOW"
        in _codes(report)
    )

    cold_limit = _inverter(
        revision_id="inv-cold-window",
        mppt_min=80.0,
        mppt_max=140.0,
    )
    electrical = _electrical(scene, inverter=cold_limit)
    report = _validate(
        scene,
        electrical,
        {
            MODULE["revision_id"]: MODULE,
            cold_limit["revision_id"]: cold_limit,
        },
    )
    assert (
        "STRING_VMPP_MIN_TEMP_OUTSIDE_MPPT_WINDOW"
        in _codes(report)
    )


def test_mppt_operating_current_and_isc_limits_are_hard_checks():
    inverter = _inverter(
        revision_id="inv-low-mppt-current",
        mppt_operating_current=10.0,
        mppt_isc=11.0,
    )
    scene = _scene()
    electrical = _electrical(scene, inverter=inverter)

    report = _validate(
        scene,
        electrical,
        {
            MODULE["revision_id"]: MODULE,
            inverter["revision_id"]: inverter,
        },
    )

    assert "MPPT_OPERATING_CURRENT_EXCEEDED" in _codes(report)
    assert "MPPT_SHORT_CIRCUIT_CURRENT_EXCEEDED" in _codes(report)
    assert report["blocking_simulation"] is True


def test_total_inverter_input_current_and_total_isc_are_checked():
    inverter = _inverter(
        revision_id="inv-low-total-current",
        total_dc_current=20.0,
        total_dc_isc=22.0,
    )
    scene = _scene()
    electrical = _electrical(scene, inverter=inverter)

    report = _validate(
        scene,
        electrical,
        {
            MODULE["revision_id"]: MODULE,
            inverter["revision_id"]: inverter,
        },
    )

    assert "INVERTER_TOTAL_DC_CURRENT_EXCEEDED" in _codes(report)
    assert "INVERTER_TOTAL_DC_ISC_EXCEEDED" in _codes(report)


def test_unequal_string_lengths_on_same_mppt_are_warning_not_invalid():
    inverter = _inverter(
        revision_id="inv-wide-window",
        mppt_min=50.0,
        mppt_max=300.0,
        mppt_operating_current=30.0,
        mppt_isc=35.0,
    )
    scene = _scene()
    electrical = _electrical(
        scene,
        inverter=inverter,
        string_lengths=(3, 5),
        same_mppt=True,
    )

    report = _validate(
        scene,
        electrical,
        {
            MODULE["revision_id"]: MODULE,
            inverter["revision_id"]: inverter,
        },
    )

    finding = _by_code(report, "MPPT_UNEQUAL_STRING_LENGTH")[0]
    assert finding["classification"] == "WARNING"
    assert report["blocking_simulation"] is False


def test_orientation_mismatch_on_same_mppt_is_warning():
    inverter = _inverter(
        revision_id="inv-orient",
        mppt_operating_current=30.0,
        mppt_isc=35.0,
    )
    scene = _scene()
    second = deepcopy(scene["pv_fields"][0])
    second["pv_field_id"] = "field-2"
    second["scene_object_id"] = "obj-field-2"
    second["azimuth_deg"] = 90.0
    scene["pv_fields"].append(second)

    ids = _module_ids(scene)
    for item in scene["module_instances"]:
        if item["module_instance_id"] in set(ids[4:]):
            item["pv_field_id"] = "field-2"
            item["transform"]["rotation_z_deg"] = 90.0

    electrical = _electrical(
        scene,
        inverter=inverter,
        string_lengths=(4, 4),
        same_mppt=True,
    )
    report = _validate(
        scene,
        electrical,
        {
            MODULE["revision_id"]: MODULE,
            inverter["revision_id"]: inverter,
        },
    )

    finding = _by_code(report, "MPPT_ORIENTATION_MISMATCH")[0]
    assert finding["classification"] == "WARNING"
    assert report["blocking_simulation"] is False


def test_missing_temperature_model_is_explicitly_invalid_not_guessed():
    module = _module(
        revision_id="mod-no-temp",
        include_coefficients=False,
    )
    scene = _scene(module)
    electrical = _electrical(scene)

    report = _validate(
        scene,
        electrical,
        {
            module["revision_id"]: module,
            INVERTER["revision_id"]: INVERTER,
        },
    )

    finding = _by_code(
        report, "MODULE_TEMPERATURE_MODEL_UNAVAILABLE"
    )[0]
    assert finding["classification"] == "INVALID"
    assert report["blocking_simulation"] is True


def test_detailed_required_policy_blocks_linear_fallback():
    scene = _scene()
    electrical = _electrical(scene)

    report = _validate(
        scene,
        electrical,
        {
            MODULE["revision_id"]: MODULE,
            INVERTER["revision_id"]: INVERTER,
        },
        temperature_model_policy="detailed_required",
    )

    assert "MODULE_TEMPERATURE_MODEL_UNAVAILABLE" in _codes(report)
    assert "MODULE_TEMPERATURE_MODEL_DOWNGRADED" not in _codes(report)
    assert report["blocking_simulation"] is True


def test_dc_ac_ratio_is_info_by_default_and_warning_only_by_policy():
    scene = _scene()
    electrical = _electrical(scene)
    components = {
        MODULE["revision_id"]: MODULE,
        INVERTER["revision_id"]: INVERTER,
    }

    report = _validate(scene, electrical, components)
    ratio = _by_code(report, "INVERTER_DC_AC_RATIO")[0]
    assert ratio["classification"] == "INFO"
    assert "INVERTER_DC_AC_RATIO_OUTSIDE_POLICY" not in _codes(report)

    report = _validate(
        scene,
        electrical,
        components,
        dc_ac_ratio_warning_max=1.0,
    )
    warning = _by_code(
        report, "INVERTER_DC_AC_RATIO_OUTSIDE_POLICY"
    )[0]
    assert warning["classification"] == "WARNING"
    assert report["blocking_simulation"] is False


def test_explicit_false_inverter_design_capability_is_invalid():
    inverter = _inverter(
        revision_id="inv-unsupported",
        mppt_design_ready=False,
    )
    scene = _scene()
    electrical = _electrical(scene, inverter=inverter)

    report = _validate(
        scene,
        electrical,
        {
            MODULE["revision_id"]: MODULE,
            inverter["revision_id"]: inverter,
        },
    )
    assert "INVERTER_MPPT_DESIGN_READY_FALSE" in _codes(report)
    assert report["blocking_simulation"] is True


def test_enabled_unassigned_string_is_structurally_invalid():
    scene = _scene()
    electrical = _electrical(scene)
    string = electrical["strings"][0]
    target = string["target_mppt_instance_id"]
    string["target_mppt_instance_id"] = None
    string["enabled"] = True
    for mppt in electrical["mppt_instances"]:
        if mppt["mppt_instance_id"] == target:
            mppt["connected_string_ids"] = [
                value
                for value in mppt["connected_string_ids"]
                if value != string["string_id"]
            ]

    report = _validate(
        scene,
        electrical,
        {
            MODULE["revision_id"]: MODULE,
            INVERTER["revision_id"]: INVERTER,
        },
    )
    assert "ENABLED_STRING_MPPT_NOT_RESOLVED" in _codes(report)
    assert report["blocking_simulation"] is True


def test_report_and_configuration_validate_against_canonical_schemas():
    scene = _scene()
    electrical = _electrical(scene)
    config = _config()
    report = _validate(
        scene,
        electrical,
        {
            MODULE["revision_id"]: MODULE,
            INVERTER["revision_id"]: INVERTER,
        },
    )
    registry = _registry()
    config_schema = _load(
        "schemas/engineering-validation-configuration.schema.json"
    )
    report_schema = _load(
        "schemas/design-validation-report.schema.json"
    )

    Draft202012Validator.check_schema(config_schema)
    Draft202012Validator(config_schema).validate(config)
    Draft202012Validator(
        report_schema, registry=registry
    ).validate(report)


def test_report_is_deterministic_for_identical_explicit_inputs():
    scene = _scene()
    electrical = _electrical(scene)
    components = {
        MODULE["revision_id"]: MODULE,
        INVERTER["revision_id"]: INVERTER,
    }
    first = _validate(scene, electrical, components)
    second = _validate(scene, electrical, components)

    assert first == second
    assert [
        item["finding_id"] for item in first["findings"]
    ] == [
        f"validation-r1:finding:{index:04d}"
        for index in range(1, len(first["findings"]) + 1)
    ]


def test_manual_module_azimuth_is_used_for_mppt_orientation_validation():
    inverter = _inverter(
        revision_id="inv-manual-module-azimuth",
        mppt_operating_current=30.0,
        mppt_isc=35.0,
    )
    scene = _scene()
    module_ids = _module_ids(scene)
    for module in scene["module_instances"]:
        if module["module_instance_id"] == module_ids[-1]:
            module["transform"]["rotation_z_deg"] = 90.0
            module.setdefault("metadata", {})[
                "manual_position_override"
            ] = True
            break

    electrical = _electrical(
        scene,
        inverter=inverter,
        string_lengths=(4, 4),
        same_mppt=True,
    )
    report = _validate(
        scene,
        electrical,
        {
            MODULE["revision_id"]: MODULE,
            inverter["revision_id"]: inverter,
        },
    )

    assert "MPPT_ORIENTATION_MISMATCH" in _codes(report)


def test_fallback_is_not_used_for_non_reference_irradiance_voltage_checks():
    scene = _scene()
    electrical = _electrical(scene)

    report = _validate(
        scene,
        electrical,
        {
            MODULE["revision_id"]: MODULE,
            INVERTER["revision_id"]: INVERTER,
        },
        design_irradiance_w_m2=800.0,
    )

    assert "MODULE_TEMPERATURE_MODEL_UNAVAILABLE" in _codes(report)
    assert report["blocking_simulation"] is True


def test_fallback_mppt_boundary_overlap_is_warning_not_false_precision_invalid():
    inverter = _inverter(
        revision_id="inv-hd-near-window",
        mppt_min=110.0,
        mppt_max=250.0,
    )
    scene = _scene()
    electrical = _electrical(scene, inverter=inverter)

    report = _validate(
        scene,
        electrical,
        {
            MODULE["revision_id"]: MODULE,
            inverter["revision_id"]: inverter,
        },
    )

    assert (
        "STRING_VMPP_MAX_TEMP_FALLBACK_UNCERTAINTY_NEAR_MPPT_WINDOW"
        in _codes(report)
    )
    assert "STRING_VMPP_MAX_TEMP_OUTSIDE_MPPT_WINDOW" not in _codes(report)


def test_absolute_voltage_limit_uses_conservative_fallback_upper_envelope():
    inverter = _inverter(
        revision_id="inv-hd-voc-envelope",
        max_dc_voltage=180.0,
    )
    scene = _scene()
    electrical = _electrical(scene, inverter=inverter)

    report = _validate(
        scene,
        electrical,
        {
            MODULE["revision_id"]: MODULE,
            inverter["revision_id"]: inverter,
        },
    )

    findings = _by_code(
        report, "STRING_VOC_EXCEEDS_INVERTER_MAX_DC"
    )
    assert findings
    assert all(item["classification"] == "INVALID" for item in findings)
    assert all(
        item["context"]["nominal_estimate_v"]
        < item["limit_value"]
        < item["measured_value"]
        for item in findings
    )


def test_current_hard_limit_uses_conservative_fallback_upper_envelope():
    inverter = _inverter(
        revision_id="inv-hd-current-envelope",
        mppt_operating_current=12.0,
        mppt_isc=20.0,
    )
    scene = _scene()
    electrical = _electrical(scene, inverter=inverter)

    report = _validate(
        scene,
        electrical,
        {
            MODULE["revision_id"]: MODULE,
            inverter["revision_id"]: inverter,
        },
    )

    finding = _by_code(
        report, "MPPT_OPERATING_CURRENT_EXCEEDED"
    )[0]
    assert finding["classification"] == "WARNING"
    assert finding["context"]["nominal_estimate_a"] < 12.0
    assert finding["measured_value"] > 12.0


def test_missing_total_inverter_current_limits_are_visible_warnings():
    inverter = _inverter(
        revision_id="inv-hd-missing-total",
        total_dc_current=None,
        total_dc_isc=None,
    )
    scene = _scene()
    electrical = _electrical(scene, inverter=inverter)

    report = _validate(
        scene,
        electrical,
        {
            MODULE["revision_id"]: MODULE,
            inverter["revision_id"]: inverter,
        },
    )

    assert "INVERTER_TOTAL_DC_CURRENT_LIMIT_UNAVAILABLE" in _codes(report)
    assert "INVERTER_TOTAL_DC_ISC_LIMIT_UNAVAILABLE" in _codes(report)


def test_uncertainty_fraction_is_explicit_and_changes_conservative_decision():
    inverter = _inverter(
        revision_id="inv-hd-policy",
        max_dc_voltage=180.0,
    )
    scene = _scene()
    electrical = _electrical(scene, inverter=inverter)
    components = {
        MODULE["revision_id"]: MODULE,
        inverter["revision_id"]: inverter,
    }

    guarded = _validate(scene, electrical, components)
    unguarded = _validate(
        scene,
        electrical,
        components,
        fallback_voltage_uncertainty_fraction=0.0,
        fallback_current_uncertainty_fraction=0.0,
    )

    assert "STRING_VOC_EXCEEDS_INVERTER_MAX_DC" in _codes(guarded)
    assert "STRING_VOC_EXCEEDS_INVERTER_MAX_DC" not in _codes(unguarded)
    assert guarded["metadata"]["validation_evidence_policy"][
        "fallback_voltage_uncertainty_fraction"
    ] == pytest.approx(0.05)
    assert unguarded["metadata"]["validation_evidence_policy"][
        "fallback_voltage_uncertainty_fraction"
    ] == pytest.approx(0.0)
